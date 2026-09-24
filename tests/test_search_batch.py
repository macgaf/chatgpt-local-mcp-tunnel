import json
from pathlib import Path
import pytest
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.server import Protocol
from home_readonly_mcp.search_tools import BATCH_READS


def fixture(space):
    root,p,svc=space[1:]
    (root/'defs.py').write_text('class Widget:\n    pass\n\ndef do_work():\n    return Widget()\n',encoding='utf-8')
    (root/'usage.py').write_text('# Widget mention\na = Widget()\nlongWidget = 1\n',encoding='utf-8')
    return root,p,svc


def test_code_ranking_and_queries(space):
    root,p,svc=fixture(space)
    r=svc.search_code(['Widget','do_work'])
    first=r['queries'][0]['results'][0]
    assert first['path']=='defs.py' and first['line']==1 and 'declaration_line' in first['signals']
    assert r['queries'][0]['observed_matches']>=4
    assert r['queries'][1]['results'][0]['line']==4
    assert not r['truncated']


def test_grep_literal_regex_context_count_pagination(space):
    root,p,svc=fixture(space)
    r=svc.grep('Widget',output_mode='content',context=1,head_limit=1)
    assert len(r['results'])==1 and r['next_offset']==1
    nextpage=svc.grep('Widget',output_mode='content',head_limit=1,offset=1)
    assert nextpage['results'][0]['line']!=r['results'][0]['line']
    r=svc.grep(r'^class\s+Widget',fixed_strings=False,output_mode='files_with_matches')
    assert r['results']==[{'path':'defs.py'}]
    r=svc.grep('Widget',output_mode='count')
    assert sum(x['count'] for x in r['results'])>=4
    with pytest.raises(Fault) as e:svc.grep('[',fixed_strings=False)
    assert e.value.code=='INVALID_SEARCH_PATTERN'


def test_ignores_and_policy_cannot_be_disabled(space):
    pytest.importorskip('pathspec')
    root,p,svc=fixture(space)
    (root/'.gitignore').write_text('ignored.py\n*.tmp\n!keep.tmp\n',encoding='utf-8')
    (root/'ignored.py').write_text('Widget')
    (root/'skip.tmp').write_text('Widget');(root/'keep.tmp').write_text('Widget')
    (root/'.env').write_text('Widget PRIVATE')
    r=svc.glob('*')
    assert 'ignored.py' not in r['results'] and 'skip.tmp' not in r['results']
    assert 'keep.tmp' in r['results'] and '.env' not in r['results']
    r=svc.glob('*',include_ignored=True)
    assert 'ignored.py' in r['results'] and '.env' not in r['results']
    assert 'PRIVATE' not in str(svc.grep('Widget',include_ignored=True,output_mode='content'))


def test_nested_ignore_and_scoped_agents(space):
    pytest.importorskip('pathspec')
    root,p,svc=fixture(space)
    (root/'AGENTS.md').write_text('root rules')
    (root/'sub').mkdir();(root/'sub/AGENTS.md').write_text('nested rules')
    (root/'sub/package.json').write_text('{"scripts":{"test":"do-not-execute"}}')
    (root/'.gitignore').write_text('sub/skip.py\n')
    (root/'sub/skip.py').write_text('Widget')
    assert 'sub/skip.py' not in svc.glob('*',path='sub')['results']
    ctx=svc.workspace_context('sub')
    assert [f['content'] for f in ctx['files'][:2]]==['root rules','nested rules']
    assert ctx['git_status'] is None and ctx['errors'][0]['code']=='NOT_A_GIT_REPOSITORY'
    overview=svc.repo_overview()
    assert 'sub/package.json' in overview['manifests']


def test_batch_reads_order_and_error_strategy(space):
    svc=space[3]
    ops=[{'tool':'read_file','arguments':{'path':'a.txt'}},
         {'tool':'read_file','arguments':{'path':'missing'}},
         {'tool':'file_info','arguments':{'path':'a.txt'}}]
    r=svc.batch_read(ops)
    assert len(r['results'])==3 and not r['ok']
    assert r['results'][1]['result']['error']['code']=='NOT_FOUND'
    r=svc.batch_read(ops,stop_on_error=True)
    assert len(r['results'])==2 and r['next_index']==2

@pytest.mark.parametrize('tool',['write_file','git_add','run_command','batch_read','key_set','__getattribute__'])
def test_batch_rejects_mutations_before_any_call(space,monkeypatch,tool):
    svc=space[3];calls=[]
    monkeypatch.setattr(svc,'read_file',lambda **kw:calls.append(kw))
    with pytest.raises((Fault,KeyError,ValueError)):
        svc.batch_read([{'tool':'read_file','arguments':{'path':'a.txt'}},{'tool':tool}])
    assert not calls


def test_batch_protocol_and_default_annotations(space):
    svc=space[3];protocol=Protocol(svc)
    r=protocol.result({'jsonrpc':'2.0','id':8,'method':'tools/call','params':{'name':'batch_read',
        'arguments':{'operations':[{'tool':'read_file','arguments':{'path':'a.txt'}}]}}})
    assert not r['result']['isError'] and r['result']['structuredContent']['results'][0]['ok']
    assert protocol.specs['batch_read']['annotations']['readOnlyHint']


def test_batch_output_limit(space):
    svc=space[3]
    (space[1]/'big.txt').write_text('a'*240000)
    r=svc.batch_read([{'tool':'read_file','arguments':{'path':'big.txt'}}]*4)
    assert r['truncated'] and r['reason']=='batch_output_limit' and r['next_index']==2


def test_scan_budget_explicit(space):
    root,p,svc=fixture(space);p.max_search_files=1
    r=svc.search_code(['Widget'])
    assert r['truncated'] and 'scan_budget' in r['truncation_reasons']


def test_regex_timeout_real_worker(space):
    root,p,svc=space[1:]
    (root/'evil.txt').write_text('a'*10000+'!')
    with pytest.raises(Fault) as e:svc.grep('(a+)+$',glob='evil.txt',fixed_strings=False)
    assert e.value.code=='SEARCH_TIMEOUT'
    assert svc.read_file('a.txt')['ok']  # main MCP runtime remains usable


def test_all_tool_input_schemas_valid(space):
    jsonschema=pytest.importorskip('jsonschema')
    space[2].enable_commands=True;space[2].enable_git_push=True
    for spec in Protocol(space[3]).specs.values():
        jsonschema.Draft202012Validator.check_schema(spec['inputSchema'])
