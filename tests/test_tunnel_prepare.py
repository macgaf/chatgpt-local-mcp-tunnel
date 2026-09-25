"""Synthetic regression fixtures: no real cloud resources or user secrets."""
from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import sys
import textwrap

import pytest
from home_readonly_mcp import browser_local as bl, tunnel_prepare as tp
from home_readonly_mcp.cli import parser
from home_readonly_mcp.policy import APP

FAKE_ID='tunnel_'+'0'*32
FAKE_KEY='sk-fake-fixture-not-a-real-credential-123456'
PROOF={'restricted':True,'read_checked':True,'use_checked':True,'others_none':True,'project_selected':True,'selected_count':2}


class MemoryStore:
    def __init__(self):self.data={};self.writes=0;self.fail_write=False
    def set_password(self,service,account,value):
        if self.fail_write and service==APP:raise RuntimeError(FAKE_KEY)
        self.data[service,account]=value;self.writes+=1
    def get_password(self,service,account):return self.data.get((service,account))
    def delete_password(self,service,account):del self.data[service,account]


class ProbeBrowser:
    def __init__(self):self.closed=False
    def __enter__(self):return self
    def __exit__(self,*args):self.closed=True
    def call(self,name,args=None):
        assert 'filePath' not in (args or {})
        return {'content':[{'type':'text','text':'1: Tunnels (https://platform.openai.com/settings/organization/tunnels)'}]}
    def text(self,r):return r['content'][0]['text']
    def evaluate(self,script):
        if 'location.origin' in script:return {'origin':tp.ORIGIN,'path':tp.TUNNELS}
        return 'not-a-real-key-generated-only-in-browser-fixture'


@pytest.fixture
def prep(space,monkeypatch):
    config=space[0]/'.config'/APP/'config.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'root':str(space[1]),'mode':'read_only','tunnel_id':FAKE_ID,
        'key_source':'keyring','enable_commands':False,'enable_git_push':False}))
    store=MemoryStore()
    p=tp.Preparation(config,backend=store,browser_factory=ProbeBrowser)
    monkeypatch.setattr(tp,'verify_read',lambda settings,backend=None:{'read_authentication':'passed','use_authentication':'not_checked'})
    return p,store


def test_cli_stage_arguments_do_not_require_id_or_key():
    p=parser()
    args=p.parse_args(['tunnel','prepare','--stage','preflight'])
    assert args.action=='prepare' and not args.allow_create
    args=p.parse_args(['tunnel','prepare','--stage','submit-key','--allow-create'])
    assert args.key_name==APP+'-runtime'
    with pytest.raises(SystemExit):p.parse_args(['tunnel','prepare','--api-key','secret'])
    with pytest.raises(SystemExit):p.parse_args(['tunnel','prepare','--tunnel-id',FAKE_ID])


def test_preflight_roundtrip_has_no_cloud_mutations_or_secret(prep):
    p,store=prep
    capture=io.StringIO()
    with contextlib.redirect_stdout(capture):result=p.run('preflight')
    assert result['ok'] and not result['cloud_mutations']
    assert result['writes_browser_payload_to_file'] is False
    assert result['uses_apple_events'] is False
    assert {x['name'] for x in result['checks']}=={'native_keystore','authorized_browser','browser_to_keystore_memory_roundtrip'}
    assert store.data=={} and capture.getvalue()==''
    assert 'not-a-real-key-generated-only-in-browser-fixture' not in json.dumps(result)


def test_preflight_keeps_independent_keystore_success_on_browser_failure(prep):
    p,store=prep
    def failed():raise bl.BrowserFailure('CHROME_DEBUG_ENDPOINT_MISSING')
    p.browser_factory=failed
    result=p.run('preflight')
    assert not result['ok'] and result['checks'][0]['status']=='pass'
    assert result['checks'][1]['error_code']=='CHROME_DEBUG_ENDPOINT_MISSING'
    assert store.data=={} and not p.journal.exists()


def test_unknown_errors_never_expose_body():
    result=tp.failure_payload(RuntimeError(FAKE_ID+' '+FAKE_KEY),'submit-key')
    assert FAKE_ID not in json.dumps(result) and FAKE_KEY not in json.dumps(result)
    assert result['error_code']=='PREPARATION_FAILED'


@pytest.mark.parametrize('field',['restricted','read_checked','use_checked','others_none','project_selected'])
def test_permissions_require_every_actual_state(field):
    proof=dict(PROOF);proof[field]=False
    with pytest.raises(tp.PreparationFailure):tp.assert_permission_proof(proof)


@pytest.mark.parametrize('value',[0,1,3,None,'2',False])
def test_clicks_are_not_selections(value):
    proof={**PROOF,'selected_count':value,'permissionOptionsClicked':2}
    with pytest.raises(tp.PreparationFailure):tp.assert_permission_proof(proof)


def test_permission_good_fixture():
    assert tp.assert_permission_proof(PROOF) is None


def test_snapshot_roles_state_not_label_presence():
    snapshot='''uid=1_1 dialog "Create new secret key"
  uid=1_2 radio "Restricted" checked
  uid=1_3 menuitemcheckbox "Read" checked
  uid=1_4 menuitemcheckbox "Use" checked=false
  uid=1_5 button "Create secret key" disabled
'''
    ns=tp.nodes(snapshot)
    assert ns[1].checked and ns[2].checked and not ns[3].checked
    with pytest.raises(tp.PreparationFailure):tp.only_node(ns,('button',),('Create secret key',))


def test_permissions_not_applied_stops_before_creation():
    class B:
        def call(self,*a):return {}
    class Page(tp.PlatformPage):
        clicked=0
        def guard(self,path):pass
        def key_nodes(self):return [tp.Node('r',0,'radio','Restricted',' checked')]
        def permission_menu(self):return [tp.Node('read',0,'checkbox','Read',''),tp.Node('use',0,'checkbox','Use','')]
        def click(self,node):self.clicked+=1
    page=Page(B())
    with pytest.raises(tp.PreparationFailure) as got:page.select_permissions()
    assert got.value.code=='PERMISSION_SELECTION_NOT_APPLIED' and page.clicked==1


class KeyPage:
    created=0;secret_ready=False;fail_submit=False;proof=PROOF
    def __init__(self,b):pass
    def open(self,path):assert path in (tp.KEYS,tp.TUNNELS)
    def secret(self,ownership):
        if not type(self).secret_ready:raise tp.PreparationFailure('KEY_NOT_CAPTURED')
        return FAKE_KEY
    def select_permissions(self):
        if type(self).secret_ready:raise tp.PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
        tp.assert_permission_proof(type(self).proof);return type(self).proof
    def submit_key(self,name,ownership):
        type(self).created+=1
        if type(self).fail_submit:raise bl.BrowserFailure('BROWSER_TIMEOUT')
        type(self).secret_ready=True
    def tunnel_record(self,name):return {'name':name,'id':FAKE_ID,'organizations':'Organization','workspaces':'Workspace'}


@pytest.fixture
def keypage(monkeypatch):
    class Fresh(KeyPage):created=0;secret_ready=False;fail_submit=False;proof=dict(PROOF)
    monkeypatch.setattr(tp,'PlatformPage',Fresh)
    return Fresh


def test_single_local_submit_capture_store_and_readback(prep,keypage):
    p,store=prep
    before=p.config.read_bytes()
    output=p.run('submit-key',allow_create=True)
    assert output['ok'] and output['key_readback']
    assert store.get_password(APP,FAKE_ID)==FAKE_KEY and keypage.created==1
    assert p.config.read_bytes()==before
    assert FAKE_ID not in json.dumps(output) and FAKE_KEY not in json.dumps(output)
    assert FAKE_KEY not in p.journal.read_text()
    again=p.run('submit-key',allow_create=True)
    assert again['key']=='reused' and again['ok'] and keypage.created==1
    assert again['live_permission_verification']=='not_checked'


def test_no_create_without_explicit_authorization(prep,keypage):
    p,store=prep
    result=p.run('submit-key')
    assert not result['ok'] and result['error_code']=='CREATE_NOT_AUTHORIZED'
    assert keypage.created==0 and not store.data


def test_zero_selected_never_submits(prep,keypage):
    p,store=prep;keypage.proof={**PROOF,'selected_count':0}
    r=p.run('submit-key',allow_create=True)
    assert not r['ok'] and keypage.created==0 and not store.data
    assert not p.journal.exists()


def test_uncertain_submit_does_not_click_again(prep,keypage):
    p,store=prep;keypage.fail_submit=True
    r=p.run('submit-key',allow_create=True)
    assert r['error_code']=='BROWSER_TIMEOUT' and keypage.created==1
    keypage.fail_submit=False
    r=p.run('submit-key',allow_create=True)
    assert r['error_code']=='CREATION_OUTCOME_UNCERTAIN' and keypage.created==1


def test_failed_save_resumes_same_popup_without_new_key(prep,keypage):
    p,store=prep;store.fail_write=True
    r=p.run('submit-key',allow_create=True)
    assert r['error_code']=='KEYSTORE_SAVE_FAILED' and keypage.created==1
    assert FAKE_KEY not in json.dumps(r)
    store.fail_write=False
    r=p.run('submit-key',allow_create=True)
    assert r['ok'] and keypage.created==1


def test_unrelated_secret_popup_is_not_imported(prep,keypage):
    p,store=prep;keypage.secret_ready=True
    r=p.run('submit-key',allow_create=True)
    assert r['error_code']=='FORM_LAYOUT_UNSUPPORTED'
    assert not store.data and keypage.created==0


def test_bind_preserves_user_settings_and_requires_target_confirmation(prep,keypage):
    p,_=prep;before=json.loads(p.config.read_text())
    assert p.run('cache-tunnel')['error_code']=='TARGET_CONFIRMATION_REQUIRED'
    result=p.run('cache-tunnel',confirm_target=True)
    assert result['ok'] and result['association_present']
    assert json.loads(p.config.read_text())==before
    assert FAKE_ID not in json.dumps(result)


def test_bind_conflict_not_overwritten(prep,keypage):
    p,_=prep;data=json.loads(p.config.read_text());data['tunnel_id']='tunnel_'+'1'*32
    p.config.write_text(json.dumps(data));before=p.config.read_bytes()
    r=p.run('cache-tunnel',confirm_target=True)
    assert r['error_code']=='BINDING_CONFLICT' and p.config.read_bytes()==before


def test_credential_source_is_not_silently_migrated(prep,keypage):
    p,_=prep;data=json.loads(p.config.read_text());data['key_source']='systemd';p.config.write_text(json.dumps(data))
    r=p.run('submit-key',allow_create=True)
    assert r['error_code']=='KEY_SOURCE_UNSUPPORTED' and keypage.created==0


def test_capture_permission_error_not_treated_as_missing(prep,keypage):
    p,store=prep
    def locked(*a):raise PermissionError(FAKE_KEY)
    store.get_password=locked
    r=p.run('submit-key',allow_create=True)
    assert not r['ok'] and keypage.created==0 and FAKE_KEY not in json.dumps(r)


def test_connection_failure_classification():
    assert bl.browser_error('Could not find DevToolsActivePort for chrome')=='CHROME_DEBUG_ENDPOINT_MISSING'
    assert bl.browser_error('Could not connect to Chrome. remote debugging')=='CHROME_CONNECTION_OR_APPROVAL_REQUIRED'


def test_configured_browser_uses_existing_identity_without_unsafe_flags(tmp_path,monkeypatch):
    conf=tmp_path/'config.toml';conf.write_text('''[mcp_servers.chrome-devtools]
command="npx"
args=["-y","chrome-devtools-mcp@1.10.1","--autoConnect","--channel","beta"]
''')
    monkeypatch.setattr(bl.shutil,'which',lambda s:'/bin/'+s)
    argv=bl.configured_browser_argv(conf)
    assert argv[:4]==['/bin/npx','--offline','chrome-devtools-mcp@1.10.1','--autoConnect']
    assert ['--channel','beta']==argv[4:6]
    assert '--allowUnrestrictedPaths' not in argv and '--acceptInsecureCerts' not in argv


def test_configured_browser_rejects_unapproved_connection(tmp_path,monkeypatch):
    conf=tmp_path/'config.toml';conf.write_text('''[mcp_servers.chrome-devtools]
command="npx"
args=["chrome-devtools-mcp@latest","--browserUrl","http://127.0.0.1:9999"]
''')
    with pytest.raises(bl.BrowserFailure):bl.configured_browser_argv(conf)


def test_private_stdio_worker_does_not_write_payloads_or_agent_stdout(tmp_path):
    worker=tmp_path/'fake_browser.py'
    worker.write_text(textwrap.dedent('''
        import json,sys
        for line in sys.stdin:
            m=json.loads(line)
            if 'id' not in m:continue
            if m['method']=='initialize':r={}
            elif m['method']=='tools/list':r={'tools':[{'name':n} for n in ['list_pages','evaluate_script','take_snapshot','click','fill']]}
            else:r={'content':[{'type':'text','text':'```json\\n"sk-fake-value-NEVER-PRINT"\\n```'}]}
            print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':r}),flush=True)
    '''))
    capture=io.StringIO()
    with contextlib.redirect_stdout(capture):
        with bl.LocalBrowser([sys.executable,str(worker)],tmp_path,timeout=5) as b:
            value=b.evaluate('() => "fictional"')
            assert value=='sk-fake-value-NEVER-PRINT'
            with pytest.raises(bl.BrowserFailure):b.call('evaluate_script',{'function':'() => 1','filePath':str(tmp_path/'x')})
            with pytest.raises(bl.BrowserFailure):b.call('take_screenshot',{})
    assert capture.getvalue()=='' and not (tmp_path/'x').exists()
    assert b.process.poll() is not None


class TunnelPage:
    record=None;created=0;fail_submit=False
    def __init__(self,b):pass
    def open(self,path):pass
    def tunnel_record(self,name):
        if type(self).record is None:raise tp.PreparationFailure('TUNNEL_NOT_FOUND')
        return type(self).record
    def tunnel_form(self,name):return {'names':[name],'organizations':['Organization'],'workspaces':['Workspace']}
    def submit_tunnel(self,name):
        type(self).created+=1
        if type(self).fail_submit:raise bl.BrowserFailure('BROWSER_TIMEOUT')
        type(self).record={'name':name,'id':FAKE_ID,'organizations':'Organization','workspaces':'Workspace'}


@pytest.fixture
def tunnelpage(prep,monkeypatch):
    p,_=prep;data=json.loads(p.config.read_text());data.pop('tunnel_id');p.config.write_text(json.dumps(data))
    class Fresh(TunnelPage):record=None;created=0;fail_submit=False
    monkeypatch.setattr(tp,'PlatformPage',Fresh)
    return Fresh


def test_tunnel_create_is_explicit_and_binding_is_reused(prep,tunnelpage):
    p,_=prep
    assert p.run('submit-tunnel',allow_create=True)['error_code']=='TARGET_CONFIRMATION_REQUIRED'
    assert p.run('submit-tunnel',confirm_target=True)['error_code']=='CREATE_NOT_AUTHORIZED'
    result=p.run('submit-tunnel',confirm_target=True,allow_create=True)
    assert result['ok'] and result['tunnel']=='created'
    assert json.loads(p.config.read_text())['tunnel_id']==FAKE_ID
    assert json.loads(p.config.read_text())['mode']=='read_only'
    assert FAKE_ID not in json.dumps(result)
    again=p.run('submit-tunnel',confirm_target=True,allow_create=True)
    assert again['ok'] and tunnelpage.created==1


def test_tunnel_uncertain_creation_cannot_be_repeated(prep,tunnelpage):
    p,_=prep;tunnelpage.fail_submit=True
    assert p.run('submit-tunnel',confirm_target=True,allow_create=True)['error_code']=='BROWSER_TIMEOUT'
    tunnelpage.fail_submit=False
    assert p.run('submit-tunnel',confirm_target=True,allow_create=True)['error_code']=='CREATION_OUTCOME_UNCERTAIN'
    assert tunnelpage.created==1 and 'tunnel_id' not in json.loads(p.config.read_text())


def test_known_tunnel_does_not_require_create_authorization(prep,tunnelpage):
    p,_=prep;tunnelpage.record={'name':APP,'id':FAKE_ID,'organizations':'Organization','workspaces':'Workspace'}
    result=p.run('submit-tunnel',confirm_target=True)
    assert result['ok'] and result['tunnel']=='reused' and tunnelpage.created==0


def test_auth_redirects_rejected():
    with pytest.raises(tp.PreparationFailure) as error:
        tp.RejectRedirects().redirect_request(None,None,302,'',{},'https://other.invalid')
    assert error.value.code=='AUTH_REDIRECT_REJECTED'


def test_linked_local_settings_are_not_read(prep):
    import os
    if os.name=='nt':pytest.skip('requires symlink privilege')
    p,_=prep
    target=p.config.with_name('original.json');p.config.rename(target);p.config.symlink_to(target)
    assert p.run('preflight')['error_code']=='UNSAFE_STATE_PATH'
