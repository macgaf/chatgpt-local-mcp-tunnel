"""会话导入必须独立启用；只向新会话写合成消息并检查持久去重。"""
import json
import os
from pathlib import Path
import shutil
import uuid
import pytest
from home_readonly_mcp import codex_history
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.onboarding import configure
from home_readonly_mcp.server import Protocol

MESSAGES = [{'role': 'user', 'content': '合成问题'}, {'role': 'assistant', 'content': '合成回答'}]


def test_history_disabled_and_configuration_ack(space):
    home, root, policy, svc = space
    assert 'save_conversation_to_codex' not in Protocol(svc).specs
    with pytest.raises(Fault): svc.save_conversation_to_codex('title', MESSAGES, 'one')
    path = home / 'local-config.json'
    with pytest.raises(Fault): configure(path, root=str(root), enable_codex_history=True)
    assert not path.exists()
    configure(path, root=str(root), enable_codex_history=True, acknowledge_codex_history=True)
    assert json.loads(path.read_text())['enable_codex_history']
    policy.enable_codex_history = True
    spec = Protocol(svc).specs['save_conversation_to_codex']
    assert not spec['annotations']['readOnlyHint'] and spec['annotations']['openWorldHint']
    policy.mode = 'read_only'
    assert 'save_conversation_to_codex' not in Protocol(svc).specs


def fake_server(monkeypatch, mismatch=False):
    class FakeServer:
        created = 0
        def __init__(self, binary, home, cwd): self.home = home
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def initialize(self, home): pass
        def request(self, method, params):
            assert method in ('thread/start', 'thread/name/set', 'thread/resume', 'thread/turns/list')
            if method == 'thread/start':
                FakeServer.created += 1
                ident = str(uuid.uuid4()); path = self.home / 'sessions' / ('rollout-' + ident + '.jsonl')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': ident}}) + '\n')
                FakeServer.path = path
                return {'thread': {'id': ident, 'path': str(path)}}
            if method == 'thread/turns/list':
                rows = [json.loads(line) for line in FakeServer.path.read_text().splitlines()]
                items = []
                for row in rows:
                    p = row['payload']
                    if row['type'] != 'response_item': continue
                    content = p['content'][0]['text']
                    items.append({'type': 'userMessage', 'content': [{'type': 'text', 'text': content}]} if
                                 p['role'] == 'user' else {'type': 'agentMessage', 'text': content})
                if mismatch: items[-1]['text'] = 'different'
                return {'data': [{'status': 'completed', 'items': items}], 'nextCursor': None}
            return {}
    monkeypatch.setattr(codex_history, 'AppServer', FakeServer)
    monkeypatch.setattr(codex_history.shutil, 'which', lambda name: '/synthetic/codex')
    return FakeServer


def test_history_roundtrip_and_persistent_dedupe(space, monkeypatch):
    _, _, policy, svc = space
    policy.enable_codex_history = True
    fake = fake_server(monkeypatch)
    result = svc.save_conversation_to_codex('title', MESSAGES, 'one')
    assert result['verified'] and result['model_called'] is False
    assert svc.save_conversation_to_codex('title', MESSAGES, 'one') == result
    assert fake.created == 1
    with pytest.raises(Fault): svc.save_conversation_to_codex('different', MESSAGES, 'one')
    assert fake.created == 1


def test_history_incomplete_does_not_retry_or_hide_created_thread(space, monkeypatch):
    _, _, policy, svc = space
    policy.enable_codex_history = True
    fake = fake_server(monkeypatch, mismatch=True)
    with pytest.raises(Fault) as error: svc.save_conversation_to_codex('title', MESSAGES, 'one')
    assert error.value.details['thread_id'] and error.value.details['phase'] == 'written'
    with pytest.raises(Fault): svc.save_conversation_to_codex('title', MESSAGES, 'one')
    assert fake.created == 1


def test_history_rejects_escape_and_existing_turn(space):
    home = space[0] / '.codex'; (home / 'sessions').mkdir(parents=True)
    ident = str(uuid.uuid4()); path = home / 'sessions' / (ident + '.jsonl')
    path.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': ident}}) + '\n' +
                    json.dumps({'type': 'event_msg', 'payload': {'type': 'user_message'}}) + '\n')
    before = path.read_bytes()
    with pytest.raises(Fault): codex_history.append_new_rollout(home, str(path), ident, [])
    assert path.read_bytes() == before
    with pytest.raises(Fault):
        codex_history.append_new_rollout(home, str(home / 'sessions/../../outside' / ident), ident, [])


@pytest.mark.skipif(not shutil.which('codex') or os.environ.get('LOCAL_MCP_TEST_CODEX_HISTORY') != '1',
                    reason='可选真实 Codex 验收；设置 LOCAL_MCP_TEST_CODEX_HISTORY=1，仅用临时 HOME')
def test_real_codex_history_roundtrip(space):
    _, _, policy, svc = space
    policy.enable_codex_history = True
    result = svc.save_conversation_to_codex('合成测试', MESSAGES, 'real-fixture')
    assert result['verified'] and result['message_count'] == 2 and not result['model_called']
    assert svc.save_conversation_to_codex('合成测试', MESSAGES, 'real-fixture') == result
