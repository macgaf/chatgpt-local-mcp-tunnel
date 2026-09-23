# home-readonly-mcp

给 **ChatGPT Pro + OpenAI Secure MCP Tunnel** 使用的本机 HOME 目录只读 MCP。

## 目标

- 根目录：当前 macOS 用户的 `$HOME`
- 默认：HOME 内普通文件只读
- 黑名单：密钥、凭证、`.env`、Keychain、浏览器 Cookie/Login Data 等敏感路径
- 白名单：配置支持 `allow`；`force_allow` 可显式覆盖 deny（默认仅放行 `.env.example/.sample/.template`）
- HOME 外：永远拒绝
- symlink：解析后的真实路径必须仍在 HOME 内
- 无写入工具、无删除、无重命名、无 shell
- MCP 工具全部声明 `readOnlyHint=true`

## 工具

1. `policy_info` — 查看有效只读策略
2. `list_directory` — 列目录，隐藏被策略拒绝的条目
3. `file_info` — 文件元数据；小文件返回 SHA-256
4. `read_file` — 读取文本文件，可按行范围读取
5. `find_files` — 用 glob 查找文件名
6. `search_text` — 在允许范围内搜索文本

## 安装

要求 Python 3.10+。

```bash
cd home-readonly-mcp
./install.sh
```

安装后：

```text
~/.local/bin/home-readonly-mcp
~/.config/home-readonly-mcp/config.json
```

可以先编辑配置：

```bash
nano ~/.config/home-readonly-mcp/config.json
```

## 本地测试 MCP

如果你装了 MCP Inspector：

```bash
~/.local/share/home-readonly-mcp/venv/bin/mcp dev \
  ~/.local/share/home-readonly-mcp/app/src/home_readonly_mcp/server.py
```

通常 Tunnel 直接使用启动器即可，不需要手工启动 MCP。

## Secure MCP Tunnel

OpenAI 当前 tunnel-client 支持用 `--mcp-command` 启动本机 stdio MCP。官方建议先创建 named profile，再 `doctor`、`run`。

安装 tunnel-client 后，设置 Runtime API key：

```bash
export CONTROL_PLANE_API_KEY='sk-...'
```

然后：

```bash
cd home-readonly-mcp
./setup-tunnel.sh tunnel_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

或手动执行：

```bash
tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile home-readonly-mcp \
  --tunnel-id tunnel_xxx \
  --mcp-command "$HOME/.local/bin/home-readonly-mcp"

tunnel-client doctor --profile home-readonly-mcp --explain
tunnel-client run --profile home-readonly-mcp
```

使用 stdio binding 时，同一个 tunnel ID 同时只能有一个活跃的 tunnel-client 实例。

## 策略规则

判定顺序：

```text
1. 路径 resolve 后必须在 HOME 内，否则拒绝
2. force_allow 命中 -> 允许
3. deny 命中 -> 拒绝
4. allow 命中 -> 允许
5. default_policy=deny -> 拒绝
6. default_policy=allow -> 允许
```

默认模式是 `default_policy=allow`，因此 `allow` 主要用于文档化常用目录，以及以后切换为 `default_policy=deny` 时使用。

### 强烈建议不要把以下内容从 deny 中移除

- `~/.ssh/**`
- `~/.gnupg/**`
- `~/.aws/**`
- `~/.kube/**`
- Keychain
- Browser Cookies / Login Data
- 私钥 `*.pem/*.key/*.p12/*.pfx`
- `.env` 与 credentials/secrets

## ChatGPT 验收提示词

连接成功后可以发：

```text
调用 home-readonly-mcp：
1. 先调用 policy_info；
2. 列出 HOME 根目录中允许访问的条目；
3. 查找 HOME 下所有 AGENTS.md；
4. 不要尝试任何写入操作。
```

再测试敏感路径：

```text
尝试读取 ~/.ssh/id_ed25519，并告诉我 MCP 返回的结果。
```

预期应为策略拒绝，而不是返回文件内容。

## 安全说明

“只读”只表示这个 MCP 不提供改变文件的工具。被读取的文件内容会发送给调用 MCP 的模型/服务，因此敏感数据依然需要通过 deny policy 阻止。
