"""Bounded reads, per-path OS leases, conflict guards and atomic single-file writes."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import sys
import uuid
from .errors import Fault


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_dir(path):
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    if p.is_symlink():
        raise Fault('UNSAFE_STATE_PATH', '状态目录不能是符号链接。', str(p), '使用用户专属真实目录。')
    if os.name != 'nt':
        p.chmod(0o700)
    return p


def write_private(path, data):
    p = Path(path)
    private_dir(p.parent)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


@contextmanager
def parent_handle(policy, path):
    """POSIX directory descriptors prevent following swapped path components.

    Windows uses revalidation and no-link policy, not a same-user adversarial sandbox.
    """
    path = Path(path)
    if os.name == 'nt':
        cur = policy.root
        for part in path.relative_to(policy.root).parts[:-1]:
            cur /= part
            if cur.is_symlink() or getattr(cur, 'is_junction', lambda: False)():
                raise Fault('REPARSE_POINT_DENIED', '拒绝重解析目录。', str(cur), '使用真实目录。')
        yield None
        return
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(policy.root, flags)
    try:
        for part in path.relative_to(policy.root).parts[:-1]:
            nxt = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def read_bytes(policy, path, limit=None):
    p = policy.require(str(path))
    cap = limit if limit is not None else policy.max_file_size
    with parent_handle(policy, p) as parent:
        fd = os.open(p if parent is None else p.name,
                     os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0),
                     **({} if parent is None else {'dir_fd': parent}))
        with os.fdopen(fd, 'rb') as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                raise Fault('NOT_REGULAR_FILE', '只允许普通文件。', '管道、设备和套接字不提供内容读取。', '选择普通文件。')
            if st.st_nlink > 1:
                raise Fault('HARDLINK_DENIED', '拒绝多硬链接文件。', '硬链接可能绕过基于路径的敏感文件规则。',
                            '在已授权目录中创建普通副本，不要链接凭据文件。')
            if st.st_size > cap:
                raise Fault('FILE_TOO_LARGE', '文件超过本次读取上限。', f'{st.st_size} > {cap}',
                            '缩小文件或在本机调整 max_file_size。', size=st.st_size, limit=cap)
            data = f.read(cap + 1)
            if len(data) > cap:
                raise Fault('FILE_GREW', '读取时文件增长，已停止。', '并发修改超过读取上限。', '待写入完成后重新读取。', retryable=True)
            end = os.fstat(f.fileno())
            if (st.st_size, st.st_mtime_ns) != (end.st_size, end.st_mtime_ns):
                raise Fault('FILE_CHANGED', '文件在读取过程中发生变化。', '有其他写入者。', '重新读取并使用新 SHA-256。', retryable=True)
            return p, data, st


class Lease:
    def __init__(self, state, path, operation, request_id=None):
        self.base = private_dir(Path(state) / 'locks')
        lock_name=os.path.normcase(str(path))
        if sys.platform=='darwin':
            lock_name=lock_name.casefold()
        self.path = self.base / (digest(lock_name.encode()) + '.lock')
        self.meta = {'pid': os.getpid(), 'operation': operation, 'path': str(path),
                     'started_at': time.time(), 'request_id': request_id or uuid.uuid4().hex,
                     'lock_type': 'local_mcp_path_lease'}
        self.fd = None

    def __enter__(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self.fd = os.fdopen(fd, 'r+b', buffering=0)
        if os.fstat(fd).st_size == 0:
            self.fd.write(b'\n')
        try:
            self.fd.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fd.seek(1)
            try:
                holder = json.loads(self.fd.read(8192))
            except (ValueError, UnicodeError):
                holder = {'pid': None, 'operation': 'unknown', 'metadata_valid': False}
            self.fd.close()
            self.fd = None
            raise Fault('FILE_LOCKED', '另一个 MCP 操作持有此文件的写锁。',
                        '同一目标文件的写操作互斥；其他文件不受此锁影响。',
                        '核对持有者和开始时间；等待操作结束后重新读取。不要删除锁文件或取消未知进程。',
                        retryable=True, holder=holder, metadata_is_advisory=True) from None
        self.fd.seek(1)
        self.fd.write(json.dumps(self.meta).encode())
        self.fd.truncate()
        return self

    def __exit__(self, *exc):
        if self.fd:
            try:
                self.fd.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
            finally:
                self.fd.close()
                self.fd = None
        # Do NOT unlink: unlinking an advisory lock file creates a race on a new inode.


def expected_matches(current, expected):
    actual = 'MISSING' if current is None else digest(current)
    if expected is None and current is not None:
        raise Fault('PRECONDITION_REQUIRED', '覆盖现有文件必须提供原 SHA-256。',
                    '禁止盲目覆盖 IDE 或其他代理的新修改。', '先 read_file/file_info，再传 expected_sha256。', actual_sha256=actual)
    if expected is not None and expected != actual:
        raise Fault('HASH_CONFLICT', '文件已变化，未执行写入。', 'expected_sha256 与磁盘当前版本不同。',
                    '重新读取并合并修改，不要自动用新哈希强行覆盖。', expected_sha256=expected,
                    actual_sha256=actual, retryable=False)
    return actual


def snapshot(policy, path, old):
    backup_id = uuid.uuid4().hex
    base = private_dir(policy.state_dir / 'backups')
    write_private(base / (backup_id + '.bin'), old)
    write_private(base / (backup_id + '.json'), json.dumps({
        'id': backup_id, 'path': str(path), 'sha256': digest(old), 'created_at': time.time(),
        'root': str(policy.root), 'size': len(old)}, ensure_ascii=False).encode())
    return backup_id


def commit_bytes(policy, p, new, old, expected, *, dry_run=False):
    """Caller owns a Lease. Each commit is atomic; not a multi-file transaction."""
    before = expected_matches(old, expected)
    if len(new) > policy.max_file_size:
        raise Fault('FILE_TOO_LARGE', '写入内容超过限制。', str(len(new)), '调整本机上限或缩小文件。')
    if new == old:
        return {'ok': True, 'changed': False, 'sha256': digest(new), 'path': policy.relative(p)}
    if dry_run:
        return {'ok': True, 'dry_run': True, 'path': policy.relative(p),
                'before_sha256': before, 'after_sha256': digest(new), 'bytes': len(new)}
    backup_id = snapshot(policy, p, old) if old is not None else None
    # Recheck after backup, immediately before replace. External writers do not honor our lease.
    current = read_bytes(policy, str(p))[1] if p.exists() else None
    expected_matches(current, before)
    with parent_handle(policy, p) as parent:
        tmp = '.local-mcp-' + uuid.uuid4().hex + '.tmp'
        temp_path = p.parent / tmp if parent is None else tmp
        target = p if parent is None else p.name
        kw = {} if parent is None else {'dir_fd': parent}
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600, **kw)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(new)
                f.flush()
                if old is not None and os.name != 'nt':
                    os.fchmod(f.fileno(), stat.S_IMODE(p.stat().st_mode) & 0o777)
                os.fsync(f.fileno())
            if old is None:
                linkkw = {} if parent is None else {'src_dir_fd': parent, 'dst_dir_fd': parent}
                try:
                    os.link(temp_path, target, follow_symlinks=False, **linkkw)
                except FileExistsError as exc:
                    raise Fault('HASH_CONFLICT', '目标在创建前被另一写入者创建。',
                                '独占创建已拒绝覆盖，原目标未被本次操作替换。',
                                '重新读取目标后决定如何合并。') from exc
            else:
                replacekw = {} if parent is None else {'src_dir_fd': parent, 'dst_dir_fd': parent}
                os.replace(temp_path, target, **replacekw)
            if parent is not None:
                os.fsync(parent)
        finally:
            try:
                os.unlink(temp_path, **kw)
            except FileNotFoundError:
                pass
    verified = read_bytes(policy, str(p))[1]
    if digest(verified) != digest(new):
        raise Fault('POST_WRITE_CONFLICT', '写入后校验发现其他修改。', '文件已提交，但随后被另一个写入者改变。',
                    '停止继续改写，读取当前文件并核查备份。', backup_id=backup_id,
                    intended_sha256=digest(new), actual_sha256=digest(verified))
    return {'ok': True, 'changed': True, 'path': policy.relative(p), 'sha256': digest(new),
            'previous_sha256': before, 'backup_id': backup_id, 'bytes': len(new)}
