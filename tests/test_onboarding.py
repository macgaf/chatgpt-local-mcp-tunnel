import json
import os
from pathlib import Path
import subprocess
import sys
from io import BytesIO
import zipfile
import pytest
from home_readonly_mcp import credentials, onboarding
from home_readonly_mcp.cli import doctor
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.policy import APP,locations
from home_readonly_mcp.storage import digest

ID='tunnel_'+'1'*32
KEY='sk-test-private-1234567890'

class MemoryBackend:
    def __init__(self):self.data={}
    def set_password(self,s,a,k):self.data[s,a]=k
    def get_password(self,s,a):return self.data.get((s,a))


def test_secure_key_store_roundtrip():
    backend=MemoryBackend();settings={'tunnel_id':ID}
    r=credentials.save_key(settings,KEY,backend)
    assert r['ok'] and KEY not in json.dumps(r)
    assert credentials.load_key(settings,backend)==KEY
    assert backend.data[APP,ID]==KEY


def test_no_plaintext_downgrade(monkeypatch):
    def unavailable():raise Fault('KEYSTORE_UNAVAILABLE','missing','test','install')
    monkeypatch.setattr(credentials,'native_backend',unavailable)
    monkeypatch.setenv('CONTROL_PLANE_API_KEY',KEY)
    with pytest.raises(Fault):credentials.load_key({'tunnel_id':ID})
    assert credentials.load_key({'key_source':'environment'})==KEY


def test_noninteractive_key_refused(monkeypatch):
    monkeypatch.setattr(sys.stdin,'isatty',lambda:False)
    with pytest.raises(Fault) as got:credentials.save_key({'tunnel_id':ID})
    assert got.value.code=='INTERACTIVE_SECRET_REQUIRED'


@pytest.mark.skipif(not sys.platform.startswith('linux'),reason='systemd credentials are a Linux-only source')
def test_headless_systemd_credentials(space,monkeypatch):
    d=space[0]/'runtime-creds';d.mkdir();p=d/'runtime-api-key'
    p.write_text(KEY);p.chmod(0o600)
    monkeypatch.setenv('CREDENTIALS_DIRECTORY',str(d))
    assert credentials.load_key({'key_source':'systemd'})==KEY
    if os.name!='nt':
        p.chmod(0o644)
        with pytest.raises(Fault):credentials.load_key({'key_source':'systemd'})


def test_configuration_and_home_confirmation(space):
    cfg=locations()[0]/'config.json'
    r=onboarding.configure(cfg)
    assert r['mode']=='read_only' and r['root']=='~'
    with pytest.raises(Fault) as got:onboarding.configure(cfg,mode='read_write')
    assert got.value.code=='HOME_WRITE_CONFIRMATION_REQUIRED'
    onboarding.configure(cfg,root=str(space[1]),mode='read_write',tunnel_id=ID)
    assert onboarding.load_settings(cfg)['mode']=='read_write'
    with pytest.raises(Fault):onboarding.configure(cfg,tunnel_id='bad')
    assert onboarding.load_settings(cfg)['tunnel_id']==ID


def test_no_secret_or_override_in_child_env(monkeypatch):
    monkeypatch.setenv('CONTROL_PLANE_API_KEY',KEY)
    monkeypatch.setenv('OPENAI_API_KEY',KEY)
    monkeypatch.setenv('MCP_SERVER_URL','https://attacker.invalid')
    env=onboarding.child_environment()
    assert not {'CONTROL_PLANE_API_KEY','OPENAI_API_KEY','MCP_SERVER_URL'} & env.keys()
    assert '127.0.0.1' in env['NO_PROXY']


def test_command_timeout_and_redaction():
    r=onboarding.run_checked([sys.executable,'-c',f'print({KEY!r})'],secrets=(KEY,))
    assert KEY not in r['output'] and '[REDACTED]' in r['output']
    with pytest.raises(Fault) as got:
        onboarding.run_checked([sys.executable,'-c','import time;time.sleep(60)'],timeout=0.15)
    assert got.value.code=='COMMAND_TIMEOUT'

@pytest.mark.parametrize('text,code',[('401 unauthorized','TUNNEL_AUTHENTICATION_FAILED'),('403 forbidden','TUNNEL_PERMISSION_DENIED'),
    ('DNS resolve error','DNS_FAILURE'),('TLS certificate failed','TLS_FAILURE')])
def test_command_failure_reasons(text,code):
    with pytest.raises(Fault) as got:onboarding.run_checked([sys.executable,'-c',f'print({text!r});raise SystemExit(1)'])
    assert got.value.code==code and got.value.details['exit_code']==1


def test_release_checksum_and_companions():
    b=BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('tunnel-client',b'executable');z.writestr('cloudflared',b'companion')
        z.writestr('LICENSE',b'license')
    body=b.getvalue();name='tunnel-client-v0.0.14-linux-amd64.zip'
    sums=f'{digest(body)}  {name}\n'.encode()
    exe,files=onboarding.verify_archive(body,sums,name)
    assert exe=='tunnel-client' and files['cloudflared']==b'companion'
    with pytest.raises(Fault):onboarding.verify_archive(body+b'corrupt',sums,name)


def test_release_rejects_paths_and_missing_companion():
    for entries in [[('tunnel-client',b'x')],[('tunnel-client',b'x'),('../cloudflared',b'x')]]:
        b=BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            for n,c in entries:z.writestr(n,c)
        name='tunnel-client-v0.0.14-linux-amd64.zip';body=b.getvalue()
        with pytest.raises(Fault):onboarding.verify_archive(body,f'{digest(body)} {name}'.encode(),name)


def test_doctor_distinguishes_cloud_not_checked(space):
    cfg=locations()[0]/'config.json'
    onboarding.configure(cfg,root=str(space[1]))
    r=doctor(cfg)
    assert r['ok']
    assert next(x for x in r['checks'] if x['name']=='tunnel_auth_and_connection')['status']=='not_checked'

@pytest.mark.skipif(os.name=='nt',reason='fake executable uses POSIX shebang; native Windows entry test is separate platform validation')
def test_codex_registration_idempotence(space):
    fake=space[0]/'codex';db=space[0]/'codex-state.json'
    fake.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
p=Path(__file__).with_name('codex-state.json')
a=sys.argv[1:];d=json.loads(p.read_text()) if p.exists() else []
if a[:2]==['mcp','list']: print(json.dumps(d))
elif a[:2]==['mcp','get']: print(json.dumps(next(x for x in d if x['name']==a[2])))
elif a[:2]==['mcp','add']:
 i=a.index('--');d.append({'name':a[2],'transport':{'type':'stdio','command':a[i+1],'args':a[i+2:]}})
 p.write_text(json.dumps(d));print('Added')
else:raise SystemExit(2)
''')
    fake.chmod(0o700)
    cfg=locations()[0]/'config.json';onboarding.configure(cfg,root=str(space[1]))
    assert onboarding.register_codex(cfg,str(fake))['changed']
    assert not onboarding.register_codex(cfg,str(fake))['changed']
    entries=json.loads(db.read_text());entries[0]['transport']['command']='other';db.write_text(json.dumps(entries))
    with pytest.raises(Fault) as got:onboarding.register_codex(cfg,str(fake))
    assert got.value.code=='CODEX_CONFIG_CONFLICT'


def test_tunnel_profile_protects_key_and_idempotent(space,monkeypatch):
    cfg=locations()[0]/'config.json'
    onboarding.configure(cfg,root=str(space[1]),tunnel_id=ID,key_source='environment')
    settings=onboarding.load_settings(cfg);settings['tunnel_client']='fake-tunnel'
    onboarding.save_settings(cfg,settings);monkeypatch.setenv('CONTROL_PLANE_API_KEY',KEY)
    calls=[]
    def fake_run(argv,env,**kwargs):
        calls.append(argv)
        assert KEY not in str(argv)
        assert env['CONTROL_PLANE_API_KEY']==KEY
        profile=argv[argv.index('--profile')+1]
        p=Path(env['TUNNEL_CLIENT_PROFILE_DIR'])/(profile+'.yaml')
        p.write_text('control_plane:\n  api_key: env:CONTROL_PLANE_API_KEY\n')
        return {'ok':True}
    monkeypatch.setattr(onboarding,'run_checked',fake_run)
    r=onboarding.tunnel_init(cfg)
    assert r['ok'];onboarding.tunnel_init(cfg)
    assert len(calls)==1
    assert KEY not in cfg.read_text()

@pytest.mark.skipif(os.name=='nt',reason='test wrapper shell path is POSIX; Windows bootstrap still covered by core unit tests')
def test_real_offline_install_and_reinstall(space):
    repo=Path(__file__).resolve().parents[1]
    argv=[sys.executable,str(repo/'bootstrap.py'),'--core-only','--root',str(space[1]),'--mode','read_write']
    one=subprocess.run(argv,text=True,encoding='utf-8',capture_output=True,timeout=30)
    assert one.returncode==0,one.stdout+one.stderr
    cfg=locations()[0]/'config.json'
    pointer=locations()[1]/'current.json'
    installed_python=Path(json.loads(pointer.read_text(encoding='utf-8'))['python'])
    assert installed_python.is_symlink()
    assert installed_python.resolve()==Path(sys._base_executable).resolve()
    assert onboarding.load_settings(cfg)['enable_codex_history'] is True
    onboarding.configure(cfg,enable_codex_history=False)
    before=onboarding.launch_argv(cfg)
    wrapper=space[0]/'.local/bin/local-mcp'
    run=subprocess.run([str(wrapper),'self-test'],capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert run.returncode==0,run.stderr
    two=subprocess.run(argv,text=True,encoding='utf-8',capture_output=True,timeout=30)
    assert two.returncode==0,two.stdout+two.stderr
    assert onboarding.launch_argv(cfg)==before
    assert onboarding.load_settings(cfg)['mode']=='read_write'
    assert onboarding.load_settings(cfg)['enable_codex_history'] is False
    reinstalled_python=Path(json.loads(pointer.read_text(encoding='utf-8'))['python'])
    assert reinstalled_python.is_symlink()
    assert reinstalled_python.resolve()==installed_python.resolve()


@pytest.mark.parametrize('platform_name',['darwin','win32'])
def test_systemd_source_rejected_on_other_platforms(monkeypatch,platform_name):
    monkeypatch.setattr(credentials.sys,'platform',platform_name)
    with pytest.raises(Fault) as got:credentials.load_key({'key_source':'systemd'})
    assert got.value.code=='UNSUPPORTED_CREDENTIAL_SOURCE'
