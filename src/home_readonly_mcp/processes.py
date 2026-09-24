"""Bounded subprocesses owned by this runtime, with output cursors and cleanup."""
from __future__ import annotations
from collections import deque
import os
import signal
import subprocess
import threading
import time
import uuid
from .errors import Fault, redact


class ProcessJob:
    def __init__(self, argv, cwd, env, timeout, output_limit=1048576):
        self.id = uuid.uuid4().hex
        self.cwd = str(cwd)
        self.started_at = time.time()
        self.timeout = timeout
        self.output_limit = output_limit
        self.state = 'running'
        self.exit_code = None
        self.cleanup_error = None
        self.lock = threading.RLock()
        self.chunks = deque()
        self.first = self.last = 0
        self.done = threading.Event()
        self.stop_requested = threading.Event()
        self.stop_reason = None
        flags = ({'start_new_session': True} if os.name != 'nt' else
                 {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP})
        self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     bufsize=0, **flags)
        self._windows_job = None
        if os.name == 'nt':
            try:
                self._windows_job = WindowsJob(self.proc)
            except Exception:
                # Fail closed: never claim descendant cleanup without a job handle.
                subprocess.run(['taskkill', '/PID', str(self.proc.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                self.proc.kill()
                self.proc.wait(timeout=5)
                self.proc.stdout.close()
                raise Fault('PROCESS_ISOLATION_FAILED', '无法建立 Windows 子进程生命周期管理。',
                            'AssignProcessToJobObject 失败。', '检查 Windows Job/安全软件限制；未继续运行命令。')
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.reader.start()
        self.monitor.start()

    def _read(self):
        try:
            while True:
                chunk = self.proc.stdout.read(8192)
                if not chunk:
                    break
                with self.lock:
                    self.chunks.append(chunk)
                    self.last += len(chunk)
                    while self.last - self.first > self.output_limit:
                        head = self.chunks.popleft()
                        excess = self.last - self.first - self.output_limit
                        if len(head) > excess:
                            self.chunks.appendleft(head[excess:])
                            self.first += excess
                        else:
                            self.first += len(head)
        except (OSError, ValueError) as exc:
            self.cleanup_error = type(exc).__name__
        finally:
            self.proc.stdout.close()

    def _kill_tree(self):
        if os.name == 'nt':
            if self._windows_job:
                self._windows_job.terminate()
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            # Kill the owned group even when its original leader has exited.
            time.sleep(0.05)
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _monitor(self):
        deadline = time.monotonic() + self.timeout
        try:
            while self.proc.poll() is None:
                if self.stop_requested.wait(0.025):
                    break
                if time.monotonic() >= deadline:
                    self.stop_reason = 'timed_out'
                    break
            # A command that leaves descendants behind must not outlive its session.
            with self.lock:
                self.state = 'stopping'
            self._kill_tree()
            self.exit_code = self.proc.wait(timeout=10)
            self.reader.join(timeout=5)
            if self.reader.is_alive():
                self.cleanup_error = 'output pipe still open after descendant cleanup'
        except Exception as exc:
            self.cleanup_error = type(exc).__name__
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass
        finally:
            if self._windows_job:
                self._windows_job.close()
            with self.lock:
                self.state = self.stop_reason or ('cleanup_failed' if self.cleanup_error else 'exited')
            self.done.set()

    def cancel(self):
        with self.lock:
            if not self.done.is_set():
                self.stop_reason = self.stop_reason or 'cancelled'
                self.state = 'stopping'
                self.stop_requested.set()
        return self.snapshot()

    def snapshot(self, cursor=0, limit=65536):
        if type(cursor) is not int or cursor < 0 or not 1 <= limit <= 262144:
            raise ValueError('cursor >=0; limit 1..262144 bytes')
        with self.lock:
            if cursor > self.last:
                raise Fault('INVALID_CURSOR', '游标超出已产生的输出。', str(cursor),
                            '使用上次返回的 next_cursor。', last_cursor=self.last)
            start = max(cursor, self.first)
            data = b''.join(self.chunks)[start-self.first:start-self.first+limit]
            next_cursor = start+len(data)
            text = redact(data.decode('utf-8', 'replace'))
            return {'ok': True, 'session_id': self.id, 'state': self.state,
                    'exit_code': self.exit_code, 'output': text, 'next_cursor': next_cursor,
                    'first_cursor': self.first, 'last_cursor': self.last,
                    'has_more': next_cursor < self.last, 'truncated': cursor < self.first,
                    'started_at': self.started_at, 'cwd': self.cwd,
                    'timeout_seconds': self.timeout, 'cleanup_error': self.cleanup_error,
                    'output_encoding': 'UTF-8 replacement on invalid/boundary bytes',
                    'completed': self.done.is_set(),
                    'succeeded': self.done.is_set() and self.state == 'exited' and self.exit_code == 0}


def bounded_run(argv, cwd, env, timeout=30, cap=2*1024*1024):
    """Internal trusted argv runner. Exhausted output budgets fail rather than parse a prefix."""
    job = ProcessJob(argv, cwd, env, timeout, cap)
    try:
        if not job.done.wait(timeout+16):
            job.cancel()
            raise Fault('PROCESS_TIMEOUT', '子进程没有在预算内结束。', os.path.basename(argv[0]),
                        '检查进程及超时；没有把启动成功当成完成。')
        with job.lock:
            data = b''.join(job.chunks)
            if job.first:
                raise Fault('PROCESS_OUTPUT_LIMIT', '子进程输出超过预算。', os.path.basename(argv[0]),
                            '缩小操作范围，未把截断输出当作完整结果。', output_limit=cap)
        if job.state != 'exited':
            raise Fault('PROCESS_TIMEOUT' if job.state == 'timed_out' else 'PROCESS_FAILED',
                        '子进程未正常结束。', job.state, '检查超时、退出状态和子进程清理。',
                        exit_code=job.exit_code, cleanup_error=job.cleanup_error)
        return job.exit_code, data
    finally:
        if not job.done.is_set():
            job.cancel()
            job.done.wait(12)


class WindowsJob:
    """KILL_ON_JOB_CLOSE: close/terminate only the job assigned to our new process."""
    def __init__(self, process):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('PerProcessUserTimeLimit',c.c_longlong),('PerJobUserTimeLimit',c.c_longlong),
                        ('LimitFlags',w.DWORD),('MinimumWorkingSetSize',c.c_size_t),
                        ('MaximumWorkingSetSize',c.c_size_t),('ActiveProcessLimit',w.DWORD),
                        ('Affinity',c.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
        class Counters(c.Structure):
            _fields_ = [(n,c.c_ulonglong) for n in ('ReadOperationCount','WriteOperationCount',
                'OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
        class Extended(c.Structure):
            _fields_ = [('BasicLimitInformation',Basic),('IoInfo',Counters),
                        ('ProcessMemoryLimit',c.c_size_t),('JobMemoryLimit',c.c_size_t),
                        ('PeakProcessMemoryUsed',c.c_size_t),('PeakJobMemoryUsed',c.c_size_t)]
        self.k = c.WinDLL('kernel32',use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [c.c_void_p,w.LPCWSTR]
        self.k.CreateJobObjectW.restype = w.HANDLE
        self.k.SetInformationJobObject.argtypes = [w.HANDLE,c.c_int,c.c_void_p,w.DWORD]
        self.k.SetInformationJobObject.restype = w.BOOL
        self.k.AssignProcessToJobObject.argtypes = [w.HANDLE,w.HANDLE]
        self.k.AssignProcessToJobObject.restype = w.BOOL
        self.k.TerminateJobObject.argtypes = [w.HANDLE,w.UINT]
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.k.CreateJobObjectW(None,None)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        if not self.handle:
            raise c.WinError(c.get_last_error())
        if (not self.k.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)) or
                not self.k.AssignProcessToJobObject(self.handle,w.HANDLE(int(process._handle)))):
            self.close()
            raise c.WinError(c.get_last_error())

    def terminate(self):
        if self.handle:
            self.k.TerminateJobObject(self.handle,1)

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None
