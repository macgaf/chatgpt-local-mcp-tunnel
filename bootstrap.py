#!/usr/bin/env python3
"""Cross-platform, per-user installer. Run from the checked-out repository.

No sudo, shell-pipe download, secret argument or silent privilege escalation.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import venv


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8')
    if sys.version_info < (3,11):
        raise SystemExit('Python 3.11+ is required. On Linux also install the distribution python3-venv package.')
    source = Path(__file__).resolve().parent
    sys.path.insert(0,str(source/'src'))
    from home_readonly_mcp import __version__
    from home_readonly_mcp.errors import normalize_error
    from home_readonly_mcp.eventlog import EventLog, error_fields
    from home_readonly_mcp.onboarding import configure, load_settings, save_settings, child_environment
    from home_readonly_mcp.policy import locations
    from home_readonly_mcp.storage import private_dir, write_private
    p = argparse.ArgumentParser(description='安装本机 MCP；默认 HOME 只读，包含 media 和 keyring 组件')
    p.add_argument('--root')
    p.add_argument('--mode',choices=['read_only','read_write'])
    p.add_argument('--allow-home-write',action='store_true')
    p.add_argument('--tunnel-id')
    p.add_argument('--core-only',action='store_true',help='离线安装核心；不安装图像/PDF/keyring 可选依赖')
    p.add_argument('--heif',action='store_true',help='安装 iPhone HEIC 适配器')
    p.add_argument('--register-codex',action='store_true')
    p.add_argument('--install-client',action='store_true')
    p.add_argument('--store-key',action='store_true',help='在终端隐藏输入并保存 key 到系统凭据库')
    p.add_argument('--setup-tunnel',action='store_true')
    p.add_argument('--plan',action='store_true',help='只显示计划，不写入')
    args = p.parse_args()
    cfgdir,appdir,state = locations()
    config = cfgdir/'config.json'
    if args.plan:
        print(json.dumps({'config':str(config),'installation':str(appdir),'root':args.root or '~',
            'mode':args.mode or 'preserve existing, otherwise read_only','media':not args.core_only,
            'register_codex':args.register_codex,'install_tunnel_client':args.install_client,
            'secrets_in_args':False},ensure_ascii=False,indent=2))
        return 0
    audit = EventLog(config)
    stage = 'configuration'
    audit.emit('install','install_started')
    try:
        # Validate desired configuration before installing anything.
        old = load_settings(config)
        legacy_path = Path.home()/'.config/home-readonly-mcp/config.json'
        if not old and legacy_path.is_file():
            legacy = load_settings(legacy_path)
            keys = ('root','default_policy','allow','deny','max_file_size','max_text_output_bytes',
                    'max_directory_entries','max_search_files','max_search_results')
            old = {k:legacy[k] for k in keys if k in legacy}
            from home_readonly_mcp.policy import DEFAULT_DENY
            old['deny'] = list(dict.fromkeys(DEFAULT_DENY+old.get('deny',[])))
            old['force_allow'] = [v for v in legacy.get('force_allow',[]) if not any(c in v for c in '*?[')]
            old['mode'] = 'read_only'
            save_settings(config,old)
            print('Migrated v0.2 config; original kept. Wildcard force_allow exceptions removed for safety.',flush=True)
        preserve_home = old.get('mode')=='read_write' and args.mode is None and args.root is None
        configure(config,root=args.root,mode=args.mode,tunnel_id=args.tunnel_id,
                  allow_home_write=args.allow_home_write or preserve_home)
        private_dir(appdir)
        destination = appdir/'versions'/f'{__version__}-{time.time_ns()}'
        private_dir(destination)
        shutil.copytree(source/'src',destination/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'))
        runfile = destination/'run.py'
        runfile.write_text("import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parent/'src'))\n"
                           "from home_readonly_mcp.cli import main\nraise SystemExit(main())\n",encoding='utf-8')
        envdir = destination/'venv'
        stage = 'venv'
        audit.emit('install','install_stage',stage=stage)
        # POSIX 复用已安装的解释器；Chrome 宿主创建的可执行副本可能带 quarantine，
        # 在 macOS 触发 Gatekeeper 弹窗。Windows 保持复制，避免依赖符号链接权限。
        venv.EnvBuilder(with_pip=not args.core_only, symlinks=os.name!='nt').create(envdir)
        python = envdir/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not args.core_only:
            stage = 'dependencies'
            audit.emit('install','install_stage',stage=stage)
            packages = ['pathspec>=0.12,<1','Pillow>=11,<13','pypdfium2>=4.30,<6','keyring>=25,<27']
            if args.heif:
                packages.append('pillow-heif>=0.22,<2')
            proc = subprocess.run([str(python),'-m','pip','install',*packages],env=child_environment(),check=False)
            if proc.returncode:
                raise RuntimeError('Optional dependency installation failed; check pip/DNS/proxy output. Re-run or use --core-only explicitly.')
        stage = 'self_test'
        audit.emit('install','install_stage',stage=stage)
        # Probe the staged release before switching the stable managed launcher.
        subprocess.run([str(python),'-I',str(runfile),'--config',str(config),'self-test'],
                       check=True,env=child_environment())
        stage = 'launcher'
        audit.emit('install','install_stage',stage=stage)
        stable = appdir/'launch.py'
        stable_content = ("# Managed by chatgpt-local-mcp-tunnel; contains no secret.\n"
            "import json, os, sys\nfrom pathlib import Path\n"
            "x=json.loads((Path(__file__).resolve().parent/'current.json').read_text())\n"
            "os.execv(x['python'], [x['python'],'-I',x['runfile'],*sys.argv[1:]])\n")
        if stable.exists() and stable.read_text()!=stable_content:
            raise RuntimeError('Existing launch.py is not the expected managed launcher; refusing to overwrite.')
        if not stable.exists():
            write_private(stable,stable_content.encode())
        pointer = appdir/'current.json'
        temporary = appdir/('current-'+str(time.time_ns())+'.tmp')
        write_private(temporary,json.dumps({'python':str(python),'runfile':str(runfile)}).encode())
        os.replace(temporary,pointer)
        settings = load_settings(config)
        settings.update({'launcher':str(stable),'python':sys.executable,'installed_version':__version__})
        save_settings(config,settings)
        base = [sys.executable,'-I',str(stable),'--config',str(config)]
        bindir = private_dir(appdir/'bin') if os.name=='nt' else Path.home()/'.local/bin'
        bindir.mkdir(parents=True,exist_ok=True)
        if os.name=='nt':
            wrapper = bindir/'local-mcp.cmd'
            literal = ' '.join('"'+arg.replace('%','%%')+'"' for arg in base)
            wrapper.write_text('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'+literal+' %*\r\n',encoding='utf-8')
        else:
            wrapper = bindir/'local-mcp'
            wrapper.write_text('#!/bin/sh\nexec '+shlex.join(base)+' "$@"\n',encoding='utf-8')
            wrapper.chmod(0o700)
        print(f'Installed launcher: {wrapper}\nConfig: {config}',flush=True)
        steps = []
        if args.install_client: steps.append(['install-tunnel-client'])
        if args.store_key: steps.append(['key','set'])
        if args.register_codex: steps.append(['codex-install'])
        if args.setup_tunnel: steps.extend([['tunnel','init'],['doctor','--with-tunnel']])
        for step in steps:
            stage = '.'.join(step)
            audit.emit('install','install_stage',stage=stage)
            subprocess.run([*base,*step],check=True)
        audit.emit('install','install_finished',ok=True)
        print(f'Logs: {audit.directory} (local-mcp logs show / logs follow)')
        print('Installation complete. Tunnel is NOT automatically left running. Start:')
        print(f'{wrapper} tunnel run')
        print('ChatGPT: enable Developer Mode, create a Tunnel app, choose this tunnel, then enable it in a new chat.')
        return 0
    except Exception as exc:
        audit.emit('install','install_failed','ERROR',stage=stage,**error_fields(exc))
        print(json.dumps(normalize_error(exc).payload(),ensure_ascii=False,indent=2),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
