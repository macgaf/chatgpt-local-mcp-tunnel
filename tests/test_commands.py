import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import pytest
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.server import Protocol
from home_readonly_mcp.onboarding import configure,load_settings
from home_readonly_mcp.policy import locations


def command(code):
    if os.name=='nt':
        return '& '+"'"+sys.executable.replace("'","''")+"' -c '"+code.replace("'","''")+"'"
    return shlex.join([sys.executable,'-c',code])


def wait(svc,sid,seconds=10):
    job=svc.commands.find(sid)
    assert job.done.wait(seconds)
    return svc.read_command_output(sid)


def test_command_default_off_and_enable_readonly_guard(space):
    p,svc=space[2:]
    assert 'run_command' not in Protocol(svc).specs
    with pytest.raises(Fault) as e:svc.run_command('echo forbidden')
    assert e.value.code=='COMMANDS_DISABLED'
    p.enable_commands=True;p.mode='read_only'
    assert 'start_command' not in Protocol(svc).specs
    with pytest.raises(Fault):svc.start_command('a','echo forbidden')


def test_sync_nonzero_and_real_file_write(space):
    root,p,svc=space[1:];p.enable_commands=True
    r=svc.run_command(command("from pathlib import Path; Path('built.txt').write_text('built'); print('DONE')"))
    assert r['completed'] and r['succeeded'] and r['exit_code']==0 and 'DONE' in r['output']
    assert (root/'built.txt').read_text()=='built'
    r=svc.run_command(command("print('FAILED');raise SystemExit(7)"))
    assert r['completed'] and not r['succeeded'] and r['exit_code']==7


def test_idempotence_and_id_conflict(space):
    root,p,svc=space[1:];p.enable_commands=True
    cmd=command("from pathlib import Path; p=Path('counter'); p.write_text(p.read_text()+'x' if p.exists() else 'x')")
    first=svc.start_command('once',cmd);wait(svc,first['session_id'])
    second=svc.start_command('once',cmd)
    assert first['session_id']==second['session_id'] and (root/'counter').read_text()=='x'
    with pytest.raises(Fault) as e:svc.start_command('once','echo different')
    assert e.value.code=='REQUEST_ID_CONFLICT'


def test_timeout_cancel_and_no_foreign_ids(space):
    root,p,svc=space[1:];p.enable_commands=True
    result=svc.start_command('timeout',command('import time;time.sleep(30)'),timeout_seconds=1)
    assert wait(svc,result['session_id'])['state']=='timed_out'
    result=svc.start_command('cancel',command('import time;time.sleep(30)'))
    svc.cancel_command(result['session_id'])
    assert wait(svc,result['session_id'])['state']=='cancelled'
    assert svc.cancel_command(result['session_id'])['state']=='cancelled'
    with pytest.raises(Fault) as e:svc.cancel_command(str(os.getpid()))
    assert e.value.code=='SESSION_NOT_FOUND'


def test_output_cursor_and_bounded_eviction(space):
    p,svc=space[2:];p.enable_commands=True;p.max_command_output_bytes=256
    result=svc.start_command('output',command("import sys; sys.stdout.write('X'*5000+'END')"))
    job=svc.commands.find(result['session_id']);assert job.done.wait(10)
    r=svc.read_command_output(job.id,0,64)
    assert r['truncated'] and r['first_cursor']>0 and r['has_more']
    allout=r['output']
    while r['has_more']:
        r=svc.read_command_output(job.id,r['next_cursor'],64);allout+=r['output']
    assert len(allout)<=256 and allout.endswith('END')
    with pytest.raises(Fault):svc.read_command_output(job.id,job.last+1)


def test_scoped_job_blocks_only_intersecting_mutation(space):
    root,p,svc=space[1:];p.enable_commands=True
    (root/'a').mkdir();(root/'b').mkdir()
    result=svc.start_command('build-a',command('import time;time.sleep(30)'),cwd='a')
    try:
        with pytest.raises(Fault) as e:svc.write_file('a/new.txt','no')
        assert e.value.code=='WORKSPACE_COMMAND_ACTIVE' and e.value.details['session_id']==result['session_id']
        assert svc.write_file('b/new.txt','allowed')['ok']
        assert svc.read_file('a.txt')['ok']
    finally:svc.cancel_command(result['session_id']);wait(svc,result['session_id'])
    assert svc.write_file('a/new.txt','allowed')['ok']


def test_concurrency_and_shutdown(space):
    p,svc=space[2:];p.enable_commands=True;p.max_active_commands=1
    result=svc.start_command('first',command('import time;time.sleep(30)'))
    with pytest.raises(Fault) as e:svc.start_command('second','echo no')
    assert e.value.code=='COMMAND_CONCURRENCY_LIMIT'
    svc.close()
    assert svc.commands.jobs[result['session_id']].done.is_set()
    with pytest.raises(Fault):svc.start_command('after','echo no')


def test_secrets_not_inherited(space,monkeypatch):
    p,svc=space[2:];p.enable_commands=True
    monkeypatch.setenv('CONTROL_PLANE_API_KEY','RUNTIME_SECRET_NOT_FOR_CHILD')
    monkeypatch.setenv('OPENAI_API_KEY','MODEL_SECRET_NOT_FOR_CHILD')
    r=svc.run_command(command("import os; print(os.environ.get('CONTROL_PLANE_API_KEY')); print(os.environ.get('OPENAI_API_KEY'))"))
    assert r['succeeded'] and 'SECRET_NOT_FOR_CHILD' not in r['output']


def test_local_risk_acknowledgement(space):
    cfg=locations()[0]/'config.json'
    configure(cfg,root=str(space[1]),mode='read_write')
    with pytest.raises(Fault) as e:configure(cfg,enable_commands=True)
    assert e.value.code=='COMMAND_RISK_ACK_REQUIRED'
    configure(cfg,enable_commands=True,acknowledge_unsandboxed_commands=True)
    assert load_settings(cfg)['enable_commands']
    configure(cfg,enable_commands=False)
    assert not load_settings(cfg)['enable_commands']


def test_descendant_cleanup(space):
    root,p,svc=space[1:];p.enable_commands=True
    # Grandchild would create a marker after the parent has exited without waiting.
    code="import subprocess,sys; subprocess.Popen([sys.executable,'-c',\"import time; from pathlib import Path; time.sleep(3);Path('orphan.txt').write_text('bad')\"]); print('parent exits')"
    r=svc.run_command(command(code),timeout_seconds=10)
    assert r['completed']
    time.sleep(3.3)
    assert not (root/'orphan.txt').exists()


def test_tool_exposure_full_mode_and_open_world(space):
    p,svc=space[2:];p.enable_commands=True;p.enable_git_push=True
    tools=Protocol(svc).specs
    assert len(tools)==38
    assert tools['run_command']['annotations']['openWorldHint']
    assert not tools['run_command']['annotations']['readOnlyHint']
    assert tools['git_push']['annotations']['openWorldHint']
    assert tools['read_command_output']['annotations']['readOnlyHint']
    p.mode='read_only'
    assert len(Protocol(svc).specs)==24


def test_stdio_shutdown_cleans_owned_jobs(space):
    root,p,svc=space[1:]
    cfg=space[0]/'commands.json';cfg.write_text(json.dumps({'root':str(root),'mode':'read_write','enable_commands':True}))
    code="import time;from pathlib import Path;time.sleep(3);Path('after-eof.txt').write_text('bad')"
    request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'start_command',
        'arguments':{'request_id':'shutdown','command':command(code)}}}
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    proc=subprocess.run([sys.executable,'-m','home_readonly_mcp.cli','--config',str(cfg),'server'],
                        input=json.dumps(request)+'\n',text=True,encoding='utf-8',capture_output=True,env=env,timeout=15)
    assert proc.returncode==0,proc.stderr
    assert not json.loads(proc.stdout)['result']['isError']
    time.sleep(3.3)
    assert not (root/'after-eof.txt').exists()


@pytest.mark.parametrize('exit_code',[0,3,19])
def test_native_exit_code_preserved(space,exit_code):
    p,svc=space[2:];p.enable_commands=True
    result=svc.run_command(command(f'raise SystemExit({exit_code})'))
    assert result['completed'] and result['exit_code']==exit_code
    assert result['succeeded']==(exit_code==0)


@pytest.mark.skipif(os.name!='nt',reason='PowerShell exit semantics require a real Windows shell')
@pytest.mark.parametrize('script,expected',[
    ("Write-Output 'OK'",0),
    ("Write-Error 'expected nonterminating fixture error'",1),
    ("throw 'expected terminating fixture error'",1),
    ("exit 23",23),
    (command('raise SystemExit(7)')+"; Write-Output 'recovered'",0),
])
def test_powershell_status_semantics(space,script,expected):
    p,svc=space[2:];p.enable_commands=True
    result=svc.run_command(script)
    assert result['completed'] and result['exit_code']==expected
    assert result['succeeded']==(expected==0)
