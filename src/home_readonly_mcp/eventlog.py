"""Local, bounded JSONL event logs. No request bodies or raw subprocess output.

Each append/rotation uses a bounded cross-process OS lock; ordinary rotating
logging handlers alone do not serialize independent Codex/Tunnel processes.
Logs remain under the protected state directory and are not an MCP tool.
"""
from __future__ import annotations
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time
import uuid
from .errors import Fault, normalize_error, redact
from .policy import locations

COMPONENTS = ('mcp', 'commands', 'tunnel', 'cli', 'install')
LEVELS = {'DEBUG': 10, 'INFO': 20, 'WARNING': 30, 'ERROR': 40}
MAX_RECORD = 16384
MAX_TAIL = 5000
MAX_READ = 8 * 1024 * 1024
# All values in free-text messages are owned by the program, never user input.
CAUSES = {
    'FILE_LOCKED': ('另一个本服务操作持有目标文件写锁。', '核对 holder_pid；等待操作完成，不删除锁文件。'),
    'WORKSPACE_COMMAND_ACTIVE': ('相交工作区存在活动命令。', '检查 session_id，等待或取消自己的任务。'),
    'OS_FILE_BUSY': ('操作系统报告文件忙；外部持有者无法可靠判断。', '检查相关应用或系统文件锁，不杀未知进程。'),
    'OS_PERMISSION_DENIED': ('操作系统拒绝访问。', '检查权限、隐私授权及挂载状态，不自动 sudo。'),
    'HASH_CONFLICT': ('磁盘版本与预期哈希不同。', '重新读取并合并，不强行替换哈希覆盖。'),
    'POLICY_DENIED': ('访问被本机策略拒绝。', '用 policy_info 核对规则，只在本机调整授权。'),
    'READ_ONLY_MODE': ('当前为只读模式。', '需要写入时由用户在本机明确选择读写模式。'),
    'KEYSTORE_UNAVAILABLE': ('系统安全凭据库不可用。', '检查系统凭据库及用户会话，不回退明文。'),
    'KEYSTORE_READ_FAILED': ('系统凭据读取失败。', '解锁凭据库并核对权限，不提供聊天明文。'),
    'RUNTIME_KEY_MISSING': ('没有可用 Runtime 凭据。', '在独立本机终端用 key set 隐藏录入。'),
    'TUNNEL_AUTHENTICATION_FAILED': ('Tunnel 报告认证失败。', '本机检查凭据及所属组织。'),
    'TUNNEL_PERMISSION_DENIED': ('Tunnel 报告权限不足。', '核对目标 Tunnel 的 Read/Use 与工作区关联。'),
    'DNS_FAILURE': ('Tunnel 报告域名解析失败。', '检查 DNS 和代理。'),
    'TLS_FAILURE': ('Tunnel 报告证书或 TLS 错误。', '检查时间、代理证书和信任链，不关闭 TLS 验证。'),
    'DISK_FULL': ('磁盘空间不足。', '检查目标卷、备份与日志空间。'),
    'LOG_WRITE_FAILED': ('日志未能落盘。', '检查日志目录权限和磁盘空间；业务操作可能已完成。'),
    'COMMAND_TIMEOUT': ('子进程超时。', '检查任务状态及超时预算，不把启动成功当成完成。'),
    'PROCESS_TIMEOUT': ('子进程超时或未能在预算内结束。', '核对任务状态，不反复启动相同写操作。'),
}
INT_FIELDS = {'duration_ms', 'exit_code', 'child_pid', 'holder_pid', 'errno', 'winerror',
              'tool_count', 'bytes', 'timeout_seconds', 'failed_count', 'item_count'}
BOOL_FIELDS = {'ok', 'completed', 'succeeded', 'retryable', 'truncated', 'enable_commands', 'enable_git_push'}
TEXT_FIELDS = {'tool', 'operation', 'method', 'mode', 'state', 'stage', 'error_type',
               'request_id', 'session_id', 'holder_started_at', 'reported_status'}


@dataclass(frozen=True)
class LogSettings:
    enabled: bool = True
    level: str = 'INFO'
    max_bytes: int = 5 * 1024 * 1024
    backup_count: int = 5
    retention_days: int = 14

    @classmethod
    def parse(cls, raw=None):
        if raw is None:
            return cls()
        if not isinstance(raw, dict) or raw.keys() - cls.__dataclass_fields__.keys():
            raise ValueError('logging must contain only enabled/level/max_bytes/backup_count/retention_days')
        result = cls(**raw)
        if type(result.enabled) is not bool or result.level not in LEVELS:
            raise ValueError('invalid logging enabled/level')
        for key, low, high in (('max_bytes', MAX_RECORD, 50*1024*1024), ('backup_count', 0, 10), ('retention_days', 1, 90)):
            value = getattr(result, key)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'logging.{key} is outside its supported range')
        return result


def _token(value, limit=128):
    """Keep useful safe IDs; hash opaque/oversized strings rather than log them."""
    text = redact(str(value))
    if len(text) <= limit and re.fullmatch(r'[A-Za-z0-9_+.:/@\[\]-]+', text):
        return text
    return 'sha256:' + hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:24]


def error_fields(error):
    """No raw exception text, traceback, result, source, URL or secret ever here."""
    if isinstance(error, BaseException):
        fault = normalize_error(error)
        code, details, retryable = fault.code, fault.details, fault.retryable
        kind = type(error).__name__
    else:
        error = error if isinstance(error, dict) else {}
        code, details, retryable = error.get('code', 'OPERATION_FAILED'), error.get('details', {}), error.get('retryable', False)
        kind = None
    code = _token(code)
    details = details if isinstance(details, dict) else {}
    result = {'error_code': code, 'retryable': bool(retryable)}
    if kind:
        result['error_type'] = _token(kind)
    for key in ('errno', 'winerror', 'exit_code'):
        if type(details.get(key)) is int:
            result[key] = details[key]
    holder = details.get('holder', {})
    if isinstance(holder, dict):
        if type(holder.get('pid')) is int:
            result['holder_pid'] = holder['pid']
        if type(holder.get('started_at')) in (int, float):
            result['holder_started_at'] = str(holder['started_at'])
    if isinstance(details.get('session_id'), str):
        result['session_id'] = _token(details['session_id'])
    return result


def safe_fields(fields):
    result = {}
    for key, value in fields.items():
        if key in INT_FIELDS and type(value) is int:
            result[key] = value
        elif key in BOOL_FIELDS and type(value) is bool:
            result[key] = value
        elif key in TEXT_FIELDS and value is not None:
            result[key] = _token(value)
        elif key == 'error_code' and value is not None:
            code = _token(value)
            result['error_code'] = code
            result['cause'], result['remediation'] = CAUSES.get(code, (
                '操作未完成；原因类别见 error_code/errno。',
                '按 request_id 对照工具错误和 docs/TROUBLESHOOTING.md；不要分享原始密钥或配置。'))
    return redact(result)


def _private_directory(path):
    path = Path(path)
    # Reject managed-directory symlinks/junctions before mkdir/chmod.
    for part in (path.parent, path):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise OSError('unsafe log directory')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        path.chmod(0o700)
    return path


def _open_regular(path, flags):
    path = Path(path)
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        raise OSError('unsafe log file')
    fd = os.open(path, flags | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise OSError('log must be a single-link regular file')
        if os.name != 'nt':
            if st.st_uid != os.geteuid():
                raise OSError('log not owned by current user')
            if flags & (os.O_WRONLY | os.O_RDWR):
                os.fchmod(fd, 0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise


class EventLog:
    def __init__(self, config=None, *, state_dir=None, settings=None):
        self.directory = Path(state_dir or locations()[2]).expanduser() / 'logs'
        self.process_id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.dropped = 0
        self.last_error = None
        self._warned = False
        self.settings_error = False
        try:
            if settings is None and config:
                p = Path(config).expanduser()
                if p.exists():
                    with p.open('rb') as f:
                        raw = f.read(262145)
                    if len(raw) > 262144:
                        raise ValueError('configuration too large')
                    settings = json.loads(raw).get('logging')
            self.settings = LogSettings.parse(settings)
        except (OSError, ValueError, TypeError, AttributeError):
            # Invalid app config must still produce a startup error log.
            self.settings = LogSettings()
            self.settings_error = True
            self._warning('LOG_CONFIG_INVALID')

    def _warning(self, code, error=None):
        if self._warned:
            return
        self._warned = True
        record = {'event': code, 'cause': '日志配置/存储不可用，可能缺少日志记录。',
                  'remediation': '运行 local-mcp logs path 和 doctor，检查权限、配置和磁盘；不要自动重试写操作。'}
        if error:
            record['error_type'] = type(error).__name__
            record['errno'] = getattr(error, 'errno', None)
        try:
            print(json.dumps(record, ensure_ascii=False), file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass

    @contextmanager
    def _locked(self, component):
        if component not in COMPONENTS:
            raise ValueError('unknown log component')
        _private_directory(self.directory)
        fd = _open_regular(self.directory / (component + '.lock'), os.O_RDWR | os.O_CREAT)
        held = False
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b'\0')
            until = time.monotonic() + 0.5
            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = True
                    break
                except OSError:
                    if time.monotonic() >= until:
                        raise TimeoutError('log lock timeout') from None
                    time.sleep(0.01)
            yield
        finally:
            if held:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)  # Never unlink a live lock inode.

    def _check_segment(self, path):
        try:
            fd = _open_regular(path, os.O_RDONLY)
        except FileNotFoundError:
            return None
        try:
            return os.fstat(fd)
        finally:
            os.close(fd)

    def _append(self, component, data):
        base = self.directory / (component + '.jsonl')
        with self.lock, self._locked(component):
            now = time.time()
            cutoff = now - self.settings.retention_days * 86400
            # Known managed names only; never recursively delete user files.
            for index in range(10, 0, -1):
                path = Path(str(base) + f'.{index}')
                st = self._check_segment(path)
                if st and (index > self.settings.backup_count or st.st_mtime < cutoff):
                    path.unlink()
            st = self._check_segment(base)
            if st and st.st_mtime < cutoff:
                base.unlink()
                st = None
            if st and st.st_size + len(data) > self.settings.max_bytes:
                if not self.settings.backup_count:
                    base.unlink()
                else:
                    for index in range(self.settings.backup_count, 0, -1):
                        src = base if index == 1 else Path(str(base) + f'.{index-1}')
                        dst = Path(str(base) + f'.{index}')
                        if src.exists():
                            self._check_segment(src)
                            self._check_segment(dst)
                            os.replace(src, dst)
            fd = _open_regular(base, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
            try:
                view = memoryview(data)
                while view:
                    n = os.write(fd, view)
                    if n <= 0:
                        raise OSError('short log write')
                    view = view[n:]
            finally:
                os.close(fd)

    def emit(self, component, event, level='INFO', **fields):
        if not self.settings.enabled or LEVELS[level] < LEVELS[self.settings.level]:
            return True
        record = {'timestamp': datetime.now(timezone.utc).isoformat(timespec='microseconds'),
                  'level': level, 'component': component, 'event': _token(event),
                  'event_id': uuid.uuid4().hex, 'process_id': self.process_id,
                  'pid': os.getpid(), **safe_fields(fields)}
        try:
            data = (json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
            if len(data) > MAX_RECORD:
                raise ValueError('event too large')
            self._append(component, data)
            self.last_error = None
            self._warned = False
            return True
        except (OSError, ValueError) as exc:
            self.dropped += 1
            self.last_error = {'code': 'LOG_WRITE_FAILED', 'error_type': type(exc).__name__, 'errno': getattr(exc, 'errno', None)}
            self._warning('LOG_WRITE_FAILED', exc)
            return False  # Logging failure never re-runs or rolls back a business operation.

    def status(self):
        return {'directory': str(self.directory), **asdict(self.settings),
                'settings_valid': not self.settings_error, 'dropped_in_this_process': self.dropped,
                'last_error': self.last_error, 'restart_required_after_config_change': True}

    def probe(self):
        if not self.settings.enabled:
            return {**self.status(), 'status': 'disabled', 'ok': True}
        ok = self.emit('cli', 'logging_probe', self.settings.level)
        return {**self.status(), 'status': 'pass' if ok and not self.settings_error else 'fail',
                'ok': ok and not self.settings_error}


def _segments(directory, component='all'):
    components = COMPONENTS if component == 'all' else (component,)
    if any(c not in COMPONENTS for c in components):
        raise ValueError('invalid component')
    directory = Path(directory)
    if directory.is_symlink() or directory.parent.is_symlink():
        raise OSError('unsafe log directory')
    result = []
    if not directory.exists():
        return result
    guard = EventLog(state_dir=directory.parent)
    for c in components:
        with guard._locked(c):
            for index in range(10, -1, -1):
                path = directory / (c + '.jsonl' + (f'.{index}' if index else ''))
                try:
                    fd = _open_regular(path, os.O_RDONLY)
                except FileNotFoundError:
                    continue
                with os.fdopen(fd, 'rb') as f:
                    st = os.fstat(f.fileno())
                result.append((path, (st.st_dev, st.st_ino), st.st_size))
    return result


def _read_records(path, offset=0, stop=None, *, tail_bytes=None, identity=None):
    """Serialize readers with writers too: Windows readers must not block rename."""
    component = Path(path).name.split('.jsonl')[0]
    guard = EventLog(state_dir=Path(path).parent.parent)
    with guard._locked(component):
        return _read_records_unlocked(path, offset, stop, tail_bytes=tail_bytes, identity=identity)


def _read_records_unlocked(path, offset=0, stop=None, *, tail_bytes=None, identity=None):
    fd = _open_regular(path, os.O_RDONLY)
    with os.fdopen(fd, 'rb') as f:
        st = os.fstat(f.fileno())
        if identity is not None and identity != (st.st_dev, st.st_ino):
            raise FileNotFoundError('log rotated since snapshot')
        size = min(os.fstat(f.fileno()).st_size, stop) if stop is not None else os.fstat(f.fileno()).st_size
        begin = max(offset, size-tail_bytes) if tail_bytes is not None else offset
        f.seek(min(begin, size))
        if begin and tail_bytes is not None and begin > offset:
            f.readline(MAX_RECORD+1)  # Drop only a potentially partial leading record.
        start = f.tell()
        records, invalid = [], 0
        while f.tell() < size and f.tell()-start < MAX_READ:
            pos = f.tell()
            line = f.readline(min(MAX_RECORD+1, size-pos))
            if not line.endswith(b'\n'):
                if len(line) > MAX_RECORD:
                    invalid += 1
                    while f.tell() < size:
                        part = f.readline(min(MAX_RECORD+1, size-f.tell()))
                        if part.endswith(b'\n'):
                            break
                    continue
                f.seek(pos)  # An incomplete writer record can be read on the next poll.
                break
            try:
                record = json.loads(line)
                if not isinstance(record, dict) or record.get('component') not in COMPONENTS or record.get('level') not in LEVELS:
                    raise ValueError('not a log record')
                # Rebuild allowlisted schema on access/export, even for edited log files.
                meta = {k: _token(record.get(k, 'unknown')) for k in
                        ('timestamp','level','component','event','event_id','process_id')}
                meta['pid'] = record.get('pid') if type(record.get('pid')) is int else None
                records.append({**meta, **safe_fields(record)})
            except (ValueError, UnicodeError):
                invalid += 1
        return records, f.tell(), invalid


def recent(directory, *, component='all', level='DEBUG', tail=100, request_id=None):
    if level not in LEVELS or type(tail) is not int or not 0 <= tail <= MAX_TAIL:
        raise ValueError('invalid level/tail (0..5000)')
    selected, invalid, scan_limited, total_matches = [], 0, False, 0
    if tail == 0:
        return {'ok': True, 'records': [], 'returned': 0, 'invalid_records': 0, 'scan_limited': False}
    for path, identity, size in _segments(directory, component):
        try:
            rows, _, bad = _read_records(path, stop=size, tail_bytes=MAX_READ, identity=identity)
        except FileNotFoundError:
            continue  # Rotated between snapshot and open; another segment may contain it.
        invalid += bad
        scan_limited |= size > MAX_READ
        matches = [r for r in rows if LEVELS[r['level']] >= LEVELS[level] and
                   (request_id is None or r.get('request_id') == _token(request_id))]
        total_matches += len(matches)
        selected.extend(matches)
        selected.sort(key=lambda r: (r['timestamp'], r['event_id']))
        selected = selected[-tail:]
    selected.sort(key=lambda r: (r['timestamp'], r['event_id']))
    return {'ok': True, 'records': selected[-tail:], 'returned': min(len(selected), tail),
            'invalid_records': invalid, 'scan_limited': scan_limited, 'tail_limited': total_matches > tail}


def render(record, json_output=False):
    if json_output:
        return json.dumps(record, ensure_ascii=False)
    keys = ('tool','operation','stage','request_id','session_id','state','exit_code','duration_ms','error_code','cause','remediation')
    details = ' '.join(f'{k}={record[k]}' for k in keys if k in record)
    return f"{record['timestamp']} {record['level']:<7} [{record['component']}] {record['event']} {details}".rstrip()


def follow(directory, *, component='all', level='DEBUG', tail=50, request_id=None,
           json_output=False, stop_event=None, interval=0.5, output=None):
    if level not in LEVELS or not 0 <= tail <= MAX_TAIL:
        raise ValueError('invalid level/tail')
    output = output or sys.stdout
    offsets = {}
    # Initial snapshot + offsets together, so appends between initial display/poll aren't lost.
    initial = []
    for path, identity, size in _segments(directory, component):
        try:
            rows, offset, _ = _read_records(path, stop=size, tail_bytes=MAX_READ, identity=identity)
        except FileNotFoundError:
            continue
        offsets[identity] = offset
        initial.extend(rows)
    def matches(row):
        return LEVELS[row['level']] >= LEVELS[level] and (request_id is None or row.get('request_id') == _token(request_id))
    initial = sorted((r for r in initial if matches(r)), key=lambda r: (r['timestamp'], r['event_id']))
    for row in initial[-tail:] if tail else []:
        print(render(row, json_output), file=output, flush=True)
    while not (stop_event and stop_event.is_set()):
        if stop_event:
            stop_event.wait(interval)
        else:
            time.sleep(interval)
        current, rows = set(), []
        for path, identity, size in _segments(directory, component):
            current.add(identity)
            start = offsets.get(identity, 0)
            if size < start:  # Truncation from outside this writer.
                start = 0
                print('[LOG_HISTORY_GAP] 日志被截短；不能保证历史完整。', file=sys.stderr)
            if start == size:
                continue
            try:
                items, end, bad = _read_records(path, offset=start, stop=size, identity=identity)
            except FileNotFoundError:
                continue
            offsets[identity] = end
            rows.extend(r for r in items if matches(r))
            if bad:
                print('[LOG_INVALID_RECORD] 已跳过不完整或非法日志记录。', file=sys.stderr)
        # Rotation beyond retention can remove unread data; never claim a complete audit trail.
        offsets = {key: val for key, val in offsets.items() if key in current}
        for row in sorted(rows, key=lambda r: (r['timestamp'], r['event_id'])):
            print(render(row, json_output), file=output, flush=True)


def export(directory, destination, **filters):
    result = recent(directory, **filters)
    from .storage import write_private
    path = Path(destination).expanduser()
    write_private(path, (json.dumps({'format': 'local-mcp-events-v1',
        'note': '所选过滤条件下最近的日志，不是全部历史；请审核后分享。', **result}, ensure_ascii=False, indent=2)+'\n').encode())
    return {'ok': True, 'path': str(path), 'returned': result['returned'],
            'invalid_records': result['invalid_records'], 'scan_limited': result['scan_limited'], 'overwritten': False}
