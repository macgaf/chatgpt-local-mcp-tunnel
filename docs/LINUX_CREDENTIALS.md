# Linux 凭据与可选用户服务

## 桌面环境：Secret Service

完整安装包含 Python keyring。Linux 只选择 Secret Service backend；需要当前用户会话中的 D-Bus 和已解锁的 Secret Service。登录会话里执行 `local-mcp key set`，系统可能要求解锁/授权。

没有 backend、没有 D-Bus 或凭据库锁定时返回明确错误，不安装明文 backend，也不写 `.env`。

## 无桌面环境：systemd encrypted credentials

这是显式选项，不是自动降级。先确认本机 `systemd-creds --help` 支持用户凭据 `--user`，`systemctl --user` 可用。老发行版/没有 user manager 时停止，按本机系统能力配置；不要把 key 改写到公开 unit 的 Environment/SetCredential。

本地配置：先由本人隐藏录入 ID，再选择凭据来源（命令中不含 ID/key）：

```bash
local-mcp tunnel configure
local-mcp configure --key-source systemd
```

用本机交互终端隐藏输入，然后通过标准输入送给 systemd-creds 加密，**没有明文中间文件或密钥命令参数**：

```python
# 保存为本机临时管理脚本，在交互式终端用 python3 运行；不要在聊天中填写 key。
import getpass
import warnings
import os
from pathlib import Path
import subprocess
import sys
if not sys.stdin.isatty():
    raise SystemExit('Run this locally in an interactive terminal.')
directory = Path.home()/'.config/chatgpt-local-mcp-tunnel'
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
output = directory/'runtime-api-key.cred'
if output.exists():
    raise SystemExit('Credential already exists; review before replacing it.')
with warnings.catch_warnings():
    warnings.simplefilter('error', getpass.GetPassWarning)
    key = getpass.getpass('Runtime API key: ')
if not key or any(ch.isspace() for ch in key):
    raise SystemExit('Invalid key input.')
old = os.umask(0o077)
try:
    subprocess.run(['systemd-creds','--user','encrypt','--name=runtime-api-key','-',str(output)],
                   input=key.encode(),check=True)
finally:
    os.umask(old)
```

先在同样的凭据注入环境里初始化和验证（直接在普通 shell 中运行、没有 CREDENTIALS_DIRECTORY，会按设计报错）：

```bash
systemd-run --user --wait --pipe \
  -p "LoadCredentialEncrypted=runtime-api-key:$HOME/.config/chatgpt-local-mcp-tunnel/runtime-api-key.cred" \
  "$HOME/.local/bin/local-mcp" tunnel init

systemd-run --user --wait --pipe \
  -p "LoadCredentialEncrypted=runtime-api-key:$HOME/.config/chatgpt-local-mcp-tunnel/runtime-api-key.cred" \
  "$HOME/.local/bin/local-mcp" doctor --with-tunnel
```

用户**明确选择常驻运行**后，可创建 `~/.config/systemd/user/chatgpt-local-mcp-tunnel.service`：

```ini
[Unit]
Description=ChatGPT local MCP tunnel
After=network-online.target

[Service]
Type=simple
ExecStart=%h/.local/bin/local-mcp tunnel run
LoadCredentialEncrypted=runtime-api-key:%h/.config/chatgpt-local-mcp-tunnel/runtime-api-key.cred
UMask=0077
NoNewPrivileges=yes
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

执行 `systemctl --user daemon-reload`、`systemctl --user enable --now chatgpt-local-mcp-tunnel`，然后查看 `systemctl --user status chatgpt-local-mcp-tunnel` 和脱敏 journal。需要退出登录后继续运行时，另行由用户/管理员审核 linger；安装器不会自动设置。

systemd 将解密后的服务凭据放在 `$CREDENTIALS_DIRECTORY/runtime-api-key`。本项目要求私有普通文件，读取后只给 Tunnel 子进程注入 runtime key。凭据仍会短暂存在于内存；这不等于对同一用户或 root 的防护。

真实 systemd 加解密与用户服务必须在目标发行版验证。本轮只测试了读取服务凭据目录的代码路径，没有把模拟文件测试称为已测试 systemd daemon。

参考：[systemd Credentials](https://systemd.io/CREDENTIALS/)、[systemd-creds 源码文档](https://github.com/systemd/systemd/blob/main/man/systemd-creds.xml)、[keyring 文档](https://keyring.readthedocs.io/en/latest/)。
