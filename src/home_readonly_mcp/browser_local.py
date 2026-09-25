"""Private local browser transport. Browser payloads never become agent output.

Uses the already configured official Chrome DevTools MCP through a private stdio
child. No Apple Events, DevTools port scanning, cookie export, output files,
remote endpoint, or permission changes. This is not a remote MCP tool.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib


class BrowserFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def configured_browser_argv(config_path=None):
    config = Path(config_path or Path.home()/'.codex/config.toml')
    if not config.is_file():
        raise BrowserFailure('BROWSER_CONFIGURATION_MISSING')
    servers = tomllib.loads(config.read_text(encoding='utf-8')).get('mcp_servers', {})
    choices = []
    for name, entry in servers.items():
        args = entry.get('args', [])
        command = entry.get('command', '')
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            continue
        package = next((a for a in args if re.fullmatch(r'chrome-devtools-mcp(?:@[a-zA-Z0-9.+_-]+)?', a)), None)
        if entry.get('enabled') is False:
            continue
        if Path(command).name in ('npx', 'npx.cmd') and package and '--autoConnect' in args:
            binary = shutil.which(command)
            if not binary:
                continue
            # Offline resolution only: never install a different browser or change its settings.
            choices.append(([binary, '--offline', package, '--autoConnect'], entry))
        elif Path(command).name in ('chrome-devtools-mcp', 'chrome-devtools-mcp.cmd') and '--autoConnect' in args:
            binary = shutil.which(command)
            if binary:
                choices.append(([binary, '--autoConnect'], entry))
    if len(choices) != 1:
        raise BrowserFailure('BROWSER_CONFIGURATION_AMBIGUOUS' if choices else 'AUTHORIZED_AUTOCONNECT_MISSING')
    selected_argv, entry = choices[0]
    selected_args = entry.get('args', [])
    identity_args = []
    for i, arg in enumerate(selected_args):
        if arg in ('--channel', '--userDataDir', '--user-data-dir'):
            if i+1 >= len(selected_args) or selected_args[i+1].startswith('--'):
                raise BrowserFailure('BROWSER_CONFIGURATION_INVALID')
            identity_args += [arg, selected_args[i+1]]
        elif arg.startswith(('--channel=', '--userDataDir=', '--user-data-dir=')):
            identity_args.append(arg)
    return selected_argv + identity_args + ['--categoryExtensions=false', '--categoryNetwork=false',
        '--categoryPerformance=false', '--categoryExperimentalThirdParty=false',
        '--performanceCrux=false', '--usageStatistics=false']


def browser_error(text: str) -> str:
    lower = text.casefold()
    if 'could not find devtoolsactiveport' in lower:
        return 'CHROME_DEBUG_ENDPOINT_MISSING'
    if 'could not connect to chrome' in lower or 'remote debugging' in lower:
        return 'CHROME_CONNECTION_OR_APPROVAL_REQUIRED'
    if 'rejected' in lower or 'not allowed' in lower or 'permission' in lower:
        return 'BROWSER_APPROVAL_REQUIRED'
    if 'timeout' in lower or 'timed out' in lower:
        return 'BROWSER_TIMEOUT'
    if 'closed' in lower:
        return 'BROWSER_DISCONNECTED'
    return 'BROWSER_TOOL_FAILED'


class LocalBrowser:
    MAX_LINE = 4 * 1024 * 1024
    ALLOWED_TOOLS = {'list_pages', 'select_page', 'new_page', 'navigate_page',
                     'evaluate_script', 'take_snapshot', 'click', 'fill', 'press_key'}

    def __init__(self, argv, workspace, timeout=30):
        self.timeout = timeout
        self.root = Path(workspace).resolve()
        self.number = 0
        self.messages = queue.Queue(maxsize=128)
        env = dict(os.environ)
        for key in list(env):
            if key in {'DEBUG', 'NODE_OPTIONS', 'BASH_ENV', 'ENV', 'PYTHONPATH'} or any(x in key.upper() for x in ('API_KEY','TOKEN','SECRET','PASSWORD')):
                env.pop(key, None)
        env['CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS'] = '1'
        process_options = {'start_new_session':True} if os.name != 'nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name != 'nt':
            # GUI launchers can inherit blocked SIGTERM/SIGINT (observed under
            # macOS FileMCP). Reset only in a small exec wrapper, not preexec_fn
            # in this potentially multithreaded parent and not in the host app.
            wrapper=('import os,signal,sys; '
                'signal.signal(signal.SIGTERM,signal.SIG_DFL); '
                'signal.signal(signal.SIGINT,signal.SIG_DFL); '
                'signal.pthread_sigmask(signal.SIG_UNBLOCK,{signal.SIGTERM,signal.SIGINT}); '
                'os.execv(sys.argv[1],sys.argv[1:])')
            argv=[sys.executable,'-I','-c',wrapper,*argv]
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, bufsize=0, **process_options)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.tools = {}
        try:
            self.rpc('initialize', {'protocolVersion':'2025-11-25',
                'capabilities':{'roots':{'listChanged':False}},
                'clientInfo':{'name':'local-tunnel-preparation','version':'1'}})
            self._send({'jsonrpc':'2.0','method':'notifications/initialized'})
            result = self.rpc('tools/list')
            self.tools = {x['name']:x for x in result.get('tools', [])}
            if not {'list_pages','evaluate_script','take_snapshot','click','fill'} <= self.tools.keys():
                raise BrowserFailure('BROWSER_TOOLSET_UNSUPPORTED')
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(self.MAX_LINE+1)
                if not line:
                    break
                if len(line) > self.MAX_LINE:
                    break
                try:
                    message = json.loads(line)
                except (ValueError,UnicodeError):
                    continue
                self.messages.put(message, timeout=1)
        finally:
            try:
                self.messages.put(None, timeout=1)
            except queue.Full:
                pass

    def _send(self, message):
        self.process.stdin.write((json.dumps(message)+'\n').encode('utf-8'))
        self.process.stdin.flush()

    def rpc(self, method, params=None):
        self.number += 1
        ident = self.number
        self._send({'jsonrpc':'2.0','id':ident,'method':method,'params':params or {}})
        deadline = time.monotonic()+self.timeout
        while True:
            if time.monotonic() >= deadline:
                raise BrowserFailure('BROWSER_TIMEOUT')
            try:
                reply = self.messages.get(timeout=max(.001, deadline-time.monotonic()))
            except queue.Empty:
                raise BrowserFailure('BROWSER_TIMEOUT') from None
            if reply is None:
                raise BrowserFailure('BROWSER_PROCESS_EXITED')
            if reply.get('method') == 'roots/list':
                self._send({'jsonrpc':'2.0','id':reply['id'],'result':{
                    'roots':[{'uri':self.root.as_uri(),'name':'authorized-workspace'}]}})
                continue
            if 'method' in reply or reply.get('id') != ident:
                continue
            if 'error' in reply:
                raise BrowserFailure(browser_error(json.dumps(reply['error'])))
            return reply['result']

    def call(self, tool, arguments=None):
        if tool not in self.ALLOWED_TOOLS:
            raise BrowserFailure('BROWSER_TOOL_NOT_PERMITTED')
        arguments = arguments or {}
        if 'filePath' in arguments:
            raise BrowserFailure('BROWSER_FILE_TRANSFER_NOT_PERMITTED')
        result = self.rpc('tools/call', {'name':tool,'arguments':arguments})
        if result.get('isError'):
            text = '\n'.join(x.get('text','') for x in result.get('content',[]))
            raise BrowserFailure(browser_error(text))
        return result

    @staticmethod
    def text(result):
        return '\n'.join(x.get('text','') for x in result.get('content',[]) if x.get('type')=='text')

    def evaluate(self, function):
        raw = self.text(self.call('evaluate_script', {'function':function}))
        match = re.search(r'```(?:json)?\s*\n(.*?)\n```', raw, re.S)
        try:
            return json.loads(match.group(1) if match else raw)
        except ValueError:
            raise BrowserFailure('BROWSER_RESULT_FORMAT_CHANGED') from None

    def snapshot(self):
        return self.text(self.call('take_snapshot', {}))

    def close(self):
        from .onboarding import stop_owned_process
        # Only the new MCP child/group belongs to us, never the attached Chrome.
        stop_owned_process(self.process, force_group=True)
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
