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
from .interactive import configure_tunnel_interactive
from .policy import APP, Policy, locations
from .storage import digest, write_private
from .eventlog import EventLog, LogSettings, COMPONENTS, LEVELS, error_fields, recent, render, follow, export


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
            {'jsonrpc':'2.0','id':6,'method':'tools/call','params':{'name':'policy_info','arguments':{}}},
        ]
        try:
            test_env = child_environment()
            test_env['XDG_STATE_HOME'] = str(root/'state')
            test_env['LOCALAPPDATA'] = str(root/'AppData'/'Local')
            proc = subprocess.run([sys.executable,'-I','-c',code],
                input=''.join(json.dumps(m)+'\n' for m in messages),capture_output=True,text=True,encoding='utf-8',
                env=test_env,timeout=20)
            output = [json.loads(line) for line in proc.stdout.splitlines()]
            by_id = {m['id']:m for m in output}
            assert proc.returncode == 0 and len(output)==6
            assert by_id[3]['result']['structuredContent']['sha256']==digest(content)
            assert 'error' in by_id[4] and not (workspace/'should-not-exist').exists()
            assert by_id[5]['result']['resultType']=='complete'
            assert all(t['annotations']['readOnlyHint'] for t in by_id[2]['result']['tools'])
            advertised=by_id[6]['result']['structuredContent']['capabilities']
            assert advertised['tool_names']==sorted(t['name'] for t in by_id[2]['result']['tools'])
            assert not advertised['file_write_enabled'] and not advertised['shell_enabled']
        except Exception as exc:
            raise Fault('MCP_SELF_TEST_FAILED','真实 stdio 子进程自检失败。',type(exc).__name__,
                        '检查 Python 安装和程序完整性；不要继续连接 Tunnel。') from exc
    return {'ok':True,'test':'real_stdio_process','legacy_handshake':True,'modern_discovery':True,
            'read_roundtrip':True,'write_hidden_in_readonly':True,'capability_catalog_consistent':True,
            'cloud_tunnel_tested':False,'chatgpt_image_consumption_tested':False}


def doctor(config_path, with_tunnel=False, network=False):
    checks = []
    audit = EventLog(config_path)
    def check(name, fn, required=True, optional_codes=()):
        try:
            details = fn()
            audit.emit('cli','diagnostic_check',stage=name,ok=True)
            checks.append({'name':name,'status':'pass','details':details})
        except Exception as exc:
            required = required and normalize_error(exc).code not in optional_codes
            audit.emit('cli','diagnostic_check','ERROR' if required else 'WARNING',stage=name,ok=False,**error_fields(exc))
            checks.append({'name':name,'status':'fail' if required else 'warning',
                           'error':normalize_error(exc).payload()['error']})
    logging_status = audit.probe()
    checks.append({'name':'logging','status':'pass' if logging_status['ok'] and logging_status['enabled'] else 'warning' if not logging_status['enabled'] else 'fail', 'details':logging_status})
    check('configuration',lambda:Policy.from_file(config_path).summary())
    def local_capabilities():
        from .service import HomeService
        service = HomeService(Policy.from_file(config_path))
        try:
            return {**service.policy_info()['capabilities'],
                    'evidence_source':'new_cli_diagnostic_instance_not_running_tunnel'}
        finally:
            service.close()
    check('tool_capabilities',local_capabilities)
    check('stdio_handshake',self_test)
    from .dependencies import media_probe
    check('media_runtime', media_probe, optional_codes=('DEPENDENCY_MISSING',))
    for package in ('keyring',):
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
    subs.add_parser('media-self-test',help='实际解码 JPEG、渲染 PDF 并校验 ImageContent')
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
    conf.add_argument('--enable-codex-history',dest='enable_codex_history',action='store_true',default=None)
    conf.add_argument('--disable-codex-history',dest='enable_codex_history',action='store_false')
    conf.add_argument('--acknowledge-codex-history',action='store_true',help=argparse.SUPPRESS)
    conf.add_argument('--acknowledge-unsandboxed-commands',action='store_true')
    key = subs.add_parser('key')
    key.add_argument('action',choices=['set','status'])
    code = subs.add_parser('codex-install',help='幂等注册到 Codex，不覆盖同名不同配置')
    code.add_argument('--codex-bin')
    subs.add_parser('install-tunnel-client',help='下载官方完整发行包并核对 SHA256SUMS')
    tunnel = subs.add_parser('tunnel')
    tunnel.add_argument('action',choices=['configure','init','doctor','run'])
    diag = subs.add_parser('doctor')
    diag.add_argument('--with-tunnel',action='store_true')
    diag.add_argument('--network',action='store_true')
    diag.add_argument('--bundle',help='保存脱敏 JSON 诊断，不收集文件内容或密钥')
    log = subs.add_parser('logs',help='本机日志位置、查看、跟踪、导出及设置；不提供远程 MCP 日志访问')
    actions = log.add_subparsers(dest='log_action',required=True)
    actions.add_parser('path',help='显示实际日志目录，不读取配置全文')
    for name in ('show','follow','export'):
        action = actions.add_parser(name)
        action.add_argument('--component',choices=['all',*COMPONENTS],default='all')
        action.add_argument('--level',choices=list(LEVELS),default='DEBUG',help='最低日志级别')
        action.add_argument('--tail',type=int,default=200 if name=='export' else 50 if name=='follow' else 100)
        action.add_argument('--request-id')
        if name=='export':
            action.add_argument('--output',required=True,help='导出 JSON 文件，不覆盖已有文件')
        else:
            action.add_argument('--json',action='store_true',help='输出 JSON Lines')
    action = actions.add_parser('configure',help='修改 logging 部分，保留其他配置；重启后生效')
    toggle = action.add_mutually_exclusive_group()
    toggle.add_argument('--enable',dest='log_enabled',action='store_true',default=None)
    toggle.add_argument('--disable',dest='log_enabled',action='store_false')
    action.add_argument('--level',choices=list(LEVELS))
    action.add_argument('--max-mib',type=int)
    action.add_argument('--keep',type=int)
    action.add_argument('--days',type=int)
    return p


def logs_command(args, audit):
    from dataclasses import asdict
    if args.log_action=='path':
        print(str(audit.directory))
        return 0
    if args.log_action=='configure':
        settings = load_settings(args.config)
        options = asdict(LogSettings.parse(settings.get('logging')))
        updates = {'enabled':args.log_enabled,'level':args.level,'max_bytes':None if args.max_mib is None else args.max_mib*1024*1024,
                   'backup_count':args.keep,'retention_days':args.days}
        options.update({key:value for key,value in updates.items() if value is not None})
        settings['logging'] = asdict(LogSettings.parse(options))
        save_settings(args.config,settings)
        print(json.dumps({'ok':True,'logging':settings['logging'],'restart_required':True},ensure_ascii=False,indent=2))
        return 0
    filters = {'component':args.component,'level':args.level,'tail':args.tail,'request_id':args.request_id}
    if args.log_action=='export':
        result = export(audit.directory,args.output,**filters)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.log_action=='follow':
        try:
            follow(audit.directory,json_output=args.json,**filters)
        except KeyboardInterrupt:
            return 0
    else:
        result = recent(audit.directory,**filters)
        for record in result['records']:
            print(render(record,args.json))
        if not result['records']:
            print('没有匹配日志。先启动服务或运行 doctor；本命令不会生成虚假调用记录。',file=sys.stderr)
        if result['invalid_records'] or result['scan_limited']:
            print('日志查询包含跳过或扫描上限，不能当作完整历史。',file=sys.stderr)
    return 0


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8')
    args = parser().parse_args(argv)
    audit = EventLog(args.config)
    operation = args.command + ('.'+args.action if args.command in ('key','tunnel') else '')
    track = args.command not in ('server','logs')
    if track:
        audit.emit('cli','operation_started',operation=operation)
    try:
        if args.command=='logs':
            return logs_command(args,audit)
        if args.command=='server':
            from .server import serve
            serve(args.config)
            return 0
        if args.command=='self-test':
            result = self_test()
        elif args.command=='media-self-test':
            from .dependencies import media_probe
            result = media_probe()
        elif args.command=='configure':
            result = configure(args.config,root=args.root,mode=args.mode,tunnel_id=args.tunnel_id,
                               key_source=args.key_source,allow_home_write=args.allow_home_write,
                               enable_commands=args.enable_commands,enable_git_push=args.enable_git_push,
                               acknowledge_unsandboxed_commands=args.acknowledge_unsandboxed_commands,
                               enable_codex_history=args.enable_codex_history,
                               acknowledge_codex_history=args.acknowledge_codex_history)
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
                audit.emit('cli','operation_finished',operation=operation,ok=True)
                return 0
            if args.action == 'configure':
                result = configure_tunnel_interactive(args.config)
            else:
                result = tunnel_init(args.config) if args.action=='init' else tunnel_doctor(args.config)
        else:
            result = doctor(args.config,args.with_tunnel,args.network)
            if args.bundle:
                # Explicit report only; no automatic logs/config/source archive collection.
                scrubbed = json.loads(json.dumps(result,ensure_ascii=False).replace(str(Path.home()),'~'))
                write_private(Path(args.bundle).expanduser(),json.dumps(scrubbed,ensure_ascii=False,indent=2).encode())
        if track:
            audit.emit('cli','operation_finished','INFO' if result.get('ok',False) else 'ERROR',operation=operation,ok=bool(result.get('ok',False)))
        print(json.dumps(redact(result),ensure_ascii=False,indent=2))
        return 0 if result.get('ok',False) else 1
    except KeyboardInterrupt:
        if track:
            audit.emit('cli','operation_cancelled','WARNING',operation=operation)
        print('已停止。',file=sys.stderr)
        return 130
    except Exception as exc:
        audit.emit('cli','operation_failed','ERROR',operation=operation,**error_fields(exc))
        print(json.dumps(normalize_error(exc).payload(),ensure_ascii=False,indent=2),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
