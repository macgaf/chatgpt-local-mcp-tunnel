"""真实 Git linked worktree 操作、共享锁及范围拒绝回归。"""
import os
import pytest
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.storage import Lease
from home_readonly_mcp.policy import Policy
from home_readonly_mcp.service import HomeService
from test_git_capabilities import raw, fault


def rewrite_gitfile(path, content):
    # Windows 下 Git 将 .git 标为隐藏文件；r+b 不使用 CREATE_ALWAYS，保留属性。
    with path.open('r+b') as stream:
        stream.write(content.encode('utf-8'))
        stream.truncate()


def linked(space):
    _, root, policy, svc = space
    main = root / 'main'; main.mkdir()
    policy.git_user_name = 'Synthetic'; policy.git_user_email = 'test@example.invalid'
    (main / 'one.txt').write_text('one\n')
    svc.git_init('main'); svc.git_add('main'); svc.git_commit('main', 'initial')
    wt = root / 'linked'
    raw(main, 'worktree', 'add', '-b', 'topic', str(wt))
    return main, wt, policy, svc


def test_linked_full_local_workflow(space):
    main, wt, policy, svc = linked(space)
    assert svc.git_status('linked')['branch'] == 'topic'
    assert svc.workspace_context('linked')['git_status']['branch'] == 'topic'
    assert svc.git_log('linked')['commits'][0]['subject'] == 'initial'
    (wt / 'one.txt').write_text('changed\n')
    assert '+changed' in svc.git_diff('linked')['diff']
    svc.git_add('linked', ['one.txt'])
    assert '+changed' in svc.git_diff('linked', staged=True)['diff']
    assert not svc.git_diff('main', staged=True)['diff']
    commit = svc.git_commit('linked', 'linked change')['commit_sha']
    assert svc.git_status('main')['head'] != commit
    assert svc.git_create_branch('new', 'linked')['created']
    assert svc.git_switch_branch('topic', 'linked')['switched']
    fault('GIT_COMMAND_FAILED', lambda: svc.git_switch_branch('main', 'linked'))
    assert raw(main, 'branch', '--show-current').strip() == b'main'
    assert not policy.enable_commands


def test_relative_gitfile_and_overlay(space):
    main, wt, _, svc = linked(space)
    gitdir = main / '.git/worktrees/linked'
    rewrite_gitfile(wt / '.git', 'gitdir: ../main/.git/worktrees/linked\n')
    raw(main, 'config', 'extensions.worktreeConfig', 'true')
    raw(main, 'config', '--file', str(gitdir / 'config.worktree'), 'core.worktree', str(wt))
    assert svc.git_status('linked')['ok']
    raw(main, 'config', '--file', str(gitdir / 'config.worktree'), 'include.path', '/never-read')
    fault('UNSAFE_GIT_CONFIG', lambda: svc.git_status('linked'))


def test_scope_and_shared_lease(space):
    main, wt, policy, svc = linked(space)
    with Lease(policy.state_dir, main / '.git', 'fixture'):
        fault('FILE_LOCKED', lambda: svc.git_status('linked'))
    policy.write_roots = ['linked/**']
    assert svc.git_status('linked')['ok']
    with pytest.raises(Fault):
        svc.git_create_branch('denied', 'linked')
    policy.write_roots = ['main/**', 'linked/**']
    assert svc.git_create_branch('allowed', 'linked')['created']
    with HomeServiceContext(Policy(root=wt, mode='read_write', state_dir=space[0] / 'state2')) as narrow:
        fault('OUTSIDE_ROOT', lambda: narrow.git_status())


class HomeServiceContext:
    def __init__(self, policy): self.svc = HomeService(policy)
    def __enter__(self): return self.svc
    def __exit__(self, *args): self.svc.close()


@pytest.mark.parametrize('target', ['gitdir', 'commondir', 'backlink', 'alternates', 'include', 'hardlink'])
def test_reject_unsafe_linked_metadata(space, target):
    main, wt, _, svc = linked(space)
    gitdir = main / '.git/worktrees/linked'
    if target == 'gitdir': rewrite_gitfile(wt / '.git', 'gitdir: /outside\n')
    if target == 'commondir': (gitdir / 'commondir').write_text('/outside\n')
    if target == 'backlink': (gitdir / 'gitdir').write_text(str(main / '.git') + '\n')
    if target == 'alternates': (main / '.git/objects/info/alternates').write_text('/outside\n')
    if target == 'include': raw(main, 'config', 'include.path', '/never-read')
    if target == 'hardlink':
        try: os.link(wt / '.git', space[0] / 'hardlink')
        except OSError: pytest.skip('hardlinks unavailable')
    with pytest.raises(Fault): svc.git_status('linked')


def test_linked_git_markers(space):
    main, _, _, svc = linked(space)
    gitdir = main / '.git/worktrees/linked'
    (gitdir / 'MERGE_HEAD').write_text('fixture')
    fault('GIT_OPERATION_IN_PROGRESS', lambda: svc.git_create_branch('blocked', 'linked'))
    (gitdir / 'MERGE_HEAD').unlink()
    (main / '.git/packed-refs.lock').write_text('fixture')
    fault('GIT_LOCKED', lambda: svc.git_create_branch('blocked', 'linked'))


def test_linked_symlink_pointer_is_rejected(space):
    _, wt, _, svc = linked(space)
    original = wt / '.git'; moved = wt / 'pointer'
    original.rename(moved)
    try: original.symlink_to(moved)
    except OSError: pytest.skip('symlinks unavailable')
    fault('UNSAFE_GIT_METADATA', lambda: svc.git_status('linked'))
