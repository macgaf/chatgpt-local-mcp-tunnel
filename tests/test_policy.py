import json
import os
from pathlib import Path
import pytest
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.policy import Policy, locations
from home_readonly_mcp.service import HomeService

@pytest.mark.parametrize('name',['.ssh/private','.aws/credentials','.gnupg/private','.kube/config',
    '.codex/auth.json','.docker/config.json','.git-credentials','.npmrc','.env','.env.local',
    'project/.env','.env.example','nested/credentials.json','private.key','public.pem',
    'a/secrets/file','node_modules/code.js','.git/config','Library/Keychains/login.keychain-db',
    'Library/Application Support/Google/Chrome/Default/Cookies','.local/share/keyrings/login.keyring'])
def test_denies_sensitive(space,name):
    home,root,policy,svc=space
    with pytest.raises(Fault) as got:
        policy.resolve(name)
    assert got.value.code=='POLICY_DENIED'

@pytest.mark.parametrize('name',['../other','/etc/passwd','a/../../x'])
def test_outside(space,name):
    with pytest.raises(Fault):
        space[2].resolve(name)

@pytest.mark.parametrize('name',['','.', 'a.txt','docs/AGENTS.md','skills/coding/SKILL.md'])
def test_normal_paths(space,name):
    assert space[2].resolve(name).is_relative_to(space[1])

def test_mode_is_enforced_even_direct_call(space):
    *_,policy,svc=space
    policy.mode='read_only'
    with pytest.raises(Fault,match='只读') as got:
        svc.write_file('new','no')
    assert got.value.code=='READ_ONLY_MODE'
    assert not (space[1]/'new').exists()

def test_exact_force_allow_not_hard_protected(space):
    p=space[2]
    p.force_allow=['.env.example','.ssh/id_ed25519']
    assert p.resolve('.env.example')
    with pytest.raises(Fault): p.resolve('.ssh/id_ed25519')

def test_wildcard_force_allow_rejected(space):
    with pytest.raises(ValueError): Policy(root=space[1],force_allow=['**/.env.example'])

def test_deny_beats_allow(space):
    p=space[2];p.allow=['**'];p.deny=['a.txt']
    with pytest.raises(Fault): p.resolve('a.txt')

def test_allow_only_policy(space):
    p=space[2];p.default_policy='deny';p.allow=['a.txt','docs/**']
    assert p.resolve('a.txt')
    with pytest.raises(Fault):p.resolve('other.txt')

def test_write_scope(space):
    p=space[2];p.write_roots=['docs/**']
    assert p.resolve('a.txt')
    with pytest.raises(Fault) as got:p.resolve('a.txt',write=True)
    assert got.value.code=='WRITE_SCOPE_DENIED'
    assert p.resolve('docs/x',write=True)

def test_narrow_root_cannot_unprotect_credentials(space):
    home=space[0];danger=home/'.ssh';danger.mkdir()
    (danger/'nonstandard-name').write_text('private')
    p=Policy(root=danger,force_allow=['nonstandard-name'])
    with pytest.raises(Fault): p.resolve('nonstandard-name')

def test_runtime_immutable(space):
    home=space[0];p=Policy(root=home)
    for x in [locations()[0]/'config.json',locations()[1]/'launch.py',locations()[2]/'backups/x',home/'.local/bin/local-mcp']:
        with pytest.raises(Fault) as got:p.resolve(str(x))
        assert got.value.code=='PROTECTED_RUNTIME'

@pytest.mark.skipif(os.name=='nt',reason='symlink creation needs Windows privilege')
def test_symlink_paths(space,tmp_path):
    root,p,svc=space[1:]
    (root/'alias').symlink_to(root/'a.txt')
    assert svc.read_file('alias')['content'].startswith('hello')
    with pytest.raises(Fault) as got:svc.write_file('alias','no')
    assert got.value.code=='SYMLINK_WRITE_DENIED'
    (root/'outside').symlink_to(tmp_path)
    with pytest.raises(Fault):svc.read_file('outside/file')
    (root/'.env').write_text('blocked')
    (root/'masked').symlink_to(root/'.env')
    with pytest.raises(Fault):svc.read_file('masked')
    assert 'masked' not in [x['name'] for x in svc.list_directory()['entries']]

def test_hardlinks_refused(space):
    root,svc=space[1],space[3]
    os.link(root/'a.txt',root/'hardlink')
    with pytest.raises(Fault) as got:svc.read_file('hardlink')
    assert got.value.code=='HARDLINK_DENIED'

def test_config_roundtrip(space):
    path=space[0]/'config.json'
    path.write_text(json.dumps({'root':str(space[1]),'mode':'read_only'}))
    p=Policy.from_file(path)
    assert p.mode=='read_only'
    with pytest.raises(Fault):p.resolve(str(path))

def test_invalid_configuration(space):
    for kw in [{'mode':'write'},{'max_file_size':0},{'allow':'*'}, {'max_file_size':300*1024*1024}]:
        with pytest.raises(ValueError):Policy(root=space[1],**kw)
