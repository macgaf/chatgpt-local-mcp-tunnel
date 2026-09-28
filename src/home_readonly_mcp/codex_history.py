"""可选 Codex 历史适配器：只新建会话，不调用模型，不修改既有会话。"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import stat
import subprocess
import threading
import time
import uuid
from .errors import Fault
from .onboarding import child_environment
from .processes import WindowsJob
from .storage import Lease, digest, private_dir, write_private


def failure(reason, **details):
    return Fault('CODEX_HISTORY_FAILED', 'Codex 会话导入未完成。', reason,
                 '核查返回的 thread_id 和 request_id；不要换 ID 盲目重试。需支持 legacy history 的 Codex。',
                 **details)


class AppServer:
    def __init__(self, binary, home, cwd):
        env = child_environment(); env['CODEX_HOME'] = str(home)
        flags = {'start_new_session': True} if os.name != 'nt' else {
            'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004}  # CREATE_SUSPENDED
        self.proc = subprocess.Popen([binary, 'app-server', '--listen', 'stdio://'], cwd=cwd, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **flags)
        self.job = None; self.ident = 0; self.responses = queue.Queue(maxsize=64)
        if os.name == 'nt':
            try: self.job = WindowsJob(self.proc)
            except Exception:
                self.proc.kill(); self.proc.wait(timeout=5)
                self.proc.stdin.close(); self.proc.stdout.close()
                raise
        self.reader = threading.Thread(target=self._read, daemon=True); self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.proc.stdout.readline(8 * 1024 * 1024 + 1)
                if not line: raise EOFError('app-server closed')
                if len(line) > 8 * 1024 * 1024: raise ValueError('app-server response limit')
                message = json.loads(line)
                # 通知不进入队列；本适配器不会发起 turn，不接受授权或工具执行请求。
                if 'id' in message:
                    self.responses.put_nowait(message)
        except Exception:
            try: self.responses.put_nowait(None)
            except queue.Full: pass

    def send(self, message):
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b'\n')
        self.proc.stdin.flush()

    def request(self, method, params):
        self.ident += 1
        self.send({'id': self.ident, 'method': method, 'params': params})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try: message = self.responses.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty: raise failure('app-server timeout: ' + method) from None
            if message is None: raise failure('app-server response unavailable: ' + method)
            if message.get('id') != self.ident: continue
            if 'error' in message or not isinstance(message.get('result'), dict):
                raise failure('app-server rejected: ' + method)
            return message['result']
        raise failure('app-server timeout: ' + method)

    def initialize(self, home):
        result = self.request('initialize', {'clientInfo': {'name': 'local_mcp_history', 'version': '1'},
                                            'capabilities': {'experimentalApi': True}})
        if Path(result.get('codexHome', '')).resolve() != home:
            raise failure('Codex HOME mismatch')
        self.send({'method': 'initialized', 'params': {}})

    def close(self):
        self.proc.stdin.close()
        try: self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired: pass
        if self.job:
            self.job.terminate(); self.job.close()
        elif os.name != 'nt':
            try: os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            time.sleep(.05)
            # 即使主进程已结束，仍回收该自有进程组中的后代。
            try: os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        self.proc.wait(timeout=5)
        self.reader.join(timeout=2)
        self.proc.stdout.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def turns_for(messages):
    turns = []
    for message in messages:
        if message['role'] == 'user': turns.append([message])
        else: turns[-1].append(message)
    return turns


def records_for(turns):
    records = []
    for turn in turns:
        turn_id = str(uuid.uuid4()); now = time.time()
        stamp = datetime.now(timezone.utc).isoformat()
        def add(kind, payload): records.append({'timestamp': stamp, 'type': kind, 'payload': payload})
        add('event_msg', {'type': 'task_started', 'turn_id': turn_id, 'started_at': int(now)})
        for index, message in enumerate(turn):
            user = message['role'] == 'user'
            payload = {'type': 'message', 'id': 'msg_' + uuid.uuid4().hex, 'role': message['role'],
                       'content': [{'type': 'input_text' if user else 'output_text', 'text': message['content']}],
                       'internal_chat_message_metadata_passthrough': {'turn_id': turn_id, 'create_time': now}}
            if not user: payload['phase'] = 'final_answer' if index == len(turn)-1 else 'commentary'
            add('response_item', payload)
            event = {'type': 'user_message' if user else 'agent_message', 'message': message['content']}
            if user: event.update(images=[], local_images=[], audio=[], local_audio=[], text_elements=[])
            add('event_msg', event)
        add('event_msg', {'type': 'task_complete', 'turn_id': turn_id, 'error': None,
                         'last_agent_message': turn[-1]['content'] if len(turn)>1 else None,
                         'started_at': int(now), 'completed_at': int(now), 'duration_ms': 0})
    return b''.join(json.dumps(r, ensure_ascii=False).encode() + b'\n' for r in records)


def append_new_rollout(home, path, thread_id, turns):
    p = Path(path)
    if (not p.is_absolute() or '..' in p.parts or p.resolve() != p or not p.is_relative_to(home / 'sessions') or thread_id not in p.name or
            any(x.is_symlink() or getattr(x, 'is_junction', lambda: False)() for x in (p, *p.parents))):
        raise failure('unsafe new rollout path')
    fd = os.open(p, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'r+b') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2 * 1024 * 1024:
            raise failure('new rollout must be a bounded regular file')
        original = stream.read(2 * 1024 * 1024 + 1)
        rows = [json.loads(line) for line in original.splitlines()]
        if (not rows or rows[0].get('type') != 'session_meta' or
                (rows[0]['payload'].get('id') or rows[0]['payload'].get('session_id')) != thread_id or
                any(row.get('type') == 'event_msg' and row.get('payload', {}).get('type') in
                    ('user_message', 'task_started') for row in rows)):
            raise failure('new rollout identity/content mismatch')
        data = records_for(turns)
        if original and not original.endswith(b'\n'): raise failure('incomplete rollout line')
        stream.seek(0, 2); stream.write(data); stream.flush(); os.fsync(stream.fileno())
        stream.seek(0)
        if stream.read(len(original)+len(data)+1) != original + data:
            raise failure('rollout write verification failed')


class CodexHistoryMixin:
    def save_conversation_to_codex(self, title, messages, request_id, repo_path='.'):
        if self.policy.mode != 'read_write' or not self.policy.enable_codex_history:
            raise Fault('CODEX_HISTORY_DISABLED', 'Codex 会话导入未启用。', 'independent opt-in required',
                        '需要 read_write 且 enable_codex_history 未被关闭；此工具会在项目目录之外创建 Codex 历史。')
        if not isinstance(title, str) or not title.strip() or len(title.encode()) > 500:
            raise ValueError('title must be 1..500 UTF-8 bytes')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError('request_id must be 1..128 characters')
        if not isinstance(messages, list) or not 1 <= len(messages) <= 500:
            raise ValueError('messages must contain 1..500 entries')
        for message in messages:
            if (not isinstance(message, dict) or set(message) != {'role', 'content'} or
                    message['role'] not in ('user', 'assistant') or
                    not isinstance(message['content'], str) or not message['content']):
                raise ValueError('messages require user/assistant roles and nonempty text')
        if messages[0]['role'] != 'user' or sum(len(m['content'].encode()) for m in messages) > 2_000_000:
            raise ValueError('conversation must start with user and fit 2 MB')
        cwd = self.policy.require(repo_path)
        if not cwd.is_dir(): raise ValueError('repo_path must be a directory')
        self.policy.resolve(str(cwd / '.local-mcp-codex-import'), write=True)
        self.commands.guard_mutation([cwd])
        binary = shutil.which('codex')
        if not binary: raise failure('codex executable not found in PATH')
        home = Path(self.policy.codex_history_home or Path.home() / '.codex').expanduser().resolve()
        journal = private_dir(self.policy.state_dir / 'codex-imports') / (digest(request_id.encode()) + '.json')
        signature = digest(json.dumps([title, messages, str(cwd), str(home)], ensure_ascii=False).encode())
        with Lease(self.policy.state_dir, journal, 'codex_history_import'):
            if journal.exists():
                previous = json.loads(journal.read_text(encoding='utf-8'))
                if previous['signature'] != signature: raise failure('request_id reused with different input')
                if previous.get('result'): return previous['result']
                raise failure('previous import is incomplete; inspect before retrying', thread_id=previous.get('thread_id'))
            state = {'signature': signature, 'phase': 'starting', 'request_id': request_id}
            write_private(journal, json.dumps(state).encode())
            def checkpoint():
                temp = journal.with_name(journal.name + '.' + uuid.uuid4().hex)
                write_private(temp, json.dumps(state).encode()); os.replace(temp, journal)
            try:
                home.mkdir(parents=True, exist_ok=True, mode=0o700)
                with AppServer(binary, home, cwd) as client:
                    client.initialize(home)
                    thread = client.request('thread/start', {'cwd': str(cwd), 'ephemeral': False,
                                            'historyMode': 'legacy'})['thread']
                    ident = thread['id']; path = thread['path']
                    uuid.UUID(ident)
                    state.update(thread_id=ident, phase='created'); checkpoint()
                    client.request('thread/name/set', {'threadId': ident, 'name': title.strip()})
                turns = turns_for(messages)
                append_new_rollout(home, path, ident, turns)
                state['phase'] = 'written'; checkpoint()
                with AppServer(binary, home, cwd) as client:
                    client.initialize(home)
                    client.request('thread/resume', {'threadId': ident})
                    actual = client.request('thread/turns/list', {'threadId': ident, 'limit': 500,
                                            'itemsView': 'full', 'sortDirection': 'asc'})
                    hydrated = []
                    for turn in actual.get('data', []):
                        if turn.get('status') != 'completed': raise failure('incomplete hydrated turn')
                        for item in turn.get('items', []):
                            if item.get('type') == 'userMessage':
                                content = ''.join(c['text'] for c in item['content'] if c.get('type') == 'text')
                                hydrated.append({'role': 'user', 'content': content})
                            elif item.get('type') == 'agentMessage':
                                hydrated.append({'role': 'assistant', 'content': item['text']})
                    if hydrated != messages or actual.get('nextCursor'):
                        raise failure('hydrated conversation differs from input')
                result = {'ok': True, 'thread_id': ident, 'title': title.strip(), 'message_count': len(messages),
                          'turn_count': len(turns), 'request_id': request_id, 'verified': True,
                          'model_called': False}
                state.update(phase='verified', result=result); checkpoint()
                return result
            except Exception as exc:
                raise failure(exc.payload()['error']['cause'] if isinstance(exc, Fault) else type(exc).__name__, thread_id=state.get('thread_id'),
                              phase=state['phase'], request_id=request_id) from exc
