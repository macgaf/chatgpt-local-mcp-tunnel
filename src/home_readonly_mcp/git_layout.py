"""解析普通仓库和授权范围内的 linked worktree；不让 Git 自行跟随指针。"""
from __future__ import annotations
import os
from pathlib import Path
import stat
from .errors import Fault


def unsafe(reason):
    return Fault('UNSAFE_GIT_METADATA', 'Git 元数据关联无效或超出授权范围。', reason,
                 '核查 worktree 注册及 root/write_roots；不会自动扩大权限。')


def checked_path(policy, path):
    # 必须在规范化 .. 之前检查链接，避免 alias/../target 被悄悄接受。
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise unsafe('linked metadata path')
    path = Path(os.path.abspath(path))
    policy.relative(path)
    if any(path == p or p in path.parents for p in policy.protected_paths):
        raise unsafe('protected runtime metadata')
    if path.resolve() != path:
        raise unsafe('noncanonical metadata path')
    return path


def pointer(policy, path, prefix=''):
    checked_path(policy, path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 4096:
            raise unsafe('pointer must be a bounded regular file')
        data = stream.read(4097)
    text = data.decode('utf-8', 'strict').rstrip('\r\n')
    if not text.startswith(prefix):
        raise unsafe('invalid pointer prefix')
    text = text[len(prefix):]
    if not text or len(data) > 4096 or any(c in text for c in '\r\n\0'):
        raise unsafe('invalid pointer value')
    target = Path(text)
    return checked_path(policy, target if target.is_absolute() else path.parent / target)


def layout(policy, repo, *, write=False):
    entry = checked_path(policy, repo / '.git')
    if entry.is_dir():
        gitdir = common = entry
    elif entry.is_file():
        gitdir = pointer(policy, entry, 'gitdir: ')
        # 在读目标目录内任何内容前验证标准注册位置及所有者授权。
        if gitdir.parent.name != 'worktrees' or gitdir.parent.parent.name != '.git':
            raise Fault('UNSUPPORTED_GIT_LAYOUT', '不是标准 linked worktree 注册目录。',
                        'submodules and separate git dirs are unsupported', '使用标准 Git worktree 布局。')
        policy.require(str(gitdir.parent.parent.parent))
        policy.resolve(str(gitdir.parent.parent.parent / '.local-mcp-git-scope'), write=write)
        if not (gitdir / 'commondir').exists():
            raise Fault('UNSUPPORTED_GIT_LAYOUT', '只支持标准仓库或已注册 linked worktree。',
                        'missing commondir; submodules and separate git dirs are unsupported',
                        '使用标准 Git worktree 布局。')
        common = pointer(policy, gitdir / 'commondir')
        if (common.name != '.git' or gitdir.parent != common / 'worktrees' or
                pointer(policy, gitdir / 'gitdir') != entry):
            raise unsafe('worktree registration does not match')
    else:
        raise Fault('UNSUPPORTED_GIT_LAYOUT', '没有可用的 Git 元数据。', '.git missing or special',
                    '使用 git_init 或检查仓库。')
    if not gitdir.is_dir() or not common.is_dir():
        raise unsafe('missing metadata directory')
    # .git 本身被文件工具默认拒绝；仓库级操作通过所有者目录检查权限。
    # linked worktree 写共享引用和对象，必须同时有主仓库的写权限。
    for owner in {repo, common.parent}:
        policy.require(str(owner))
        policy.resolve(str(owner / '.local-mcp-git-scope'), write=write)
    return gitdir, common
