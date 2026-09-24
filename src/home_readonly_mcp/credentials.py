"""Explicit native backends; never fall back to a plaintext keyring."""
from __future__ import annotations
import getpass
import os
from pathlib import Path
import stat
import sys
import warnings
from .errors import Fault
from .policy import APP


def hidden_input(prompt):
    """Local TTY only; no getpass fallback that might echo protected input."""
    if not sys.stdin.isatty():
        raise Fault('INTERACTIVE_SECRET_REQUIRED', '请在本机交互式终端录入。',
                    '当前输入不是 TTY，未读取任何值。',
                    '由本人打开独立终端；不要把 Tunnel ID 或 key 发到聊天或命令参数。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            return getpass.getpass(prompt)
    except getpass.GetPassWarning:
        raise Fault('HIDDEN_INPUT_UNAVAILABLE', '终端无法保证隐藏输入，已停止。',
                    'getpass 无法关闭回显；拒绝回退为明文输入。',
                    '换用本机正常交互终端，不使用管道、录屏或会话录制。') from None
    except EOFError:
        raise Fault('INTERACTIVE_INPUT_CANCELLED', '交互输入已结束，未保存。',
                    '终端输入关闭。', '准备好后在本机终端重试。') from None


def validate_key(value):
    if not isinstance(value,str) or not 12 <= len(value) <= 4096 or any(c.isspace() for c in value):
        raise Fault('INVALID_RUNTIME_KEY', 'Runtime key 为空或格式无效。',
                    '密钥必须是无空白的单行字符串。', '从本机密码框重新输入；不要粘贴到聊天。')
    return value


def native_backend():
    try:
        if sys.platform == 'darwin':
            from keyring.backends.macOS import Keyring
        elif os.name == 'nt':
            from keyring.backends.Windows import WinVaultKeyring as Keyring
        else:
            from keyring.backends.SecretService import Keyring
        return Keyring()
    except Exception as exc:
        raise Fault('KEYSTORE_UNAVAILABLE', '安全凭据存储不可用。', type(exc).__name__,
            '安装 keyring；Linux 需要同一用户会话中的 D-Bus 和 Secret Service。'
            '无桌面服务器可显式选择 systemd credentials；不会改存明文。') from exc


def key_account(settings):
    tunnel_id = settings.get('tunnel_id')
    if not tunnel_id:
        raise Fault('TUNNEL_ID_MISSING', '尚未设置 tunnel_id。', '无法确定凭据所属隧道。', '先在本机执行 local-mcp tunnel configure。')
    return tunnel_id


def save_key(settings, value=None, backend=None):
    # No CLI argument accepts the secret. A value parameter exists for tests only.
    key = validate_key(value if value is not None else hidden_input('Runtime API key（隐藏输入）: '))
    backend = backend or native_backend()
    try:
        backend.set_password(APP, key_account(settings), key)
        if backend.get_password(APP, key_account(settings)) != key:
            raise RuntimeError('credential readback mismatch')
    except Exception as exc:
        raise Fault('KEYSTORE_WRITE_FAILED', '保存或读回凭据失败。', type(exc).__name__,
                    '解锁系统凭据库并检查访问权限；未降级为明文文件。') from exc
    return {'ok':True, 'stored':True, 'backend':type(backend).__module__}


def load_key(settings, backend=None):
    source = settings.get('key_source','keyring')
    try:
        if source == 'keyring':
            backend = backend or native_backend()
            value = backend.get_password(APP, key_account(settings))
        elif source == 'systemd':
            if not sys.platform.startswith('linux'):
                raise Fault('UNSUPPORTED_CREDENTIAL_SOURCE', 'systemd 凭据只适用于 Linux。',
                            f'当前平台为 {sys.platform}；不能用 POSIX 权限位验证 Windows 凭据。',
                            'macOS/Windows 使用 key_source=keyring 对应的系统凭据库。')
            folder = os.environ.get('CREDENTIALS_DIRECTORY')
            if not folder:
                raise Fault('SYSTEMD_CREDENTIAL_MISSING', '没有 systemd 凭据目录。',
                            'CREDENTIALS_DIRECTORY 未设置。', '通过 LoadCredentialEncrypted=runtime-api-key:... 启动服务。')
            p = Path(folder) / 'runtime-api-key'
            if p.is_symlink():
                raise ValueError('credential cannot be a symlink')
            st = p.stat()
            if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
                raise ValueError('credential must be a private regular file')
            with p.open('r',encoding='utf-8') as f:
                value = f.read(4097).strip()
        elif source == 'environment':
            # Explicit opt-in for ephemeral secrets; never a silent keyring fallback.
            value = os.environ.get('CONTROL_PLANE_API_KEY')
        else:
            raise ValueError('unknown key_source')
        if not value:
            raise Fault('RUNTIME_KEY_MISSING', '找不到此 tunnel 的 Runtime key。', source,
                        '运行 local-mcp key set，或正确配置显式凭据来源。')
        return validate_key(value)
    except Fault:
        raise
    except Exception as exc:
        raise Fault('KEYSTORE_READ_FAILED', '读取 Runtime key 失败。', type(exc).__name__,
                    '解锁凭据库或检查 systemd 服务会话；不会把密钥打印出来。') from exc
