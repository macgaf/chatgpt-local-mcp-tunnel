"""有备份、哈希前置条件及明确部分失败结果的删除操作。"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import stat
import time
from .errors import Fault
from .storage import Lease, digest, expected_matches, parent_handle, read_bytes, snapshot


class FileActions:
    def _delete_path(self, path):
        p = self.policy.require(path, write=True)
        supplied = Path(path).expanduser()
        supplied = supplied if supplied.is_absolute() else self.policy.root / supplied
        if (p != supplied or p.is_symlink() or
                getattr(p, 'is_junction', lambda: False)() or '.git' in p.parts):
            raise Fault('DELETE_PATH_DENIED', '删除目标含链接或 Git 元数据。', 'unsafe deletion target',
                        '使用真实的普通项目文件；Git 元数据只能通过 Git 工具维护。')
        return p

    def _unlink_checked(self, p, old):
        with parent_handle(self.policy, p) as parent:
            current = read_bytes(self.policy, str(p))[1]
            expected_matches(current, digest(old))
            os.unlink(p if parent is None else p.name,
                      **({} if parent is None else {'dir_fd': parent}))

    def delete_file(self, path, expected_sha256, dry_run=False):
        p = self._delete_path(path)
        self.commands.guard_mutation([p])
        with Lease(self.policy.state_dir, p, 'delete_file'):
            old = read_bytes(self.policy, str(p))[1]
            expected_matches(old, expected_sha256)
            if dry_run:
                return {'ok': True, 'dry_run': True, 'path': self.policy.relative(p), 'sha256': digest(old)}
            backup = snapshot(self.policy, p, old)
            self._unlink_checked(p, old)
            if p.exists():
                raise Fault('DELETE_POSTCONDITION_FAILED', '删除后目标重新出现。', 'concurrent mutation',
                            '检查实际文件，不自动重复删除。', backup_id=backup)
            return {'ok': True, 'deleted': True, 'path': self.policy.relative(p), 'backup_id': backup}

    def _directory_snapshot(self, p):
        rows = []; files = {}; directories = [p]; size = 0
        deadline = time.monotonic() + 10
        for root, dirs, names in os.walk(p, followlinks=False, onerror=lambda exc: (_ for _ in ()).throw(exc)):
            for name in sorted(dirs + names):
                if len(rows) >= min(self.policy.max_search_files, 1000) or time.monotonic() > deadline:
                    raise Fault('DELETE_BUDGET', '目录删除预检超过预算。', 'entry/time limit', '分批处理较小目录。')
                child = self._delete_path(str(Path(root) / name))
                info = child.lstat()
                if stat.S_ISDIR(info.st_mode):
                    directories.append(child)
                    rows.append({'path': child.relative_to(p).as_posix(), 'type': 'directory'})
                elif stat.S_ISREG(info.st_mode):
                    data = read_bytes(self.policy, str(child))[1]
                    size += len(data)
                    if size > self.policy.max_patch_bytes:
                        raise Fault('DELETE_BUDGET', '目录内容超过备份预算。', 'aggregate byte limit', '分批处理较小目录。')
                    files[child] = data
                    rows.append({'path': child.relative_to(p).as_posix(), 'type': 'file', 'sha256': digest(data)})
                else:
                    raise Fault('DELETE_PATH_DENIED', '目录含特殊文件。', 'nonregular entry', '在本机处理该条目。')
        rows.sort(key=lambda row: row['path'])
        manifest = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        return digest(manifest), files, directories, size

    def delete_directory(self, path, expected_sha256=None, dry_run=True):
        p = self._delete_path(path)
        if not p.is_dir():
            raise ValueError('path must be a directory')
        self.commands.guard_mutation([p])
        with ExitStack() as stack:
            stack.enter_context(Lease(self.policy.state_dir, p, 'delete_directory'))
            sha, files, dirs, size = self._directory_snapshot(p)
            plan = {'path': self.policy.relative(p), 'sha256': sha,
                    'file_count': len(files), 'directory_count': len(dirs), 'size': size}
            if dry_run:
                if expected_sha256 is not None and expected_sha256 != sha:
                    raise Fault('HASH_CONFLICT', '目录内容已变化。', 'manifest mismatch', '重新预览。')
                return {'ok': True, 'dry_run': True, **plan}
            if expected_sha256 is None or expected_sha256 != sha:
                raise Fault('HASH_CONFLICT', '删除目录需要匹配的预览哈希。', 'missing or stale manifest',
                            '先 dry_run=true，再传 sha256；不得盲目刷新哈希。')
            for item in sorted((set(files) | set(dirs)) - {p}, key=str):
                stack.enter_context(Lease(self.policy.state_dir, item, 'delete_directory'))
            if self._directory_snapshot(p)[0] != sha:
                raise Fault('HASH_CONFLICT', '加锁期间目录发生变化。', 'manifest mismatch', '重新核查。')
            backups = [{'path': self.policy.relative(file), 'backup_id': snapshot(self.policy, file, data)}
                       for file, data in sorted(files.items())]
            deleted = []; removed_dirs = []
            try:
                for file, data in sorted(files.items()):
                    self._unlink_checked(file, data)
                    deleted.append(self.policy.relative(file))
                for directory in sorted(dirs, key=lambda item: (-len(item.parts), str(item))):
                    with parent_handle(self.policy, directory) as parent:
                        os.rmdir(directory if parent is None else directory.name,
                                 **({} if parent is None else {'dir_fd': parent}))
                    removed_dirs.append(self.policy.relative(directory))
            except Exception as exc:
                raise Fault('DELETE_INCOMPLETE', '目录删除未全部完成，停止操作。', type(exc).__name__,
                            '核查 deleted 和备份；先重建父目录，再用 restore_file 和 MISSING 恢复缺失文件。',
                            deleted=deleted, removed_directories=removed_dirs, backups=backups) from exc
            return {'ok': True, 'deleted': True, **plan, 'backups': backups,
                    'removed_directories': removed_dirs, 'atomic': False}
