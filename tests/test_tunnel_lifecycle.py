"""真实进程验证 Tunnel 包装器收到终止信号后不会遗留旧客户端。"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


@pytest.mark.skipif(os.name == 'nt', reason='POSIX 进程组终止语义')
@pytest.mark.parametrize('stop_signal', [signal.SIGTERM, signal.SIGINT])
def test_sigterm_stops_tunnel_group(space, tmp_path, stop_signal):
    source = str(Path(__file__).resolve().parents[1]/'src')
    # tunnel_context 返回真实 Python；它把临时目录的 run 文件当作脚本执行。
    (tmp_path/'run').write_text(
        'import subprocess,sys,time,os,json\n'
        'from pathlib import Path\n'
        'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(120)"])\n'
        'Path("child.json").write_text(json.dumps([os.getpid(),child.pid]))\n'
        'print("ready",flush=True)\n'
        'time.sleep(120)\n')
    cfg = space[0]/'config.json'; cfg.write_text('{}')
    code = (
        f'import sys,os;sys.path.insert(0,{source!r})\n'
        'from home_readonly_mcp import onboarding\n'
        'onboarding.tunnel_context=lambda p: ({"tunnel_id":"test-owned"},sys.executable,"",None,"test",dict(os.environ))\n'
        f'onboarding.tunnel_run({str(cfg)!r})\n')
    proc = subprocess.Popen([sys.executable, '-c', code], cwd=tmp_path,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    children = []
    try:
        until = time.monotonic()+10
        while time.monotonic() < until and not (tmp_path/'child.json').exists():
            time.sleep(.02)
        children = json.loads((tmp_path/'child.json').read_text())
        proc.send_signal(stop_signal)
        proc.wait(timeout=10)
        def alive(pid):
            r = subprocess.run(['ps','-o','stat=','-p',str(pid)], capture_output=True, text=True)
            return bool(r.stdout.strip()) and not r.stdout.strip().startswith('Z')
        until = time.monotonic()+2
        while time.monotonic() < until and any(alive(p) for p in children): time.sleep(.02)
        assert not any(alive(p) for p in children), '终止包装器后仍有旧 Tunnel/MCP 进程'
    finally:
        # 只清理本测试启动的两个进程组。
        for group in ([children[0]] if children else [])+[proc.pid]:
            try: os.killpg(group, signal.SIGKILL)
            except ProcessLookupError: pass
        proc.wait(timeout=5)
        proc.stdout.close(); proc.stderr.close()
