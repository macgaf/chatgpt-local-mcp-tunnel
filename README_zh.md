# chatgpt-local-mcp-tunnel

本机文件 MCP：**可配置只读/读写、原生图片传输、PDF 页面预览、ZIP 内文件读取、安全凭据存储、Codex/Tunnel 自动安装与分层诊断**。

模型仍在你选择的客户端中运行。ChatGPT 通过 Secure MCP Tunnel 访问本机；Codex 可直接启动同一 stdio 服务，不必绕 Tunnel。项目不调用 Responses API，也不假设某种订阅一定能/不能写入。最终工具可用性由本机配置、客户端支持及其授权共同决定。

**当前版本：0.3.0。** 源码包与自动化测试已经实现；真实 ChatGPT 图片消费、真实 Tunnel 认证、macOS/Windows 凭据库仍须在目标机器验收，不能以本地测试代替。测试范围见 [TEST_REPORT.md](TEST_REPORT.md)。

## 1. 最少步骤安装

要求：Python **3.11+**；安装图像/PDF/keyring 组件及官方 Tunnel 客户端时需要网络。无 sudo、不关闭 TLS、不修改其他 MCP 条目、不把密钥写入项目。

在已经登录 GitHub 的本机取得这个私有仓库后，进入仓库目录。macOS/Linux：

```bash
./install.sh --root "$HOME/git_local" --mode read_write --register-codex --install-client
```

`$HOME/git_local` 必须已存在；可换成实际项目目录。默认完整安装包括 Pillow、PDFium、keyring。iPhone HEIC 支持可额外加 `--heif`。

Windows PowerShell：

```powershell
python .\bootstrap.py --root "$HOME\git_local" --mode read_write --register-codex --install-client
```

也提供 `install.ps1`。脚本不会修改 PowerShell 执行策略；脚本受策略限制时直接使用上面的 Python 命令。

**只想保持整个 HOME 只读**，省略 root/mode：

```bash
./install.sh --register-codex --install-client
```

预览安装计划：`python3 bootstrap.py --plan`。离线只安装核心：`python3 bootstrap.py --core-only`；此模式不会伪称具备图片/PDF/系统凭据库依赖。

安装器输出 `local-mcp` 的绝对路径。macOS/Linux 默认是 `~/.local/bin/local-mcp`。没有加入 PATH 时使用绝对路径；Windows 使用安装器输出的 `local-mcp.cmd`。

然后设置 Tunnel（ID 不是密钥）：

```bash
~/.local/bin/local-mcp configure --tunnel-id tunnel_替换为32位真实ID
~/.local/bin/local-mcp key set
~/.local/bin/local-mcp tunnel init
~/.local/bin/local-mcp doctor --with-tunnel
~/.local/bin/local-mcp tunnel run
```

`key set` 只接受**本机交互式终端的隐藏输入**；没有 TTY 就停止，不降级为回显输入。不要把 Runtime key 写进提示词、命令参数、README 或截图。密钥仅在启动 Tunnel 子进程时注入其环境，MCP 进程启动后清除已知 API key 环境变量。

已经有 ID、准备在终端输入 key 时，也可用一条完整安装命令：

```bash
./install.sh --root "$HOME/git_local" --mode read_write \
  --register-codex --install-client \
  --tunnel-id tunnel_替换为32位真实ID --store-key --setup-tunnel
```

这会安装、保存凭据、创建 profile 并检查；**不会偷偷留下后台进程或配置开机自启**。最后用 `local-mcp tunnel run` 前台运行；退出后云端连接离线。Linux 长期服务方式见 [Linux 凭据与服务](docs/LINUX_CREDENTIALS.md)。

官方完整 Tunnel 发行包中包含 companion `cloudflared`；安装器会一起安装，不能只复制主程序。下载仅来自 OpenAI 官方 GitHub 发行包，并核对 SHA256SUMS；**未实现独立签名/attestation 验证**。

## 2. 在 ChatGPT 激活

先确认本机 Tunnel 正在运行。ChatGPT 中开启 Developer Mode，创建开发者 App/插件，连接类型选择 **Tunnel**，选择配置的 Tunnel，并在新聊天里启用该 App。不同版本界面可能变化；不要把 Codex 的本地注册当成 ChatGPT 已连接。

需要在 Platform 创建/关联 Tunnel 与 Runtime key。Runtime 需要 Tunnel Read + Use；创建/管理 Tunnel 的权限与 ChatGPT 工作区连接权限是另一个检查点。首次登录、工作区授权、创建密钥和系统凭据库弹窗需要用户本人完成；脚本不绕过授权。

推荐验收提示词：

> 使用 chatgpt-local-mcp-tunnel。先调用 policy_info，报告真实 root 与 mode。然后调用 visual_probe，读出图中六位字符；看不到图片就明确报告。再读取我指定项目的 README。只有本机配置为 read_write 且我授权测试时，创建一个新的测试文件、读回验证，不改动现有业务文件。

`visual_probe` 的答案只存在于图像像素中，工具文本不提供答案。能回答字符比“返回了 Base64”更能证明视觉链路可用；工具返回的 answer_sha256 可在本机核对。

## 3. 不再手工上传图片、PDF 或 ZIP

| 文件 | 工具 | 实际处理 |
|---|---|---|
| UTF-8 代码、JSON、Markdown | `read_file` / `search_text` | 范围读取、哈希、截断提示 |
| PNG/JPEG/WebP/GIF/TIFF 等 | `read_image` | 本机解码，返回真正 MCP ImageContent；支持 EXIF 方向、缩放、裁剪 |
| iPhone HEIC/HEIF | `read_image` | 安装 `--heif` 后解码；缺依赖明确报错 |
| PDF | `read_document` + `render_pdf_page` | 提取文字与逐页渲染分开；图表必须看渲染，不做自动 OCR |
| ZIP 内的上述文件 | `list_archive` + `read_archive_member` | 在内存中读取成员，不落地解压、不上传整包 |
| 其他二进制 | `read_binary` / `resources/read` | 分块 EmbeddedResource、整文件/分块哈希、版本校验 |

针对建模会话可直接说：

> 读取项目里的 additional-visual-review-inputs.zip，先列出成员，再直接读取端帽/墙体相关图片；需要局部细节时读取原图并按区域 crop。保留 EXIF 方向及缩放映射，不要把预览像素当作原图坐标，不要让我重新手工上传服务已经能读取的文件。

图片结果保留原文件 SHA、原始尺寸、方向修正尺寸、裁剪区域和预览缩放比例。**原图不会被修改**；用于测量/标定时应选择适当的高分辨率局部，而不是只用缩略图。

**边界：**服务端能发送图像不等于所有客户端会把图像传给模型；必须做 `visual_probe` 真实验收。EmbeddedResource 不会自动变成 ChatGPT 沙箱里的文件路径。`.blend`、视频、大型点云等需要专用本地导出适配器，或者支持资源落盘的客户端。此版实现原始字节传输，**没有声称实现全部格式的内容理解**。自动化扩展方案见 [非文本文件设计](docs/MEDIA_PIPELINE.md)。

默认读取单文件上限 32 MiB，可在本机配置提高，硬上限 256 MiB；二进制分块上限 512 KiB，图片响应默认 2 MiB。协议单条输入硬上限 12 MiB；写文本字段上限 8M 字符、二进制 Base64 字段 11M 字符，仍受总消息上限约束。不要把大文件原始 Base64 塞进提示词。

## 4. root、只读/读写、黑白名单

配置文件：macOS/Linux `~/.config/chatgpt-local-mcp-tunnel/config.json`（支持 XDG）；Windows `%APPDATA%\chatgpt-local-mcp-tunnel\config.json`。

```bash
local-mcp configure --root "$HOME/git_local" --mode read_write
local-mcp configure --mode read_only
```

更改后重启 MCP/Tunnel，并刷新客户端工具列表。只读模式**不注册写工具**，服务方法也再次校验；提示词不能开写权限。

整个 HOME 可读、只允许几个项目写入的配置示例：

```json
{
  "root": "~",
  "mode": "read_write",
  "write_roots": ["git_local/tank-forge-kimi/**", "git_local/pwr-stt-twin/**"],
  "default_policy": "allow",
  "allow": [],
  "force_allow": ["git_local/demo/.env.example"],
  "key_source": "keyring"
}
```

省略 `deny` 使用内置黑名单；显式填写 `deny` 会替换可配置部分，不替换不可绕过的凭据/运行时保护。空 `write_roots` 表示在读写模式下整个授权 root 可写；HOME 全范围写入须显式 `--allow-home-write`，不作为默认。

判定顺序：授权根目录及真实路径 → 不可绕过的系统凭据/自身运行时保护 → 精确 `force_allow` → `deny` → `allow` → `default_policy`。默认 HOME 普通文件可读，普通 allow 不是“只允许这些目录”；只允许白名单要设 `default_policy=deny`，并直接从允许的目录搜索。

黑白名单使用相对 root 的大小写不敏感 glob；Python fnmatch 的 `*` 可以跨目录，`**/` 也匹配根级文件。`force_allow` 只接受**具体文件**，不接受通配符，不能覆盖硬性凭据保护。缩小 root 到 `.ssh` 也不能绕过保护。

读取拒绝越界符号链接和多硬链接；写入不经过符号链接。POSIX 使用 no-follow 目录描述符减少路径替换风险。**Windows 路径检查不是 OS 沙箱，同一用户的恶意程序不在本实现的隔离保证内**。只有数据内容的黑名单不可能识别所有文件中的秘密；上传给模型之前仍需控制授权范围。

## 5. 写入和恢复

写工具：`write_file`、`write_binary`、`edit_file`、`apply_patch`、`create_directory`、`restore_file`。

已有文件必须提供刚读取的 `expected_sha256`；新文件可传 `MISSING`。覆盖前备份，使用同目录临时文件原子替换，再读回校验。支持 `dry_run` 预览，冲突不强制覆盖。`apply_patch` 是**一个文件内**的有序唯一文本替换，不是 unified-diff 解析器，也不是跨文件事务。

备份位于私有状态目录，通过 `list_backups(path)` 获得备份 ID，恢复仍要求当前文件哈希。备份保留原文件内容，具有敏感性；没有自动清理/保留期限，长期使用需监控磁盘。此版不提供 shell、Git push、删除目录或任意进程取消工具。

本服务的按文件锁只约束合作的 MCP 实例；IDE 等外部编辑器不会遵守此锁。哈希复查可发现许多并发变化，但不能保证对非合作写入者实现操作系统级 compare-and-swap。写后发现冲突会明确报告“文件已提交但随后变化”，不能误当作未写入。

## 6. 系统凭据库

- macOS：Keychain；Windows：Credential Manager/WinVault。
- Linux 桌面：Secret Service（需要 D-Bus 会话及已解锁的凭据库）。
- Linux 无桌面：显式 `key_source=systemd`，通过 `LoadCredentialEncrypted` 注入；见 [Linux 配置](docs/LINUX_CREDENTIALS.md)。

只加载这些明确的 native backend；不会选中明文 keyring 插件或在失败时写 `.env`。凭据库不可用/锁定会返回原因。`key_source=environment` 仅为用户显式选择的临时方式，绝不是自动 fallback。`local-mcp key status` 只报告是否存在，不显示 key。

## 7. 用提示词完成 Codex 安装

把下面这段交给**有本机终端权限的 Codex**，不用把 key 放进提示词：

> 在当前 chatgpt-local-mcp-tunnel 仓库中，先阅读 docs/INSTALL_WITH_CODEX.md 和 skills/local-mcp-setup/SKILL.md。授权 root 使用 ~/git_local，mode=read_write。先执行 bootstrap.py --plan，再按文档完成安装、Codex 注册和真实 stdio self-test，保留其他 MCP 配置；检测到已有相同配置则跳过。已有 Tunnel ID 就配置并验证，没有就指出缺失项。Runtime key 只能在我本机的隐藏输入框录入，不向我索取聊天明文；系统授权或非交互密钥录入阻碍时停止该步。不要把进程启动当成连接成功；报告每层真实结果。

也可在具备 Computer Use 的本地助手里执行同一流程，**只把界面导航交给 Computer Use**；登录、创建/复制密钥和系统授权停在用户确认，文件与配置操作仍由脚本执行。详细步骤、失败恢复和验证等级见 [安装提示词](docs/INSTALL_WITH_CODEX.md)。

## 8. 故障诊断

```bash
local-mcp doctor
local-mcp doctor --network --with-tunnel
local-mcp doctor --with-tunnel --bundle ./diagnostic-local-mcp.json
```

每层返回 pass/warning/fail/not_checked，不混淆“装好了”“本机能握手”“云端已认证”“模型能看图”。Bundle 只保存脱敏诊断，不打包用户 HOME、项目、key 或原始日志；生成文件后仍应自行检查再分享。

工具错误包含 `code`、`message`、`cause`、`remediation`、`retryable`、`request_id`。锁错误给出本服务持有者 PID、操作、开始时间、路径和锁类型；外部 OS 锁持有者无法可靠判断时明确写 unknown，不编造、不自动删除锁文件。

完整错误码对照：[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 9. 开发、测试与升级

```bash
python3 -m pip install -e '.[dev,media]'
python3 -m pytest -q
python3 -m home_readonly_mcp.cli self-test
```

stdlib 核心不依赖 MCP SDK；实现有限的 stdio JSON-RPC、legacy initialize 以及 2026-07-28 self-contained discovery/tools/resources 子集，不提供 HTTP 服务、任意插件代码执行或后台任务协议。没有宣称通过完整 MCP 官方一致性认证。

升级重新执行安装器。稳定 launcher 不变、版本化目录保留旧代码；安装探针通过后切换当前版本。首次发现 v0.2 配置会复制兼容项，原配置不动；旧通配符 force_allow 被取消并提示，权限仍保持只读。旧 Codex/MCP 条目不自动删除。root/mode/规则迁移后应再次 `policy_info` 验收。

## 参考

设计参考 FileMCP 的功能与故障经验，本实现没有复制其 Swift/.NET 源码。

- [FileMCP](https://github.com/anhnv02/file-mcp)
- [OpenAI Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Tunnel 客户端配置](https://github.com/openai/tunnel-client/blob/master/docs/configuration.md)
- [Codex MCP](https://developers.openai.com/codex/mcp)
- [MCP image/resource 内容规范](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP 版本协商](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning)
- [keyring](https://keyring.readthedocs.io/en/latest/)
- [systemd credentials](https://systemd.io/CREDENTIALS/)
