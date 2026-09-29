"""Tunnel 诊断必须依据错误上下文，不能把内容中的数字当 HTTP 状态。"""
import json
import os
from contextlib import redirect_stdout
import sys

import pytest

from home_readonly_mcp.errors import Fault
from home_readonly_mcp.eventlog import EventLog, recent
from home_readonly_mcp.onboarding import record_tunnel_event, run_checked
from home_readonly_mcp import onboarding
from home_readonly_mcp.tunnel_diagnostics import diagnostic, error_code, fingerprint


@pytest.mark.parametrize('text', [
    'request_id=req_401403 duration_ms=403 bytes=401',
    '{"level":"INFO","msg":"request completed","status":200,"body":"401 unauthorized 403 forbidden"}',
    'failure: file /tmp/403.txt not found',
    'HTTP 200 OK: documentation mentions 401 Unauthorized',
    '{"level":"ERROR","msg":"body contains 403 forbidden","error":{"body":"HTTP 401"}}',
    'unauthorized appears in documentation; DNS and TLS configuration exists',
    'time=now level=INFO msg="request completed" status_code=200 body="HTTP 401"',
])
def test_incidental_numbers_are_not_auth_failures(tmp_path, text):
    log = EventLog(state_dir=tmp_path)
    record_tunnel_event(log, text)
    rows = recent(log.directory, component='tunnel')['records']
    assert not any(r.get('error_code') in ('TUNNEL_AUTHENTICATION_FAILED', 'TUNNEL_PERMISSION_DENIED') for r in rows)
    with pytest.raises(Fault) as caught:
        run_checked([sys.executable, '-c', f'print({text!r});raise SystemExit(1)'])
    assert caught.value.code == 'COMMAND_FAILED'


@pytest.mark.parametrize('text,code,status', [
    ('HTTP/1.1 401 Unauthorized','TUNNEL_AUTHENTICATION_FAILED',401),
    ('HTTP 403 Forbidden','TUNNEL_PERMISSION_DENIED',403),
    ('unexpected status code: 503','TUNNEL_HTTP_FAILED',503),
    ('{"level":"ERROR","attrs":{"http_status":403,"request_id":"req-one","component":"control_plane"}}','TUNNEL_PERMISSION_DENIED',403),
    ('time=now level=ERROR msg="request failed" status_code=401 request_id=req-one','TUNNEL_AUTHENTICATION_FAILED',401),
    ('{"level":"ERROR","error":"connection refused"}','CONNECTION_REFUSED',None),
])
def test_explicit_errors_keep_evidence(tmp_path, text, code, status):
    log = EventLog(state_dir=tmp_path)
    evidence = record_tunnel_event(log,text)
    assert error_code(evidence)==code and evidence.get('http_status')==status
    row = recent(log.directory,component='tunnel')['records'][0]
    assert row['error_code']==code and row['diagnostic']==evidence
    with pytest.raises(Fault) as caught:
        run_checked([sys.executable,'-c',f'print({text!r});raise SystemExit(1)'],audit=log)
    assert caught.value.code==code and caught.value.details['diagnostic']==evidence


def test_payloads_headers_and_unknown_secrets_never_persist(tmp_path):
    from home_readonly_mcp.eventlog import export
    log = EventLog(state_dir=tmp_path, settings={'max_bytes':16384,'backup_count':2})
    secret='opaque-private-value-without-key-prefix'
    record={'level':'ERROR','message':'private full payload '+secret,
            'attrs':{'component':'control_plane','request_id':secret,'rpc_request_id':'rpc-one',
                     'cmd_request_id':'cmd-one','http_status':403,'error':'HTTP 403 Forbidden',
                     'Authorization':'Basic '+secret,'headers':{'Cookie':secret},
                     'api_key':secret,'body':{'sensitive_payload':secret},'url':'https://host/?token='+secret}}
    for _ in range(100):
        record_tunnel_event(log,json.dumps(record))
    files=list(log.directory.glob('tunnel.jsonl*'))
    assert len(files)==3 and all(p.stat().st_size<=16384 for p in files)
    disk=''.join(p.read_text(encoding='utf-8') for p in files)
    for forbidden in (secret,'Authorization','Basic ','Cookie','sensitive_payload','https://'):
        assert forbidden not in disk
    rows=recent(log.directory,component='tunnel',tail=100)['records']
    assert rows and all(r['diagnostic']['request_id_hash']==fingerprint(secret) for r in rows)
    evidence=rows[-1]['diagnostic']
    assert evidence['last_reached_layer']=='control_plane'
    assert evidence['original_error']=='HTTP 403 Forbidden'
    assert evidence['unconfirmed']==['cross_layer_correlation','root_cause','downstream_execution']
    dest=tmp_path/'export.json'
    export(log.directory,dest,component='tunnel')
    assert secret not in dest.read_text(encoding='utf-8')


def test_unrecognized_and_forged_diagnostic_are_explicitly_omitted(tmp_path):
    log=EventLog(state_dir=tmp_path)
    record_tunnel_event(log,'Authorization: Basic super-private-header')
    row=recent(log.directory,component='tunnel')['records'][0]
    assert row['diagnostic']['outcome']=='unknown'
    assert 'original_error_text_omitted' in row['diagnostic']['unconfirmed']
    # 日志读回／导出再次过滤，不信任磁盘上已有的诊断字段。
    row['diagnostic'].update(original_error='private body',request_id_hash='private key',body='private payload')
    (log.directory/'tunnel.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
    reread=recent(log.directory,component='tunnel')['records'][0]
    assert 'private' not in json.dumps(reread)


def test_real_tunnel_stdout_devnull_still_retains_safe_evidence(space,tmp_path,monkeypatch):
    secret='opaque-test-key'
    wire=json.dumps({'level':'ERROR','message':'full private response',
                     'attrs':{'status_code':403,'request_id':'req-forward','layer':'control_plane',
                              'error':'HTTP 403 Forbidden','headers':{'Authorization':'Basic '+secret}}})
    (tmp_path/'run').write_text(
        'import sys\n'
        'assert "--log.http-raw-unsafe=false" in sys.argv and "--harpoon.capture-payloads=false" in sys.argv\n'
        'assert sys.argv[sys.argv.index("--log.file")+1]==""\n'
        'assert sys.argv[sys.argv.index("--log.format")+1]=="json"\n'
        f'print({wire!r})\n',encoding='utf-8')
    cfg=space[0]/'config.json';cfg.write_text('{}',encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(onboarding,'tunnel_context',lambda p: (
        {'tunnel_id':'test-owned'},sys.executable,secret,None,'test',dict(os.environ)))
    with open(os.devnull,'w') as out,redirect_stdout(out):
        onboarding.tunnel_run(cfg)
    rows=recent(EventLog(cfg).directory,component='tunnel')['records']
    evidence=next(r['diagnostic'] for r in rows if r['event']=='tunnel_diagnostic')
    assert evidence['http_status']==403 and evidence['request_id_hash']==fingerprint('req-forward')
    assert evidence['last_reached_layer']=='control_plane'
    assert secret not in json.dumps(rows) and 'full private response' not in json.dumps(rows)


def test_tunnel_management_output_is_also_safe(tmp_path):
    log=EventLog(state_dir=tmp_path)
    wire='Authorization: Basic opaque-unprefixed-secret'
    result=run_checked([sys.executable,'-c',f'print({wire!r})'],audit=log)
    assert 'opaque-unprefixed-secret' not in json.dumps(result)
    assert 'Authorization' not in (log.directory/'tunnel.jsonl').read_text(encoding='utf-8')


def test_known_secret_redacted_before_parsing():
    assert error_code(diagnostic('HTTP 401',secrets=('HTTP 401',))) is None
    assert diagnostic('x'*65537)['truncated']


def test_execution_failure_does_not_become_http_refusal():
    evidence=diagnostic('{"level":"ERROR","layer":"child_process","exit_code":1,"body":"401 unauthorized"}')
    assert evidence['outcome']=='execution_failure_reported'
    assert evidence['exit_code']==1 and evidence['last_reached_layer']=='child_process'
    assert error_code(evidence) is None


def test_native_dispatch_event_is_not_execution_success():
    wire={'level':'INFO','message':'dispatcher forwarded command to MCP server',
          'attrs':{'component':'dispatcher','request_id':'request-one','rpc_request_id':'7'}}
    evidence=diagnostic(json.dumps(wire))
    assert evidence['outcome']=='request_forwarded'
    assert evidence['last_reached_layer']=='local_mcp_dispatch'
    assert evidence['rpc_request_id_hash']==fingerprint('7')
    assert 'downstream_execution' in evidence['unconfirmed']
    assert error_code(evidence) is None


def test_conflicting_http_status_fields_are_not_classified():
    evidence=diagnostic('{"http_status":401,"status_code":200}')
    assert evidence['conflicting_status'] and error_code(evidence) is None
    assert error_code(diagnostic('{"status_code":200,"status_code":401}')) is None


def test_error_excerpt_and_record_remain_bounded(tmp_path):
    log=EventLog(state_dir=tmp_path)
    record_tunnel_event(log,'HTTP'+' '*50000+'401 Unauthorized')
    assert log.dropped==0
    assert (log.directory/'tunnel.jsonl').stat().st_size<16384


def test_native_controlplane_error_keeps_prefix_but_not_response_body():
    wire={'level':'WARN','component':'controlplane','msg':'poll failed; backing off',
          'status_code':403,'error':'controlplane client: unexpected status 403: private key and response body'}
    evidence=diagnostic(json.dumps(wire))
    assert evidence['last_reached_layer']=='control_plane'
    assert evidence['operation']=='control_plane_poll'
    assert evidence['original_error']=='controlplane client: unexpected status 403'
    assert error_code(evidence)=='TUNNEL_PERMISSION_DENIED'
    assert 'private' not in json.dumps(evidence)


def test_legacy_auth_labels_without_evidence_are_unverified_on_read(tmp_path):
    log=EventLog(state_dir=tmp_path)
    log.emit('tunnel','placeholder')
    path=log.directory/'tunnel.jsonl'
    row=json.loads(path.read_text(encoding='utf-8'))
    row.update(event='tunnel_reported_error',level='ERROR',error_code='TUNNEL_PERMISSION_DENIED')
    original=json.dumps(row)+'\n';path.write_text(original,encoding='utf-8')
    loaded=recent(log.directory,component='tunnel')['records'][0]
    assert loaded['error_code']=='TUNNEL_CLASSIFICATION_UNVERIFIED'
    assert loaded['legacy_error_code']=='TUNNEL_PERMISSION_DENIED'
    assert path.read_text(encoding='utf-8')==original
