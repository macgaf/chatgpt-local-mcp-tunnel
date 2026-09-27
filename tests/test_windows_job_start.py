"""Windows 子进程必须在 Job 绑定完成前保持挂起。"""
import os
import sys
import time
import pytest
from home_readonly_mcp import processes
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.onboarding import child_environment

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='需要真实 Windows Job Object')


def test_delayed_job_assignment_cannot_lose_fast_child(space, monkeypatch):
    root = space[1]; marker = root / 'started.txt'
    original = processes.WindowsJob
    class DelayedJob(original):
        def __init__(self, process):
            time.sleep(.25)
            assert process.poll() is None
            assert not marker.exists()
            super().__init__(process)
    monkeypatch.setattr(processes, 'WindowsJob', DelayedJob)
    code, output = processes.bounded_run(
        [sys.executable, '-c', 'from pathlib import Path; Path("started.txt").write_text("done"); print("done")'],
        root, child_environment(), timeout=10)
    assert code == 0 and output.strip() == b'done' and marker.read_text() == 'done'


def test_failed_job_assignment_never_starts_child(space, monkeypatch):
    root = space[1]; marker = root / 'never.txt'
    def denied(process):
        time.sleep(.25)
        assert process.poll() is None and not marker.exists()
        raise OSError('synthetic job assignment failure')
    monkeypatch.setattr(processes, 'WindowsJob', denied)
    with pytest.raises(Fault) as error:
        processes.bounded_run([sys.executable, '-c', 'from pathlib import Path; Path("never.txt").touch()'],
                              root, child_environment(), timeout=10)
    assert error.value.code == 'PROCESS_ISOLATION_FAILED' and not marker.exists()
