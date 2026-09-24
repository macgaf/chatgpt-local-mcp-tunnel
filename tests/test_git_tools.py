import os
from pathlib import Path
import shutil
import subprocess
import pytest
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.server import Protocol

pytestmark=pytest.mark.skipif(not shutil.which('git'),reason='Git is required for native Git integration tests')


def raw(root,*args):
    env=dict(os.environ,GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT='0')
    return subprocess.run(['git',*args],cwd=root,env=env,check=True,capture_output=True).stdout


def setup(space):
    root,p,svc=space[1:]
    p.git_user_name='MCP Test';p.git_user_email='test@example.invalid'
    assert svc.git_init()['created']
    return root,p,svc


def test_git_lifecycle_real(space):
    root,p,svc=setup(space)
    assert not svc.git_init()['created']
    assert svc.git_log()['commits']==[]
    assert any(x['path']=='a.txt' for x in svc.git_status()['entries'])
    assert svc.git_add(paths=['a.txt'])['staged_paths']==['a.txt']
    assert '+hello' in svc.git_diff(staged=True)['diff']
    commit=svc.git_commit(message='initial')
    assert len(commit['commit_sha'])==40
    assert svc.git_log()['commits'][0]['subject']=='initial'
    info=svc.read_file('a.txt');svc.edit_file('a.txt','hello','changed',info['sha256'])
    assert '+changed' in svc.git_diff()['diff']
    assert svc.git_diff(staged=True)['diff']==''
    svc.git_add();svc.git_commit(message='second')
    assert len(svc.git_log()['commits'])==2
    assert svc.git_status()['entries']==[]


def test_git_readonly(space):
    root,p,svc=setup(space);p.mode='read_only'
    assert svc.git_status()['ok']
    with pytest.raises(Fault) as e:svc.git_add()
    assert e.value.code=='READ_ONLY_MODE'
    specs=Protocol(svc).specs
    assert 'git_status' in specs and not {'git_add','git_push','git_commit'}&specs.keys()


def test_git_sensitive_paths_not_exposed_or_staged(space):
    root,p,svc=setup(space)
    (root/'.env').write_text('NEVER_EXPOSE_PRIVATE_VALUE')
    raw(root,'add','.env');raw(root,'-c','user.name=T','-c','user.email=t@example.invalid','commit','-m','sensitive fixture')
    (root/'.env').write_text('NEVER_EXPOSE_PRIVATE_VALUE_2')
    assert '.env' not in str(svc.git_status()['entries'])
    assert 'PRIVATE_VALUE' not in svc.git_diff()['diff']
    with pytest.raises(Fault):svc.git_add(paths=['.'])
    raw(root,'add','.env')
    with pytest.raises(Fault) as e:svc.git_commit(message='must not commit protected staged path')
    assert e.value.code=='GIT_PATH_DENIED'

@pytest.mark.parametrize('key,value',[
    ('include.path','/outside/config'),('filter.evil.clean','touch /tmp/should-not-run'),
    ('core.worktree','/tmp'),('core.sshCommand','sh -c echo'),
    ('http.cookieFile','/outside/cookies'),('remote.origin.receivepack','evil'),
    ('url.ext::evil.insteadOf','https://'),('extensions.partialClone','origin')])
def test_git_unsafe_config_rejected(space,key,value):
    root,p,svc=setup(space)
    raw(root,'config','--local',key,value)
    with pytest.raises(Fault) as e:svc.git_status()
    assert e.value.code=='UNSAFE_GIT_CONFIG'


def test_git_hooks_disabled(space):
    root,p,svc=setup(space)
    hook=root/'.git/hooks';hook.mkdir(exist_ok=True)
    (hook/'pre-commit').write_text('#!/bin/sh\necho ran > "'+str(root/'HOOK_RAN')+'"\nexit 1\n')
    (hook/'pre-commit').chmod(0o755)
    svc.git_add();svc.git_commit(message='no hooks')
    assert not (root/'HOOK_RAN').exists()


def test_git_external_diff_disabled(space):
    root,p,svc=setup(space);svc.git_add();svc.git_commit(message='initial')
    raw(root,'config','diff.external','touch '+str(root/'DIFF_RAN'))
    (root/'a.txt').write_text('changed')
    assert '+changed' in svc.git_diff()['diff']
    assert not (root/'DIFF_RAN').exists()


def test_git_alternates_and_redirects(space):
    root,p,svc=setup(space)
    info=root/'.git/objects/info';info.mkdir(exist_ok=True)
    (info/'alternates').write_text('/outside/objects')
    with pytest.raises(Fault) as e:svc.git_status()
    assert e.value.code=='UNSAFE_GIT_METADATA'
    (info/'alternates').unlink()
    other=root/'worktree';other.mkdir();(other/'.git').write_text('gitdir: /outside')
    with pytest.raises(Fault) as e:svc.git_status('worktree')
    assert e.value.code=='UNSUPPORTED_GIT_LAYOUT'


def test_git_identity_required_and_index_lock_reason(space):
    root,p,svc=setup(space);svc.git_add()
    p.git_user_name='';p.git_user_email=''
    with pytest.raises(Fault) as e:svc.git_commit(message='none')
    assert e.value.code=='GIT_IDENTITY_MISSING'
    (root/'.git/index.lock').write_text('occupied')
    with pytest.raises(Fault) as e:svc.git_add()
    assert e.value.code=='GIT_LOCKED' and e.value.details['holder']=='unknown'
    assert (root/'.git/index.lock').exists()


def test_git_literal_paths_no_flag_injection(space):
    root,p,svc=setup(space)
    (root/'--force').write_text('literal')
    svc.git_add(paths=['--force']);r=svc.git_commit(message='literal')
    assert '--force' in r['files']
    with pytest.raises(Fault):svc.git_add(paths=['../outside'])


def test_git_push_requires_flags_and_url_allowlist(space,monkeypatch):
    root,p,svc=setup(space);svc.git_add();svc.git_commit(message='initial')
    with pytest.raises(Fault) as e:svc.git_push()
    assert e.value.code=='GIT_PUSH_DISABLED'
    p.enable_git_push=True
    raw(root,'remote','add','origin','https://example.invalid/test.git')
    with pytest.raises(Fault) as e:svc.git_push()
    assert e.value.code=='GIT_REMOTE_NOT_APPROVED'
    p.git_push_remotes=['https://example.invalid/test.git']
    original=svc.git.run;sent=[]
    def intercept(repo,args,**kwargs):
        if args[0]=='push':
            sent.append((args,kwargs));return 0,b'Done'
        return original(repo,args,**kwargs)
    monkeypatch.setattr(svc.git,'run',intercept)
    assert svc.git_push()['ok']
    assert sent[0][0][-1]=='HEAD:refs/heads/main' and sent[0][1]['network']
    assert not any(x in sent[0][0] for x in ('--force','--mirror','--delete'))

@pytest.mark.parametrize('url',['/tmp/local.git','file:///tmp/repo','ext::sh malicious','https://u:secret@example.invalid/r.git'])
def test_git_push_disallowed_transport(space,url):
    root,p,svc=setup(space);p.enable_git_push=True;p.git_push_remotes=[url]
    raw(root,'remote','add','origin',url)
    with pytest.raises(Fault) as e:svc.git_push()
    assert e.value.code=='GIT_TRANSPORT_DENIED'


def test_coding_workflow_end_to_end(space):
    import shlex,sys
    root,p,svc=setup(space)
    p.enable_commands=True
    (root/'calc.py').write_text('def add(a,b):\n    return a-b\n',encoding='utf-8')
    (root/'test_calc.py').write_text('from calc import add\nassert add(2,3)==5\n',encoding='utf-8')
    svc.git_add();svc.git_commit(message='fixture')
    assert svc.workspace_context()['git_status']['entries']==[]
    assert svc.search_code(['add'])['queries'][0]['results']
    reads=svc.batch_read([{'tool':'read_file','arguments':{'path':name}} for name in ('calc.py','test_calc.py')])
    sha=reads['results'][0]['result']['sha256']
    result=svc.apply_patch(changes=[{'path':'calc.py','old_text':'return a-b','new_text':'return a+b','expected_sha256':sha}])
    assert result['ok']
    cmd=("& '"+sys.executable.replace("'","''")+"' test_calc.py") if os.name=='nt' else shlex.join([sys.executable,'test_calc.py'])
    run=svc.run_command(cmd,request_id='verify-add')
    assert run['succeeded'] and run['exit_code']==0
    assert '+    return a+b' in svc.git_diff()['diff']
    svc.git_add(paths=['calc.py']);commit=svc.git_commit(message='fix addition')
    assert svc.git_log()['commits'][0]['sha']==commit['commit_sha']
