"""Local-only protected identifier entry; no MCP tools or permission changes."""
from pathlib import Path
import re

from .credentials import hidden_input
from .errors import Fault
from .onboarding import load_settings, save_settings


def configure_tunnel_interactive(path):
    """Acquire an identifier locally, never as an agent prompt or CLI argument."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise Fault('CONFIG_MISSING', '请先完成本机安装和目录／模式选择。',
                    '尚无本工具配置文件。', '先运行安装器，再执行 local-mcp tunnel configure。')
    data = load_settings(p)
    previous = data.get('tunnel_id')
    prompt = ('Tunnel ID（隐藏输入；回车保留已配置值）: ' if previous
              else 'Tunnel ID（隐藏输入）: ')
    value = hidden_input(prompt).strip()
    if not value and previous:
        value = previous
    if not re.fullmatch(r'tunnel_[0-9a-f]{32}', value):
        raise Fault('INVALID_TUNNEL_ID', 'Tunnel ID 为空或格式不正确。',
                    '需要 tunnel_ 后接 32 位小写十六进制字符；输入值不会回显。',
                    '在本机重新运行 local-mcp tunnel configure 并隐藏录入。')
    changed = value != previous
    if changed:
        data['tunnel_id'] = value
        save_settings(p, data)
    return {'ok': True, 'tunnel_id_configured': True, 'changed': changed,
            'restart_required': changed, 'identifier_displayed': False,
            'next_step': 'local-mcp key status；缺少凭据时由本人执行 local-mcp key set'}

