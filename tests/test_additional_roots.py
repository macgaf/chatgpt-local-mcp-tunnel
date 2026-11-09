"""使用合成目录验证附加授权范围，不访问真实临时文件或凭据。"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from io import BytesIO
import unicodedata
import zipfile

import pytest

from home_readonly_mcp.errors import Fault
from home_readonly_mcp.policy import Policy
from home_readonly_mcp.service import HomeService
from home_readonly_mcp.storage import digest


@pytest.fixture
def external(space, tmp_path):
    directory = tmp_path / 'external-temp'
    directory.mkdir()
    (directory / 'a.txt').write_bytes(b'external\n')
    return directory


def policy_for(space, external, **options):
    return Policy(root=space[1], mode='read_write',
                  additional_roots=[{'path': str(external), **options}])


def test_additional_readonly_and_path_roundtrip(space, external):
    policy = policy_for(space, external)
    service = HomeService(policy)
    try:
        result = service.read_file(str(external / 'a.txt'))
        assert result['path'] == (external / 'a.txt').as_posix()
        assert service.read_file(result['path'])['content'] == 'external\n'
        assert service.read_file('a.txt')['content'].startswith('hello')
        assert service.list_directory(str(external))['entries'][0]['path'] == result['path']
        with pytest.raises(Fault) as got:
            service.write_file(str(external / 'new'), 'denied')
        assert got.value.code == 'READ_ONLY_ROOT'
        with pytest.raises(Fault) as got:
            service.read_file(str(external.parent / 'unauthorized'))
        assert got.value.code == 'OUTSIDE_ROOT'
    finally:
        service.close()


def test_additional_write_backup_restore_and_global_readonly(space, external):
    policy = policy_for(space, external, mode='read_write')
    policy.write_roots = ['docs/**']
    service = HomeService(policy)
    try:
        path = str(external / 'a.txt')
        before = service.read_file(path)
        changed = service.write_file(path, 'changed', before['sha256'])
        assert service.list_backups(path)['backups'][0]['id'] == changed['backup_id']
        restored = service.restore_file(path, changed['backup_id'], changed['sha256'])
        assert restored['sha256'] == before['sha256']
        service.create_directory(str(external / 'new-dir'))
        service.write_file(str(external / 'new-dir' / 'new.txt'), 'new')
        with pytest.raises(Fault) as got:
            service.write_file('a.txt', 'outside main write scope', space[3].read_file('a.txt')['sha256'])
        assert got.value.code == 'WRITE_SCOPE_DENIED'
        policy.mode = 'read_only'
        with pytest.raises(Fault) as got:
            service.write_file(str(external / 'never-created'), 'denied')
        assert got.value.code == 'READ_ONLY_MODE'
        assert not (external / 'never-created').exists()
    finally:
        service.close()


def test_configuration_expands_temp_and_reports_effective_modes(space, external, monkeypatch):
    monkeypatch.setenv('TMPDIR', str(external))
    config = space[0] / 'config.json'
    config.write_text(json.dumps({'root': str(space[1]), 'mode': 'read_only',
        'additional_roots': [{'path': '${TMPDIR}', 'mode': 'read_write'}]}))
    policy = Policy.from_file(config)
    assert policy.summary()['additional_roots'] == [
        {'path': str(external), 'mode': 'read_write', 'effective_mode': 'read_only'}]
    monkeypatch.setattr('home_readonly_mcp.policy.tempfile.gettempdir', lambda: str(external))
    assert policy_for(space, '${TEMP_DIR}').root_for(external / 'a.txt') == external


@pytest.mark.parametrize('entries', [None, {}, ['path'], [{'path': ''}],
    [{'path': 'relative'}], [{'path': '/missing', 'mode': 'write'}],
    [{'path': '/missing', 'unknown': True}]])
def test_invalid_additional_configuration(space, entries):
    with pytest.raises((ValueError, Fault)):
        Policy(root=space[1], additional_roots=entries)


def test_missing_env_root_and_duplicate_are_rejected(space, external, monkeypatch):
    monkeypatch.delenv('TMPDIR', raising=False)
    for path in ('${TMPDIR}', '${UNKNOWN_TEMP}', str(external / 'missing')):
        with pytest.raises((ValueError, Fault)):
            policy_for(space, path)
    for path in (str(space[1]), str(Path(space[0]).parent)):
        with pytest.raises((ValueError, Fault)):
            policy_for(space, path)
    with pytest.raises(ValueError):
        Policy(root=space[1], additional_roots=[{'path': str(external)}, {'path': str(external)}])


@pytest.mark.parametrize('name', ['.env', '.ssh/private', 'private.key', 'secrets/file'])
def test_additional_honors_explicit_path_rules(space, external, name):
    policy = policy_for(space, external, mode='read_write')
    policy.deny = [name]
    with pytest.raises(Fault) as got:
        policy.resolve(str(external / name))
    assert got.value.code == 'POLICY_DENIED'


def test_nested_scopes_cannot_reset_denies_or_main_write_roots(space, external):
    child = external / 'nested'
    child.mkdir()
    policy = Policy(root=space[1], mode='read_write', deny=['nested/blocked.txt'],
        additional_roots=[{'path': str(external)}, {'path': str(child), 'mode': 'read_write'}])
    assert policy.resolve(str(child / 'allowed.txt'), write=True) == child / 'allowed.txt'
    with pytest.raises(Fault) as got:
        policy.resolve(str(child / 'blocked.txt'), write=True)
    assert got.value.code == 'POLICY_DENIED'
    for root in (external, child):
        with pytest.raises(Fault) as got:
            policy.resolve(str(root), write=True)
        assert got.value.code == 'ROOT_MUTATION_DENIED'
    main_child = space[1] / 'nested'
    main_child.mkdir()
    policy = Policy(root=space[1], mode='read_write', write_roots=['docs/**'],
        additional_roots=[{'path': str(main_child), 'mode': 'read_write'}])
    with pytest.raises(Fault) as got:
        policy.resolve(str(main_child / 'file.txt'), write=True)
    assert got.value.code == 'WRITE_SCOPE_DENIED'


@pytest.mark.skipif(os.name == 'nt', reason='创建符号链接需要 Windows 特权')
def test_configured_root_alias_and_child_symlink_checks(space, external, tmp_path):
    alias = tmp_path / 'temp-alias'
    alias.symlink_to(external, target_is_directory=True)
    policy = policy_for(space, alias, mode='read_write')
    service = HomeService(policy)
    try:
        assert service.read_file(str(alias / 'a.txt'))['path'] == (external / 'a.txt').as_posix()
        service.write_file(str(alias / 'new.txt'), 'alias root')
        (external / 'inner-alias').symlink_to(external / 'a.txt')
        with pytest.raises(Fault) as got:
            service.write_file(str(external / 'inner-alias'), 'denied')
        assert got.value.code == 'SYMLINK_WRITE_DENIED'
        (external / 'escape').symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(Fault) as got:
            service.read_file(str(external / 'escape' / 'other'))
        assert got.value.code == 'OUTSIDE_ROOT'
        alias.unlink()
        alias.symlink_to(space[1], target_is_directory=True)
        with pytest.raises(Fault) as got:
            service.read_file(str(alias / 'a.txt'))
        assert got.value.code == 'ROOT_ALIAS_CHANGED'
    finally:
        service.close()


def test_additional_resource_uri_roundtrip(space, external):
    (external / 'binary.bin').write_bytes(b'\0external bytes')
    service = HomeService(policy_for(space, external))
    try:
        result = service.read_binary(str(external / 'binary.bin'))
        resource = service.read_resource(result['structuredContent']['uri'])
        assert base64.b64decode(resource['content'][1]['resource']['blob']) == b'\0external bytes'
    finally:
        service.close()


def test_external_archive_resource_roundtrip(space, external):
    archive = BytesIO()
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('binary.bin', b'\0archive bytes')
    (external / 'archive.zip').write_bytes(archive.getvalue())
    service = HomeService(policy_for(space, external))
    try:
        result = service.read_archive_member(str(external / 'archive.zip'), 'binary.bin', view='binary')
        again = service.read_resource(result['structuredContent']['uri'])
        assert base64.b64decode(again['content'][1]['resource']['blob']) == b'\0archive bytes'
    finally:
        service.close()


def test_search_and_context_use_external_boundary(space, external):
    (external.parent / 'AGENTS.md').write_text('未经授权的上级说明', encoding='utf-8')
    (external / 'AGENTS.md').write_text('附加目录说明', encoding='utf-8')
    (external / 'build').mkdir()
    (external / 'build' / 'generated.txt').write_text('external generated', encoding='utf-8')
    service = HomeService(policy_for(space, external))
    try:
        path = str(external)
        expected = (external / 'a.txt').as_posix()
        assert service.glob('*.txt', path)['results'] == [expected]
        assert service.grep('external', path)['results'] == [{'path': expected}]
        assert service.search_code(['external'], path)['queries'][0]['results'][0]['path'] == expected
        assert service.search_text('external', path, glob='a.txt')['results'][0]['path'] == expected
        assert service.find_files('a.txt', path)['results'] == [expected]
        assert (external / 'build' / 'generated.txt').as_posix() in service.glob('*.txt', path, include_ignored=True)['results']
        assert service.repo_overview(path)['path'] == external.as_posix()
        context = service.workspace_context(path)
        assert context['root'] == str(external)
        assert [item['content'] for item in context['files']] == ['附加目录说明']
        assert context['errors'][0]['code'] == 'NOT_A_GIT_REPOSITORY'
        assert service.batch_read([{'tool': 'read_file', 'arguments': {'path': expected}}])['ok']
    finally:
        service.close()


def test_search_respects_external_ignore(space, external):
    pytest.importorskip('pathspec')
    (external / '.gitignore').write_text('ignored.txt\n', encoding='utf-8')
    (external / 'ignored.txt').write_text('external ignored', encoding='utf-8')
    service = HomeService(policy_for(space, external))
    try:
        assert service.glob('*.txt', str(external))['results'] == [(external / 'a.txt').as_posix()]
        assert (external / 'ignored.txt').as_posix() in service.glob('*.txt', str(external), include_ignored=True)['results']
    finally:
        service.close()


@pytest.mark.skipif(os.name == 'nt', reason='创建符号链接需要 Windows 特权')
def test_configured_alias_cannot_skip_original_scope_rules(space, external):
    alias = space[1] / 'temp-alias'
    alias.symlink_to(external, target_is_directory=True)
    policy = Policy(root=space[1], mode='read_write', deny=['temp-alias/a.txt'],
        additional_roots=[{'path': str(alias), 'mode': 'read_write'}])
    with pytest.raises(Fault) as got:
        policy.resolve(str(alias / 'a.txt'))
    assert got.value.code == 'POLICY_DENIED'
    policy.deny = []
    policy.write_roots = ['docs/**']
    with pytest.raises(Fault) as got:
        policy.resolve(str(alias / 'a.txt'), write=True)
    assert got.value.code == 'WRITE_SCOPE_DENIED'


def test_cross_root_patch_prevalidation_and_backups(space, external):
    service = HomeService(policy_for(space, external, mode='read_write'))
    try:
        main = space[3].read_file('a.txt')
        other = service.read_file(str(external / 'a.txt'))
        changes = [
            {'path': 'a.txt', 'old_text': 'hello', 'new_text': 'main', 'expected_sha256': main['sha256']},
            {'path': other['path'], 'old_text': 'external', 'new_text': 'temp', 'expected_sha256': '0' * 64}]
        with pytest.raises(Fault) as got:
            service.apply_patch(changes=changes)
        assert got.value.code == 'HASH_CONFLICT'
        assert service.read_file('a.txt')['sha256'] == main['sha256']
        changes[1]['expected_sha256'] = other['sha256']
        result = service.apply_patch(changes=changes)
        assert result['file_count'] == 2 and result['changed']
        for path in ('a.txt', other['path']):
            assert service.list_backups(path)['backups']
    finally:
        service.close()


@pytest.mark.parametrize('external_change', [False, True])
def test_cross_root_rollback_preserves_external_changes(space, external, monkeypatch, external_change):
    from home_readonly_mcp import patches
    original_commit = patches.commit_bytes
    service = HomeService(policy_for(space, external, mode='read_write'))
    try:
        paths = sorted([space[1] / 'a.txt', external / 'a.txt'], key=lambda p: os.path.normcase(str(p)))
        original = {path: path.read_bytes() for path in paths}

        def fail_second(policy, path, *args, **kwargs):
            if path == paths[1]:
                if external_change:
                    paths[0].write_bytes(b'concurrent external edit')
                raise OSError('合成的第二文件写入失败')
            return original_commit(policy, path, *args, **kwargs)

        monkeypatch.setattr(patches, 'commit_bytes', fail_second)
        changes = [{'path': str(path), 'old_text': body.decode('utf-8'), 'new_text': 'updated',
                    'expected_sha256': digest(body)} for path, body in original.items()]
        with pytest.raises(Fault) as got:
            service.apply_patch(changes=changes)
        assert got.value.code == ('PATCH_ROLLBACK_INCOMPLETE' if external_change else 'PATCH_FAILED_ROLLED_BACK')
        assert paths[1].read_bytes() == original[paths[1]]
        assert paths[0].read_bytes() == (b'concurrent external edit' if external_change else original[paths[0]])
    finally:
        service.close()


def test_commands_require_writable_additional_cwd(space, external):
    policy = policy_for(space, external)
    policy.enable_commands = True
    service = HomeService(policy)
    try:
        with pytest.raises(Fault) as got:
            service.run_command('echo additional', cwd=str(external))
        assert got.value.code == 'READ_ONLY_ROOT' and not service.commands.jobs
    finally:
        service.close()


def test_native_git_in_additional_root_and_readonly_rejection(space, external):
    policy = policy_for(space, external, mode='read_write')
    policy.git_user_name = 'Synthetic'
    policy.git_user_email = 'synthetic@example.invalid'
    service = HomeService(policy)
    try:
        assert service.git_init(str(external))['created']
        service.git_add(str(external), ['a.txt'])
        committed = service.git_commit(str(external), '合成提交')
        assert service.git_status(str(external))['head'] == committed['commit_sha']
        assert service.git_create_branch('feature/temp', str(external))['created']
        assert service.git_switch_branch('main', str(external))['branch'] == 'main'
        readonly = HomeService(policy_for(space, external))
        try:
            assert readonly.git_status(str(external))['branch'] == 'main'
            with pytest.raises(Fault) as got:
                readonly.git_create_branch('denied', str(external))
            assert got.value.code == 'READ_ONLY_ROOT'
        finally:
            readonly.close()
    finally:
        service.close()


def test_credentials_runtime_and_hardlinks_stay_protected(space, external):
    policy = policy_for(space, external, mode='read_write')
    service = HomeService(policy)
    try:
        os.link(external / 'a.txt', external / 'hardlink')
        with pytest.raises(Fault) as got:
            service.read_file(str(external / 'hardlink'))
        assert got.value.code == 'HARDLINK_DENIED'
        sensitive = space[0] / '.aws'
        sensitive.mkdir()
        with pytest.raises(Fault) as got:
            policy_for(space, sensitive, mode='read_write')
        assert got.value.code == 'POLICY_DENIED'
        protected = external / 'runtime'
        protected.mkdir()
        policy.protected_paths.append(protected)
        with pytest.raises(Fault) as got:
            service.write_file(str(protected / 'config.json'), 'denied')
        assert got.value.code == 'PROTECTED_RUNTIME'
    finally:
        service.close()


def test_real_stdio_external_read_write_and_readonly_rejection(space, external):
    readonly = external.parent / 'readonly-temp'
    readonly.mkdir()
    config = space[0] / 'server.json'
    config.write_text(json.dumps({'root': str(space[1]), 'mode': 'read_write',
        'additional_roots': [{'path': str(external), 'mode': 'read_write'}, {'path': str(readonly)}]}))
    operations = [('policy_info', {}),
        ('read_file', {'path': str(external / 'a.txt')}),
        ('write_file', {'path': str(external / 'created.txt'), 'content': '真实 stdio'}),
        ('read_file', {'path': str(external / 'created.txt')}),
        ('write_file', {'path': str(readonly / 'denied.txt'), 'content': 'denied'})]
    requests = [{'jsonrpc': '2.0', 'id': index, 'method': 'tools/call',
                 'params': {'name': name, 'arguments': arguments}}
                for index, (name, arguments) in enumerate(operations, 1)]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    run = subprocess.run([sys.executable, '-m', 'home_readonly_mcp.cli', '--config', str(config), 'server'],
        input='\n'.join(json.dumps(request) for request in requests) + '\n',
        capture_output=True, text=True, encoding='utf-8', env=env, timeout=15)
    assert run.returncode == 0, run.stderr
    results = [json.loads(line)['result'] for line in run.stdout.splitlines()]
    assert len(results) == len(operations)
    assert results[0]['structuredContent']['additional_roots'][0]['effective_mode'] == 'read_write'
    assert results[1]['structuredContent']['content'] == 'external\n'
    assert results[3]['structuredContent']['sha256'] == digest('真实 stdio'.encode())
    assert results[4]['structuredContent']['error']['code'] == 'READ_ONLY_ROOT'
    assert (external / 'created.txt').read_text(encoding='utf-8') == '真实 stdio'
    assert not (readonly / 'denied.txt').exists()


@pytest.mark.parametrize('variant', ['upper', 'unicode', 'parent_case'])
def test_filesystem_alias_cannot_bypass_nested_readonly(space, external, variant):
    child = external / ('r\u00e9adonly' if variant == 'unicode' else 'readonly')
    child.mkdir()
    if variant == 'unicode':
        alias = child.with_name(unicodedata.normalize('NFD', child.name))
    elif variant == 'parent_case':
        alias = external.with_name(external.name.upper()) / child.name
    else:
        alias = child.with_name(child.name.upper())
    if not alias.exists() or not alias.samefile(child):
        pytest.skip('此文件系统区分当前目录的大小写或 Unicode 写法')
    policy = Policy(root=space[1], mode='read_write', additional_roots=[
        {'path': str(external), 'mode': 'read_write'}, {'path': str(child)}])
    assert policy.resolve(str(alias)) == child
    with pytest.raises(Fault) as got:
        policy.resolve(str(alias / 'never-created'), write=True)
    assert got.value.code == 'READ_ONLY_ROOT'
    assert not (child / 'never-created').exists()


@pytest.mark.parametrize('use_primary', [False, True])
def test_duplicate_root_identity_includes_case_alias(space, external, use_primary):
    root = space[1] if use_primary else external
    alias = root.with_name(root.name.upper())
    if not alias.exists() or not alias.samefile(root):
        pytest.skip('此文件系统区分目录大小写')
    entries = [{'path': str(alias), 'mode': 'read_write'}]
    if not use_primary:
        entries.insert(0, {'path': str(root)})
    with pytest.raises(ValueError, match='重复'):
        Policy(root=space[1], additional_roots=entries)


def test_case_alias_cannot_authorize_home_ancestor(space):
    parent = space[0].parent
    alias = parent.with_name(parent.name.upper())
    if not alias.exists() or not alias.samefile(parent):
        pytest.skip('此文件系统区分目录大小写')
    for options in ({'root': alias}, {'root': space[1], 'additional_roots': [{'path': str(alias)}]}):
        with pytest.raises(Fault) as got:
            Policy(**options)
        assert got.value.code == 'ROOT_TOO_BROAD'


def test_case_sensitive_directories_are_separate_roots(space, external):
    other = external.with_name(external.name.upper())
    if other.exists():
        pytest.skip('此文件系统不区分目录大小写')
    other.mkdir()
    policy = Policy(root=space[1], mode='read_write', additional_roots=[
        {'path': str(external)}, {'path': str(other), 'mode': 'read_write'}])
    assert policy.resolve(str(other / 'new'), write=True) == other / 'new'
    with pytest.raises(Fault) as got:
        policy.resolve(str(external / 'new'), write=True)
    assert got.value.code == 'READ_ONLY_ROOT'


@pytest.mark.skipif(os.name == 'nt', reason='创建符号链接需要 Windows 特权')
@pytest.mark.parametrize('protected', ['credentials', 'runtime'])
def test_configured_protected_alias_is_rejected(space, external, protected):
    base = space[0] / ('.ssh' if protected == 'credentials' else '.config/chatgpt-local-mcp-tunnel')
    base.mkdir(parents=True, exist_ok=True)
    alias = base / 'external-alias'
    alias.symlink_to(external, target_is_directory=True)
    with pytest.raises(Fault) as got:
        policy_for(space, alias)
    assert got.value.code == ('POLICY_DENIED' if protected == 'credentials' else 'PROTECTED_RUNTIME')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX no-follow 目录句柄专项')
def test_nested_root_ancestor_swap_is_not_followed(space, external, monkeypatch):
    from home_readonly_mcp import storage
    shared = space[1] / 'shared'
    grant = shared / 'grant'
    grant.mkdir(parents=True)
    (grant / 'data.txt').write_text('inside')
    (external / 'grant').mkdir()
    (external / 'grant' / 'data.txt').write_text('OUTSIDE_FIXTURE')
    policy = Policy(root=space[1], additional_roots=[{'path': str(grant)}])
    original_open = storage.os.open
    swapped = False

    def swap_before_open(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and (Path(path) == grant or (str(path) == 'shared' and 'dir_fd' in kwargs)):
            shared.rename(space[1] / 'original-shared')
            shared.symlink_to(external, target_is_directory=True)
            swapped = True
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(storage.os, 'open', swap_before_open)
    with pytest.raises(OSError):
        storage.read_bytes(policy, str(grant / 'data.txt'))
    assert swapped


@pytest.mark.skipif(os.name == 'nt' or getattr(os, 'geteuid', lambda: 0)() == 0,
                    reason='POSIX 普通用户的仅搜索目录权限专项')
def test_single_root_under_search_only_ancestor_still_works(space, tmp_path):
    from home_readonly_mcp.storage import read_bytes
    ancestor = tmp_path / 'search-only'
    root = ancestor / 'workspace'
    root.mkdir(parents=True)
    target = root / 'data.txt'
    target.write_bytes(b'permitted file')
    ancestor.chmod(0o111)
    try:
        assert target.read_bytes() == b'permitted file'
        assert read_bytes(Policy(root=root), str(target))[1] == b'permitted file'
    finally:
        ancestor.chmod(0o700)


def test_additional_append_delete_and_restore(space, external):
    service = HomeService(policy_for(space, external, mode='read_write'))
    try:
        path = str(external / 'a.txt')
        before = service.read_file(path)
        result = service.write_file(path, 'appended', before['sha256'], append=True)
        assert service.read_file(path)['content'] == 'external\nappended'
        deleted = service.delete_file(path, result['sha256'])
        service.restore_file(path, deleted['backup_id'], 'MISSING')
        assert service.read_file(path)['sha256'] == result['sha256']
        directory = external / 'disposable'
        service.create_directory(str(directory))
        service.write_file(str(directory / 'data.txt'), 'disposable')
        preview = service.delete_directory(str(directory))
        result = service.delete_directory(str(directory), preview['sha256'], dry_run=False)
        assert result['deleted'] and not directory.exists()
        with pytest.raises(Fault) as got:
            service.delete_directory(str(external))
        assert got.value.code == 'ROOT_MUTATION_DENIED'
    finally:
        service.close()


@pytest.mark.skipif(os.name == 'nt', reason='创建符号链接需要 Windows 特权')
def test_delete_through_configured_root_alias(space, external, tmp_path):
    alias = tmp_path / 'configured-temp-alias'
    alias.symlink_to(external, target_is_directory=True)
    service = HomeService(policy_for(space, alias, mode='read_write'))
    try:
        original = service.read_file(str(alias / 'a.txt'))
        result = service.delete_file(str(alias / 'a.txt'), original['sha256'])
        assert result['deleted'] and not (external / 'a.txt').exists()
    finally:
        service.close()


def test_linked_worktree_across_authorized_roots(space, external):
    policy = policy_for(space, external, mode='read_write')
    policy.git_user_name = 'Synthetic'
    policy.git_user_email = 'synthetic@example.invalid'
    service = HomeService(policy)
    linked = external / 'linked'
    try:
        service.git_init()
        service.git_add(paths=['a.txt'])
        service.git_commit(message='合成主仓库')
        service.git.run(space[1], ['worktree', 'add', '-b', 'feature/external', str(linked)])
        assert service.git_status(str(linked))['branch'] == 'feature/external'
        path = str(linked / 'a.txt')
        old = service.read_file(path)
        service.write_file(path, 'external worktree', old['sha256'])
        service.git_add(str(linked), ['a.txt'])
        assert service.git_commit(str(linked), '合成外部工作树')['commit_sha']
        policy.write_roots = ['docs/**']
        with pytest.raises(Fault) as got:
            service.git_create_branch('denied/shared-main', str(linked))
        assert got.value.code == 'WRITE_SCOPE_DENIED'
        isolated = HomeService(Policy(root=external))
        try:
            with pytest.raises(Fault) as got:
                isolated.git_status(str(linked))
            assert got.value.code == 'OUTSIDE_ROOT'
        finally:
            isolated.close()
    finally:
        service.close()
