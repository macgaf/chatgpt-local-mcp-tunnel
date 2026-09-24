import base64
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from home_readonly_mcp.errors import Fault,normalize_error,redact
from home_readonly_mcp.storage import digest,Lease


def test_write_edit_backup_restore(space):
    root,svc=space[1],space[3]
    original=svc.read_file('a.txt')
    new=svc.edit_file('a.txt','hello','HELLO',original['sha256'])
    assert svc.read_file('a.txt')['content']=='HELLO\n世界\n'
    assert new['backup_id'] in [x['id'] for x in svc.list_backups('a.txt')['backups']]
    restored=svc.restore_file('a.txt',new['backup_id'],new['sha256'])
    assert restored['sha256']==original['sha256']
    assert restored['backup_id']!=new['backup_id']
    if os.name!='nt':
        assert (space[2].state_dir/'backups'/f"{new['backup_id']}.bin").stat().st_mode & 0o777==0o600


def test_new_file_and_binary(space):
    svc=space[3]
    r=svc.write_file('new.txt','中文',expected_sha256='MISSING')
    assert r['previous_sha256']=='MISSING' and r['backup_id'] is None
    body=b'\0\xff\x11'
    r=svc.write_binary('b.bin',base64.b64encode(body).decode())
    assert (space[1]/'b.bin').read_bytes()==body
    assert r['sha256']==digest(body)

@pytest.mark.parametrize('expected,code',[(None,'PRECONDITION_REQUIRED'),('0'*64,'HASH_CONFLICT'),('MISSING','HASH_CONFLICT')])
def test_conflicts_never_write(space,expected,code):
    svc=space[3];before=(space[1]/'a.txt').read_bytes()
    with pytest.raises(Fault) as got:svc.write_file('a.txt','no',expected)
    assert got.value.code==code
    assert (space[1]/'a.txt').read_bytes()==before


def test_dry_run_creates_no_backup(space):
    svc=space[3];before=svc.read_file('a.txt')
    r=svc.apply_patch('a.txt',[{'old_text':'hello','new_text':'bye'}],before['sha256'],True)
    assert 'bye' in r['diff'] and r['dry_run']
    assert svc.read_file('a.txt')==before
    assert svc.list_backups('a.txt')['backups']==[]

@pytest.mark.parametrize('needle',['','not in file','l'])
def test_ambiguous_edits(space,needle):
    svc=space[3];h=svc.read_file('a.txt')['sha256']
    with pytest.raises(Fault) as got:svc.edit_file('a.txt',needle,'x',h)
    assert got.value.code=='AMBIGUOUS_EDIT'
    assert svc.read_file('a.txt')['sha256']==h


def test_ordered_patch_no_partial_change(space):
    svc=space[3];h=svc.read_file('a.txt')['sha256']
    with pytest.raises(Fault):svc.apply_patch('a.txt',[{'old_text':'hello','new_text':'bye'},
        {'old_text':'absent','new_text':'x'}],h)
    assert svc.read_file('a.txt')['sha256']==h


def test_mkdir_only_one_level(space):
    svc=space[3]
    assert svc.create_directory('docs')['created']
    assert not svc.create_directory('docs')['created']
    with pytest.raises(FileNotFoundError):svc.create_directory('missing/subdir')


def test_no_root_mutation(space):
    with pytest.raises(Fault) as got:space[3].create_directory('.')
    assert got.value.code=='ROOT_MUTATION_DENIED'


def test_backup_scope_and_corruption(space):
    svc=space[3];h=svc.read_file('a.txt')['sha256']
    r=svc.write_file('a.txt','b',h)
    with pytest.raises(Fault) as got:svc.restore_file('elsewhere',r['backup_id'],'MISSING')
    assert got.value.code=='BACKUP_SCOPE_MISMATCH'
    (space[2].state_dir/'backups'/f"{r['backup_id']}.bin").write_bytes(b'corrupt')
    with pytest.raises(Fault) as got:svc.restore_file('a.txt',r['backup_id'],r['sha256'])
    assert got.value.code=='BACKUP_CORRUPT'


def test_limits_and_text_ranges(space):
    svc=space[3];p=space[2]
    assert svc.read_file('a.txt',2,2)['content']=='世界\n'
    p.max_file_size=2
    with pytest.raises(Fault):svc.read_file('a.txt')
    with pytest.raises(Fault):svc.write_file('large','123')


def test_search_skips_sensitive_and_has_budget(space):
    root,p,svc=space[1:]
    (root/'.env').write_text('NEEDLE')
    (root/'b.txt').write_text('needle')
    assert [r['path'] for r in svc.search_text('NEEDLE')['results']]==['b.txt']
    for i in range(5):(root/f'dir{i}').mkdir()
    p.max_search_files=2
    assert svc.find_files('never-found')['truncated']


def test_list_pagination(space):
    svc=space[3];root=space[1]
    for i in range(4):(root/f'{i}.txt').write_text('x')
    first=svc.list_directory(limit=2)
    second=svc.list_directory(offset=first['next_offset'],limit=2)
    assert not {x['name'] for x in first['entries']} & {x['name'] for x in second['entries']}


def test_crossprocess_lock_and_stale_recovery(space):
    root,p,svc=space[1:]
    code="""import sys,time
from home_readonly_mcp.storage import Lease
with Lease(sys.argv[1],sys.argv[2],'test_writer'):
 print('locked',flush=True)
 time.sleep(30)
"""
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    proc=subprocess.Popen([sys.executable,'-c',code,str(p.state_dir),str(root/'a.txt')],
        stdout=subprocess.PIPE,text=True,encoding='utf-8',env=env)
    try:
        assert proc.stdout.readline().strip()=='locked'
        with pytest.raises(Fault) as got:svc.write_file('a.txt','blocked')
        assert got.value.code=='FILE_LOCKED'
        holder=got.value.details['holder']
        assert holder['pid']==proc.pid and holder['operation']=='test_writer'
        assert 'started_at' in holder
        assert svc.write_file('unrelated','allowed')['ok']
        assert svc.diagnose('a.txt')['lock']['held']
    finally:
        proc.terminate();proc.wait(timeout=5);proc.stdout.close()
    # Metadata remains, but OS releases lease when process dies; never unlink a held lock.
    assert not svc.diagnose('a.txt')['lock']['held']
    h=svc.read_file('a.txt')['sha256']
    assert svc.write_file('a.txt','recovered',h)['ok']

@pytest.mark.parametrize('number,code',[(errno.EBUSY,'OS_FILE_BUSY'),(errno.EACCES,'OS_PERMISSION_DENIED'),
    (errno.ENOSPC,'DISK_FULL'),(errno.EROFS,'READ_ONLY_FILESYSTEM'),(errno.ENOENT,'NOT_FOUND')])
def test_os_errors_have_remediation(number,code):
    result=normalize_error(OSError(number,'testing')).payload()['error']
    assert result['code']==code and result['cause'] and result['remediation'] and result['request_id']


def test_redaction():
    key='sk-test-secret-1234567890'
    assert key not in json.dumps(redact({'api_key':key,'other':'error '+key,'authorization':'Bearer abcd'}))


def test_crlf_read_edit_and_restore_preserve_bytes(space):
    original='hello\r\n世界\r\n'.encode('utf-8')
    root,svc=space[1],space[3]
    (root/'crlf.txt').write_bytes(original)
    before=svc.read_file('crlf.txt')
    assert before['content']=='hello\r\n世界\r\n'
    assert before['sha256']==digest(original)
    assert svc.read_file('crlf.txt',2,2)['content']=='世界\r\n'
    result=svc.edit_file('crlf.txt','hello','HELLO',before['sha256'])
    assert (root/'crlf.txt').read_bytes()=='HELLO\r\n世界\r\n'.encode('utf-8')
    svc.restore_file('crlf.txt',result['backup_id'],result['sha256'])
    assert (root/'crlf.txt').read_bytes()==original
