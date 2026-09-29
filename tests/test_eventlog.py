"""Real bounded files/rotation/processes/CLI; no credentials or user files."""
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import errno
import pytest
from home_readonly_mcp.eventlog import EventLog, LogSettings, error_fields, recent, follow, export
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.policy import locations
from home_readonly_mcp.onboarding import record_tunnel_event, configure

SECRET = 'sk-log-test-private-1234567890123'
TUNNEL = 'tunnel_' + 'a' * 32


def logger(space, **options):
    return EventLog(state_dir=space[2].state_dir, settings=options or None)


def records(log, **options):
    return recent(log.directory, tail=5000, **options)['records']


def test_default_location_and_options(space):
    log = logger(space)
    assert log.directory == locations()[2]/'logs'
    assert log.settings.max_bytes == 5242880
    assert log.settings.backup_count == 5 and log.settings.retention_days == 14
    assert not log.directory.exists()  # path lookup isn't a write


@pytest.mark.parametrize('bad', [False, [], {'extra': 1}, {'level':'TRACE'}, {'enabled':1},
    {'max_bytes':0}, {'backup_count':11}, {'retention_days':0}])
def test_invalid_log_settings(bad):
    with pytest.raises((ValueError, TypeError)):
        LogSettings.parse(bad)


def test_jsonl_metadata_without_bodies_or_credentials(space):
    log = logger(space)
    assert log.emit('mcp','tool_call',tool='write_file',request_id='request-001',ok=True,
        content='PRIVATE_SOURCE',command='PRIVATE_COMMAND',output='PRIVATE_OUTPUT',
        arguments={'password':SECRET},api_key=SECRET,tunnel_id=TUNNEL)
    row = records(log)[0]
    assert row['timestamp'].endswith('+00:00') and row['request_id']=='request-001'
    assert row['pid']==os.getpid() and row['tool']=='write_file'
    raw=(log.directory/'mcp.jsonl').read_text(encoding='utf-8')
    for value in ['PRIVATE_SOURCE','PRIVATE_COMMAND','PRIVATE_OUTPUT',SECRET,TUNNEL]:
        assert value not in raw
    if os.name!='nt':
        assert (log.directory/'mcp.jsonl').stat().st_mode & 0o777 == 0o600
        assert log.directory.stat().st_mode & 0o777 == 0o700


def test_id_and_known_secret_redaction(space):
    log=logger(space)
    log.emit('mcp','tool_call',request_id=TUNNEL,operation=SECRET)
    assert SECRET not in (log.directory/'mcp.jsonl').read_text(encoding='utf-8')
    assert TUNNEL not in json.dumps(records(log))
    assert records(log)[0]['request_id']=='[REDACTED]'


def test_error_reason_not_raw_exception(space):
    log=logger(space)
    error=Fault('FILE_LOCKED','PRIVATE_ERROR','PRIVATE_CAUSE','PRIVATE_ACTION',
                holder={'pid':234,'started_at':12.3,'command':SECRET},token=SECRET)
    log.emit('mcp','tool_call','ERROR',**error_fields(error))
    r=records(log)[0]
    assert r['error_code']=='FILE_LOCKED' and r['holder_pid']==234
    assert r['cause'] and r['remediation']
    assert 'PRIVATE_' not in json.dumps(r) and SECRET not in json.dumps(r)


def test_unknown_error_suppresses_source_and_stack(space):
    log=logger(space)
    log.emit('mcp','tool_call','ERROR',**error_fields(RuntimeError('PRIVATE_SOURCE '+SECRET)))
    assert records(log)[0]['error_type']=='RuntimeError'
    assert 'PRIVATE_SOURCE' not in json.dumps(records(log))


def test_level_and_disabled(space):
    log=logger(space,level='WARNING')
    log.emit('mcp','hidden')
    assert not log.directory.exists()
    log.emit('mcp','problem','ERROR')
    assert len(records(log))==1
    off=logger(space,enabled=False)
    off.emit('mcp','hidden','ERROR')
    assert len(records(log))==1 and off.probe()['status']=='disabled'


def test_rotation_bounded_and_retention(space):
    log=logger(space,max_bytes=16384,backup_count=2,retention_days=1)
    for i in range(220):
        assert log.emit('mcp','tool_call',request_id=str(i),error_code='HASH_CONFLICT')
    paths=list(log.directory.glob('mcp.jsonl*'))
    assert len(paths)==3
    assert all(p.stat().st_size <= 16384 for p in paths)
    assert records(log)[-1]['request_id']=='219'
    aged=log.directory/'mcp.jsonl.2'
    os.utime(aged,(time.time()-2*86400,)*2)
    log.emit('mcp','fresh')
    assert not aged.exists() or aged.stat().st_mtime > time.time()-86400


def test_zero_backups_and_unrelated_files_preserved(space):
    log=logger(space,max_bytes=16384,backup_count=0)
    log.emit('cli','start')
    other=log.directory/'user-notes.txt';other.write_text('keep')
    for i in range(100):log.emit('cli','step',request_id=str(i))
    assert not (log.directory/'cli.jsonl.1').exists()
    assert other.read_text(encoding='utf-8')=='keep'


def test_threaded_logs_not_interleaved(space):
    log=logger(space)
    threads=[threading.Thread(target=lambda n=n: [log.emit('mcp','thread',request_id=f'{n}-{i}') for i in range(20)]) for n in range(6)]
    for t in threads:t.start()
    for t in threads:t.join()
    rows=records(log)
    assert len(rows)==120 and len({r['request_id'] for r in rows})==120 and log.dropped==0


def test_multiprocess_append(space):
    state=space[2].state_dir
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    code="""import sys
from home_readonly_mcp.eventlog import EventLog
x=EventLog(state_dir=sys.argv[1])
for i in range(30):
 assert x.emit('mcp','process',request_id=sys.argv[2]+'-'+str(i))
"""
    children=[subprocess.Popen([sys.executable,'-c',code,str(state),str(n)],env=env,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE) for n in range(4)]
    for proc in children:
        stdout,stderr=proc.communicate(timeout=15)
        assert proc.returncode==0,(stdout,stderr)
    rows=records(logger(space))
    assert len(rows)==120 and len({r['event_id'] for r in rows})==120


@pytest.mark.skipif(os.name=='nt',reason='symlink creation needs Windows privilege')
def test_reject_symlink_log_without_touching_target(space,capsys):
    log=logger(space);log.directory.mkdir(parents=True)
    target=space[1]/'protected';target.write_text('unchanged')
    (log.directory/'mcp.jsonl').symlink_to(target)
    assert not log.emit('mcp','event')
    assert target.read_text(encoding='utf-8')=='unchanged'
    assert 'LOG_WRITE_FAILED' in capsys.readouterr().err


def test_reject_hardlink_log(space):
    log=logger(space);log.directory.mkdir(parents=True)
    target=space[1]/'target';target.write_text('unchanged')
    os.link(target,log.directory/'mcp.jsonl')
    assert not log.emit('mcp','event')
    assert target.read_text(encoding='utf-8')=='unchanged'


def test_disk_failure_warns_once_without_stdout_or_secrets(space,monkeypatch,capsys):
    log=logger(space)
    def fail(*args):raise OSError(errno.ENOSPC,SECRET)
    monkeypatch.setattr(log,'_append',fail)
    assert not log.emit('mcp','first') and not log.emit('mcp','second')
    output=capsys.readouterr()
    assert output.out=='' and output.err.count('LOG_WRITE_FAILED')==1 and SECRET not in output.err
    assert log.dropped==2 and log.last_error['errno']==errno.ENOSPC


def test_bad_config_falls_back_and_does_not_dump_config(space,capsys):
    p=space[0]/'bad.json';p.write_text('{PRIVATE '+SECRET)
    log=EventLog(p)
    log.emit('cli','configuration_failed','ERROR')
    assert log.settings_error and len(records(log))==1
    assert SECRET not in capsys.readouterr().err


def test_recent_filters_and_export_safe_schema(space,tmp_path):
    log=logger(space)
    log.emit('mcp','tool_call',request_id='7')
    log.emit('mcp','tool_call','ERROR',request_id='8',error_code='HASH_CONFLICT')
    log.emit('cli','diagnostic_check',stage='stdio_handshake')
    assert len(records(log,component='mcp',level='ERROR',request_id='8'))==1
    # A manually edited log is not trusted as a bag of arbitrary user data.
    with (log.directory/'mcp.jsonl').open('a') as f:
        f.write(json.dumps({'timestamp':'2026-09-24T00:00:00+00:00','component':'mcp','level':'ERROR',
            'event':'edited','event_id':'id','process_id':'id','content':SECRET})+'\n')
        f.write('{corrupt}\n')
    destination=tmp_path/'export.json'
    result=export(log.directory,destination,tail=30)
    assert result['invalid_records']==1 and SECRET not in destination.read_text(encoding='utf-8')
    with pytest.raises(FileExistsError):export(log.directory,destination)


def test_follow_rotation_and_future_file(space, monkeypatch):
    from home_readonly_mcp import eventlog
    log=logger(space,max_bytes=16384,backup_count=5)
    out=StringIO();stop=threading.Event()
    ready=threading.Event()
    original_segments=eventlog._segments
    def snapshot_then_signal(*args, **kwargs):
        result=original_segments(*args, **kwargs)
        ready.set()
        return result
    monkeypatch.setattr(eventlog,'_segments',snapshot_then_signal)
    thread=threading.Thread(target=follow,args=(log.directory,),kwargs={
        'component':'commands','tail':0,'stop_event':stop,'interval':0.02,'output':out,'json_output':True})
    thread.start()
    try:
        # tail=0 会跳过初始快照；先等空快照完成，再开始写未来记录。
        assert ready.wait(5), '日志跟随器未完成初始快照'
        for i in range(70):
            assert log.emit('commands','command_started',request_id=f'{i}')
            time.sleep(0.005)
        until=time.monotonic()+3
        while len(out.getvalue().splitlines())<70 and time.monotonic()<until:time.sleep(0.02)
    finally:
        stop.set();thread.join(timeout=5)
    rows=[json.loads(x) for x in out.getvalue().splitlines()]
    assert len(rows)==70 and len({r['request_id'] for r in rows})==70


def test_tunnel_persists_categories_not_raw_output(space):
    log=logger(space,level='DEBUG')
    for text in [json.dumps({'error':error,'body':'PRIVATE_SOURCE '+SECRET,'authorization':TUNNEL})
                 for error in ('401 unauthorized','403 forbidden','DNS error','TLS error','connected','unknown')]:
        record_tunnel_event(log,text)
    rows=records(log,component='tunnel')
    assert len(rows)==6 and any(r.get('error_code')=='DNS_FAILURE' for r in rows)
    text=(log.directory/'tunnel.jsonl').read_text(encoding='utf-8')
    assert SECRET not in text and TUNNEL not in text and 'PRIVATE_SOURCE' not in text


def test_service_logs_failures_and_leaves_stdout_clean(space,capsys):
    from home_readonly_mcp.server import Protocol
    p=Protocol(space[3])
    (space[1]/'private.txt').write_text('PRIVATE_BODY')
    result=p.result({'jsonrpc':'2.0','id':19,'method':'tools/call',
        'params':{'name':'read_file','arguments':{'path':'private.txt'}}})
    assert not result['result']['isError']
    result=p.result({'jsonrpc':'2.0','id':20,'method':'tools/call',
        'params':{'name':'read_file','arguments':{'path':'.env'}}})
    assert result['result']['isError']
    rows=records(space[3].audit,component='mcp')
    assert [r['request_id'] for r in rows]==['19','20']
    assert rows[-1]['error_code']=='POLICY_DENIED' and 'PRIVATE_BODY' not in json.dumps(rows)
    assert capsys.readouterr().out==''


def test_real_command_completion_no_command_output_logging(space):
    import shlex
    p,svc=space[2:];p.enable_commands=True
    body="print('PRIVATE_COMMAND_OUTPUT')"
    cmd=("& '"+sys.executable+"' -c \""+body+"\"") if os.name=='nt' else shlex.join([sys.executable,'-c',body])
    result=svc.run_command(cmd,timeout_seconds=60,request_id='logger-command')
    assert result['completed'] and result['exit_code']==0
    rows=records(svc.audit,component='commands')
    assert [r['event'] for r in rows]==['command_started','command_finished']
    assert rows[-1]['exit_code']==0 and 'PRIVATE_COMMAND_OUTPUT' not in json.dumps(rows)


def test_logging_failure_does_not_retry_or_break_write(space,monkeypatch):
    from home_readonly_mcp.server import Protocol
    svc=space[3]
    def fail(*args):raise OSError(errno.ENOSPC,'disk full')
    monkeypatch.setattr(svc.audit,'_append',fail)
    response=Protocol(svc).result({'jsonrpc':'2.0','id':1,'method':'tools/call',
        'params':{'name':'write_file','arguments':{'path':'new.txt','content':'ONCE'}}})
    assert not response['result']['isError'] and (space[1]/'new.txt').read_text(encoding='utf-8')=='ONCE'


def test_real_cli_path_configure_show_export(space):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cfg=locations()[0]/'config.json'
    configure(cfg,root=str(space[1]))
    data=json.loads(cfg.read_text(encoding='utf-8'));data['tunnel_id']=TUNNEL;data['custom_setting']='keep'
    cfg.write_text(json.dumps(data))
    def run(*args):
        proc=subprocess.run([sys.executable,'-m','home_readonly_mcp.cli','--config',str(cfg),*args],
            env=env,capture_output=True,text=True,encoding='utf-8',timeout=15)
        assert proc.returncode==0,proc.stderr
        return proc
    assert Path(run('logs','path').stdout.strip())==locations()[2]/'logs'
    run('logs','configure','--level','DEBUG','--max-mib','1','--keep','2','--days','7')
    settings=json.loads(cfg.read_text(encoding='utf-8'))
    assert settings['custom_setting']=='keep' and settings['tunnel_id']==TUNNEL
    run('self-test')
    output=run('logs','show','--component','cli','--json').stdout
    assert 'operation_finished' in output and TUNNEL not in output
    dest=space[0]/'diagnostics.json'
    run('logs','export','--output',str(dest))
    assert TUNNEL not in dest.read_text(encoding='utf-8')


def test_stdio_eof_and_startup_failure_recorded(space):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cfg=space[0]/'cfg.json';cfg.write_text(json.dumps({'root':str(space[1])}))
    command=[sys.executable,'-m','home_readonly_mcp.cli','--config',str(cfg),'server']
    r=subprocess.run(command,input='',env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert r.returncode==0 and r.stdout==''
    rows=records(logger(space),component='mcp')
    assert {'server_started','server_stopped'} <= {r['event'] for r in rows}
    cfg.write_text('invalid '+SECRET)
    r=subprocess.run(command,input='',env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert r.returncode!=0 and r.stdout==''
    assert 'server_start_failed' in {r['event'] for r in records(logger(space),component='mcp')}
    assert SECRET not in json.dumps(records(logger(space)))
