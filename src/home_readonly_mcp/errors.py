"""Safe, actionable errors shared by CLI and MCP. Never log file contents."""
from __future__ import annotations
import errno
import re
import uuid

_SECRET = re.compile(r'(?i)(?:chatgpt-local-mcp-tunnel-[a-f0-9]{8}|tunnel_[a-z0-9]{32}|sk-[a-z0-9_-]{12,}|(?:github_pat_|gh[pousr]_)[a-z0-9_]{12,}|Bearer\s+[^\s"\']+)')


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if str(k).lower() in {'api_key', 'runtime_api_key', 'tunnel_id', 'control_plane_tunnel_id', 'password', 'token', 'authorization'}
                    else redact(v, secrets)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return _SECRET.sub('[REDACTED]', value)
    return value


class Fault(Exception):
    def __init__(self, code, message, cause, action, *, retryable=False, **details):
        super().__init__(message)
        self.code, self.message, self.cause, self.action = code, message, cause, action
        self.retryable, self.details = retryable, details

    def payload(self, request_id=None):
        return redact({'ok': False, 'error': {'code': self.code, 'message': self.message,
            'cause': self.cause, 'remediation': self.action, 'retryable': self.retryable,
            'details': self.details, 'request_id': request_id or uuid.uuid4().hex}})


def normalize_error(exc):
    if isinstance(exc, Fault):
        return exc
    winerror = getattr(exc, 'winerror', None)
    number = getattr(exc, 'errno', None)
    if winerror in (32, 33) or number in (errno.EBUSY, errno.ETXTBSY):
        return Fault('OS_FILE_BUSY', '操作系统拒绝访问正在使用的文件。',
            '可能是文件共享锁、应用占用或正在执行的文件；本进程无法可靠识别外部持有者。',
            '保存并关闭相关应用后重试；检查系统资源监视器/lsof。不要删除未知锁文件或杀死未知进程。',
            retryable=True, errno=number, winerror=winerror, holder='unknown')
    if isinstance(exc, PermissionError):
        return Fault('OS_PERMISSION_DENIED', '操作系统拒绝访问。',
            '可能为文件权限、macOS 隐私授权、只读挂载或安全软件限制；并非 MCP 黑名单判定。',
            '检查文件权限、挂载状态和 macOS 隐私与安全性；不要直接用 sudo 或关闭安全策略。',
            errno=number, winerror=winerror)
    if isinstance(exc, FileNotFoundError):
        return Fault('NOT_FOUND', '文件、父目录或可执行程序不存在。',
            '目标不存在、配置过期或 PATH 中没有所需程序。', '检查路径及依赖，运行 local-mcp doctor。')
    if number == errno.ENOSPC:
        return Fault('DISK_FULL', '磁盘空间不足。', '目标卷或备份卷已满。', '释放空间后重试；检查备份目录。')
    if number == errno.EROFS:
        return Fault('READ_ONLY_FILESYSTEM', '文件系统为只读。', '操作系统挂载策略禁止写入。',
                     '选择可写目录；MCP 的读写开关不能覆盖只读挂载。')
    if isinstance(exc, (ValueError, TypeError, UnicodeError)):
        return Fault('INVALID_ARGUMENT', '参数或文件编码无效。', str(exc)[:500],
                     '核对工具参数；二进制文件请使用 read_image、read_document 或 read_binary。')
    return Fault('OPERATION_FAILED', '操作未完成。',
                 f'{type(exc).__name__}: {redact(str(exc))[:500]}',
                 '运行 local-mcp doctor；提供 request_id 与脱敏诊断，不要提供密钥。', errno=number)
