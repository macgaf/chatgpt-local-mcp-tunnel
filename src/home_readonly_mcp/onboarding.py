"""Local-only configuration, verified downloads, Codex registration and tunnel launch."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from .credentials import load_key
from .errors import Fault, redact
from .policy import APP, Policy, locations
from .storage import private_dir, Lease, write_private
from .media import safe_member
from .eventlog import EventLog, LogSettings, error_fields
from .tunnel_diagnostics import diagnostic, error_code as diagnostic_error_code


def load_settings(path):
    p = Path(path).expanduser()
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def save_settings(path, data):
    p = Path(path).expanduser()
    LogSettings.parse(data.get('logging'))
    private_dir(p.parent)
    Policy(**{k:v for k,v in data.items() if k in Policy.__dataclass_fields__ and
              k not in ('config_path','protected_paths','state_dir')}, config_path=p)
    temp = p.with_name(p.name + '.' + str(time.time_ns()) + '.tmp')
    write_private(temp, json.dumps(data,ensure_ascii=False,indent=2).encode()+b'\n')
    if p.exists():
        backup = p.with_name(p.name + f'.backup-{time.time_ns()}')
        write_private(backup,p.read_bytes())
    os.replace(temp,p)


def configure(path, *, root=None, mode=None, tunnel_id=None, key_source=None, allow_home_write=False,
              enable_commands=None, enable_git_push=None, acknowledge_unsandboxed_commands=False,
              enable_codex_history=None, acknowledge_codex_history=False):
    data = load_settings(path)
    data.setdefault('root','~')
    data.setdefault('mode','read_only')
    data.setdefault('key_source','keyring')
    for key,value in (('root',root),('mode',mode),('tunnel_id',tunnel_id),('key_source',key_source)):
        if value is not None:
            data[key] = value
    if enable_commands is True and not acknowledge_unsandboxed_commands:
        raise Fault('COMMAND_RISK_ACK_REQUIRED','开启 Shell 需要明确确认风险。',
                    'Shell 不受文件黑名单或 root 沙箱限制，只有 cwd 被检查。',
                    '在本机显式添加 --acknowledge-unsandboxed-commands；没有自动开启。')
    # 保留 acknowledge_codex_history 参数兼容旧命令；导入默认开启，无需额外确认。
    data.setdefault('enable_codex_history', True)
    for key,value in (('enable_commands',enable_commands),('enable_git_push',enable_git_push),
                      ('enable_codex_history',enable_codex_history)):
        if value is not None:data[key]=value
    if data.get('tunnel_id') and not re.fullmatch(r'tunnel_[0-9a-f]{32}',data['tunnel_id']):
        raise Fault('INVALID_TUNNEL_ID', 'Tunnel ID 格式不正确。', '应为 tunnel_ 后接 32 位小写十六进制字符。',
                    '复制 Platform Tunnels 页面提供的完整 ID。')
    if data.get('key_source') not in ('keyring','systemd','environment'):
        raise ValueError('key_source must be keyring/systemd/environment')
    broad_write = (data['mode']=='read_write' and Path(data['root']).expanduser().resolve()==Path.home().resolve()
                   and not data.get('write_roots'))
    if broad_write and not allow_home_write:
        raise Fault('HOME_WRITE_CONFIRMATION_REQUIRED', '整个 HOME 的写权限需要明确选择。',
                    'HOME 中包含用户配置和个人数据。', '改用项目 root/write_roots，或显式加 --allow-home-write。')
    save_settings(path,data)
    return {'ok':True,'config':str(Path(path).expanduser()),'root':data['root'],
            'mode':data['mode'],'restart_required':True}


def child_environment():
    allow = {'PATH','HOME','USER','LOGNAME','USERPROFILE','APPDATA','LOCALAPPDATA','SYSTEMROOT',
        'SystemRoot','WINDIR','COMSPEC','PATHEXT','TEMP','TMP','TMPDIR','LANG','LC_ALL',
        'HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','https_proxy','http_proxy','all_proxy',
        'SSL_CERT_FILE','SSL_CERT_DIR','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME',
        'XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','TUNNEL_CLIENT_HTTP_PROXY','CA_BUNDLE'}
    env = {k:v for k,v in os.environ.items() if k in allow or k.startswith('LC_')}
    env['NO_PROXY'] = 'localhost,127.0.0.1,::1'
    env['no_proxy'] = env['NO_PROXY']
    return env


def stop_owned_process(proc, force_group=False):
    """Only terminate the process/group we launched; never a discovered foreign PID."""
    if proc.poll() is not None and not (force_group and os.name!='nt'):
        return
    if os.name != 'nt':
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=10,check=False)
            proc.kill()
        proc.wait(timeout=5)


def run_checked(argv, *, env=None, timeout=60, secrets=(), audit=None):
    # Read a capped response with a watchdog; no unbounded communicate()/capture_output.
    flags = {'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
    try:
        proc = subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**flags)
    except FileNotFoundError as exc:
        raise Fault('DEPENDENCY_NOT_FOUND', '所需命令不存在。', Path(argv[0]).name,
                    '运行安装脚本；检查 PATH 或设置可执行程序绝对路径。') from exc
    timed_out = threading.Event()
    def expire():
        timed_out.set()
        stop_owned_process(proc,force_group=True)
    timer = threading.Timer(timeout,expire)
    timer.daemon = True
    timer.start()
    try:
        raw = proc.stdout.read(1024*1024+1)
        if len(raw)>1024*1024:
            stop_owned_process(proc)
            if audit is not None:
                audit.emit('tunnel','tunnel_output_dropped','WARNING',error_code='COMMAND_OUTPUT_LIMIT',bytes=len(raw))
            raise Fault('COMMAND_OUTPUT_LIMIT','命令输出超过 1 MiB，已停止本次子进程。',Path(argv[0]).name,
                        '检查命令是否意外进入持续日志模式；未把截断内容当作成功。')
        status = proc.wait(timeout=5)
        if timed_out.is_set():
            if audit is not None:
                audit.emit('tunnel','tunnel_command_timeout','ERROR',error_code='COMMAND_TIMEOUT',exit_code=status)
            raise Fault('COMMAND_TIMEOUT', '配置/验证命令超时。', Path(argv[0]).name,
                        '检查网络或被阻塞的凭据授权；重试 doctor，不要将超时视为成功。',retryable=True)
    finally:
        timer.cancel()
        stop_owned_process(proc)
        proc.stdout.close()
    # Redact BEFORE truncation, otherwise a boundary could split a secret.
    clean = redact(raw.decode('utf-8','replace'),secrets)
    lines = clean.splitlines()
    evidence = diagnostic(lines[-1] if lines else '')
    if audit is not None:
        for line in lines:
            record_tunnel_event(audit, line)
        audit.emit('tunnel','tunnel_command_completed','ERROR' if status else 'INFO',exit_code=status)
        # Tunnel 管理命令也只输出安全投影，不能让认证头和负载落入终端日志。
        output = json.dumps(evidence,ensure_ascii=False)
    else:
        output = clean[-24000:]
    if status:
        code = diagnostic_error_code(evidence) or 'COMMAND_FAILED'
        raise Fault(code, '命令执行失败。', '已确认子进程非零退出；错误证据及未确认项见 diagnostic。',
                    '按同一请求及最后到达层级核对错误；无明确证据时不归因为认证、权限或模型拒绝。',
                    executable=Path(argv[0]).name,exit_code=status,diagnostic=evidence)
    return {'ok':True,'exit_code':0,'output':output}


def launch_argv(config_path):
    # Installed run.py writes its absolute path to config; editable use is also supported.
    settings = load_settings(config_path)
    launcher = settings.get('launcher')
    python = settings.get('python',sys.executable)
    if launcher:
        return [python,'-I',launcher,'--config',str(Path(config_path).expanduser()),'server']
    return [sys.executable,'-m','home_readonly_mcp.cli','--config',str(Path(config_path).expanduser()),'server']


def register_codex(config_path, binary=None):
    binary = binary or shutil.which('codex')
    if not binary:
        raise Fault('CODEX_NOT_FOUND', '未找到 Codex CLI。', 'PATH 中没有 codex。',
                    '安装或定位 Codex CLI 后执行 local-mcp codex-install；不会偷偷改写 Codex 配置。')
    name = APP
    listing = run_checked([binary,'mcp','list','--json'])
    try:
        entries = json.loads(listing['output'].strip())
    except ValueError as exc:
        raise Fault('CODEX_OUTPUT_UNRECOGNIZED','无法解析 Codex MCP 配置。',
                    'mcp list --json 未返回预期 JSON。','检查 Codex 版本；不覆盖现有配置。') from exc
    if not isinstance(entries,list):
        raise ValueError('codex mcp list --json must return a list')
    argv = launch_argv(config_path)
    for item in entries:
        if item.get('name') != name:
            continue
        transport = item.get('transport',item)
        if transport.get('command')==argv[0] and transport.get('args',[])==argv[1:]:
            return {'ok':True,'status':'already_registered','name':name,'changed':False}
        raise Fault('CODEX_CONFIG_CONFLICT', 'Codex 中已有同名但不同配置。', name,
                    '人工审核现有条目后再决定替换；安装器没有删除或覆盖它。')
    # Official CLI edits only its own entry; no replacement of the whole config.toml.
    result = run_checked([binary,'mcp','add',name,'--',*argv])
    verified = run_checked([binary,'mcp','get',name,'--json'])
    obj = json.loads(verified['output'].strip())
    transport = obj.get('transport',obj)
    if transport.get('command')!=argv[0] or transport.get('args',[])!=argv[1:]:
        raise Fault('CODEX_REGISTRATION_UNVERIFIED','注册后配置与预期不符。',name,
                    '检查 codex mcp get；不要继续假定工具已连接。')
    return {'ok':True,'name':name,'changed':True,'restart_required':True,
            'verification':'registered config only; reopen Codex and call policy_info to verify host connection'}


def download_bytes(url, cap):
    if not url.startswith(('https://github.com/openai/tunnel-client/', 'https://api.github.com/repos/openai/tunnel-client/')):
        raise ValueError('download URL must belong to official OpenAI tunnel-client repository')
    req = urllib.request.Request(url,headers={'User-Agent':APP,'Accept':'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(req,timeout=30) as response:
            body = response.read(cap+1)
    except Exception as exc:
        raise Fault('DOWNLOAD_FAILED','无法下载官方依赖。',type(exc).__name__,
                    '检查 DNS、代理、TLS 与 GitHub 访问；不关闭 TLS 校验、不切换不明镜像。',retryable=True) from exc
    if len(body)>cap:
        raise ValueError('download exceeds size limit')
    return body


def verify_archive(archive, checksums, asset_name):
    lines = [line.split() for line in checksums.decode('utf-8').splitlines()]
    matching = [parts[0] for parts in lines if len(parts)==2 and parts[1].lstrip('*')==asset_name]
    if len(matching)!=1 or hashlib.sha256(archive).hexdigest()!=matching[0]:
        raise Fault('CHECKSUM_MISMATCH','官方发行包 SHA-256 校验失败。',asset_name,
                    '停止安装；重新下载并检查来源，不忽略此错误。')
    exe = 'tunnel-client.exe' if 'windows-' in asset_name else 'tunnel-client'
    with zipfile.ZipFile(BytesIO(archive)) as z:
        if len(z.infolist())>2000:
            raise ValueError('too many release archive members')
        seen, matches_exe, files, total_size = set(), [], {}, 0
        for info in z.infolist():
            member = safe_member(info.filename)
            if member in seen or ((info.external_attr>>16)&0o170000)==0o120000:
                raise ValueError('duplicate or symlink release member')
            seen.add(member)
            total_size += info.file_size
            if info.file_size>200*1024*1024 or total_size>500*1024*1024:
                raise ValueError('oversized release archive/member')
            if not info.is_dir():
                files[member] = z.read(info)
            if Path(member).name==exe and not info.is_dir():
                matches_exe.append(info)
        if len(matches_exe)!=1:
            raise ValueError('release must contain exactly one tunnel-client executable')
        executable = safe_member(matches_exe[0].filename)
        companion = Path(executable).with_name('cloudflared.exe' if exe.endswith('.exe') else 'cloudflared').as_posix()
        if companion not in files:
            raise Fault('RELEASE_COMPANION_MISSING', '发行包缺少相邻的 cloudflared 组件。', asset_name,
                        '下载官方完整发行包；不要只复制 tunnel-client 单文件或 runtime-only 包。')
        return executable, files


def install_tunnel_client():
    system = {'Darwin':'darwin','Linux':'linux','Windows':'windows'}.get(platform.system())
    arch = {'aarch64':'arm64','arm64':'arm64','x86_64':'amd64','amd64':'amd64'}.get(platform.machine().lower())
    if not system or not arch:
        raise Fault('UNSUPPORTED_PLATFORM','没有此系统架构的自动安装规则。',platform.platform(),
                    '从 OpenAI 官方发行页面选择兼容的完整 tunnel-client。')
    base = 'https://api.github.com/repos/openai/tunnel-client/releases/latest'
    release = json.loads(download_bytes(base,4*1024*1024))
    tag = release['tag_name']
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+',tag):
        raise ValueError('unexpected release tag; select release manually')
    name = f'tunnel-client-{tag}-{system}-{arch}.zip'
    assets = {item['name']:item['browser_download_url'] for item in release['assets']}
    if name not in assets or 'SHA256SUMS.txt' not in assets:
        raise Fault('RELEASE_ASSET_MISSING','官方发行包缺少匹配资产或校验表。',name,'检查官方 release；不猜测下载路径。')
    archive = download_bytes(assets[name],200*1024*1024)
    sums = download_bytes(assets['SHA256SUMS.txt'],1024*1024)
    exe, files = verify_archive(archive,sums,name)
    dest = private_dir(locations()[1]/'tools'/tag)
    target = dest/exe
    content = files[exe]
    for relative, body in files.items():
        output = dest/relative
        if output.exists():
            if output.is_symlink() or hashlib.sha256(output.read_bytes()).digest()!=hashlib.sha256(body).digest():
                raise Fault('BINARY_CONFLICT','已安装发行文件与官方下载不一致。',relative,
                            '审核现有文件后再处理，不自动覆盖。')
        else:
            write_private(output,body)
        if output.name in ('tunnel-client','tunnel-client.exe','cloudflared','cloudflared.exe'):
            output.chmod(0o700)
    manifest = dest/'provenance.json'
    if not manifest.exists():
        write_private(manifest,json.dumps({'release':tag,'asset':name,'source':assets[name],
            'archive_sha256':hashlib.sha256(archive).hexdigest(),'binary_sha256':hashlib.sha256(content).hexdigest(),
            'verification':'official HTTPS + published SHA256SUMS; attestation NOT verified'}).encode())
    run_checked([str(target),'--version'])
    return str(target)


def tunnel_context(config_path):
    settings = load_settings(config_path)
    tunnel_id = settings.get('tunnel_id','')
    if not re.fullmatch(r'tunnel_[0-9a-f]{32}',tunnel_id):
        raise Fault('TUNNEL_ID_MISSING','Tunnel ID 未配置或无效。','无法选择隧道。','执行 configure --tunnel-id。')
    binary = settings.get('tunnel_client') or shutil.which('tunnel-client')
    if not binary:
        raise Fault('TUNNEL_CLIENT_NOT_FOUND','没有找到 tunnel-client。','未安装或不在 PATH。',
                    '运行 local-mcp install-tunnel-client；不会安装 runtime-only 精简包。')
    key = load_key(settings)
    profile_dir = private_dir(Path(config_path).expanduser().parent/'tunnel-profiles')
    profile = APP+'-'+tunnel_id[-8:]
    env = child_environment()
    env['CONTROL_PLANE_API_KEY'] = key
    env['TUNNEL_CLIENT_PROFILE_DIR'] = str(profile_dir)
    return settings,binary,key,profile_dir,profile,env


def tunnel_init(config_path):
    settings,binary,key,directory,profile,env = tunnel_context(config_path)
    profile_path = directory/(profile+'.yaml')
    metadata = directory/(profile+'.owner.json')
    argv = launch_argv(config_path)
    command = subprocess.list2cmdline(argv) if os.name=='nt' else shlex.join(argv)
    owner = {'tunnel_id':settings['tunnel_id'],'mcp_command':command}
    if profile_path.exists():
        if not metadata.exists() or json.loads(metadata.read_text())!=owner:
            raise Fault('TUNNEL_PROFILE_CONFLICT','已有 profile 不属于当前配置。',profile,
                        '审核该 profile；不会使用 --force 覆盖不明配置。')
    else:
        run_checked([binary,'init','--sample','sample_mcp_stdio_local','--profile',profile,
                     '--tunnel-id',settings['tunnel_id'],'--mcp-command',command],env=env,secrets=(key,),audit=EventLog(config_path))
        if not profile_path.exists():
            raise Fault('TUNNEL_PROFILE_NOT_CREATED','init 成功但预期 profile 不存在。',profile,
                        '检查 tunnel-client 版本和 TUNNEL_CLIENT_PROFILE_DIR 行为。')
        if key in profile_path.read_text():
            profile_path.unlink()  # Only the just-created app-owned secret-bearing profile.
            raise Fault('SECRET_PERSISTENCE_BLOCKED','发现 profile 包含明文 Runtime key，已删除新建 profile。',
                        '安装器拒绝密钥落盘。','升级 tunnel-client，确保 api_key 使用 env 引用。')
        write_private(metadata,json.dumps(owner).encode())
        if os.name!='nt':
            profile_path.chmod(0o600)
    return {'ok':True,'profile':profile,'profile_dir':str(directory),'key_in_config':False}


def tunnel_doctor(config_path):
    _,binary,key,_,profile,env = tunnel_context(config_path)
    return run_checked([binary,'doctor','--profile',profile,'--explain'],env=env,secrets=(key,),timeout=90,audit=EventLog(config_path))


@contextmanager
def _tunnel_termination_signals():
    """服务管理器的 SIGTERM 必须进入 finally，清理本次启动的独立进程组。"""
    previous = {}
    def terminate(signum, frame):
        # 清理期间重复信号不应打断子进程回收。
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        raise SystemExit(128+signum)
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, terminate)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def tunnel_run(config_path):
    settings,binary,key,_,profile,env = tunnel_context(config_path)
    audit = EventLog(config_path)
    audit.emit('tunnel','tunnel_starting')
    state = private_dir(locations()[2]/'tunnel')
    argv = [binary,'run','--profile',profile,'--health.listen-addr','127.0.0.1:0',
            '--health.url-file',str(state/'health-url'),
            '--log.format','json','--log.file','','--log.http-raw-unsafe=false',
            '--harpoon.capture-payloads=false']
    with _tunnel_termination_signals(), Lease(locations()[2],settings['tunnel_id'],'tunnel_run'):
        kwargs = {'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
        proc = subprocess.Popen(argv,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**kwargs)
        audit.emit('tunnel','tunnel_process_started',child_pid=proc.pid)
        try:
            # 写入有界证据后才输出；原生自由文本和负载不进入持久日志或终端。
            while True:
                line = proc.stdout.readline(65537)
                if not line:
                    break
                if len(line)>65536 and not line.endswith(b'\n'):
                    while line and not line.endswith(b'\n'):
                        line = proc.stdout.readline(65537)
                    audit.emit('tunnel','tunnel_output_dropped','WARNING',error_code='LOG_LINE_TOO_LONG')
                    print('[dropped overlong tunnel log line]',flush=True)
                else:
                    evidence = record_tunnel_event(audit, line.decode('utf-8','replace'),secrets=(key,))
                    print(json.dumps(evidence,ensure_ascii=False),flush=True)
            status = proc.wait()
            if status:
                raise Fault('TUNNEL_EXITED','Tunnel 进程异常退出。','见上方脱敏日志。',
                            '运行 local-mcp tunnel doctor；核对认证、网络和本机 MCP。',exit_code=status)
        finally:
            stop_owned_process(proc, force_group=True)
            proc.stdout.close()
            audit.emit('tunnel','tunnel_process_stopped','INFO' if proc.returncode == 0 else 'WARNING',exit_code=proc.returncode)


def record_tunnel_event(audit, text, *, secrets=()):
    """持久化逐行安全证据；在 stdout 被服务管理器丢弃时仍可定位。"""
    evidence = diagnostic(text, secrets)
    code = diagnostic_error_code(evidence)
    level = 'ERROR' if code else evidence.get('reported_level', 'INFO')
    # DEBUG 输出也保留 INFO 摘要，未知正文只保存指纹和省略说明。
    if level == 'DEBUG':
        level = 'INFO'
    audit.emit('tunnel','tunnel_diagnostic',level,diagnostic=evidence,error_code=code)
    return evidence
