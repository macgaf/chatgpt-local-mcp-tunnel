"""Regression coverage for branch controls, worktree config and capability evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.server import Protocol, WRITES

pytestmark = pytest.mark.skipif(not shutil.which('git'), reason='native Git required')


def raw(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_TERMINAL_PROMPT='0')
    return subprocess.check_output(['git', '-c', 'core.hooksPath=' + os.devnull,
                                   '-c', 'core.fsmonitor=false', '-c', 'commit.gpgSign=false',
                                   *args], cwd=root, env=env, stderr=subprocess.PIPE)


def ready(space):
    root, policy, svc = space[1:]
    policy.git_user_name = 'Synthetic User'
    policy.git_user_email = 'synthetic@example.invalid'
    svc.git_init()
    svc.git_add()
    svc.git_commit(message='fixture')
    return root, policy, svc


def commit_raw(root, *paths):
    raw(root, 'add', '-f', '--', *paths)
    raw(root, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
        'commit', '-m', 'fixture only')


def fault(code, action):
    with pytest.raises(Fault) as exc:
        action()
    assert exc.value.code == code
    return exc.value


def test_branches_work_without_shell(space):
    root, policy, svc = ready(space)
    assert not policy.enable_commands
    before = svc.git_status()
    assert before['branch'] == 'main' and before['head']
    created = svc.git_create_branch('fix/security', expected_head=before['head'])
    assert created['created'] and created['checked_out']
    assert svc.git_status()['branch'] == 'fix/security'
    assert svc.git_create_branch('topic/only-ref', checkout=False)['created']
    assert svc.git_status()['branch'] == 'fix/security'
    listed = svc.git_branches(limit=1)
    assert listed['has_more'] and listed['total'] == 3
    assert svc.git_branches(offset=listed['next_offset'])['branches']
    assert svc.git_switch_branch('main')['switched']
    assert not svc.git_switch_branch('main')['switched']
    fault('GIT_BRANCH_EXISTS', lambda: svc.git_create_branch('fix/security'))
    fault('GIT_BRANCH_NOT_FOUND', lambda: svc.git_switch_branch('not-created'))
    assert not policy.enable_commands


@pytest.mark.parametrize('branch', ['--force', '-B', '@{-1}', 'HEAD', 'refs/../evil',
                                    'a..b', 'a.lock', 'a//b', 'a:', 'x\ny', 'a b', '', 'x' * 201])
def test_branch_name_injection_rejected(space, branch):
    root, _, svc = ready(space)
    fault('INVALID_BRANCH_NAME', lambda: svc.git_create_branch(branch))
    assert svc.git_status()['branch'] == 'main'
    assert svc.git_branches()['total'] == 1


@pytest.mark.parametrize('dirty', ['tracked', 'staged', 'untracked', 'protected'])
def test_branch_refuses_dirty_state(space, dirty):
    root, _, svc = ready(space)
    if dirty in ('tracked', 'staged'):
        (root / 'a.txt').write_text('unsaved')
        if dirty == 'staged': raw(root, 'add', 'a.txt')
    else:
        (root / ('.env' if dirty == 'protected' else 'new.txt')).write_text('PRIVATE_FIXTURE')
    err = fault('GIT_DIRTY_WORKTREE', lambda: svc.git_create_branch('fix/blocked'))
    assert 'PRIVATE_FIXTURE' not in str(err.payload())
    assert svc.git_branches()['total'] == 1


@pytest.mark.parametrize('marker', ['MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD',
                                    'REBASE_HEAD', 'rebase-merge', 'rebase-apply', 'sequencer', 'BISECT_LOG'])
def test_unfinished_operations_block_branch(space, marker):
    root, _, svc = ready(space)
    (root / '.git' / marker).write_text('fixture')
    fault('GIT_OPERATION_IN_PROGRESS', lambda: svc.git_create_branch('fix/blocked'))


def test_branch_lock_and_head_preconditions(space):
    root, _, svc = ready(space)
    fault('GIT_HEAD_CHANGED', lambda: svc.git_create_branch('fix/stale', expected_head='0' * 40))
    lock = root / '.git/index.lock'
    lock.write_text('foreign lock')
    fault('GIT_LOCKED', lambda: svc.git_create_branch('fix/locked'))
    assert lock.read_text() == 'foreign lock'
    assert svc.git_branches()['total'] == 1


def test_detached_and_unborn_branch_refused(space):
    root, policy, svc = space[1:]
    svc.git_init()
    fault('GIT_BRANCH_STATE_UNSUPPORTED', lambda: svc.git_create_branch('fix/unborn'))
    policy.git_user_name = 'Fixture'; policy.git_user_email = 'fixture@example.invalid'
    svc.git_add(); svc.git_commit(message='fixture')
    raw(root, 'checkout', '--detach', 'HEAD')
    fault('GIT_BRANCH_STATE_UNSUPPORTED', lambda: svc.git_create_branch('fix/detached'))
    assert svc.git_status()['detached_head']


@pytest.mark.parametrize('flag', ['--skip-worktree', '--assume-unchanged'])
def test_hidden_index_changes_refused(space, flag):
    root, _, svc = ready(space)
    raw(root, 'update-index', flag, 'a.txt')
    (root / 'a.txt').write_text('hidden edits')
    fault('GIT_INDEX_FLAGS_UNSUPPORTED', lambda: svc.git_create_branch('fix/hidden'))
    assert (root / 'a.txt').read_text() == 'hidden edits'


def test_switch_honors_protected_target_path(space):
    root, _, svc = ready(space)
    svc.git_create_branch('fixture/secret')
    (root / '.env').write_text('PRIVATE_FIXTURE')
    commit_raw(root, '.env')
    raw(root, 'checkout', 'main')
    fault('GIT_PATH_DENIED', lambda: svc.git_switch_branch('fixture/secret'))
    assert not (root / '.env').exists()
    assert svc.git_status()['branch'] == 'main'


def test_switch_honors_write_roots_and_regular_changes(space):
    root, policy, svc = ready(space)
    svc.git_create_branch('fixture/changed')
    (root / 'a.txt').write_text('new contents')
    svc.git_add(); svc.git_commit(message='changed')
    svc.git_switch_branch('main')
    policy.write_roots = ['.local-mcp-git-scope']
    fault('GIT_PATH_DENIED', lambda: svc.git_switch_branch('fixture/changed'))
    policy.write_roots = []
    assert svc.git_switch_branch('fixture/changed')['switched']
    assert (root / 'a.txt').read_text() == 'new contents'


@pytest.mark.parametrize('kind', ['symlink', 'gitlink', 'oversized'])
def test_switch_rejects_unsafe_objects(space, kind):
    root, policy, svc = ready(space)
    svc.git_create_branch('fixture/objects')
    if kind == 'symlink':
        # Index plumbing builds a synthetic symlink tree even on Windows.
        (root / 'target').write_text('/outside/never-follow')
        sha = raw(root, 'hash-object', '-w', 'target').decode().strip()
        (root / 'target').unlink()
        raw(root, 'update-index', '--add', '--cacheinfo', '120000,' + sha + ',target')
    elif kind == 'gitlink':
        sha = svc.git_status()['head']
        raw(root, 'update-index', '--add', '--cacheinfo', '160000,' + sha + ',target')
    else:
        (root / 'target').write_text('x' * 4096)
        raw(root, 'add', 'target')
    raw(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
    raw(root, 'checkout', 'main')
    policy.max_file_size = 1024
    fault('GIT_CHECKOUT_PATH_DENIED', lambda: svc.git_switch_branch('fixture/objects'))
    assert svc.git_status()['branch'] == 'main'


def test_ignored_file_not_overwritten(space):
    root, _, svc = ready(space)
    (root / '.gitignore').write_text('scratch.txt\n')
    svc.git_add(); svc.git_commit(message='ignore fixture')
    svc.git_create_branch('fixture/ignored')
    (root / 'scratch.txt').write_text('tracked version')
    commit_raw(root, 'scratch.txt')
    raw(root, 'checkout', 'main')
    (root / 'scratch.txt').write_text('user ignored contents')
    fault('GIT_COMMAND_FAILED', lambda: svc.git_switch_branch('fixture/ignored'))
    assert (root / 'scratch.txt').read_text() == 'user ignored contents'
    assert svc.git_status()['branch'] == 'main'


def test_post_checkout_hooks_do_not_run(space):
    root, _, svc = ready(space)
    hook = root / '.git/hooks/post-checkout'
    hook.parent.mkdir(exist_ok=True)
    hook.write_text('#!/bin/sh\necho ran > "' + str(root / 'HOOK_RAN') + '"\n')
    hook.chmod(0o755)
    svc.git_create_branch('fix/no-hook')
    svc.git_switch_branch('main')
    assert not (root / 'HOOK_RAN').exists()


@pytest.mark.parametrize('enabled', ['true', 'false', '1', '0'])
def test_worktree_config_valid_and_preserved(space, enabled):
    root, policy, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', enabled)
    raw(root, 'config', '--local', 'user.name', 'Common Identity')
    raw(root, 'config', '--local', 'user.email', 'common@example.invalid')
    config = root / '.git/config.worktree'
    config.write_text('[user]\n name = Worktree Identity\n email = worktree@example.invalid\n[core]\n sparseCheckout = false\n')
    snapshots = {p: p.read_bytes() for p in (root / '.git/config', config)}
    policy.git_user_name = ''; policy.git_user_email = ''
    assert svc.git_status()['ok'] and svc.git_diff()['ok']
    svc.git_create_branch('fix/worktree-config')
    (root / 'a.txt').write_text('changed')
    svc.git_add(); svc.git_commit(message='identity fixture')
    expected = 'Worktree Identity' if enabled in ('true', '1') else 'Common Identity'
    assert svc.git_log()['commits'][0]['author'] == expected
    assert all(p.read_bytes() == body for p, body in snapshots.items())


@pytest.mark.parametrize('key,value', [
    ('include.path', '/outside/private'), ('includeIf.onbranch:main.path', '/outside/private'),
    ('filter.attack.clean', 'never-execute'), ('credential.helper', '!never-execute'),
    ('http.cookieFile', '/outside/private'), ('core.sshCommand', 'never-execute'),
    ('core.worktree', '/outside/private'), ('remote.origin.uploadpack', 'never-execute'),
    ('extensions.worktreeConfig', 'true')])
def test_worktree_config_dangerous_still_rejected(space, key, value):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', 'true')
    config = root / '.git/config.worktree'
    raw(root, 'config', '--file', str(config), key, value)
    fault('UNSAFE_GIT_CONFIG', lambda: svc.git_status())
    assert not (root / 'never-execute').exists()


def test_worktree_config_can_only_point_to_current_worktree(space):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', 'true')
    (root / '.git/config.worktree').write_text('[core]\n worktree = ..\n bare = false\n')
    assert svc.git_status()['ok']
    assert svc.git_create_branch('fix/same-root')['created']


def test_worktree_config_malformed_bool_does_not_leak(space):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', 'PRIVATE_SENTINEL')
    err = fault('INVALID_GIT_CONFIG', lambda: svc.git_status())
    assert 'PRIVATE_SENTINEL' not in str(err.payload())


def test_worktree_config_symlink_rejected(space):
    root, _, svc = ready(space)
    other = space[0] / 'private-config'
    other.write_text('[user]\n name = SECRET_FIXTURE\n')
    try: (root / '.git/config.worktree').symlink_to(other)
    except OSError: pytest.skip('symlink not available')
    fault('UNSAFE_GIT_METADATA', lambda: svc.git_status())


def test_worktree_config_hardlink_rejected(space):
    root, _, svc = ready(space)
    other = space[0] / 'private-config'
    other.write_text('[user]\n name = SECRET_FIXTURE\n')
    try: os.link(other, root / '.git/config.worktree')
    except OSError: pytest.skip('hardlink not available')
    fault('UNSAFE_GIT_METADATA', lambda: svc.git_status())


@pytest.mark.parametrize('mode,commands,push,count', [
    ('read_only', False, False, 25), ('read_only', True, True, 25),
    ('read_write', False, False, 38), ('read_write', True, False, 42),
    ('read_write', True, True, 43)])
def test_capabilities_exactly_match_registry(space, mode, commands, push, count):
    _, policy, svc = ready(space)
    policy.mode = mode; policy.enable_commands = commands; policy.enable_git_push = push
    protocol = Protocol(svc)
    info = svc.policy_info()['capabilities']
    assert info['tool_count'] == count == len(protocol.specs)
    assert info['tool_names'] == sorted(protocol.specs)
    assert info['file_write_enabled'] == (mode == 'read_write')
    assert info['shell_enabled'] == (mode == 'read_write' and commands)
    assert info['git_branch_create_enabled'] == (mode == 'read_write')
    assert info['client_tool_visibility_verified'] is False
    assert info['write_scope_semantics'] == 'root_minus_denies'
    assert len(info['tool_catalog_sha256']) == 64
    assert svc.diagnose()['capabilities']['tool_catalog_sha256'] == info['tool_catalog_sha256']
    for name in ('git_create_branch', 'git_switch_branch'):
        if name in protocol.specs:
            assert name in WRITES and protocol.specs[name]['annotations']['readOnlyHint'] is False
    assert protocol.specs['git_branches']['annotations']['readOnlyHint'] is True


def test_git_failure_does_not_report_files_readonly(space):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'include.path', '/outside/never-read')
    result = svc.diagnose('a.txt')
    assert result['file_write']['allowed'] and not result['file_write']['disk_write_tested']
    assert not result['git']['supported']
    assert result['git']['error']['code'] == 'UNSAFE_GIT_CONFIG'
    assert result['capabilities']['file_write_enabled'] and not result['capabilities']['shell_enabled']
    assert not (root / '.local-mcp-capability-probe').exists()


def test_branch_readonly_and_batch_boundaries(space):
    _, policy, svc = ready(space)
    assert svc.batch_read([{'tool': 'git_branches'}])['ok']
    fault('BATCH_TOOL_DENIED', lambda: svc.batch_read([{'tool': 'git_create_branch', 'arguments': {'branch': 'fix/a'}}]))
    policy.mode = 'read_only'
    assert svc.git_branches()['ok']
    fault('READ_ONLY_MODE', lambda: svc.git_create_branch('fix/no'))
    fault('READ_ONLY_MODE', lambda: svc.git_switch_branch('main'))


def test_current_submodule_rejected_before_status(space, monkeypatch):
    root, _, svc = ready(space)
    sha = svc.git_status()['head']
    raw(root, 'update-index', '--add', '--cacheinfo', '160000,' + sha + ',module')
    raw(root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'gitlink fixture')
    original = svc.git.run
    def guarded(repo, args, **kwargs):
        assert args[0] != 'status', 'must reject gitlink before running status'
        return original(repo, args, **kwargs)
    monkeypatch.setattr(svc.git, 'run', guarded)
    fault('GIT_SUBMODULE_UNSUPPORTED', lambda: svc.git_create_branch('fix/submodule'))


def test_branch_in_other_worktree_is_not_stolen(space):
    root, _, svc = ready(space)
    other = space[0] / 'other-worktree'
    raw(root, 'worktree', 'add', '-b', 'fixture/occupied', str(other))
    fault('GIT_COMMAND_FAILED', lambda: svc.git_switch_branch('fixture/occupied'))
    assert svc.git_status()['branch'] == 'main'
    assert raw(other, 'branch', '--show-current').strip() == b'fixture/occupied'


def test_branch_mutation_obeys_active_command_guard(space, monkeypatch):
    _, _, svc = ready(space)
    def busy(paths):
        raise Fault('WORKSPACE_BUSY', 'fixture', 'synthetic active command', 'finish fixture')
    monkeypatch.setattr(svc.commands, 'guard_mutation', busy)
    fault('WORKSPACE_BUSY', lambda: svc.git_create_branch('fix/busy'))
    assert svc.git_branches()['total'] == 1


def test_worktree_config_without_optional_file(space):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', 'true')
    assert not (root / '.git/config.worktree').exists()
    assert svc.git_status()['ok']
    assert svc.git_create_branch('fix/no-overlay')['created']


def test_worktree_config_hook_override_stays_disabled(space):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', 'true')
    hookdir = space[0] / 'untrusted-hooks'
    hookdir.mkdir()
    hook = hookdir / 'post-checkout'
    hook.write_text('#!/bin/sh\necho ran > "' + str(root / 'HOOK_RAN') + '"\n')
    hook.chmod(0o755)
    config = root / '.git/config.worktree'
    raw(root, 'config', '--file', str(config), 'core.hooksPath', str(hookdir))
    assert svc.git_create_branch('fix/overlay-hook')['created']
    assert not (root / 'HOOK_RAN').exists()


def test_worktree_config_bare_or_oversized_rejected(space):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', 'true')
    config = root / '.git/config.worktree'
    config.write_text('[core]\n bare = true\n')
    fault('UNSUPPORTED_GIT_LAYOUT', lambda: svc.git_status())
    config.write_text('#' * 262145)
    fault('INVALID_GIT_CONFIG', lambda: svc.git_status())


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='POSIX FIFO required')
def test_worktree_config_fifo_rejected_without_reading(space):
    root, _, svc = ready(space)
    os.mkfifo(root / '.git/config.worktree')
    fault('UNSAFE_GIT_METADATA', lambda: svc.git_status())


def test_diagnostics_distinguish_linked_layout_and_file_write(space):
    root, _, svc = ready(space)
    linked = root / 'linked'
    raw(root, 'worktree', 'add', '-b', 'fixture/linked', str(linked))
    result = svc.diagnose(str(linked))
    assert result['file_write']['allowed']
    assert result['git']['supported']
    assert result['git']['branch'] == 'fixture/linked'
    assert result['capabilities']['client_tool_visibility_verified'] is False


def test_tool_fingerprint_covers_schema_and_flags(space):
    _, policy, svc = ready(space)
    one = svc.policy_info()['capabilities']
    two = svc.policy_info()['capabilities']
    assert one['runtime_instance'] == two['runtime_instance']
    tools = [Protocol(svc).specs[n] for n in sorted(Protocol(svc).specs)]
    expected = hashlib.sha256(json.dumps(tools, sort_keys=True, separators=(',', ':'),
                                         ensure_ascii=False).encode()).hexdigest()
    assert expected == one['tool_catalog_sha256']
    policy.mode = 'read_only'
    assert svc.policy_info()['capabilities']['tool_catalog_sha256'] != expected


def test_branch_workflow_real_stdio_offline(space):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', 'true')
    cfg = space[0] / 'stdio-config.json'
    cfg.write_text(json.dumps({'root': str(root), 'mode': 'read_write', 'enable_commands': False}))
    src = str(Path(__file__).resolve().parents[1] / 'src')
    code = f'import sys; sys.path.insert(0,{src!r}); from home_readonly_mcp.server import serve; serve({str(cfg)!r})'
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'git_create_branch', 'arguments': {'branch': 'fix/stdio'}}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'git_status', 'arguments': {}}},
        {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {'name': 'policy_info', 'arguments': {}}},
        {'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call', 'params': {'name': 'git_switch_branch', 'arguments': {'branch': 'main'}}},
    ]
    from home_readonly_mcp.onboarding import child_environment
    env = child_environment()
    env.update(HOME=str(space[0]), USERPROFILE=str(space[0]),
               XDG_STATE_HOME=str(space[0] / 'stdio-state'), LOCALAPPDATA=str(space[0] / 'AppData/Local'))
    result = subprocess.run([sys.executable, '-I', '-c', code], env=env,
                            input='\n'.join(json.dumps(r) for r in requests) + '\n',
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
    responses = {r['id']: r for r in map(json.loads, result.stdout.splitlines())}
    assert responses[3]['result']['structuredContent']['created']
    assert responses[4]['result']['structuredContent']['branch'] == 'fix/stdio'
    cap = responses[5]['result']['structuredContent']['capabilities']
    assert cap['tool_names'] == sorted(t['name'] for t in responses[2]['result']['tools'])
    assert cap['git_branch_create_enabled'] and not cap['shell_enabled']
    assert responses[6]['result']['structuredContent']['branch'] == 'main'
    assert svc.git_status()['branch'] == 'main'


@pytest.mark.parametrize('alias_style', ['absolute_alias', 'alias_then_parent'])
def test_worktree_same_target_alias_is_rejected(space, alias_style):
    root, _, svc = ready(space)
    raw(root, 'config', '--local', 'extensions.worktreeConfig', 'true')
    if alias_style == 'absolute_alias':
        alias = space[0] / 'worktree-alias'
        target = root
        value = str(alias)
    else:
        target = root / 'nested'
        target.mkdir()
        alias = root / 'worktree-alias'
        value = '../worktree-alias/..'
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('directory symlink unavailable')
    config = root / '.git/config.worktree'
    raw(root, 'config', '--file', str(config), 'core.worktree', value)
    before = config.read_bytes()
    fault('UNSAFE_GIT_CONFIG', lambda: svc.git_status())
    assert config.read_bytes() == before
