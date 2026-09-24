# chatgpt-local-mcp-tunnel

**让 ChatGPT 直接分析和修改你的本地项目。**

版本：**v0.4.0** · 支持 macOS / Windows / Linux · 默认 HOME 只读

[这是什么](#what) · [主要能力](#capabilities) · [配置网站](#platform) · [本机安装](#install) · [故障排查](#troubleshooting) · [Codex 激活与示例](#codex) · [ChatGPT 激活与示例](#chatgpt)

<a id="what"></a>
## 1. 这是什么？解决什么问题？

这是一个运行在你电脑上的 **MCP 服务**。连接后，你可以在 ChatGPT 聊天窗口中直接要求它阅读项目、查找代码、查看图片和 PDF、修改多个文件，以及在授权后运行测试、操作 Git，减少来回复制代码和手工上传文件的步骤。

```text
ChatGPT 聊天窗口 → OpenAI Secure MCP Tunnel → 本机 MCP → 你授权的项目目录
```

**ChatGPT 负责理解任务，本机 MCP 负责实际操作文件。** 文件无需预先打包成聊天附件；工具读取到的内容会发送给调用它的模型，所以仍需限定目录和权限。

**Codex 在本文中有两个用途：**帮助你安装、配置和排错；也可以直接连接同一个本机 MCP。Codex 本地直连使用 stdio，不需要 Tunnel ID 或 Runtime API key。ChatGPT 远程访问才需要 Tunnel；在 Codex 注册成功不等于 ChatGPT 已连接。本程序不调用模型 API，Runtime API key 用于 Tunnel 认证，不是把 ChatGPT 换成 API 编程工具。连接方式见 [OpenAI MCP 文档](https://developers.openai.com/codex/mcp)和 [Secure MCP Tunnel 文档](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。

<a id="capabilities"></a>
## 2. 主要能力：完整 MCP 工具列表

最多 **38 个工具**。只读模式提供 **24 个**；读写模式、命令和推送均关闭时提供 **33 个**；另行开启命令增加 4 个，开启推送再增加 1 个。以下“读取”表示只读模式即可使用；“读写”表示必须设置 `mode=read_write`。

| 分类 | MCP 工具 | 能做什么 | 所需模式 |
|---|---|---|---|
| 文件读取 | `list_directory` | 分页查看目录、文件大小、类型和修改时间 | 读取 |
| 文件读取 | `file_info` | 获取元数据和符合读取条件文件的 SHA-256 | 读取 |
| 文件读取 | `read_file` | 读取 UTF-8 文本或指定行，返回原文件哈希和截断信息 | 读取 |
| 文件读取 | `find_files` | 按文件名或路径通配符查找文件 | 读取 |
| 文件读取 | `search_text` | 搜索字面文本，支持文件过滤和大小写控制 | 读取 |
| 代码检索 | `glob` | 路径搜索、修改时间排序、分页和忽略规则 | 读取 |
| 代码检索 | `grep` | 字面／逐行正则搜索，返回命中文件、上下文或匹配次数 | 读取 |
| 代码检索 | `search_code` | 最多 6 个查询，优先排列声明行和完整标识符匹配 | 读取 |
| 项目上下文 | `repo_overview` | 汇总项目结构、清单文件、扩展名统计和扫描范围 | 读取 |
| 项目上下文 | `workspace_context` | 获取适用的 AGENTS.md、项目清单和 Git 状态 | 读取 |
| 批量读取 | `batch_read` | 一次执行 1–16 个只读操作，逐项返回结果和错误 | 读取 |
| 文件修改 | `write_file` | 新建／覆盖文本；覆盖前校验哈希、备份，写后验证 | 读写 |
| 文件修改 | `write_binary` | 解码 Base64 后写入二进制文件，不执行文件 | 读写 |
| 文件修改 | `edit_file` | 单文件内唯一文本的精确替换，支持预览 | 读写 |
| 文件修改 | `apply_patch` | 1–64 项跨文件精确替换、整批预检、备份和失败恢复 | 读写 |
| 文件修改 | `create_directory` | 创建一级目录，父目录须存在 | 读写 |
| 备份恢复 | `list_backups` | 查看指定文件的备份 ID、时间和哈希 | 读取 |
| 备份恢复 | `restore_file` | 恢复指定备份，恢复前校验当前版本并备份现状 | 读写 |
| 图片 | `read_image` | 直接返回图片，支持缩放、裁剪、EXIF 方向及坐标映射 | 读取 |
| PDF | `read_document` | 提取 PDF 指定页文字；目前不是通用 Office 解析器 | 读取 |
| PDF | `render_pdf_page` | 将 PDF 指定页渲染为图片，查看图表和版面 | 读取 |
| ZIP | `list_archive` | 列出允许访问的 ZIP 成员，过滤危险和敏感条目 | 读取 |
| ZIP | `read_archive_member` | 直接读取 ZIP 内文本、图片、PDF 页面或二进制资源 | 读取 |
| 二进制 | `read_binary` | 分块传输原始字节，返回偏移量及哈希 | 读取 |
| 图像验收 | `visual_probe` | 生成随机字符图片，检验模型是否真的收到图片 | 读取 |
| Git | `git_status` | 查看工作区和暂存区状态 | 读取 |
| Git | `git_log` | 查看提交历史 | 读取 |
| Git | `git_diff` | 查看工作区或暂存区差异，可指定路径 | 读取 |
| Git | `git_init` | 初始化普通 Git 仓库 | 读写 |
| Git | `git_add` | 检查权限后暂存指定文件 | 读写 |
| Git | `git_commit` | 使用配置的 Git 身份提交已暂存文件 | 读写 |
| Git | `git_push` | 向批准的远端推送当前分支到同名分支 | 读写＋推送开关＋远端白名单 |
| 命令执行 | `run_command` | 执行短任务，返回输出、完成状态和真实退出码 | 读写＋命令开关 |
| 命令执行 | `start_command` | 启动长任务，返回会话 ID，支持超时和请求去重 | 读写＋命令开关 |
| 命令执行 | `read_command_output` | 按游标读取任务输出、状态和退出码 | 读写＋命令开关 |
| 命令执行 | `cancel_command` | 取消本运行实例启动的任务并清理子进程 | 读写＋命令开关 |
| 权限诊断 | `policy_info` | 查询实际根目录、读写模式、规则和权限开关 | 读取 |
| 权限诊断 | `diagnose` | 查询诊断信息，探测指定路径的本服务锁 | 读取 |

配套提供：**三平台安装脚本、Codex 自动注册、系统密钥库、Tunnel 配置、分层诊断和脱敏报告**。这些是本机管理功能，不计入 38 个 MCP 工具。

开始使用前记住三点：**命令执行和推送默认关闭**；已有文件覆盖需要原 SHA-256；图片必须经客户端实际视觉验收。Shell 开启后不是 OS 沙箱，文件黑名单不能限制任意命令访问其他目录／网络。跨文件补丁是失败后尽力恢复，不是多文件原子事务。`.blend`、视频、点云和 Office 的专用解析器尚未实现，二进制传输也不等于自动进入 ChatGPT 沙箱。详细参数和限制见 [编程工具说明](docs/CODING_TOOLS.md)及[非文本文件说明](docs/MEDIA_PIPELINE.md)。

## 3. 如何用

**下面的安装和排错提示词发给运行在你本机、具备终端权限的 Codex。** 首次安装不需要先启用本 MCP，直接使用 Codex 已有的本机工具。网站操作还需要当前 Codex 已启用并获授权的浏览器或 Computer Use；仅有 CLI 不代表具备网页点击能力。

完整使用顺序：**网站配置 → 本机安装与配置 → 诊断 → Codex 本地验收 → ChatGPT 连接使用**。只在 Codex 本地使用时，可跳过网站和 Tunnel 步骤。

<a id="platform"></a>
### 3.1 在 Codex 中用提示词配置网站上的 Tunnel 和 API key

**准备：**登录自己的 OpenAI Platform 和目标 ChatGPT 工作区。已有 Tunnel 可以复用，但同一个 Tunnel ID 不要同时交给 FileMCP 和本工具两个运行实例使用。

| 网站入口 | 要完成的设置 |
|---|---|
| [Platform → Tunnels](https://platform.openai.com/settings/organization/tunnels) | 创建或选择 Tunnel，记录 `tunnel_id`，核对所属组织和目标 ChatGPT 工作区关联 |
| [Platform → Runtime API keys](https://platform.openai.com/settings/organization/api-keys) | 创建 Restricted Runtime key，仅授予需要的 Tunnels Read + Use |
| [Platform → Organization roles](https://platform.openai.com/settings/organization/people/roles) | 权限不足时核对角色；创建／修改 Tunnel 需要 Read + Manage，运行或选用 Tunnel 需要 Read + Use |

Runtime key 的所属用户／服务账号也必须对目标 Tunnel 有权限。通过网站创建 Tunnel 的流程不需要给本程序配置 Admin key。以上权限划分见 [OpenAI Tunnel 权限说明](https://github.com/openai/tunnel-client/blob/master/docs/permissions.md)。

**复制给 Codex：**

```text
请帮助我在 OpenAI 开发者网站配置 chatgpt-local-mcp-tunnel 使用的 Tunnel。

请先检查当前是否有已授权的浏览器或 Computer Use 工具。有则操作网站；没有则明确说明缺少网页操作能力，并给出下面两个页面的操作步骤，不要假称已配置。

1. 打开 https://platform.openai.com/settings/organization/tunnels ，核对当前组织及我要使用的 ChatGPT 工作区。已有合适的 Tunnel 优先复用；没有则创建名为 chatgpt-local-mcp-tunnel 的 Tunnel。组织／工作区不明确时先让我选择，不随意关联其他工作区。
2. 核对 Tunnel 包含目标组织和 ChatGPT 工作区，记录真实 tunnel_id。不要只建在 Platform 组织下就判定 ChatGPT 能看到。
3. 打开 https://platform.openai.com/settings/organization/api-keys ，准备创建名为 chatgpt-local-mcp-tunnel-runtime 的 Restricted Runtime key，权限仅为 Tunnels Read + Use；不要使用 All 或 Admin key。已有有效凭据时不重复创建或撤销旧 key。
4. 登录、验证码、权限审批由我本人完成。进入会显示密钥的最后一步前把控制交给我，我会在本机完成生成并保存到密码管理器；不要读取、截图、转录或把明文 key 发到聊天、源码、普通配置文件中。下一阶段我会通过 local-mcp key set 隐藏录入。
5. 权限缺失时报告具体缺项及需哪个管理员处理；不要擅自扩大账号权限。

最后只报告：tunnel_id、组织／工作区关联、权限检查结果、Runtime key 是否已由我安全保存，以及尚未完成的项。不要输出密钥正文。
```

**完成标志：**拿到真实 `tunnel_id`，Runtime key 已由本人安全保存，组织和工作区关联已核对。此时还没有完成本机部署或 ChatGPT 连接。

<a id="install"></a>
### 3.2 在 Codex 中用提示词安装本机 MCP，并配置目录、权限和密钥

要求 **Python 3.11+**。Git 和 Codex CLI 需能在本机找到；完整安装需要联网获取媒体、密钥库、搜索依赖及官方 Tunnel 客户端。源码为私有仓库时，使用你已有的 GitHub 登录，不把 GitHub token 写进提示词。

当前 v0.4.0 在 `feat/local-mcp-v0.3` 分支；分支名沿用旧名称。安装时检查实际版本，若 `main` 尚未包含这一版，不要误装旧版。

**修改下列参数后，复制给 Codex；不要在其中填写 API key：**

```text
请在本机安装并配置这个项目，不只是告诉我安装命令。

仓库：https://github.com/macgaf/chatgpt-local-mcp-tunnel
版本：v0.4.0；main 未包含时使用 feat/local-mcp-v0.3 分支。
访问根目录：~/git_local
模式：read_write
可写子目录：整个上述 root；不扩大到整个 HOME。
命令执行：关闭。
Git 推送：关闭。
Tunnel ID：<填入第 3.1 步得到的真实 tunnel_id>
Runtime key：我在本机隐藏输入，不提供聊天明文。

1. 优先使用已有本机仓库，核对分支、版本和未提交修改；不存在才克隆。不覆盖本地修改，不强制切换脏工作区。
2. 阅读 README、bootstrap.py 和 docs/INSTALL_WITH_CODEX.md；检查 Python 3.11+、Git、Codex CLI。缺系统依赖时说明原因并征求安装授权，不自行 sudo。
3. 先执行 bootstrap.py --plan，再按上面的 root/mode 安装完整组件、注册 Codex、安装官方 Tunnel 客户端。macOS/Linux 使用 install.sh；Windows 使用 Python 执行 bootstrap.py。不要把 core-only 安装当成已具备图片/PDF能力。
4. 使用安装器输出的 local-mcp 绝对路径配置上述 Tunnel ID，并明确关闭命令执行和 Git 推送。保留其他 MCP 条目和无关设置；同名配置冲突时比较差异，不覆盖整个 Codex 配置。
5. 用 key status 检查本工具是否已有该 Tunnel 的可用凭据。没有时给出本机交互式终端的 key set 命令，由我隐藏录入并授权系统凭据库；没有 TTY 或凭据库不可用时不要改用明文。macOS 使用 Keychain，Windows 使用 Credential Manager，Linux 桌面使用 Secret Service；无桌面 Linux 按 docs/LINUX_CREDENTIALS.md 配置。
6. 运行 self-test、tunnel init、doctor --with-tunnel；检查每步退出码和实际结果。需要本人输入或授权的步骤明确暂停，先完成其他不受影响的步骤。
7. 初始化和诊断通过后，给出在独立本机终端运行 tunnel run 的完整命令。不要自动添加开机自启，也不要把“开始运行”写成“ChatGPT 已连接”。

最后报告安装版本、启动器和配置路径、实际 root/mode/开关、Codex 注册结果、Tunnel 诊断结果，以及第 3.4、3.5 节还需完成的客户端验收。不要输出 key。
```

**参数怎么选：**不传 root/mode 的首次安装默认是 `root=~`、`read_only`；上面的提示词则明确授权 `~/git_local` 读写。后续升级会保留已有配置，不会自动恢复默认值。

| 参数 | 含义及常用选择 |
|---|---|
| `root` | 访问根目录；`~` 为本用户目录，也可设为 `~/git_local` 或更具体的项目 |
| `mode` | `read_only` 只读；`read_write` 允许写入 |
| `write_roots` | 相对 root 的可写路径规则；空列表表示读写模式下整个授权 root 可写 |
| `allow` / `deny` | 文件访问规则；默认普通 HOME 文件可读，敏感路径受保护。省略 deny 使用内置规则 |
| `force_allow` | 具体文件的例外，不接受通配符，不能覆盖硬性凭据保护 |
| `enable_commands` | 命令执行开关；默认 false，开启还需确认非沙箱风险 |
| `enable_git_push` / `git_push_remotes` | 推送开关及精确远端 URL 白名单；默认不推送 |
| `tunnel_id` | 网站生成的 Tunnel 标识，可以存入配置 |
| `key_source` | 通常为 `keyring`；API key 正文不写入 config.json |

例如要“HOME 可读，但只允许指定项目写入”，可以让 Codex **合并以下字段到已有配置**，保留 Tunnel、启动器及其他设置，不整份覆盖：

```json
{
  "root": "~",
  "mode": "read_write",
  "write_roots": ["git_local/pwr-stt-twin/**", "git_local/tank-forge-kimi/**"],
  "enable_commands": false,
  "enable_git_push": false
}
```

这些配置在本机管理，不通过远程 MCP 自改权限。更改后重启相应 MCP/Tunnel 和客户端连接，再以 `policy_info` 核验。

<details>
<summary>命令速查：安装、录入密钥、启动、开启测试命令</summary>

macOS/Linux，在已检出的 v0.4.0 仓库内：

```bash
./install.sh --root "$HOME/git_local" --mode read_write --register-codex --install-client
```

Windows，在仓库内：

```powershell
python .\bootstrap.py --root "$HOME\git_local" --mode read_write --register-codex --install-client
```

下列为 macOS/Linux 的默认启动器路径，先替换 `<TUNNEL_ID>`。Windows 使用安装器输出的 `local-mcp.cmd` 绝对路径；PowerShell 通过 `& "路径" 参数` 调用。

```bash
~/.local/bin/local-mcp configure --tunnel-id '<TUNNEL_ID>' --disable-commands --disable-git-push
~/.local/bin/local-mcp key set
~/.local/bin/local-mcp self-test
~/.local/bin/local-mcp tunnel init
~/.local/bin/local-mcp doctor --with-tunnel
~/.local/bin/local-mcp tunnel run
```

`key set` 需本人在本机交互式终端隐藏输入。`tunnel run` 要保持运行；停止后 ChatGPT 不能通过它访问本机。重复安装时，已有可用凭据不必重新录入。不要另行手动启动第二个同 ID 的 Tunnel 客户端。

需要让 MCP 运行测试时，在理解 Shell **不是 OS 沙箱**后明确开启：

```bash
~/.local/bin/local-mcp configure --enable-commands --acknowledge-unsandboxed-commands
# 关闭：
~/.local/bin/local-mcp configure --disable-commands
```

上述命令不改变 root/mode；必须已处于读写模式，配置变更后需重启连接。整个 HOME 无限制写入另需显式 `--allow-home-write`，不建议作为默认。

</details>

<a id="troubleshooting"></a>
### 3.3 在本地用提示词排查故障

**即使本 MCP 连接失败，也可以让 Codex 用原有终端工具排查**，不要依赖故障中的 MCP 自己完成修复。

**复制给 Codex，附上实际报错即可：**

```text
请在本机排查 chatgpt-local-mcp-tunnel 的问题，并修复已确认的安装或配置故障。
现象／报错：<粘贴错误文本，先删除密钥等敏感信息>

1. 用你已有的本机终端工具检查，不假定这个 MCP 当前可用。先定位真实安装版本、local-mcp 启动器、配置及源码，阅读 docs/TROUBLESHOOTING.md。
2. 按层定位：可执行程序/PATH与依赖 → root/mode/规则 → 本机 self-test → Codex 注册和工具加载 → 凭据库/Tunnel profile → 网络及授权 → ChatGPT App选择和图片消费。只在需要时检查对应层。
3. 执行 doctor；Tunnel 问题再执行 doctor --with-tunnel，网络问题可加 --network。直连探针失败不一定说明代理下的 Tunnel 失败，要分别核查。
4. command not found 时查安装器输出的绝对路径；401/403 时区分 key 无效、所属组织、Read/Use 权限及工作区关联。不要输出 key。
5. 锁冲突先查 diagnose 和任务状态，区分本服务锁、活动命令和 OS 占用；不删除活锁、不杀未知 PID。哈希冲突先重新读取和比较，不强行覆盖。
6. 配置修改前备份，只修复已确认项，保留其他 MCP 和权限边界。不要关闭 TLS、取消黑名单、开启 Full Access 或扩大 root 来掩盖问题。
7. 修复后重跑失败的步骤，再实际调用 policy_info 和一个只读工具。图片问题用 visual_probe；Shell 任务核对终止状态、exit_code 和输出是否读完，不能把 ok=true 当成测试通过。
8. 本机可修复部分继续完成；需网站授权、本人密钥输入或客户端重连时，明确缺项和下一步。需要报告时用 doctor --bundle 生成脱敏 JSON，分享前仍检查内容。

最后按“现象 → 已确认原因 → 修改内容 → 验证证据 → 剩余阻碍”报告，标明哪些是通过、警告、失败或尚未检查。
```

**验收只看对应证据：**

| 检查项 | 通过的证据 |
|---|---|
| 本机 MCP | `self-test` 实际握手、发现工具和读取成功 |
| Codex 注册 | `codex mcp list/get` 配置正确；当前会话还需实际调用工具 |
| Tunnel | 官方诊断实际通过，运行实例健康；不等于 ChatGPT 已选中 App |
| 图片 | 当前客户端实际显示图片，模型正确读出 `visual_probe` 字符 |
| 写入／命令 | 授权测试文件写后读回一致；命令正常结束且退出码符合预期 |

完整错误码和处理办法见 [故障排查手册](docs/TROUBLESHOOTING.md)。

<a id="codex"></a>
### 3.4 在 Codex 中激活这个 MCP，并开始使用

**注册 → 重连 → 验收 → 使用。**本地 stdio 模式不需要 `codex mcp login`，也不依赖 Tunnel 在线。

安装时用了 `--register-codex` 就已经执行注册。尚未注册时，让 Codex 运行下面的本机管理命令；启动器不在 PATH 时用第 3.2 节输出的绝对路径：

```bash
local-mcp codex-install
codex mcp list
codex mcp get chatgpt-local-mcp-tunnel --json
```

注册后在 Codex CLI 重新打开交互会话，用 **`/mcp`** 查看活动连接；桌面／IDE 客户端使用 MCP 设置中的重连或重启入口。`/mcp` 是查看连接的入口，不是安装命令，也不能提升服务器权限。配置及客户端操作以 [OpenAI 官方 MCP 文档](https://developers.openai.com/codex/mcp)为准。

**激活与验收提示词：**

```text
请使用本机已注册的 chatgpt-local-mcp-tunnel MCP。
先检查当前会话能否调用它；若只注册但未加载，请说明需在哪个客户端重新连接，不要改用 shell 读取结果冒充 MCP 验收。
能调用后，实际执行 policy_info，报告 root、mode、shell_enabled、git_push_enabled。
然后调用 list_directory 列出 root 一级条目，再调用 visual_probe 并读出图中字符。
本次只验证读取和图像，不写入文件、不执行项目命令、不推送 Git。
若工具不存在、图片不可见或调用被拒绝，报告真实错误。
```

**使用示例一：分析项目，不修改。**假设 root 为 `~/git_local`，工具中的项目路径就是 `pwr-stt-twin`：

```text
使用 chatgpt-local-mcp-tunnel 分析 pwr-stt-twin。
先 workspace_context，再 repo_overview 和 search_code，定位建模流程相关代码；用 batch_read 读取关键文件。
本次只输出模块关系、关键入口和有依据的问题，不改代码、不执行命令。
```

**使用示例二：修复代码并运行测试。**需事先开启读写和命令权限；提示词本身不会改变开关：

```text
使用 chatgpt-local-mcp-tunnel 修复 demo 项目中 <具体问题>。
读取规则、相关实现与测试，记录原 SHA-256；先预览跨文件 apply_patch，再应用必要修改。
运行项目已有的相关测试；长任务使用 start_command，读取输出直到终止且 has_more=false，核对退出码。
最后用 git_diff 展示修改和测试结果。本次不要 git_add、git_commit 或 git_push。
权限未开启时明确说明，不自行提升权限；测试失败就继续查原因，不把“已启动”当成通过。
```

**使用示例三：查看本地图片和 ZIP，无须重复上传：**

```text
使用 chatgpt-local-mcp-tunnel 查看 pwr-stt-twin 中的 additional-visual-review-inputs.zip。
先 list_archive，再 read_archive_member 读取相关图片；ZIP 内 PDF 用 read_archive_member 的 page 视图，独立 PDF 用 render_pdf_page。
需要细节时使用 read_image 裁剪原图区域，保留 EXIF 方向和缩放坐标说明，不修改原文件。
不要让我重新手工上传服务能读取的文件；客户端确实无法显示时报告具体限制，不凭文本猜图。
```

<a id="chatgpt"></a>
### 3.5 在 ChatGPT 聊天窗口使用：最终目标

本机验收之后，完成 ChatGPT 这一端的连接：

1. 在独立本机终端运行 `local-mcp tunnel run`，保持在线。
2. 在 ChatGPT 当前账号／工作区启用 Developer Mode，进入 **Plugins / Apps** 创建开发者 App，名称建议同样用 `chatgpt-local-mcp-tunnel`。
3. 连接方式选择 **Tunnel**，选择或填写第 3.1 节的 Tunnel ID，完成工具扫描及必要授权。
4. 新开聊天，在工具／App 菜单中选择它，或从 `@` 候选中选中该 App；再发送任务。只输入名称不能激活尚未连接的服务。

页面入口和可用操作受当前账号、工作区及平台政策影响；没有入口或写工具被平台拒绝时要查对应权限，不能靠修改本机工具声明绕过。官方说明：[通过 Tunnel 连接 ChatGPT](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#connect-from-chatgpt)、[Developer Mode 与 MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)。

**在已选中 App 的 ChatGPT 聊天里发送：**

```text
使用 chatgpt-local-mcp-tunnel 直接分析我的本地项目 pwr-stt-twin。
先实际调用 policy_info 和 workspace_context，确认访问范围与权限，再读取相关代码；不要只凭聊天记忆回答。
本次先分析，不改文件。涉及本地图片或 PDF 时调用相应图像工具，不要求我重复上传。
```

确认读取和图片可见后，再授权具体修改；可沿用第 3.4 节的修复与测试提示词。**Codex 本地连接与 ChatGPT Tunnel 连接是两个独立验收项，但可以操作同一套授权项目文件。**

## 4. 详细说明与验证记录

| 文档 | 什么时候看 |
|---|---|
| [编程接口与权限](docs/CODING_TOOLS.md) | 查 Git、命令、检索、批量读取、补丁参数及安全限制 |
| [安装执行细则](docs/INSTALL_WITH_CODEX.md) | 排查安装步骤、授权及客户端验收 |
| [故障排查](docs/TROUBLESHOOTING.md) | 根据错误码定位原因和恢复办法 |
| [Linux 凭据与用户服务](docs/LINUX_CREDENTIALS.md) | Linux 桌面凭据库、无桌面 systemd 凭据和常驻运行 |
| [非文本文件说明](docs/MEDIA_PIPELINE.md) | 图片、PDF、ZIP、二进制传输及尚未实现的专用适配器 |
| [测试报告](TEST_REPORT.md) | 区分实际测试、替身测试、平台跳过和待实机验收项目 |
| [变更记录](CHANGELOG.md) | 查看版本变化 |

当前测试记录包含三平台自动化测试与真实 stdio 自检；不代表已在你的机器上部署，也不代表原生凭据库、真实 Git 网络推送、Tunnel 认证和 ChatGPT 图片消费已全部实机验收。以对应测试报告及你本机的实际验证结果为准。
