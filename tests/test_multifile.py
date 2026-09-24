import json
import pytest
from home_readonly_mcp import patches
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.storage import digest,Lease
from home_readonly_mcp.server import Protocol


def changes(space):
    root,p,svc=space[1:]
    (root/'b.txt').write_bytes(b'world\r\n')
    return [dict(path='a.txt',old_text='hello',new_text='HELLO',expected_sha256=svc.read_file('a.txt')['sha256']),
            dict(relative_path='b.txt',old_text='world',new_text='WORLD',expected_sha256=svc.read_file('b.txt')['sha256'])]


def test_multifile_and_samefile_order(space):
    root,p,svc=space[1:];c=changes(space)
    c.append(dict(c[0],old_text='HELLO',new_text='final'))
    result=svc.apply_patch(changes=c)
    assert result['file_count']==2 and result['change_count']==3
    assert svc.read_file('a.txt')['content'].startswith('final')
    assert (root/'b.txt').read_bytes()==b'WORLD\r\n'
    assert len(svc.list_backups('a.txt')['backups'])==1
    assert not result['atomic_across_files'] and not result['crash_atomic']
    j=json.loads((p.state_dir/'transactions'/(result['transaction_id']+'.json')).read_text())
    assert j['state']=='committed' and len(j['applied'])==2


def test_batch_validates_before_any_write(space):
    svc=space[3];c=changes(space);before=svc.read_file('a.txt')['sha256']
    c[1]['expected_sha256']='0'*64
    with pytest.raises(Fault) as e:svc.apply_patch(changes=c)
    assert e.value.code=='HASH_CONFLICT'
    assert svc.read_file('a.txt')['sha256']==before
    assert svc.list_backups('a.txt')['backups']==[]


def test_multifile_dry_run_no_backups_or_journal(space):
    svc=space[3];c=changes(space)
    result=svc.apply_patch(changes=c,dry_run=True)
    assert result['dry_run'] and len(result['files'])==2
    assert svc.read_file('a.txt')['content'].startswith('hello')
    assert not (space[2].state_dir/'transactions').exists()


def test_failure_rolls_back_without_losing_original(space,monkeypatch):
    root,p,svc=space[1:];c=changes(space);original=patches.commit_bytes
    def fail(policy,path,new,old,expected,**kwargs):
        if path.name=='b.txt' and new.startswith(b'WORLD'):raise OSError('simulated replace failure')
        return original(policy,path,new,old,expected,**kwargs)
    monkeypatch.setattr(patches,'commit_bytes',fail)
    with pytest.raises(Fault) as e:svc.apply_patch(changes=c)
    assert e.value.code=='PATCH_FAILED_ROLLED_BACK'
    assert svc.read_file('a.txt')['content'].startswith('hello')
    assert (root/'b.txt').read_bytes()==b'world\r\n'
    assert any(x['status']=='restored' for x in e.value.details['rollback'])


def test_failure_never_clobbers_external_edit(space,monkeypatch):
    root,p,svc=space[1:];c=changes(space);original=patches.commit_bytes
    def fail(policy,path,new,old,expected,**kwargs):
        if path.name=='b.txt':
            (root/'a.txt').write_text('EXTERNAL USER CHANGE')
            raise OSError('simulated later write failure')
        return original(policy,path,new,old,expected,**kwargs)
    monkeypatch.setattr(patches,'commit_bytes',fail)
    with pytest.raises(Fault) as e:svc.apply_patch(changes=c)
    assert e.value.code=='PATCH_ROLLBACK_INCOMPLETE'
    assert (root/'a.txt').read_text()=='EXTERNAL USER CHANGE'
    assert any(x['status']=='external_change_not_overwritten' for x in e.value.details['rollback'])


def test_overlapping_matches_are_ambiguous(space):
    svc=space[3];(space[1]/'overlap').write_text('aaa')
    with pytest.raises(Fault) as e:svc.edit_file('overlap','aa','x',digest(b'aaa'))
    assert e.value.code=='AMBIGUOUS_EDIT'


def test_crossfile_budget_and_mixed_api_forms(space):
    c=changes(space);p,svc=space[2:];p.max_patch_bytes=1
    with pytest.raises(Fault) as e:svc.apply_patch(changes=c)
    assert e.value.code=='PATCH_BUDGET_EXCEEDED'
    with pytest.raises(ValueError):svc.apply_patch(path='a.txt',changes=c)


def test_multifile_protocol(space):
    c=changes(space)
    result=Protocol(space[3]).result({'jsonrpc':'2.0','id':1,'method':'tools/call',
        'params':{'name':'apply_patch','arguments':{'changes':c}}})
    assert not result['result']['isError']
    assert result['result']['structuredContent']['file_count']==2
