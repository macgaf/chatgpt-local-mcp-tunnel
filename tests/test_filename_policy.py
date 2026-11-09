"""文件名不是秘密分类器；全部内容和 HOME 都是合成测试数据。"""
from io import BytesIO
import json
import os
import zipfile

import pytest

from home_readonly_mcp.errors import Fault
from home_readonly_mcp.policy import Policy
from home_readonly_mcp.service import HomeService


@pytest.mark.parametrize('name', [
    'credentials.py', 'src/credentials.ts', 'secrets/module.py', 'private.key', 'public.pem',
    'sample.p12', 'sample.pfx', '.env', '.env.example', '.npmrc', 'src/id_ed25519',
    '.ssh/parser.py', '.aws/config', '.config/demo/tokens.py', '.config/demo/auth.json',
])
def test_source_names_do_not_imply_secrets(space, name):
    root, service = space[1], space[3]
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'SOURCE_MARKER\n')
    before = service.read_file(name)
    assert before['content'] == 'SOURCE_MARKER\n'
    updated = service.write_file(name, 'UPDATED_SOURCE\n', before['sha256'])
    assert service.read_file(name)['sha256'] == updated['sha256']


def test_external_directory_name_is_not_a_credential_store(space, tmp_path):
    external = tmp_path / '.aws'
    external.mkdir()
    (external / 'credentials.py').write_bytes(b'SOURCE_MARKER\n')
    policy = Policy(root=space[1], mode='read_write',
                    additional_roots=[{'path': str(external), 'mode': 'read_write'}])
    service = HomeService(policy)
    try:
        assert service.read_file(str(external / 'credentials.py'))['content'] == 'SOURCE_MARKER\n'
    finally:
        service.close()


def test_user_store_protection_depends_on_actual_location(space):
    home, root = space[:2]
    for base in (home, root):
        (base / '.ssh').mkdir(exist_ok=True)
        (base / '.ssh' / 'parser.py').write_bytes(b'SOURCE_MARKER\n')
    assert space[3].read_file('.ssh/parser.py')['content'] == 'SOURCE_MARKER\n'
    policy = Policy(root=home, mode='read_write', force_allow=['.ssh/parser.py'])
    with pytest.raises(Fault) as got:
        policy.resolve(str(home / '.ssh' / 'parser.py'))
    assert got.value.code == 'POLICY_DENIED'


@pytest.mark.skipif(os.name == 'nt', reason='创建符号链接需要 Windows 特权')
def test_actual_user_store_link_target_remains_protected(space, tmp_path):
    home = space[0]
    store = tmp_path / 'user-store'
    store.mkdir()
    (store / 'parser.py').write_bytes(b'SYNTHETIC_STORE\n')
    (home / '.ssh').symlink_to(store, target_is_directory=True)
    policy = Policy(root=store, force_allow=['parser.py'])
    with pytest.raises(Fault) as got:
        policy.resolve('parser.py')
    assert got.value.code == 'POLICY_DENIED'
    assert policy.summary()['credential_protection'] == 'explicit_user_paths'
    with pytest.raises(Fault):
        Policy(root=space[1], additional_roots=[{'path': str(store)}])


def test_archive_member_names_do_not_imply_secrets(space):
    archive = BytesIO()
    with zipfile.ZipFile(archive, 'w') as output:
        output.writestr('secrets/credentials.py', b'SOURCE_MARKER\n')
        output.writestr('.ssh/parser.py', b'SOURCE_MARKER\n')
    (space[1] / 'source.zip').write_bytes(archive.getvalue())
    service = space[3]
    assert service.list_archive('source.zip')['skipped_unsafe_or_denied'] == 0
    for member in ('secrets/credentials.py', '.ssh/parser.py'):
        assert service.read_archive_member('source.zip', member, view='text')['content'] == 'SOURCE_MARKER\n'


def test_explicit_user_deny_remains_explicit(space):
    config = space[0] / 'custom-policy.json'
    config.write_text(json.dumps({'root': str(space[1]), 'deny': ['**/*credentials*']}), encoding='utf-8')
    policy = Policy.from_file(config)
    with pytest.raises(Fault) as got:
        policy.resolve('credentials.py')
    assert got.value.code == 'POLICY_DENIED'


def test_source_names_work_in_search_and_git(space):
    root, policy, service = space[1:]
    path = root / 'credentials.py'
    path.write_bytes(b'SOURCE_MARKER\n')
    assert service.grep('SOURCE_MARKER')['results'] == [{'path': 'credentials.py'}]
    policy.git_user_name = 'Synthetic'
    policy.git_user_email = 'synthetic@example.invalid'
    service.git_init()
    assert 'credentials.py' in str(service.git_status()['entries'])
    service.git_add(paths=['credentials.py'])
    assert 'SOURCE_MARKER' in service.git_diff(staged=True)['diff']
    assert service.git_commit(message='合成文件名回归')['files'] == ['credentials.py']
