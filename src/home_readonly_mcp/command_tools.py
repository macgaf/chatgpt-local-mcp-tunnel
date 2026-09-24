"""Opt-in unsandboxed command execution. Local configuration is the authority."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
from .errors import Fault
from .onboarding import child_environment
from .processes import ProcessJob

COMMAND_TOOLS = {'run_command','start_command','read_command_output','cancel_command'}


def powershell_command(command):
    """Preserve a final native exit code instead of PowerShell -Command's 0/1.

    Capture $? before doing anything else. A successful last PowerShell command
    clears an earlier native failure, like ordinary shell last-command semantics.
    Explicit user `exit N` still exits before the appended status handler.
    """
    return ("$global:LASTEXITCODE = 0\n" + command +
            "\n$local_mcp_final_success = $?\n"
            "if (-not $local_mcp_final_success) {\n"
            "  if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
            "  exit 1\n"
            "}\n"
            "exit 0\n")


class CommandManager:
    def __init__(self, policy):
        self.policy = policy
        self.lock = threading.RLock()
        self.jobs = {}
        self.requests = {}
        self.closed = False

    def permitted(self):
        if self.policy.mode != 'read_write' or not self.policy.enable_commands:
            raise Fault('COMMANDS_DISABLED', '命令执行未启用。',
                        '需要本机 read_write 及 enable_commands=true。',
                        '在本机明确确认非沙箱命令风险后开启；提示词不能升级权限。')

    def start(self, request_id, command, cwd='.', timeout_seconds=600):
        self.permitted()
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}',request_id):
            raise ValueError('request_id must be 1..128 ASCII letters/digits/._-')
        if not command or len(command)>32000 or '\0' in command:
            raise ValueError('command must be nonempty and <=32000 characters')
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= self.policy.max_command_timeout:
            raise ValueError('timeout_seconds outside local configured range')
        p = self.policy.require(cwd)
        if not p.is_dir():
            raise ValueError('cwd must be an existing directory')
        # Check write scope without trying to mutate the directory itself.
        self.policy.resolve(str(p/'.local-mcp-command-scope'),write=True)
        fingerprint = hashlib.sha256(json.dumps([command,str(p),timeout_seconds]).encode()).hexdigest()
        with self.lock:
            if self.closed:
                raise Fault('RUNTIME_STOPPING','服务正在关闭。','不能再启动命令。','重新连接服务。')
            if request_id in self.requests:
                old, sid = self.requests[request_id]
                if old != fingerprint:
                    raise Fault('REQUEST_ID_CONFLICT','相同 request_id 对应不同命令。',request_id,
                                '重试原操作用原参数，新操作用新的 request_id。')
                if sid not in self.jobs:
                    raise Fault('SESSION_EXPIRED','此请求的会话输出已过期。',sid,
                                '不会重复执行原命令；核查磁盘结果后决定是否新建请求。')
                return self.jobs[sid].snapshot()
            if len(self.requests)>=10000:
                raise Fault('REQUEST_HISTORY_LIMIT','本次运行的请求记录已满。','最多保留 10000 个去重键。',
                            '结束任务后重启 MCP；没有遗忘旧键后偷偷重跑命令。')
            active = [j for j in self.jobs.values() if not j.done.is_set()]
            if len(active)>=self.policy.max_active_commands:
                raise Fault('COMMAND_CONCURRENCY_LIMIT','活动命令已达上限。','本机配置限制并发。',
                            '读完或取消自己的任务后再提交。',sessions=[j.id for j in active],retryable=True)
            terminal = [j for j in self.jobs.values() if j.done.is_set()]
            for job in terminal[:-7]:
                del self.jobs[job.id]
            shell = (shutil.which('powershell.exe') or shutil.which('pwsh.exe')) if os.name=='nt' else '/bin/sh'
            if not shell:
                raise Fault('SHELL_NOT_FOUND','找不到受支持的系统 shell。','Windows 需要 PowerShell。',
                            '安装或修复系统 shell；不使用任意下载的执行程序。')
            argv = [shell,'-NoProfile','-NonInteractive','-Command',powershell_command(command)] if os.name=='nt' else [shell,'-c',command]
            env = child_environment()
            if os.name == 'nt':
                # The stripped environment must still provide built-in cmdlet discovery.
                # Do not inherit repository-controlled/user-injected module search paths.
                env['PSModulePath'] = str(Path(shell).resolve().parent / 'Modules')
            # Commands do not inherit runtime keys, Python injection vars or shell rc env.
            job = ProcessJob(argv,p,env,timeout_seconds,self.policy.max_command_output_bytes)
            self.jobs[job.id] = job
            self.requests[request_id] = (fingerprint,job.id)
            result = job.snapshot()
            result['request_id'] = request_id
            result['warning'] = '非 OS 沙箱：cwd 检查不限制命令可访问的文件和网络；以本机用户权限执行。'
            return result

    def find(self, sid):
        self.permitted()
        with self.lock:
            if sid not in self.jobs:
                raise Fault('SESSION_NOT_FOUND','命令会话不存在或已过期。',sid,
                            '使用本次 runtime 返回的 session_id；不要把其他进程 PID 当作会话。')
            return self.jobs[sid]

    def guard_mutation(self, paths):
        # Only intersecting subtrees, NOT FileMCP's global "any job blocks everything".
        with self.lock:
            for job in self.jobs.values():
                if job.done.is_set():
                    continue
                cwd = Path(job.cwd)
                if any(p == cwd or cwd in p.parents or p in cwd.parents for p in paths):
                    raise Fault('WORKSPACE_COMMAND_ACTIVE','目标工作区仍有本服务的活动命令。',
                                '避免编译/测试与同一目录的修改相互干扰；其他项目不受影响。',
                                '先 read_command_output 等待终止，或 cancel_command 取消此会话。',
                                retryable=True,session_id=job.id,cwd=job.cwd,started_at=job.started_at)

    def close(self):
        with self.lock:
            self.closed=True
            jobs=list(self.jobs.values())
        for job in jobs:
            job.cancel()
        for job in jobs:
            job.done.wait(12)


class CommandMixin:
    def start_command(self, request_id, command, cwd='.', timeout_seconds=600):
        return self.commands.start(request_id,command,cwd,timeout_seconds)

    def run_command(self, command, cwd='.', timeout_seconds=30, request_id=None):
        import uuid
        result = self.commands.start(request_id or uuid.uuid4().hex,command,cwd,timeout_seconds)
        job = self.commands.find(result['session_id'])
        job.done.wait(timeout_seconds+16)
        return job.snapshot(limit=262144)

    def read_command_output(self, session_id, cursor=0, limit=65536):
        return self.commands.find(session_id).snapshot(cursor,limit)

    def cancel_command(self, session_id):
        return self.commands.find(session_id).cancel()
