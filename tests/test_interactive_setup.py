"""Synthetic identifiers and credentials only. Never exercise a user's keystore."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import warnings

import pytest

from home_readonly_mcp import cli, credentials, onboarding, interactive
from home_readonly_mcp.errors import Fault, redact

ID = 'tunnel_' + 'b' * 32
OLD_ID = 'tunnel_' + 'a' * 32
KEY = 'sk-synthetic-interactive-1234567890'


def config_file(space, **extra):
    p = space[0] / 'setup-config.json'
    onboarding.save_settings(p, {'root': str(space[1]), 'mode': 'read_write',
        'enable_commands': False, 'enable_git_push': False, 'write_roots': ['src/**'],
        'launcher': 'preserve-launcher', 'key_source': 'keyring', **extra})
    return p


def test_interactive_id_preserves_unrelated_settings(space, monkeypatch, capsys):
    p = config_file(space)
    before = json.loads(p.read_text())
    monkeypatch.setattr(interactive, 'hidden_input', lambda prompt: ID)
    result = interactive.configure_tunnel_interactive(p)
    after = json.loads(p.read_text())
    assert after.pop('tunnel_id') == ID
    assert after == before
    assert result['ok'] and result['changed'] and not result['identifier_displayed']
    assert ID not in json.dumps(result) + capsys.readouterr().out


def test_existing_id_blank_retains_without_write(space, monkeypatch):
    p = config_file(space, tunnel_id=OLD_ID)
    before = p.read_bytes()
    before_files = set(p.parent.iterdir())
    prompts = []
    def ask(prompt):
        prompts.append(prompt)
        return ''
    monkeypatch.setattr(interactive, 'hidden_input', ask)
    result = interactive.configure_tunnel_interactive(p)
    assert not result['changed'] and p.read_bytes() == before
    assert set(p.parent.iterdir()) == before_files
    assert OLD_ID not in ''.join(prompts)


@pytest.mark.parametrize('bad', ['', 'not-a-tunnel', KEY])
def test_invalid_id_does_not_change_config_or_echo(space, monkeypatch, bad):
    p = config_file(space)
    before = p.read_bytes()
    monkeypatch.setattr(interactive, 'hidden_input', lambda prompt: bad)
    with pytest.raises(Fault) as got:
        interactive.configure_tunnel_interactive(p)
    assert got.value.code == 'INVALID_TUNNEL_ID'
    assert p.read_bytes() == before
    if bad:
        assert bad not in json.dumps(got.value.payload())


def test_cancel_preserves_configuration(space, monkeypatch):
    p = config_file(space, tunnel_id=OLD_ID)
    before = p.read_bytes()
    def cancel(prompt):
        raise KeyboardInterrupt()
    monkeypatch.setattr(interactive, 'hidden_input', cancel)
    with pytest.raises(KeyboardInterrupt):
        interactive.configure_tunnel_interactive(p)
    assert p.read_bytes() == before


def test_missing_config_does_not_ask_for_identifier(tmp_path, monkeypatch):
    def unexpected(prompt):
        pytest.fail('should validate installation before prompting')
    monkeypatch.setattr(interactive, 'hidden_input', unexpected)
    with pytest.raises(Fault) as got:
        interactive.configure_tunnel_interactive(tmp_path / 'missing.json')
    assert got.value.code == 'CONFIG_MISSING'


def test_no_tty_refuses_to_read(monkeypatch):
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    def unexpected(prompt):
        pytest.fail('must not call getpass without a local TTY')
    monkeypatch.setattr(credentials.getpass, 'getpass', unexpected)
    with pytest.raises(Fault) as got:
        credentials.hidden_input('hidden: ')
    assert got.value.code == 'INTERACTIVE_SECRET_REQUIRED'


def test_getpass_fallback_warning_is_an_error(monkeypatch):
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    def insecure(prompt):
        warnings.warn('cannot disable echo', credentials.getpass.GetPassWarning)
        pytest.fail('getpass must not reach echoed input')
    monkeypatch.setattr(credentials.getpass, 'getpass', insecure)
    with pytest.raises(Fault) as got:
        credentials.hidden_input('hidden: ')
    assert got.value.code == 'HIDDEN_INPUT_UNAVAILABLE'


def test_eof_is_actionable(monkeypatch):
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    def eof(prompt):
        raise EOFError()
    monkeypatch.setattr(credentials.getpass, 'getpass', eof)
    with pytest.raises(Fault) as got:
        credentials.hidden_input('hidden: ')
    assert got.value.code == 'INTERACTIVE_INPUT_CANCELLED'


def test_key_set_uses_same_hidden_input(monkeypatch):
    monkeypatch.setattr(credentials, 'hidden_input', lambda prompt: KEY)
    class Store:
        def set_password(self, service, account, value):
            assert account == ID and value == KEY
            self.value = value
        def get_password(self, service, account):
            return self.value
    result = credentials.save_key({'tunnel_id': ID}, backend=Store())
    assert result['ok']
    assert ID not in json.dumps(result) and KEY not in json.dumps(result)


def test_redaction_covers_id_fields_and_strings():
    payload = {'tunnel_id': ID, 'CONTROL_PLANE_TUNNEL_ID': OLD_ID,
        'runtime_api_key': KEY, 'log': f'connect {ID}: key={KEY}',
        'tunnel_id_configured': True, 'profile': 'chatgpt-local-mcp-tunnel-' + ID[-8:]}
    output = redact(payload)
    rendered = json.dumps(output)
    assert all(x not in rendered for x in (ID, OLD_ID, KEY))
    assert output['tunnel_id_configured'] is True
    assert ID[-8:] not in rendered


def test_cli_interactive_command(space, monkeypatch, capsys):
    p = config_file(space)
    monkeypatch.setattr(interactive, 'hidden_input', lambda prompt: ID)
    assert cli.main(['--config', str(p), 'tunnel', 'configure']) == 0
    output = capsys.readouterr()
    assert ID not in output.out + output.err
    assert json.loads(p.read_text())['tunnel_id'] == ID


@pytest.mark.skipif(os.name == 'nt', reason='POSIX PTY echo check; no simulated Windows TTY guarantee')
def test_real_local_pty_hides_identifier(space):
    import pty
    import select
    import termios
    p = config_file(space)
    master, slave = pty.openpty()
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    argv = [sys.executable, '-m', 'home_readonly_mcp.cli', '--config', str(p), 'tunnel', 'configure']
    proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True)
    os.close(slave)
    transcript = b''
    sent = False
    deadline = time.monotonic() + 12
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    data = os.read(master, 8192)
                except OSError:
                    break
                if not data:
                    break
                transcript += data
            # Check actual terminal echo before supplying synthetic data.
            if not sent and b'Tunnel ID' in transcript and not (termios.tcgetattr(master)[3] & termios.ECHO):
                os.write(master, (ID + '\n').encode())
                sent = True
            if proc.poll() is not None and not ready:
                break
        assert sent, transcript.decode('utf-8', 'replace')
        assert proc.wait(timeout=3) == 0, transcript.decode('utf-8', 'replace')
        assert ID.encode() not in transcript
        assert json.loads(p.read_text())['tunnel_id'] == ID
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=3)
        os.close(master)


def test_readme_interactive_contract():
    root = Path(__file__).resolve().parents[1]
    doc = (root / 'README.md').read_text(encoding='utf-8')
    assert doc == (root / 'README_zh.md').read_text(encoding='utf-8')
    assert 'git_local' not in doc
    assert '<TUNNEL_ID>' not in doc and '填入第 3.1 步' not in doc
    assert '等我选择' in doc and 'tunnel configure' in doc and 'key set' in doc
    assert '不通过工具参数转发输入' in doc or '不通过工具参数转发' in doc
