# chatgpt-local-mcp-tunnel

**让 ChatGPT 直接分析和修改你的本地项目。**

版本：**v0.4.0** · 安装分支：**`main`** · 支持 macOS / Windows / Linux · 默认 HOME 只读

[这是什么](#what) · [主要能力](#capabilities) · [配置网站](#platform) · [本机安装](#install) · [故障排查](#troubleshooting) · [Codex 激活与示例](#codex) · [ChatGPT 激活与示例](#chatgpt) · [日志](#logs) · [更新与升级](#upgrade)

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

配套提供：**三平台安装脚本、Codex 自动注册、系统密钥库、Tunnel 配置、持久日志、分层诊断和脱敏报告**。这些是本机管理功能，不计入 38 个 MCP 工具。

开始使用前记住三点：**命令执行和推送默认关闭**；已有文件覆盖需要原 SHA-256；图片必须经客户端实际视觉验收。Shell 开启后不是 OS 沙箱，文件黑名单不能限制任意命令访问其他目录／网络。跨文件补丁是失败后尽力恢复，不是多文件原子事务。`.blend`、视频、点云和 Office 的专用解析器尚未实现，二进制传输也不等于自动进入 ChatGPT 沙箱。详细参数和限制见 [编程工具说明](docs/CODING_TOOLS.md)及[非文本文件说明](docs/MEDIA_PIPELINE.md)。

## 3. 如何用

**下面的安装和排错提示词发给运行在你本机、具备终端权限的 Codex。** 首次安装不需要先启用本 MCP，直接使用 Codex 已有的本机工具。网站操作还需要当前 Codex 已启用并获授权的浏览器或 Computer Use；仅有 CLI 不代表具备网页点击能力。

完整使用顺序：**检查已有配置与凭据 → 缺失时准备网站资源并安全保存 → 本机安装接续缓存 → 诊断 → Codex 本地验收 → ChatGPT 连接使用**。已有安装先复用，不必为了按章节顺序操作而重建资源；只在 Codex 本地使用时，可跳过网站和 Tunnel 步骤。

<a id="platform"></a>
### 3.1 在 Codex 中自动准备 Tunnel 和 Runtime key：已有则复用，缺少才创建

**目标不是只打开网页，而是完成“查找／创建 → 本机安全保存 → 读回与认证验证”。** 允许本机程序读取并保存敏感值；禁止把值暴露在模型对话、工具参数／结果或日志里。目录和模式仍由用户选择，这一步不会自动开启文件写入、Shell 或 Git 推送。

| 当前情况 | 自动处理 |
|---|---|
| 已有匹配的 Tunnel 和本机有效受限 key | 核验目标、权限与认证，直接复用 |
| 网站已有合适 Tunnel，但本机未配置 | 核验工作区关联后自动缓存 ID |
| 没有合适 Tunnel 或可用完整 key | 建立本项目专用资源，key 仅 Tunnels Read + Use |
| 网站只剩旧 key 的掩码、本机没有完整值 | 不假称可以恢复；检查授权凭据来源，确实缺失才新建，保留旧 key |
| 需要登录、验证码、系统授权或确有歧义 | 暂停该项等待用户处理，其他步骤继续 |

**执行条件与代码状态：**电脑工具负责普通界面，本机执行器负责探针与凭据保存；必须本人批准的系统授权仍交由本人完成。先实际检查工具和完整转存通道，不能以打开页面或点击次数代替结果验证。

`tunnel prepare` 的候选实现位于 [`fix/browser-tunnel-preparation` / PR #2](https://github.com/macgaf/chatgpt-local-mcp-tunnel/pull/2)，尚未合并且真实网站创建流程待验收。main 的文档同步不等于主线程序已经提供该命令；先核对实际提交和 --help，优先复用已有执行器，不强制切换有修改的工作区。细则见 [自动准备与安全保存](docs/AUTOMATED_TUNNEL_SETUP.md)。

| 网站入口 | 用途 |
|---|---|
| [Platform → Tunnels](https://platform.openai.com/settings/organization/tunnels) | 查找／创建并核验目标组织与 ChatGPT 工作区关联 |
| [Platform → Runtime API keys](https://platform.openai.com/settings/organization/api-keys) | 创建本项目的 Restricted Runtime key，仅授予 Tunnels Read + Use |

创建／修改 Tunnel 需要 Read + Manage，运行需要 Read + Use；Runtime key 的所属主体也须有对应权限，不需要额外新建 Admin key。旧 key 的完整值仅在创建时显示，网页掩码不能用于恢复。依据：[官方 Tunnel 权限说明](https://github.com/openai/tunnel-client/blob/master/docs/permissions.md)、[API key 显示规则](https://help.openai.com/en/articles/4936850-where-do-i-find-my-openai-api-key)。

**复制给本机 Codex。** 完整提示词同时保存在 [docs/prompts/setup-with-computer.txt](docs/prompts/setup-with-computer.txt)，与下方内容一致；修改时同步维护，不仅提供聊天附件。

```text
请使用已启用的「电脑 / Computer Use」及已授权的本机执行工具，实际完成 chatgpt-local-mcp-tunnel 的 Tunnel 和 Runtime API key 准备。
仓库：https://github.com/macgaf/chatgpt-local-mcp-tunnel

目标：已有合适资源和有效本机凭据就复用；确实缺少时创建本项目专用资源，自动保存到本机并验证。不要只打开网页、输出操作说明，或再次只改提示词。除确实需要本人批准或选择的步骤外，持续完成所有可推进的工作。

一、授权范围和执行分工

我授权你为本项目查找、创建缺失的 Tunnel 和仅含 Tunnels Read + Use 的 Restricted Runtime key，并将它们安全绑定到本机。
- 电脑工具：操作获授权的浏览器，定位页面、选择组织/项目/工作区、填写非敏感字段、操作权限控件、核查界面结果。
- 本机程序：检查缓存、运行探针、处理真实 ID/key、直接写入配置/系统凭据库、执行诊断。命令使用已授权的执行工具，不通过电脑操纵终端或 Codex/ChatGPT 自身来规避权限限制。
- 本人：登录、验证码、系统或宿主要求本人完成的安全授权，以及无法从既有信息确定的目标选择。

不得撤销旧 key、使用 All/Admin key、扩大组织角色权限、抢占正在运行的 FileMCP Tunnel、修改其他应用的凭据或自动配置常驻服务。本次不改变 root、mode、write_roots、命令执行或 Git 推送开关。

二、先确认真实能力和已有进度

1. 读取当前可用的电脑/浏览器工具说明，实际调用合适的最小无敏感数据探针。区分“插件已安装”“本会话有接口”“已获应用授权”“确实可以操作”；不能只看到 @电脑 或发现工具名就判定可用。
2. 电脑接口缺失时，先使用宿主提供的插件发现/连接入口确认。需要我启用或换到支持的任务界面时，只说明缺少的具体一步；不要反复猜插件路径，也不要把 Chrome DevTools 连接失败等同于电脑工具不可用。已有其他合规通道时可继续独立检查。
3. 优先定位已有仓库及本项目配置，检查分支、提交、工作区修改和准备状态，不扫描其他应用的凭据库。阅读 AGENTS.md、README、docs/AUTOMATED_TUNNEL_SETUP.md、相关实现及命令 --help。
4. 核对是否已具备 tunnel prepare。本次上下文中的修复来源为 fix/browser-tunnel-preparation / PR #2：main 已包含时使用 main；尚未包含时检查已有修复副本或该分支的实际代码，不退回只有文档、没有执行器的旧实现。不得覆盖本地修改、强制切换脏工作区或把草稿修复说成已完成实机验收。
5. 优先运行已有分阶段执行器，不另造一套重复实现。阶段名称和参数以实际 --help 为准；可用时使用 preflight、cache-tunnel、permissions、submit-tunnel、submit-key、verify。缺少依赖或页面适配时，只做本任务所需的最小修复和虚构数据测试，不无边界扩展项目。

三、主动申请权限，不把普通排查交回给我

1. 使用电脑完成已获授权的普通页面操作。需要系统/浏览器/宿主批准时，主动通过正常机制发起申请；能够导航到准确位置就先导航，再说明哪个应用、哪项权限需要我批准。
2. 电脑工具的屏幕录制/辅助功能权限、Chrome 调试连接权限、Apple Events、终端执行权限、文件工具 roots 是不同层，分别检查，不用一个错误推断其他层都不可用。
3. 遇到 CHROME_DEBUG_ENDPOINT_MISSING，核对实际 Chrome 实例、配置的 profile 和连接方式。需要时定位 chrome://inspect/#remote-debugging，安全开关或连接批准由本人完成，再重新验证实际连接；不因为 Chrome 已运行就宣称可连接，也不默认改走 AppleScript。
4. 遇到 filePath 越界，不继续把真实凭据写进临时文件，不直接切换 Apple Events。优先检查已授权的本机内存转存路径。确需调整工具 roots 时，展示只涉及本项目专用目录的最小变更，取得授权后操作。
5. 遇到 -1743，仅在确实采用 Apple Events 时请求对应宿主权限；不把 Apple Events 当作电脑或 CDP 的必需条件。执行工具权限不足则走宿主审批，不自行 sudo 或改成 Full Access。
6. 不修改 TCC 数据库、不关闭系统保护/TLS、不猜调试端口、不导出 Cookie、不绕过明确的工具拒绝。不能用电脑替本人批准安全和隐私权限。
7. 我完成一次授权后，重新跑对应探针并从中断处继续，不重复询问已有业务授权。每个失败动作先查原因和当前状态，不无证据循环重试；暂停时只留下最小必要的人工作业。

四、在创建前验证敏感数据处理通道

允许本机程序读取真实 ID/key 并直接存储；禁止真实值经过模型中转。
- 不将完整或部分 ID/key 返回聊天、工具参数/结果、普通日志、截图、HAR、trace、源码或剪贴板历史；不通过工具参数转发输入。
- 电脑截图仅用于确认不含这些值的页面或区域。页面可能显示已有 ID/key 时，先用支持的本机过滤/遮蔽机制，确保在任何截图或工具结果离开本机之前完成；无法保证就改用已授权、仅返回安全状态的本机接口。不能先截图上传再打码。
- 不用电脑截图读取最终密钥弹窗。若电脑工具每次操作自动截图，最终提交和保存由已验证的本机程序独立完成；纯电脑点击能力不等于具备安全保存能力。
- 先用本项目临时条目和虚构值，实际验证“浏览器 → 本机程序内存 → 系统凭据库 → 读回比较”，清理自己创建的测试条目。仅 Keychain 测试成功、或仅工具发现成功，不算整条链路通过。
- macOS 使用 Keychain，Windows 使用 Credential Manager，Linux 桌面使用 Secret Service；已采用 systemd 等来源的配置按原方案处理，不擅自迁移或改存明文。

端到端探针未通过前，不提交创建真实 key。已有保存失败的结果弹窗先保护和恢复，不关闭后再建一个。ID 必要时存本机受保护配置，key 正文只存授权凭据存储；不承诺操作系统和第三方程序完全零留痕。

五、复用或创建 Tunnel

页面：https://platform.openai.com/settings/organization/tunnels
1. 复用已经明确的组织和目标 ChatGPT 工作区，不重复询问。多个候选有歧义时仅按非敏感名称询问一次，不默认选择列表第一项。
2. 优先核验本机绑定及已有专用 Tunnel，检查归属、目标工作区关联和是否被其他 runtime 使用。不能仅凭名称相同、网页当前选中或保存过一个状态文件，就认定适合复用。
3. 有合适资源就由本机程序取得并缓存 ID；没有才创建本项目专用 Tunnel。普通表单尽量由电脑操作，出现敏感结果的提交阶段交给本机程序。
4. 不修改其他工具正在使用的 Tunnel 关联，不停止 FileMCP。改变既有共享资源的关联范围时先单独确认。
5. 核对实际组织与工作区关联；操作账号缺少创建/管理权限时报告具体缺项，不自授权限。保存绑定必须写入运行器真实读取的位置，保留无关配置。

六、正确设置并创建 Runtime key

页面：https://platform.openai.com/settings/organization/api-keys
1. 先检查本项目已授权凭据来源。完整值存在、所属目标正确、权限合适且验证可用时直接复用。库被锁、403、超时或网络错误不能被当成“没有 key”。网页只有掩码也不能算已取得完整值。
2. 确实缺少合适完整凭据时，创建本项目专用 Restricted Runtime key，保留旧 key。既有 All 权限 key 不用于替代最小权限配置。
3. 用真实界面操作选择正确项目、Restricted、Tunnels Read 和 Use。项目尚未选择或控件 disabled 时先解决前置条件；不移除 disabled 属性，不直接篡改页面内部状态冒充选择成功。
4. 每次点击后读取真实 checked/aria-checked/selected 状态或等效可靠界面证据；必要时重新打开权限菜单复核。点击次数、脚本无报错不代表权限已生效。
5. 提交前必须确认：Restricted 生效；Tunnels 的 Read、Use 均已选；其他权限关闭。页面有已选数量时应为 2；界面变化时使用等效证据，不能仅靠某段文字或正则猜测。仍显示 None、0 selected permissions 或状态不明时不得提交。
6. 由同一个本机程序连续执行“提交一次 → 等待明确成功 → 获取完整新 key → 写入对应凭据库条目 → 读回比较 → 保存绑定/阶段状态”。确认保存成功后才能关闭一次性结果弹窗，对模型只返回状态。
7. 创建请求超时或结果不明时，先核对云端列表、本次结果弹窗与本地进度；不再次点击创建、不自动撤销资源、不覆盖旧凭据。确实创建失败且已查明原因后才决定重试。

七、验证和接续

1. 从运行器实际读取的本机存储重新取值，分别核验绑定、凭据可读、权限配置以及真实 Tunnel 认证；不调用付费模型 API 试 key。
2. 已有 local-mcp 时实际运行适用的 key status、tunnel prepare 验证阶段、tunnel init、doctor --with-tunnel，检查退出码和每项结果。缺 MCP 安装或运行实例时分开报告，不冒称完成部署。
3. 区分：Keychain 可读 ≠ key 有效；Tunnel 元数据 Read 请求通过 ≠ Use 权限已实测；进程启动/doctor 通过 ≠ ChatGPT 已连接。Use 无对应实际请求证据就标记未验证。
4. 已自动保存且运行器可读取时，不再让我执行 tunnel configure/key set 重新输入。只在确认缺少合规转存能力后，说明准确阻碍和最小人工备用步骤，不把手工复制作为默认方案。
5. 仅保存脱敏事件和必要的本地接续状态；给出实际配置/日志路径及当前程序支持的查看命令。不输出原始配置、凭据库内容或未经审核的浏览器结果。

八、结束条件与报告

依次完成：工具实际可用 → 目标确认 → 安全转存探针 → Tunnel 复用/创建并保存 → 权限实际确认 → key 复用/创建并保存 → 读回及认证。
能继续的工作继续执行，不在“找到工具”“网页打开”“点击完成”处停止。遇到必须由本人完成的批准时，只暂停受影响步骤，明确一个具体动作；我完成后复测并继续。

最终仅报告：
- 实际使用的电脑/浏览器/本机执行通道，以及程序来源和提交。
- Tunnel：复用／新建／未完成；目标组织和工作区关联：已核验／未核验。
- Runtime key：复用／新建／未完成；Restricted 与 Read + Use：实际核验结果。
- 本机保存和读回：通过／失败；认证 Read、Use 分别是什么证据或尚未验证。
- 配置和日志的实际路径，以及查看脱敏日志的方法。
- 未完成项、准确原因、下一步最小必要操作。

不要输出完整或部分 ID/key，不把历史测试或模拟结果当成本次实机证据，也不要用再次提供一份提示词替代执行结果。
```

**完成标志：**Tunnel 已存在且关联核对、本机保存及读回成功、认证有明确实际结果；仅打开网页或看到 key 名称不算完成。新 key 正文直接保存到系统凭据库，不需要再经用户复制到聊天或重复录入。无法确认的项目报告“未验证”，不能把这个步骤称为 ChatGPT 已连接。

<a id="install"></a>
### 3.2 在 Codex 中用提示词安装本机 MCP：选择目录和模式，复用已保存凭据

要求 **Python 3.11+**、Git、Codex CLI。完整安装会获取图片、PDF、凭据库和代码检索依赖，以及官方 Tunnel 客户端。私有仓库使用已有 GitHub 登录，认证凭据不写在提示词中。

**目录不固定为某个人的项目路径。**默认候选是本用户目录 `~/`（等同 `~/.`），也可选择任意已存在且有权访问的更具体目录。**只读和读写都可选，由用户在安装前确认**，不能因“本地编程”自动开写权限。

**源码入口统一为 `main`。**v0.4.0 的编程工具、交互安装和持久日志已纳入主线；原功能分支不再作为安装入口。已有安装更新方式见 [第 3.7 节](#upgrade)。

**下面的提示词可直接复制，无须事先填写目录、模式、Tunnel ID 或 key：**

```text
请在本机安装并配置 chatgpt-local-mcp-tunnel，不只是告诉我命令。
仓库：https://github.com/macgaf/chatgpt-local-mcp-tunnel
版本：v0.4.0（包含交互安装和持久日志），从 main 分支安装，并核对当前安装文档。

先通过交互确认以下非敏感选项；本次对话已经明确的选项直接复用，不重复询问：
- 访问根目录：使用默认 ~/（本用户目录），还是我指定的其他目录？不要默认采用开发者个人目录。
- 模式：只读 read_only，还是读写 read_write？说明区别后等我选择，未确认前不启用写入。
- 若选读写：是整个所选 root 可写，还是只允许其中指定子目录？不自动扩大已选范围。若 root 是 HOME 且全部可写，单独说明并取得明确确认。
命令执行和 Git 推送保持关闭。

Tunnel ID 和 Runtime API key 不在聊天中询问、填写或复述。先复用第 3.1 节由本机程序安全保存的配置和凭据；有可用缓存就不要再要求我输入。缺少时按第 3.1 节的授权执行自动准备，无法安全转存时才使用独立本机终端隐藏输入。不要通过工具参数/结果中转实际值。

1. 优先检查已有本机仓库的分支、版本及未提交修改；不存在才克隆 main。已有仓库先确认 origin 指向上述仓库，再获取远端状态。仅在工作区干净且本地 main 可快进时切换／更新；存在本地修改或分叉时暂停该步，不覆盖修改、不强制重置。
2. 阅读 README、bootstrap.py、docs/INSTALL_WITH_CODEX.md；核查 Python 3.11+、Git、Codex CLI。缺系统依赖时说明并征求授权，不自行 sudo。
3. 目录和模式确认后，先用同样参数执行 bootstrap.py --plan，再安装完整组件、注册 Codex并安装官方 Tunnel 客户端。macOS/Linux 使用 install.sh，Windows 使用 Python 执行 bootstrap.py。不要把 core-only 当成已经安装图片/PDF能力。
4. 根据我的选择设置 root、mode、write_roots，明确关闭命令和推送；保留其他 MCP 条目、启动器、凭据来源及无关设置。同名配置冲突时比较差异，不覆盖整个 Codex 配置。不要打印包含真实 ID/key 的配置全文。
5. 使用安装器输出的 local-mcp 绝对路径，先核验已有 Tunnel 配置。第 3.1 节若只生成了本机准备状态，由本机辅助程序核验目标后导入 config.json，保留其他设置；不要假定安装器会自动识别辅助程序的状态文件。已有正确绑定则跳过 tunnel configure，不要求重新录入 ID。
6. 运行 key status，确认当前运行器能从正确的系统凭据库条目读取 Runtime key；此前自动保存且可读的 key 直接复用，跳过 key set。缺失时按第 3.1 节继续自动创建/保存；无安全转存通道时才安排本人独立终端隐藏输入。库锁定是授权问题，不是不存在，不因此新建 key。Linux 无桌面保留原 systemd 方案，不明文回退。
7. 运行 self-test；ID及凭据就绪后再运行 tunnel init、doctor --with-tunnel，逐项检查退出码和结果。需本人输入/授权的步骤暂停，但继续完成不受影响的检查。输出、诊断和最后报告均不要包含 ID/key 正文。
8. 初始化和诊断通过后，给出独立本机终端中 tunnel run 的完整命令。不自动开机自启，不将开始运行当成 ChatGPT 已连接。

最后报告：版本、启动器和配置路径、实际 root/mode/write_roots/开关、Codex注册结果、Tunnel是否已配置及诊断结果，以及第3.4、3.5节尚待完成的验收。ID/key只报告状态，不显示正文或尾号。
```

**选择方式示意（这不是已授权配置）：**

```text
访问目录：默认 ~/，也可由用户指定其他目录
运行模式：① 只读——分析和查看；② 读写——还可修改文件和进行本地 Git 写操作
可写范围：选择读写后，再确认整个所选目录或具体子目录
Tunnel ID：优先复用/自动保存；隐藏输入仅备用，不出现在提示词或工具结果中
Runtime key：本机程序直接保存到系统凭据库，已有有效条目不重复录入
```

首次未传 root/mode 时，程序的安全默认仍是 HOME 只读；后续升级会保留已有配置。**使用上述提示词时应先确认用户选项，不应靠默认值替用户作决定。**目录和权限可以在 Codex 对话中选择；ID/key 则不进入对话。

| 参数 | 如何确定 |
|---|---|
| `root` | 用户选择 `~/` 或其他现有目录；不是固定的个人项目路径 |
| `mode` | 用户选择 `read_only` 或 `read_write` |
| `write_roots` | 读写时确认可写子目录；空列表意味着整个所选 root 可写，不可悄悄清空现有限制 |
| `allow` / `deny` / `force_allow` | 保留现有文件规则；例外限具体文件，不因安装自动放宽 |
| `enable_commands` / `enable_git_push` | 本安装流程关闭；日后需单独授权 |
| `tunnel_id` | 第 3.1 节核验后自动保存/复用；本机 `tunnel configure` 隐藏输入作为备用 |
| `key_source` | 通常为 `keyring`；Runtime key 正文只入系统凭据库，不入 config.json |

<details>
<summary>已有缓存的验证命令，以及无法自动转存时的手工备用入口</summary>

安装前由用户选择目录与模式，再将**非敏感选择**传给 `--root`、`--mode`；不要原样执行占位符。macOS/Linux 用 `./install.sh`，Windows 用 `python .\bootstrap.py`。完整安装参数包括 `--register-codex --install-client`；相同参数先交给 `bootstrap.py --plan` 检查计划。

**第 3.1 节已自动保存成功时，不要执行下面两项录入命令，直接做后续验证。**只有无法自动转存、用户选择手工方式时，本人才在独立本机交互终端使用备用入口（macOS/Linux 默认路径如下；Windows 使用安装器输出的 `local-mcp.cmd` 绝对路径）：

```bash
~/.local/bin/local-mcp tunnel configure
~/.local/bin/local-mcp key status
# 仅在缺少可用凭据、本人决定录入时执行：
~/.local/bin/local-mcp key set
```

`tunnel configure` 提示隐藏输入 ID；已有值可回车保留，不修改目录和模式。`key set` 隐藏输入 key。两个命令的参数都不包含实际值；不要使用 echo、管道、heredoc、会话录制或让助手用工具参数转发输入。没有 TTY、或无法关闭回显时会停止，不退回明文。

自动保存或本人备用录入完成后，Codex 继续运行以下不含敏感值参数的检查：

```bash
~/.local/bin/local-mcp self-test
~/.local/bin/local-mcp tunnel init
~/.local/bin/local-mcp doctor --with-tunnel
```

诊断通过后，在独立本机终端启动：

```bash
~/.local/bin/local-mcp tunnel run
```

**存储和日志边界：**隐藏输入避免把值写进聊天提示词和 shell 命令历史。本工具的格式化输出对 Tunnel ID/key 脱敏；ID仍需保存在本机配置和 Tunnel profile 中，Runtime key 由系统凭据库保存。底层 Tunnel 工具、系统审计或会话录制不受本输入机制完全控制，不能承诺系统中任何地方都不留痕；不要公开原始配置、profile 或未经审核的诊断日志。

旧的 `configure --tunnel-id` 参数保留兼容，但不用于本文的人机交互安装流程。开启命令／推送属于额外授权，见 [编程工具说明](docs/CODING_TOOLS.md)。

</details>

<a id="troubleshooting"></a>
### 3.3 在本地用提示词排查故障

**即使本 MCP 连接失败，也可以让 Codex 用原有终端工具排查**，不要依赖故障中的 MCP 自己完成修复。

**复制给 Codex，附上实际报错即可：**

```text
请在本机排查 chatgpt-local-mcp-tunnel 的问题，并修复已确认的安装或配置故障。
现象／报错：<粘贴错误文本，先去除 Tunnel ID、key 等实际值>

1. 用你已有的本机终端工具检查，不假定这个 MCP 当前可用。先定位真实安装版本、local-mcp 启动器、配置及源码，阅读 docs/TROUBLESHOOTING.md。
2. 按层定位：可执行程序/PATH与依赖 → root/mode/规则 → 本机 self-test → Codex 注册和工具加载 → 凭据库/Tunnel profile → 网络及授权 → ChatGPT App选择和图片消费。只在需要时检查对应层。
3. 执行 doctor；Tunnel 问题再执行 doctor --with-tunnel，网络问题可加 --network。直连探针失败不一定说明代理下的 Tunnel 失败，要分别核查。
4. command not found 时查安装器输出的绝对路径；401/403 时区分 key 无效、所属组织、Read/Use 权限及工作区关联。只报告 ID/key 配置状态，不输出正文或尾号；不要 cat 原始配置。
5. 锁冲突先查 diagnose 和任务状态，区分本服务锁、活动命令和 OS 占用；不删除活锁、不杀未知 PID。哈希冲突先重新读取和比较，不强行覆盖。
6. 配置修改前备份，只修复已确认项，保留其他 MCP 和权限边界。不要关闭 TLS、取消黑名单、开启 Full Access 或扩大 root 来掩盖问题。
7. 修复后重跑失败的步骤，再实际调用 policy_info 和一个只读工具。图片问题用 visual_probe；Shell 任务核对终止状态、exit_code 和输出是否读完，不能把 ok=true 当成测试通过。
8. 本机可修复部分继续完成；先判断已有 ID/key 是缺失、凭据库锁定、权限错误还是网络失败，不遇错就生成新 key。需要重新准备时按第 3.1 节在本机自动复用/保存；确实无安全通道才用独立终端隐藏录入，不让实际值进入工具消息。需本人登录、系统授权或客户端重连时明确缺项。需要报告时用 doctor --bundle，分享前仍审核。

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

<a id="codex"></a>
### 3.4 在 Codex 中激活 MCP，并开始使用

安装器的 `--register-codex` 或本机 `local-mcp codex-install` 会调用 Codex 官方 CLI 注册 stdio 服务。它不会给 Codex 填入 Tunnel ID/API key；Codex 直接在本机启动服务。

**先让 Codex 完成以下检查：**

```text
检查 chatgpt-local-mcp-tunnel 是否已注册到当前 Codex 配置。
用 codex mcp list 和 codex mcp get chatgpt-local-mcp-tunnel --json 核对 command/args，勿输出任何其他 MCP 的环境密钥。
没有条目时运行本工具的 codex-install；已有相同条目不重复添加，有差异则比较并说明，不覆盖其他条目。
确认后提示我重新打开 Codex 会话或刷新 MCP 连接，再进行实际工具调用。注册成功本身不等于当前会话已经加载。
```

重新连接后，在支持该命令的 Codex CLI 中可用 `/mcp` 查看连接；实际界面以当前客户端为准。官方参考：[Codex MCP](https://developers.openai.com/codex/mcp)。

**激活与验收提示词：**

```text
请使用本机已注册的 chatgpt-local-mcp-tunnel MCP。
先检查当前会话能否调用它；若只注册但未加载，请说明需在哪个客户端重新连接，不要改用 shell 读取结果冒充 MCP 验收。
能调用后，实际执行 policy_info，报告 root、mode、shell_enabled、git_push_enabled。
然后调用 list_directory 列出 root 一级条目，再调用 visual_probe 并读出图中字符。
本次只验证读取和图像，不写入文件、不执行项目命令、不推送 Git。
若工具不存在、图片不可见或调用被拒绝，报告真实错误。
```

**使用示例一：分析项目，不修改。**将 `demo` 换成所选 root 内的项目相对路径。root 直接设为项目目录时使用 `.`；root 是 HOME 且项目在 `~/projects/demo` 时使用 `projects/demo`。不要把示例路径当成用户机器上的既有目录：

```text
使用 chatgpt-local-mcp-tunnel 分析 demo。
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
使用 chatgpt-local-mcp-tunnel 查看 demo 中的 additional-visual-review-inputs.zip。
先 list_archive，再 read_archive_member 读取相关图片；ZIP 内 PDF 用 read_archive_member 的 page 视图，独立 PDF 用 render_pdf_page。
需要细节时使用 read_image 裁剪原图区域，保留 EXIF 方向和缩放坐标说明，不修改原文件。
不要让我重新手工上传服务能读取的文件；客户端确实无法显示时报告具体限制，不凭文本猜图。
```

<a id="chatgpt"></a>
### 3.5 在 ChatGPT 聊天窗口使用：最终目标

本机验收之后，完成 ChatGPT 这一端的连接：

1. 在独立本机终端运行 `local-mcp tunnel run`，保持在线。
2. 在 ChatGPT 当前账号／工作区启用 Developer Mode，进入 **Plugins / Apps** 创建开发者 App，名称建议同样用 `chatgpt-local-mcp-tunnel`。
3. 连接方式选择 **Tunnel**，由本人在本机网页中选择已保存的 Tunnel；确需填写 ID 时也在网页完成，不粘贴到聊天或让助手转录。然后完成工具扫描和授权。
4. 新开聊天，在工具／App 菜单中选择它，或从 `@` 候选中选中该 App；再发送任务。只输入名称不能激活尚未连接的服务。

页面入口和可用操作受当前账号、工作区及平台政策影响；没有入口或写工具被平台拒绝时要查对应权限，不能靠修改本机工具声明绕过。官方说明：[通过 Tunnel 连接 ChatGPT](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#connect-from-chatgpt)、[Developer Mode 与 MCP Apps](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)。

**在已选中 App 的 ChatGPT 聊天里发送：**

```text
使用 chatgpt-local-mcp-tunnel 直接分析我的本地项目 demo。
先实际调用 policy_info 和 workspace_context，确认访问范围与权限，再读取相关代码；不要只凭聊天记忆回答。
本次先分析，不改文件。涉及本地图片或 PDF 时调用相应图像工具，不要求我重复上传。
```

确认读取和图片可见后，再授权具体修改；可沿用第 3.4 节的修复与测试提示词。**Codex 本地连接与 ChatGPT Tunnel 连接是两个独立验收项，但可以操作同一套授权项目文件。**

<a id="logs"></a>
### 3.6 如何访问日志

服务默认把运行事件持久保存，退出终端后仍可查看。**先用下面的命令定位实际日志目录：**

```bash
local-mcp logs path
local-mcp logs show --tail 100
local-mcp logs show --level ERROR
local-mcp logs follow --component tunnel
local-mcp logs export --tail 500 --output ./local-mcp-logs.json
```

没有加入 PATH 时，macOS/Linux 把 `local-mcp` 换成 `~/.local/bin/local-mcp`；Windows 使用安装器输出的 `local-mcp.cmd` 绝对路径。`follow` 在独立终端使用，按 Ctrl+C 只停止查看，不停止服务。

| 系统 | 默认日志目录 |
|---|---|
| macOS / Linux | `~/.local/state/chatgpt-local-mcp-tunnel/logs/`；设置 XDG_STATE_HOME 时跟随该设置 |
| Windows | `%LOCALAPPDATA%\chatgpt-local-mcp-tunnel\state\logs\` |

日志按 `mcp`（调用/服务）、`commands`（任务状态/退出码）、`tunnel`（连接事件类别）、`cli`（配置/诊断）、`install`（安装阶段）分类。可用 `--component` 筛选，用 `--request-id` 关联某次工具调用；普通文本和 `--json` 两种显示方式均支持。

默认 **INFO、单文件 5 MiB、每类最多 5 个历史文件、14 天过期策略**；清理在下一次写入时发生，容量上限可能更早淘汰。需要调整：

```bash
local-mcp logs configure --level DEBUG
local-mcp logs configure --level INFO --max-mib 5 --keep 5 --days 14
```

改变设置后重启长驻服务。日志只保留安全事件摘要，**不保存文件正文、命令内容、完整命令输出、图像、配置全文或 ID/key 正文**；Tunnel 日志也只保存识别出的事件类别，不是原始输出副本。导出重新过滤字段，不覆盖已有文件，但仍需审核后分享。日志写入故障会单独报告，不因此重复执行业务写入。

**复制给本机 Codex：**

```text
请用你原有的本机终端工具定位 local-mcp，执行 logs path，并查看相关分类最近 200 条和 ERROR 日志。
结合 doctor，按时间、process_id、request_id/session_id 找出失败阶段及原因。
不要打印 ID/key 或配置全文，不要把缺失日志当作操作未执行而重试写入，不要删除未知锁文件。
需要提供诊断材料时使用 logs export，先审核后分享；不依赖故障中的 MCP 来读其私有日志目录。
```

完整字段、轮转/保留规则、权限与排错方法见 [日志使用说明](docs/LOGGING.md)。`doctor --bundle` 仍仅导出诊断摘要，不自动附带日志。日志管理是本机 CLI 功能，MCP 工具数量不变。

<a id="upgrade"></a>
### 3.7 更新到 main 并升级本机安装

**拉取源码不等于升级已安装的 MCP。** 安装器使用版本化安装目录；更新本机仓库后，还需重新执行安装器，并重启由你管理的 MCP／Tunnel 实例。版本号仍为 `0.4.0`，仅凭 `--version` 不能区分早期源码和包含交互安装、日志的主线源码；请同时记录安装所用的 Git 提交。

**复制给本机 Codex：**

```text
请将本机 chatgpt-local-mcp-tunnel 更新到 origin/main，并升级现有安装。

1. 先定位已存在的仓库并核对 origin 地址、当前分支、提交及未提交修改。不要扫描或输出凭据文件。
2. 从正确远端获取状态。工作区有修改、本地 main 与 origin/main 分叉、存在未完成的合并时，暂停源码更新并说明原因，不 stash/reset/clean/强制覆盖，不删除原分支。
3. 条件满足时切换到 main，并只做快进更新。原 feat/local-mcp-v0.3 分支无需删除，也不再作为安装来源。
4. 阅读 main 的 README、bootstrap.py 和 docs/INSTALL_WITH_CODEX.md。保留用户已选 root、mode、write_roots、文件规则、密钥来源、日志设置、Codex 中其他条目和无关配置。不要因升级自动开启命令或 Git 推送，也不要擅自收回已有明确授权；需要改变权限时先让我确认。
5. 先运行安装计划，再执行对应平台的完整安装器；不要用 core-only 替代已有媒体依赖，也不要覆盖同名但不同的 Codex 条目。已有正确 Tunnel 和凭据优先复用，不把实际值带进聊天或命令参数。
6. 运行 self-test，检查 logs path、logs show；凭据可用时再运行 doctor --with-tunnel。安装器检查失败时，不把它记为升级成功。
7. 提醒我结束并重启自己管理的旧 MCP／Tunnel 进程，刷新 Codex／ChatGPT 的工具列表；不擅自终止未知进程，不建立开机自启。

报告源码提交、安装版本、启动器和配置路径、实际权限开关、日志位置，以及哪些客户端验收完成或仍未执行。不要输出 Tunnel ID/key 正文或尾号。
```

`main` 的合并记录见 [PR #1](https://github.com/macgaf/chatgpt-local-mcp-tunnel/pull/1)。合并只更新 GitHub 源码，不会替用户在本机安装、重启服务或重新授权。

## 4. 详细说明与验证记录

| 文档 | 什么时候看 |
|---|---|
| [编程接口与权限](docs/CODING_TOOLS.md) | 查 Git、命令、检索、批量读取、补丁参数及安全限制 |
| [自动准备 Tunnel 与凭据](docs/AUTOMATED_TUNNEL_SETUP.md) | 自动查找/创建、安全转存、缓存判断和必要人工边界 |
| [安装执行细则](docs/INSTALL_WITH_CODEX.md) | 排查安装步骤、授权及客户端验收 |
| [故障排查](docs/TROUBLESHOOTING.md) | 根据错误码定位原因和恢复办法 |
| [Linux 凭据与用户服务](docs/LINUX_CREDENTIALS.md) | Linux 桌面凭据库、无桌面 systemd 凭据和常驻运行 |
| [非文本文件说明](docs/MEDIA_PIPELINE.md) | 图片、PDF、ZIP、二进制传输及尚未实现的专用适配器 |
| [测试报告](TEST_REPORT.md) | 区分实际测试、替身测试、平台跳过和待实机验收项目 |
| [变更记录](CHANGELOG.md) | 查看版本变化 |

当前测试记录包含三平台自动化测试与真实 stdio 自检；不代表已在你的机器上部署，也不代表原生凭据库、真实 Git 网络推送、Tunnel 认证和 ChatGPT 图片消费已全部实机验收。以对应测试报告及你本机的实际验证结果为准。
