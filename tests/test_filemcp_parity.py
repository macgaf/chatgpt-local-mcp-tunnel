"""补齐文件和搜索能力，同时保持冲突、范围、备份及协议边界。"""
import os
import pytest
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.server import Protocol
from home_readonly_mcp.storage import digest


def test_append_conflict_backup_and_limit(space):
    _, root, policy, svc = space
    before = svc.read_file('a.txt')
    with pytest.raises(Fault): svc.write_file('a.txt', 'extra', append=True)
    svc.write_file('a.txt', 'extra', before['sha256'], append=True)
    assert (root / 'a.txt').read_text() == before['content'] + 'extra'
    with pytest.raises(Fault): svc.write_file('a.txt', 'lost', before['sha256'], append=True)
    assert svc.list_backups('a.txt')['backups'][0]['sha256'] == before['sha256']
    policy.max_file_size = (root / 'a.txt').stat().st_size
    with pytest.raises(Fault): svc.write_file('a.txt', 'x', svc.file_info('a.txt')['sha256'], append=True)


def test_delete_and_restore(space):
    _, root, _, svc = space
    before = svc.read_file('a.txt')
    assert svc.delete_file('a.txt', before['sha256'], True)['dry_run']
    assert (root / 'a.txt').exists()
    with pytest.raises(Fault): svc.delete_file('a.txt', '0' * 64)
    result = svc.delete_file('a.txt', before['sha256'])
    assert not (root / 'a.txt').exists()
    svc.restore_file('a.txt', result['backup_id'], 'MISSING')
    assert svc.read_file('a.txt')['sha256'] == before['sha256']


def test_recursive_delete_preflight_and_recovery(space):
    _, root, _, svc = space
    folder = root / 'folder'; (folder / 'empty').mkdir(parents=True)
    (folder / 'data.txt').write_text('old')
    plan = svc.delete_directory('folder')
    (folder / 'data.txt').write_text('changed')
    with pytest.raises(Fault): svc.delete_directory('folder', plan['sha256'], False)
    assert (folder / 'empty').exists()
    plan = svc.delete_directory('folder')
    result = svc.delete_directory('folder', plan['sha256'], False)
    assert not folder.exists() and result['atomic'] is False
    for name in reversed(result['removed_directories']): svc.create_directory(name)
    for backup in result['backups']: svc.restore_file(backup['path'], backup['backup_id'], 'MISSING')
    assert (folder / 'data.txt').read_text() == 'changed' and (folder / 'empty').is_dir()


@pytest.mark.parametrize('kind', ['secret', 'git', 'link', 'hardlink'])
def test_directory_rejects_entire_batch_before_delete(space, kind):
    _, root, _, svc = space
    folder = root / 'folder'; folder.mkdir()
    (folder / 'allowed.txt').write_text('keep')
    if kind == 'secret': (folder / '.env').write_text('synthetic')
    if kind == 'git': (folder / '.git').mkdir()
    if kind == 'link':
        try: (folder / 'alias').symlink_to(root / 'a.txt')
        except OSError: pytest.skip('symlinks unavailable')
    if kind == 'hardlink':
        try: os.link(root / 'a.txt', folder / 'hard')
        except OSError: pytest.skip('hardlinks unavailable')
    with pytest.raises(Fault): svc.delete_directory('folder')
    assert (folder / 'allowed.txt').read_text() == 'keep'


def test_directory_partial_failure_returns_backups(space, monkeypatch):
    _, root, _, svc = space
    folder = root / 'folder'; folder.mkdir()
    (folder / 'a').write_text('a'); (folder / 'b').write_text('b')
    plan = svc.delete_directory('folder')
    original = svc._unlink_checked
    def fail_second(p, old):
        if p.name == 'b': raise OSError('synthetic failure')
        original(p, old)
    monkeypatch.setattr(svc, '_unlink_checked', fail_second)
    with pytest.raises(Fault) as exc: svc.delete_directory('folder', plan['sha256'], False)
    assert exc.value.code == 'DELETE_INCOMPLETE'
    assert exc.value.details['deleted'] == ['folder/a']
    assert len(exc.value.details['backups']) == 2 and (folder / 'b').exists()


def test_file_actions_readonly_and_batch(space):
    _, root, policy, svc = space
    policy.mode = 'read_only'
    for name in ('delete_file', 'delete_directory'): assert name not in Protocol(svc).specs
    with pytest.raises(Fault): svc.delete_file('a.txt', digest((root / 'a.txt').read_bytes()))
    with pytest.raises(Fault): svc.batch_read([{'tool': 'delete_directory', 'arguments': {'path': '.'}}])


def test_search_multiline_type_context_and_file(space):
    _, root, _, svc = space
    (root / 'sample.PY').write_text('before\nstart\nend\nafter\n')
    (root / 'sample.js').write_text('start\nend\n')
    result = svc.grep('start.*end', type='py', multiline=True, fixed_strings=False,
                      output_mode='content', context_before=1, context_after=0)
    assert [row['line'] for row in result['results']] == [2, 3]
    assert result['results'][0]['context_before'] == ['before']
    assert result['results'][0]['context_after'] == []
    assert svc.grep('start.*end', type='py', fixed_strings=False)['results'] == []
    assert svc.grep('end', path='sample.PY')['results'] == [{'path': 'sample.PY'}]
    assert set(svc.glob('*.{py,js}')['results']) == {'sample.PY', 'sample.js'}
    with pytest.raises(ValueError): svc.grep('start', type='unknown-type')
