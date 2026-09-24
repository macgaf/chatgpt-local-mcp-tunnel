import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from home_readonly_mcp.server import Protocol,WRITES,MODERN
from home_readonly_mcp.storage import digest
from home_readonly_mcp.cli import self_test


def call(protocol,method,params=None,ident=1):
    return protocol.result({'jsonrpc':'2.0','id':ident,'method':method,'params':params or {}})


def test_real_stdio_core():
    r=self_test()
    assert r['ok'] and r['legacy_handshake'] and r['modern_discovery']
    assert r['cloud_tunnel_tested'] is False


def test_tool_annotations_and_readonly(space):
    protocol=Protocol(space[3])
    tools=call(protocol,'tools/list')['result']['tools']
    assert len(tools)==33
    for t in tools:
        assert t['annotations']['readOnlyHint']==(t['name'] not in WRITES)
    space[2].mode='read_only'
    readonly=Protocol(space[3])
    assert not WRITES.intersection(readonly.specs)
    r=call(readonly,'tools/call',{'name':'write_file','arguments':{'path':'x','content':'bad'}})
    assert 'error' in r and not (space[1]/'x').exists()

@pytest.mark.parametrize('args',[{'path':'a.txt','start_line':True},{'path':'a.txt','start_line':0},
    {'path':'a.txt','unknown':1},{'path':3},{'path':'a.txt','end_line':'2'}])
def test_strict_schema_errors(space,args):
    result=call(Protocol(space[3]),'tools/call',{'name':'read_file','arguments':args})['result']
    assert result['isError'] and result['structuredContent']['error']['code']=='INVALID_ARGUMENT'


def test_error_cause_roundtrip(space):
    result=call(Protocol(space[3]),'tools/call',{'name':'read_file','arguments':{'path':'.env'}})['result']
    assert result['isError']
    obj=result['structuredContent']['error']
    assert obj['code']=='POLICY_DENIED' and obj['cause'] and obj['remediation']


def test_modern_and_unknown_versions(space):
    p=Protocol(space[3]);meta={'io.modelcontextprotocol/protocolVersion':MODERN,
                              'io.modelcontextprotocol/clientCapabilities':{}}
    r=call(p,'server/discover',{'_meta':meta})['result']
    assert MODERN in r['supportedVersions'] and r['resultType']=='complete'
    meta['io.modelcontextprotocol/protocolVersion']='2099-01-01'
    err=call(p,'tools/list',{'_meta':meta})['error']
    assert err['code']==-32022 and MODERN in err['data']['supported']


def test_actual_rw_stdio(space):
    from home_readonly_mcp.policy import locations
    root=space[1];cfg=space[0]/'config.json'
    cfg.write_text(json.dumps({'root':str(root),'mode':'read_write'}))
    requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}},
        {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'write_file','arguments':{'path':'new.txt','content':'actual process'}}},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'read_file','arguments':{'path':'new.txt'}}}]
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    run=subprocess.run([sys.executable,'-m','home_readonly_mcp.cli','--config',str(cfg),'server'],
        input='\n'.join(json.dumps(x) for x in requests)+'\n',capture_output=True,text=True,encoding='utf-8',env=env,timeout=10)
    assert run.returncode==0,run.stderr
    lines=[json.loads(x) for x in run.stdout.splitlines()]
    assert len(lines)==3 and all('result' in x for x in lines)
    assert lines[2]['result']['structuredContent']['content']=='actual process'
    assert (root/'new.txt').read_text()=='actual process'
    assert 'actual process' not in run.stderr


def test_resource_protocol_roundtrip(space):
    (space[1]/'x.bin').write_bytes(b'\0binary')
    p=Protocol(space[3])
    r=call(p,'tools/call',{'name':'read_binary','arguments':{'path':'x.bin'}})['result']
    uri=r['structuredContent']['uri']
    again=call(p,'resources/read',{'uri':uri})['result']
    assert base64.b64decode(again['contents'][0]['blob'])==b'\0binary'


def test_invalid_jsonrpc(space):
    p=Protocol(space[3])
    for message in [[],{}, {'jsonrpc':'2.0','id':True,'method':'ping'}]:
        assert p.result(message)['error']['code']==-32600
    assert p.result({'jsonrpc':'2.0','method':'notifications/initialized'}) is None
    assert call(p,'not_a_method')['error']['code']==-32601


def test_selftest_uses_explicit_utf8_pipe_decoding(monkeypatch):
    from home_readonly_mcp import cli
    original=cli.subprocess.run
    invoked=[]
    def checked_run(*args,**kwargs):
        assert kwargs.get('encoding')=='utf-8'
        invoked.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(cli.subprocess,'run',checked_run)
    assert cli.self_test()['ok'] and invoked
