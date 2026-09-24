from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
from . import __version__
from .credentials import save_key, load_key
from .errors import Fault, normalize_error, redact
from .onboarding import (configure, load_settings, save_settings, register_codex,
    install_tunnel_client, tunnel_init, tunnel_doctor, tunnel_run, child_environment)
from .policy import APP, Policy, locations
from .storage import digest, write_private


def self_test():
    """A real child process handshake; fixtures only, not user files or an API call."""
    with tempfile.TemporaryDirectory(prefix='local-mcp-selftest-') as folder:
        root = Path(folder)
        workspace = root/'workspace'
        workspace.mkdir()
        content = b'LOCAL_MCP_HANDSHAKE_OK\n'
        (workspace/'probe.txt').write_bytes(content)
        config = root/'config.json'
        config.write_text(json.dumps({'root':str(workspace),'mode':'read_only'}))
        src = str(Path(__file__).resolve().parents[1])
        code = f'import sys; sys.path.insert(0,{src!r}); from home_readonly_mcp.server import serve; serve({str(config)!r})'
        messages = [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'selftest','version':'1'}}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'read_file','arguments':{'path':'probe.txt'}}},
            {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'write_file','arguments':{'path':'should-not-exist','content':'no'}}},
            {'jsonrpc':'2.0','id':5,'method':'server/discover','params':{'_meta':{
                'io.modelcontextprotocol/protocolVersion':'2026-07-28',
                'io.modelcontextprotocol/clientCapabilities':{}}}},
        ]
        try:
            proc = subprocess.run([sys.executable,'-I','-c',code],
                input=''.join(json.dumps(m)+'\n' for m in messages),capture_output=True,text=True,encoding='utf-8',
                env=child_environment(),timeout=20)
            output = [json.loads(line) for line in proc.stdout.splitlines()]
            by_id = {m['id']:m for m in output}
            assert proc.returncode == 0 and len(output)==5
            assert by_id[3]['result']['structuredContent']['sha256']==digest(content)
            assert 'error' in by_id[4] and not (workspace/'should-not-exist').exists()
            assert by_id[5]['result']['resultType']=='complete'
            assert all(t['annotations']['readOnlyHint'] for t in by_id[2]['result']['tools'])
        except Exception as exc:
            raise Fault('MCP_SELF_TEST_FAILED','真实 stdio 子进程自检失败。',type(exc).__name__,
                        '检查 Python 安装和程序完整性；不要继续连接 Tunnel。') from exc
    return {'ok':True,'test':'real_stdio_process','legacy_handshake':True,'modern_discovery':True,
            'read_roundtrip':True,'write_hidden_in_readonly':True,
            'cloud_tunnel_tested':False,'chatgpt_image_consumption_tested':False}


def doctor(config_path, with_tunnel=False, network=False):
    checks = []
    def check(name, fn, required=True):
        try:
            details = fn()
            checks.append({'name':name,'status':'pass','details':details})
        except Exception as exc:
            checks.append({'name':name,'status':'fail' if required else 'warning',
                           'error':normalize_error(exc).payload()['error']})
    check('configuration',lambda:Policy.from_file(config_path).summary())
    check('stdio_handshake',self_test)
    for package in ('PIL','pypdfium2','keyring'):
        found = importlib.util.find_spec(package) is not None
        checks.append({'name':'dependency_'+package,'status':'pass' if found else 'warning',
                       'details':'installed' if found else '重新运行安装脚本安装 media/keyring 组件'})
    settings = load_settings(config_path)
    checks.append({'name':'codex_binary','status':'pass' if shutil.which('codex') else 'warning',
                   'details':'optional for ChatGPT Tunnel; required for automatic Codex registration'})
    binary = settings.get('tunnel_client') or shutil.which('tunnel-client')
    checks.append({'name':'tunnel_binary','status':'pass' if binary and Path(binary).is_file() else 'warning',
                   'details':binary or 'local-mcp install-tunnel-client'})
    if network:
        def tls_check():
            with socket.create_connection(('api.openai.com',443),timeout=8) as sock:
                with ssl.create_default_context().wrap_socket(sock,server_hostname='api.openai.com') as tls:
                    return {'direct_tls':tls.version(),'note':'direct connection only; explicit proxy routes may differ'}
        check('network_dns_tls',tls_check)
    if with_tunnel:
        check('runtime_key',lambda:{'present':bool(load_key(settings))})
        check('tunnel_doctor',lambda:tunnel_doctor(config_path))
    else:
        checks.append({'name':'tunnel_auth_and_connection','status':'not_checked',
                       'details':'执行 doctor --with-tunnel；本地通过不等于云端已连接'})
    return redact({'ok':not any(x['status']=='fail' for x in checks),'version':__version__,
                   'platform':platform.system(),'python':platform.python_version(),'checks':checks})


def parser():
    p = argparse.ArgumentParser(prog='local-mcp',description='本机文件 MCP、凭据存储与 Tunnel/Codex 安装诊断')
    p.add_argument('--version',action='version',version=__version__)
    p.add_argument('--config',default=os.environ.get('LOCAL_MCP_CONFIG',str(locations()[0]/'config.json')))
    subs = p.add_subparsers(dest='command',required=True)
    subs.add_parser('server',help='启动 stdio MCP；stdout 只输出协议')
    subs.add_parser('self-test',help='使用临时文件验证真实 stdio 握手')
    conf = subs.add_parser('configure',help='本机设置 root、模式与 Tunnel 参数')
    conf.add_argument('--root')
    conf.add_argument('--mode',choices=['read_only','read_write'])
    conf.add_argument('--tunnel-id')
    conf.add_argument('--key-source',choices=['keyring','systemd','environment'])
    conf.add_argument('--allow-home-write',action='store_true')
    conf.add_argument('--enable-commands',dest='enable_commands',action='store_true',default=None)
    conf.add_argument('--disable-commands',dest='enable_commands',action='store_false')
    conf.add_argument('--enable-git-push',dest='enable_git_push',action='store_true',default=None)
    conf.add_argument('--disable-git-push',dest='enable_git_push',action='store_false')
    conf.add_argument('--acknowledge-unsandboxed-commands',action='store_true')
    key = subs.add_parser('key')
    key.add_argument('action',choices=['set','status'])
    code = subs.add_parser('codex-install',help='幂等注册到 Codex，不覆盖同名不同配置')
    code.add_argument('--codex-bin')
    subs.add_parser('install-tunnel-client',help='下载官方完整发行包并核对 SHA256SUMS')
    tunnel = subs.add_parser('tunnel')
    tunnel.add_argument('action',choices=['init','doctor','run'])
    diag = subs.add_parser('doctor')
    diag.add_argument('--with-tunnel',action='store_true')
    diag.add_argument('--network',action='store_true')
    diag.add_argument('--bundle',help='保存脱敏 JSON 诊断，不收集文件内容或密钥')
    return p


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    try:
        if args.command=='server':
            from .server import serve
            serve(args.config)
            return 0
        if args.command=='self-test':
            result = self_test()
        elif args.command=='configure':
            result = configure(args.config,root=args.root,mode=args.mode,tunnel_id=args.tunnel_id,
                               key_source=args.key_source,allow_home_write=args.allow_home_write,
                               enable_commands=args.enable_commands,enable_git_push=args.enable_git_push,
                               acknowledge_unsandboxed_commands=args.acknowledge_unsandboxed_commands)
        elif args.command=='key':
            settings = load_settings(args.config)
            if args.action=='set':
                result = save_key(settings)
                settings['key_source'] = 'keyring'
                save_settings(args.config,settings)
            else:
                result = {'ok':True,'present':bool(load_key(settings)),
                          'source':settings.get('key_source','keyring'),'key_displayed':False}
        elif args.command=='codex-install':
            result = register_codex(args.config,args.codex_bin)
        elif args.command=='install-tunnel-client':
            binary = install_tunnel_client()
            settings = load_settings(args.config)
            settings.setdefault('root','~')
            settings.setdefault('mode','read_only')
            settings['tunnel_client'] = binary
            save_settings(args.config,settings)
            result = {'ok':True,'installed':binary,'verification':'published SHA256 checksum; not attestation'}
        elif args.command=='tunnel':
            if args.action=='run':
                tunnel_run(args.config)
                return 0
            result = tunnel_init(args.config) if args.action=='init' else tunnel_doctor(args.config)
        else:
            result = doctor(args.config,args.with_tunnel,args.network)
            if args.bundle:
                # Explicit report only; no automatic logs/config/source archive collection.
                scrubbed = json.loads(json.dumps(result,ensure_ascii=False).replace(str(Path.home()),'~'))
                write_private(Path(args.bundle).expanduser(),json.dumps(scrubbed,ensure_ascii=False,indent=2).encode())
        print(json.dumps(redact(result),ensure_ascii=False,indent=2))
        return 0 if result.get('ok',False) else 1
    except KeyboardInterrupt:
        print('已停止。',file=sys.stderr)
        return 130
    except Exception as exc:
        print(json.dumps(normalize_error(exc).payload(),ensure_ascii=False,indent=2),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
