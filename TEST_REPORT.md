# v0.5.2 版本提升（2026-09-30）

按用户要求将日志修复从 0.5.1 提升至 0.5.2，通过 [PR #7](https://github.com/macgaf/chatgpt-local-mcp-tunnel/pull/7) 合并交付。代码行为沿用已完成本机 355 passed／9 skipped 的日志修复；以下候选及 CI 阻塞记录保留原验证时间。合并状态、最终提交与远端检查以 PR 为准；本次版本提升不代表用户现有 0.5.1 服务已更新。

版本提升后复核：协议／日志专项 **37 passed，0.79 秒**，临时 XDG 目录内真实 CLI stdio self-test 通过；源码版本、项目版本、双 README 一致性及 git diff --check 通过。没有把 GitHub 账单／额度阻塞下未执行的任务记为三平台通过。

# Tunnel 日志证据与分类修复（2026-09-29，候选）

基线 main `f890f74`，分支 `fix/tunnel-diagnostic-evidence`，基础版本保持 0.5.1。本段是候选源码验证，不代表现有安装或常驻实例已更新。

最终本机完整回归：**355 passed、9 skipped，116.35 秒，退出码 0**。补充的测试文件读写统一显式 UTF-8。提交 `951d526` 的 push run `36569496343` 与 PR run `36569604481` 六个任务均未开始任何步骤；GitHub 注释明确为账号付款失败或消费额度限制，不能算三平台验证通过。修复保留在 [PR #7](https://github.com/macgaf/chatgpt-local-mcp-tunnel/pull/7) 草稿，未变更账单、合并 main 或替换用户部署。

- 首轮最小复现：请求 ID、耗时、路径及 HTTP 200 正文包含 401/403 的四个案例全部失败；实测证明原分类器将无关数字／正文误认成认证或权限错误。
- 修复两条路径：运行期 `record_tunnel_event` 和失败管理命令 `run_checked` 共用严格证据解析；JSON／logfmt 状态字段、完整错误语法、未知格式、冲突／重复字段分别验证。不扫描响应正文中的关键词来推断失败类别。
- 首轮完整本机回归 **353 passed、9 skipped，114.84 秒**。随后补充原生日志参数及控制面格式支持，相关四组专项 **73 passed、1 skipped**；最后旧标签读回保护的日志／诊断专项 **54 passed，2.07 秒**。这些集合重叠，不相加；最终完整跨平台结果以 PR 的具体提交 CI 为准。
- CLI 真实 stdio self-test 在临时 XDG 配置／状态目录通过，legacy／modern discovery、读回、只读隐藏写工具及目录一致性均通过。首次默认沙箱执行核心自检也成功，但写宿主日志提示 PermissionError；临时目录复测没有该提示，未把日志写入失败当作成功。
- 使用本机原生 tunnel-client v0.0.15、临时 HOME、虚构 key 和回环 HTTP 服务合成 403，未访问真实控制面认证：捕获 **267 行**，**9 个请求／9 条 HTTP 拒绝证据**，关联响应请求 ID 哈希，层级为 control_plane，原始片段为 `controlplane client: unexpected status 403`，明确跨层关联／根因／下游执行仍未确认。落盘摘要不含虚构 key、认证头或响应正文；没有未处理的原生日志文件。
- 原生实测发现 `--log.file stdout` 会创建同名文件；改用空字符串后 JSON 输出进入管道。合成测试生成的旧 `stdout` 文件已删除；运行器显式关闭 HTTP raw 与 Harpoon payload capture，测试同时检查这些参数。
- 真子进程在 stdout 指向 `/dev/null` 时仍产生有请求关联的 `tunnel_diagnostic`；轮转在 16 KiB／2 份历史配置下验证每段上限与文件数量，未知头／payload／URL 不落盘，导出重新过滤。旧认证／权限标签缺少匹配 HTTP 证据时显示 TUNNEL_CLASSIFICATION_UNVERIFIED，原历史文件不改写。
- 仅读取运行中 Tunnel 的 100 条原生事件并在内存投影，确认其请求关联字段及 dispatcher 转发模板；“转发给 MCP”不等于已执行，也不能用这些样本解释未指定的某次线上失败。没有声称真实平台拒绝、真实工具失败或模型拒绝的端到端归因已完成。

# v0.5.1 macOS 原生媒体修复验证（2026-09-28）

修复基于 main `64108d5`，通过 [PR #6](https://github.com/macgaf/chatgpt-local-mcp-tunnel/pull/6) 交付。首个修复提交 `6e51846` 的本机部署仍标为 0.5.0，随后用户再次报告弹窗；以下记录补查原因、增加进程清理以及实际安装并启动 0.5.1 后的结果。

首个修复提交的 [PR CI](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/36398587527) 与 [push CI](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/36398528950) 共六项三平台检查均通过。包含后续进程清理与版本提升的最终跨平台检查以 PR 对应提交状态为准，不能沿用首个提交的结果。

- 原始故障：15:37:29 系统对 `_imaging.cpython-314-darwin` 显示 Gatekeeper 提示，15:37:56 MCP `read_image` 失败。Pillow 已安装，但原生库带 Chrome 来源的 quarantine；旧代码把加载失败报为 DEPENDENCY_MISSING，doctor 只检查模块存在。
- 再次弹窗：16:51:28 系统出现同一旧原生库的提示，16:52:10 旧 MCP PID 的 `read_image` 失败并仍报 DEPENDENCY_MISSING。该进程使用首次安装的 0.5.0，未使用新修复。先前仅确认新实例健康，遗漏了旧进程仍可接受请求，不能据此认为升级切换已完整验收。
- 进程根因：旧 Tunnel 包装器收到 SIGTERM 时未进入 finally，其独立子进程组可残留。真实合成进程测试在修复前失败；增加 SIGTERM／SIGINT 处理后，两个信号均验证包装器及后代退出，不削弱断言。
- 原生依赖专项：首轮 **88 passed、1 skipped**。包含真实 macOS 合成文件隔离属性检查／定向移除／其他属性保留，篡改时不部分放行，符号链接拒绝，官方 wheel 哈希不符拒绝，以及媒体失败时不切换安装指针。
- 最终完整本机回归：`python -m pytest -q`，**331 passed、9 skipped，117.14 秒，退出码 0**。包含新增的两个退出清理用例。本轮未显式启用真实 Codex 会话导入测试；Windows 专用用例在本机跳过，其他平台结果由 CI 单独记录。
- 本机实际安装 `0.5.1-1790586437536521000`：8 个官方 PyPI wheel 校验通过，**27 个原生 `.so`／`.dylib`** 字节与对应 wheel 一致，再定向移除这些新文件上的 quarantine。JPEG 解码、PDF 渲染／文字提取及 ImageContent 自检、真实 stdio self-test 通过后才切换启动器；安装源码与当前源码逐文件一致。
- 仍被独立 Codex 客户端引用的旧 0.5.0 环境，另行按已安装版本下载官方 Pillow／PDFium wheel 并验证，**27 个原生文件**全部匹配后定向移除 quarantine；其真实 stdio 图片与 PDF 读取通过。没有终止那些独立客户端、修改系统 Python 或改变系统安全策略；这次定向修复不是安装器自动修改全部旧环境的功能。
- 仅清理经路径、父子关系和进程组核实的旧服务链，再由原 LaunchAgent 启动 0.5.1。实机向新包装器发送 SIGTERM，其 Tunnel、MCP 与 Tunnel 自己启动的 Codex app-server 均自动退出，未手动补杀；再次启动成功。Tunnel main 通道 `probe_status=ok`，`enable_commands=true`、原 HOME 读写配置及 Git push 关闭状态保留。
- 通过 0.5.1 实际安装启动器的 stdio `tools/call` 调用 `read_image` 和 `render_pdf_page`：合成 JPEG 返回 120×60 ImageContent，PDF 在 `max_edge=320` 下返回 320×160 ImageContent，与先前已查看的红绿蓝色块和“MCP media test”图像哈希一致。此项是本机 MCP 协议与图片内容验证，不冒充 ChatGPT 云端客户端视觉验收。
- 最后媒体调用后检查最近 10 分钟 syspolicyd 日志，没有匹配 `_imaging`、`pdfium` 或 `Prompt shown` 的记录。此结论只覆盖已查时段，不等于对所有未来弹窗的保证。独立 Codex stdio 连接仍需重连才能使用新版本代码。

# v0.5.0 默认开启会话导入与合并验证（2026-09-28）

## 信息一致性复核

基于已合并的 `3fdb870`，核对全部 17 份 Markdown／文本中的本轮能力、默认值、版本、安装和发布状态。修正安装 Skill、README 内嵌安装提示词、Git／排错／自动准备说明的过期事实；标识旧部署记录的时间范围。源码仅修改会话导入禁用时的一条错误原因文案，权限及执行条件不变，版本保留 0.5.0。

实际校验：90 个相对链接及锚点有效；双 README 和电脑工具版内嵌提示词一致；README 44 个工具与实际注册表一致；16 组 mode／Shell／push／history 组合数量吻合；配置样例、版本、AST 和 git diff --check 通过。完整本机回归（包含真实临时 HOME 的 Codex 导入）**318 passed、8 skipped，118.45 秒，退出码 0**；真实 stdio CLI self-test 通过。未重装或重启用户服务。

## v0.5.0 功能合并证据

v0.5.0 已由 [PR #4](https://github.com/macgaf/chatgpt-local-mcp-tunnel/pull/4) 合并到 main，合并提交 `3fdb870337665ad4557b7c3998f295ca48c8fba7`，源码树与已测试 `f0b7b69` 一致。[PR CI](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/36370304235) 和 [push CI](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/36370302098) 六项检查全部通过；PR CI：Ubuntu 318 passed / 8 skipped、macOS 317 passed / 9 skipped、Windows 318 passed / 8 skipped，三平台 CLI self-test 通过。该记录不代表用户现有部署已升级。

用户授权将 Codex 会话导入默认开启、提升版本并在验证后合并 main。源码版本统一为 0.5.0；read_write 默认注册 39 个工具，read_only 仍为 25 个。缺省配置使用新默认值，显式 false 保留；导入不开启模型调用，也不自动导入任何内容。

实际 CLI 在临时 HOME 验证了新建配置默认开启、显式关闭、普通 configure 保留关闭、无需额外确认重新开启。真实 stdio self-test、版本一致性、Python AST、双 README 一致性和 git diff --check 通过。三平台 CI 与合并提交的最终证据记录于 [PR #4](https://github.com/macgaf/chatgpt-local-mcp-tunnel/pull/4)。本轮没有安装或重启用户现有服务。

## macOS 安装弹窗根因及修复

默认值变更后的首次专项为 124 passed、6 skipped、1 failed；失败仍在安装测试。用户截图与 syspolicyd 日志对应同一临时 `versions/0.5.0-.../venv/bin/python`：日志明确出现 Prompt shown 和 Gatekeeper denial。副本与 Homebrew Python 3.14.6 的 SHA-256 相同、codesign 验证通过，但副本额外带 `com.apple.quarantine`（来源 Chrome），基础解释器无此标记。这给出了前期安装超时／-9 的具体解释，不再笼统归为未知环境问题。

bootstrap 改为 POSIX 使用 `EnvBuilder(symlinks=True)`，Windows 保留复制。真实安装／重装测试在同一 Chrome 宿主环境 2.01 秒通过，同期系统日志无新 Prompt shown；新增断言验证两次安装均链接基础解释器，并验证默认开启及重装保留显式关闭。没有执行 xattr 清除、重新签名、关闭 Gatekeeper 或永久放行。系统弹窗 UI 读取超时，未宣称已操作关闭旧提示。

修复后完整本机回归：`LOCAL_MCP_TEST_CODEX_HISTORY=1 .venv/bin/python -m pytest -q`，**318 passed、8 skipped，121.35 秒，退出码 0**。包含真实临时 HOME 的 Codex 导入读回，以及此前失败的离线安装／重装；没有排除或弱化失败用例。

以下保留功能开发阶段的实际结果与失败记录；其中“候选／未合并／版本保持 0.4.1”为当时状态，不是 v0.5.0 的版本声明。

# linked worktree 与 FileMCP 能力补齐候选（2026-09-28）

分支 `feat/linked-worktree-filemcp`，基线 `e7542ebb28ebd228907be078ac90265e4f7a3abb`。独立克隆内修改；基础版本保留 0.4.1，未修改现有 MCP 安装、配置、凭据、自启或在线进程。

## 本机实际结果

- `da219a9` 的 PR CI run 36342227000 三平台通过（Ubuntu 317/8、macOS 316/9、Windows 317/8，分别为 passed/skipped）；同提交 push run 36342224608 Windows 为 316 passed、8 skipped、1 failed，唯一失败是原有日志跟随测试少读一条。测试在 `tail=0` 初始快照完成前开始写入，记录可能被视为旧记录跳过；改为用事件等待空快照完成再写入，仍要求 70 条全部且唯一，并逐次检查写入成功。本机日志专项 30 passed；修正后的跨平台结果以 PR 最终 CI 为准。

- 新文件/Git/搜索/协议专项：50 passed，退出码 0（依赖补齐后的记录）。
- 完整集合：`LOCAL_MCP_TEST_CODEX_HISTORY=1 .venv/bin/python -m pytest -q --tb=short`，315 passed、6 skipped、1 failed，145.66 秒；退出码 1，不能称为完整本机验收通过。
- 唯一失败为 `test_real_offline_install_and_reinstall`：临时安装器 30 秒超时。相同测试在未修改 origin/main 的独立源码副本也超时；临时安装的复制型 Python 连 `-V` 探针也曾返回 -9。沙箱外复测仍超时，准确 OS 根因未确认，没有归因为本轮代码，也没有修改安装器或弱化断言。
- 真实 CLI `python -m home_readonly_mcp.cli self-test`：在临时 HOME 执行，退出码 0；legacy handshake、modern discovery、read roundtrip、只读隐藏写工具、目录指纹一致性全部通过。
- Codex 0.157.0 实际 app-server：临时 HOME 新建会话、写入中文 user/assistant 消息、新进程 resume/turns-list 逐条一致；未调用模型。该真实测试显式由 LOCAL_MCP_TEST_CODEX_HISTORY=1 启用，普通 CI 没有 Codex 时跳过，不将替身验证算实机。
- Python AST、两份 README 一致性和 git diff --check 通过。

最后 Git 路径权限预检与 Codex 子进程组清理改动后，Git／linked worktree／Codex 导入／文件／搜索／协议相关复测为 **150 passed in 103.52s**，退出码 0，包含真实 Codex 导入。文档及 onboarding／协议／交互配置相关检查为 **45 passed、1 skipped、1 deselected**（显式排除上述安装环境失败项），退出码 0。各轮重叠用例不相加。远端三平台 CI 以本候选实际提交为准；不用历史 main 的 CI 代替。

## 首轮远端 CI 与夹具修订

代码提交 `b71bdea698b8416847fd639a354343fe5bde7d52` 的 [Actions run 36341050300](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/36341050300) 中 Ubuntu、macOS 的完整 pytest 和 self-test 通过，包含本机失败的安装测试。Windows 为 310 passed、8 skipped、4 failed：两项新增夹具使用系统默认编码读取 UTF-8 中文，两项使用 CREATE_ALWAYS 覆盖 Git 创建的隐藏 .git 文件而被 Windows 拒绝。改为显式 UTF-8 读取、r+b 原地改写测试指针；另沿编码路径检查了备份恢复：备份元数据本来写为 UTF-8，现在显式按 UTF-8 读取，新增中文文件名删除／恢复回归；会话 journal 读取也显式指定 UTF-8。权限检查不变，修订后以新提交 CI 为准。

修订 `5acc87b` 的两轮 CI 中，新夹具及中文文件名恢复均通过；Windows 各剩一个相同的旧 Git 测试失败，日志为快速 Git 进程已经退出 0、AssignProcessToJobObject 返回 WinError 5。没有跳过该断言或去掉 Job 隔离：后续改为 CREATE_SUSPENDED → Job 绑定 → 验证主线程归属并 ResumeThread，绑定失败则终止挂起进程；新增 Windows 专用测试人为延迟 Job 绑定并验证命令在绑定前不执行。macOS/Linux 不走该路径。后续 CI 结果以包含此修复的提交为准。

本机既有 `chatgpt-local-mcp-tunnel-fix-git-capabilities-20260927` 工作树也由新代码在 read_only 策略下真实读取成功：分支 `fix/git-capabilities-20260927`，HEAD 为 `f6ef1641ebf690f6d435932ca02c8b63ff174560`，无状态条目及截断；未修改该工作树。

## 覆盖与边界

真实 Git linked worktree 的 status/log/diff/add/commit/create/switch、独立索引、共享 lease、主库写权限、root 外拒绝、相对 gitfile、工作树配置、反向关联、危险配置及对象 alternates；普通仓库已有回归继续运行。

文件追加的哈希冲突、大小限制及备份；删除的预览、备份恢复、目录清单冲突、受保护条目整批拒绝、部分失败清单；搜索类型、跨行、前后独立上下文、brace glob 和单文件路径；Codex 独立开关、启用确认、请求去重、失败不重试、只写新历史及真实读回。

没有真实网络 Git push、用户现有 Codex 历史写入、用户安装升级或 Tunnel/ChatGPT 新工具目录验收。候选源码通过不等于在线服务升级。比较范围与语义差异见 [FILEMCP_PARITY.md](docs/FILEMCP_PARITY.md)。

---

# v0.4.1 合并与部署补记（2026-09-27）

用户明确授权合并、重新安装和重启后，PR #3 已合并为 `2bb42104b5091a68d1b31f6954ed157db1f299aa`，合并树与三平台测试通过的 `f6ef1641ebf690f6d435932ca02c8b63ff174560` 一致。安装复制的20个 Python 文件与该源码逐一一致；通过现有 LaunchAgent 重启后，ChatGPT 真实调用 policy_info 已返回0.4.1 / 36个服务端工具，git_status 原故障项目成功，临时文件真实写入和读回哈希一致。完整部署范围、配置保持及客户端目录待刷新事项见 docs/DEPLOYMENT_20260927.md。以下保留修复开发时的原始记录，不把当时尚未部署的描述当作当前状态。

---

# v0.4.1 分支接口、工作树配置与能力诊断（2026-09-27）

候选分支：`fix/git-capabilities-20260927`。基于 main 的 `6170439d25b7f4d64e833347aeb99ba0a61c96ac`，在独立工作树修改源码，原 main 不切换、不合并。版本提升至 0.4.1，但本次没有安装、重启在线 MCP/Tunnel，也没有调整 root/mode/write_roots、Shell、推送或凭据设置。

## 本机实际验证

通过已授权 FileMCP 在用户 macOS、Python 3.14.6 环境运行，业务测试使用合成仓库与临时 HOME。

| 验证 | 实际结果 |
|---|---|
| 第一版 Git/协议专项测试 | 96 passed，退出码 0；其后又补充了子模块边界与真实 stdio 测试 |
| 完整 pytest 首轮 | 286 passed、6 skipped、2 failed，退出码 1；没有把失败算作通过 |
| 修订后的本机回归 | 287 passed、6 skipped、1 deselected，退出码 0，107.57 秒；仅单独排除下述环境受限项，不称为本机完整集合通过 |
| 真实 CLI stdio self-test | 退出码 0；legacy handshake、modern discovery、读取回环、只读隐藏写工具及 capability_catalog_consistent 均通过 |
| Python/文档静态检查 | src/tests 全部 Python AST、两份 README 一致性、正式提示词一致性、git diff --check 通过 |
| 原故障项目只读验证 | 新代码的 git_status 已成功；Git 配置文件读前读后哈希一致，没有修改该项目。该项目当时存在的工作区变更保持原状 |

首轮两个失败的处理：

1. README.md 与 README_zh.md 的第 3.1 节在基线提交中已经不同。按 docs/prompts/setup-with-computer.txt 正式入口同步两份说明，保留后续自启说明及敏感值不经工具参数转发要求；对应测试复测通过。这是文档同步，不是实际扩大账号或 MCP 权限。
2. `tests/test_service.py::test_crossprocess_lock_and_stale_recovery` 的锁断言通过，但其合成子进程在 `terminate()/wait(5)` 阶段超时。只读检查确认 FileMCP 启动的进程继承了包含 SIGTERM 的阻塞信号集。没有绕过宿主拒绝去修改信号设置，也没有削弱或删除该测试；本机复测显式 deselect 此一项。独立 GitHub Actions 仍执行原样完整集合，结论须以本修复提交的实际结果为准。

## 最后边界复核补充

首次代码提交为 `7b3d8460cc123c1fa1def4ca45c7075f7d663478`。之后在合成仓库中确认 core.worktree 的同目标符号链接别名仍可通过，于是增加规范化路径与真实路径双重一致检查，并拒绝任何链接路径组件；没有仅因最终 resolve 相同而接受可变别名。

补充两个别名回归案例后，执行 `pytest -q tests/test_git_capabilities.py -k worktree`，结果 **25 passed、48 deselected in 23.55s**，退出码 0。这是针对性复测，不与上表重叠用例相加，也不冒充完整集合。最终远端验证必须检查包含此收紧修复的新提交，不能把前一提交的 CI 当作最终版本结果。

## 覆盖的安全边界

关闭 Shell 时创建和切换分支；分支名/HEAD 预期检查；拒绝脏工作区、未跟踪受保护文件、现有锁、未完成 Git 操作、隐藏修改的索引标记和子模块索引；保护忽略文件及其他工作树占用的分支；目标检出路径策略、符号链接/gitlink/超大对象拒绝；hooks 不执行。

普通仓库 extensions.worktreeConfig 的 true/false/数值布尔语义、可选 overlay、提交身份合并、原配置不改写；危险 include/filter/credential/外部 worktree 路径继续拒绝；符号链接/硬链接/FIFO/超限配置拒绝；畸形配置错误不泄露值。

工具目录/指纹与真实注册表一致；只读/读写/命令/推送矩阵；Git 失败与文件写权限分开；batch_read 不接受分支写操作；真实独立 stdio 子进程完成创建/切换分支。

## 尚未验证和明确不支持的事项

本文件初次提交时远端三平台 CI 尚待本提交触发，不沿用历史成功记录；后续结果以相应 commit/run 为证据。真实 Tunnel/ChatGPT 工具目录刷新、用户安装更新、网络推送工具的实机测试不在上述合成测试范围。

`.git` 为 gitdir 重定向文件的 linked worktree / submodule 仍不受新 Git 工具支持；本次解决的是普通仓库的 config.worktree 误拒绝。CLI doctor 的目录摘要是新诊断实例，不冒充在线 Tunnel。详细用法及部署边界见 docs/GIT_CAPABILITIES.md。

---

# 电脑工具提示词与仓库同步核验（2026-09-26）

本次基于 main 的 24ffe848087410b70eb3dfb2d3f1625bd237757c 补交电脑工具版提示词、更新配套文档，并在 AGENTS.md 记录默认 GitHub 同步约定。只改文档与提示词，未修改运行代码、测试实现、依赖、权限或部署。

通过已授权 FileMCP 在用户 macOS 上的独立文档 worktree 执行，业务测试使用临时 HOME 和合成资源：完整 pytest 为 **217 passed、6 skipped in 34.81s**，退出码 0，已读完输出；跳过为平台专用测试，不算通过。测试启动进程解除自身继承的 SIGTERM/SIGINT 阻塞，不更改宿主或测试断言。

两份 README 内容一致，README 第 3.1 节与 docs/prompts/setup-with-computer.txt 完整提示词一致；58 个相对链接／锚点和 Markdown 代码围栏检查通过，git diff --check 通过。

候选浏览器执行器仍位于 PR #2；本次未将其代码合并到 main，未操作真实 Tunnel/key 或更改本机安装。以上结果不是本次远程 CI 或网站自动化实机验收；旧报告保留原日期与验证范围。

---

# 主线整合核验（2026-09-25）

安装来源统一为 `main`，功能整合记录见 [PR #1](https://github.com/macgaf/chatgpt-local-mcp-tunnel/pull/1)。本次仅更新文档与合并历史，保留功能分支；没有修改运行时代码、测试、依赖、工作流、版本号或用户本机配置。

## 合并代码基线与三平台证据

包含交互安装和持久日志的代码提交：`3850b34bd45533da28fe34b241414c6c4bd8c003`。源码树：`d6022a0eb782fa5863fbb6b99dce098a1b2d4bf6`。已对本轮使用的源码副本重算 Git tree，确认与该基线一致后再修改文档。

本次重新读取了 [Actions run 36024605104](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/36024605104) 的 Jobs API，确认：

| 系统 | pytest | 真实 stdio self-test | Job ID |
|---|---|---|---|
| Ubuntu | success | success | 107717828722 |
| Windows | success | success | 107717829101 |
| macOS | success | success | 107717829154 |

完整测试集为 223 个用例，各平台专用 skip 不计入通过数。下面的日志修订报告保留了原本地 218 passed、5 skipped 的分组记录。这些结果归属于上述代码提交，不能说成在用户机器上执行的测试。

## 文档核验范围

两份 README 同步；主线安装提示词不再包含“main 未包含时使用功能分支”的回退指令。安装细则、Skill、排错和变更记录同步主线来源，并保留目录／模式交互确认、凭据本机隐藏输入、日志入口和安全升级边界。检查 Markdown 相对链接／显式锚点、38 个工具名与注册表一致；验证改动仅为 Markdown，原运行代码及工作流未改。

GitHub 合并和重新安装是不同操作；本轮没有执行用户本机安装、原生 keystore、真实 Tunnel/ChatGPT 或 MCP Git 网络推送验收。后续 Actions 结果以对应提交／合并提交的实际运行记录为准。

---

## 以下为各次修订的历史记录

# 持久日志修订验证（2026-09-24）

基线为 `f2a9533f8860d0de4d3b0870a4925129ebf732ad`；从附件解出的全部源码已重算 Git tree，与远端 `9ba000c01c26e86d77901a8f645c573d7dd718ad` 完全一致，再开始修改。

新增本机日志存储与访问入口，未改变 38 个 MCP 工具及权限默认值。新增 30 个日志测试，连同原有测试共 **223 项用例**。

## 本次实际完成的本地验证

| 不重叠分组 | 实际结果 |
|---|---|
| 日志、路径、文件与媒体 | 110 passed |
| 安装、交互录入及协议 | 47 passed |
| 命令、Git、跨文件补丁 | 45 passed、5 个 Windows 专用 skipped |
| 代码检索与批量读取 | 16 passed |
| 合计 | **218 passed、5 skipped** |

全部在隔离 Linux 开发容器中运行；真实 stdio self-test、compileall、安装脚本语法检查和 README 相对链接检查通过。两个 README 内容一致。一次大分组因执行工具 45 秒上限中断，不计为通过；上表使用重新完成的不重叠分组。

日志测试实际覆盖：JSONL 文件写入、大小轮转和过期、线程/多进程并发、轮转后跟踪、新出现文件、级别/请求 ID 筛选、脱敏导出及拒绝覆盖、符号链接/硬链接拒绝、真实 CLI 和 stdio 生命周期、真实命令结束事件。磁盘满使用失败注入，确认不污染 stdout、不打印敏感异常原文、不影响或重复文件写入。

持久日志不保存请求/响应正文、命令内容/完整输出、配置全文或凭据；错误只保留安全分类和已知原因。对人工修改的日志，查看/导出仍重新过滤字段。Tunnel 输出分类用合成消息测试，不是使用真实凭据的云端验收。

本修订的三平台远程 CI 必须以本修订提交的实际 Actions 结果为准，不能沿用下面历史提交的通过状态。用户目标机器安装、原生 keystore、真实 Tunnel/ChatGPT 连接未执行。日志不是防篡改/零丢失审计系统；满磁盘等故障会告警并可能缺记录，业务操作仍可能成功。

---

# 交互安装修订验证（2026-09-24）

在原 v0.4.0 基础上调整通用安装提示词，新增 `local-mcp tunnel configure`，加强 ID/key 隐藏输入与脱敏。MCP 工具列表和权限默认值不变，目录/模式在 Codex 安装前由用户交互选择。

本次本地 Linux / Python 3.13.5 验证：**188 passed、5 个 Windows 专用 skipped，共 193 个用例**。按三个不重叠分组完成：

| 分组 | 结果 |
|---|---|
| 交互录入、安装配置、协议 | 47 passed |
| 路径、文件、媒体、检索/批量 | 96 passed |
| 命令、Git、跨文件补丁 | 45 passed，5 skipped |

新增 15 个用例涵盖实际 POSIX PTY 不回显、保留已有 ID、不覆盖无关配置、取消/非法输入、无 TTY、getpass 无法关闭回显时拒绝明文回退，以及 ID/key/派生 profile 名称脱敏。系统凭据库用内存替身，无用户真实密钥。新用例及相关回归已运行；真实 stdio self-test、编译、Shell 语法检查通过。

首次整套测试被开发容器单次 45 秒执行上限中断，没有计作通过；上述三个分组才是完成的验证。此次修订的远程三平台 CI 需另查提交记录；以下历史报告的通过状态只属于原提交，不能冒充本次新代码的远程结果。用户本机安装、真实 keystore、Tunnel 认证仍未执行。

---

## 以下为原 v0.4.0 历史记录

# v0.4.0 最终验证记录

日期：2026-09-24。代码验证提交：`36fda0964bdd2229c3c961ed0dd09a46c989e9b8`；代码及测试树：`43bae7169acf8f7a6e65baed5df77c91b8486652`。本报告与说明文件的后续提交不修改这份已验证运行时代码。

## 最终结果

共有 **178 个用例**。不同操作系统按适用性跳过专用用例，不将 skip 算作通过。测试在隔离 Linux 开发容器和 GitHub Hosted Runner 上执行，不是用户目标机器。

[最终三平台 CI：run 35982777237](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/35982777237)

| Hosted Runner | pytest | 真实 stdio self-test | Job ID |
|---|---|---|---|
| macos-latest | success | success | 107578369436 |
| ubuntu-latest | success | success | 107578369531 |
| windows-latest | success | success | 107578369592 |

上述结果已从 GitHub Jobs API 真实读取。Windows 最终不是靠跳过命令失败用例通过；原始非零退出码断言保留，新增 PowerShell 测试还要求 `state=exited`，防止超时恰好返回预期非零值而误通过。

本地 Linux 按不重叠分组验证：**173 passed，5 个 Windows 专用用例 skipped**。

| 分组 | 结果 |
|---|---|
| Git、跨文件补丁、协议 | 43 passed |
| 路径策略、文件服务、媒体、代码检索与批量读取 | 96 passed |
| 安装、凭据与 Tunnel 管理 | 19 passed |
| 命令会话及退出码 | 15 passed，5 skipped |

`compileall`、安装 Shell 脚本语法检查及真实 stdio 自检通过。开发工具有单次执行时限，所以本地分组运行；远程 CI 运行完整 `pytest -q`，未把被中止的本地测试进程算作成功。

## 真实执行覆盖

- 本地 Git init/status/log/diff/add/commit；禁用 hooks/外部 diff，拒绝不安全 include/filter/alternates/gitdir 及敏感暂存路径。
- 完整编程流程：创建有缺陷的函数和测试 → workspace_context/search_code/batch_read → 跨文件接口修复 → run_command 实际执行测试 → git_diff/add/commit。
- 实际命令进程的文件写入、退出码、取消、超时、输出游标与淘汰、请求去重、相交工作区门控、EOF/服务退出和后代清理。
- 正则独立 worker 的实际超时、忽略文件、字面/声明/标识符排序、扫描预算和批量读取错误处理。
- 跨文件预检、多锁、dry-run、失败注入回滚、外部新修改不被回滚覆盖、旧单文件参数兼容。
- 继承的图片解码、PDF 渲染、ZIP/二进制传输、SHA 冲突、备份恢复、路径保护及离线安装回归。

## Windows CI 发现及处理

1. [首轮 run 35981498872](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/35981498872)：macOS/Ubuntu 通过；Windows 原生命令退出码 7 被 PowerShell 折为 1。运行器增加最终状态捕获和显式退出码传递，并新增 0/3/19、PowerShell 错误、显式退出和恢复场景。
2. [回归 run 35982168767](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/35982168767)：原生命令用例通过，但纯 Write-Output 场景仍失败。原断言没有显示完整状态，不能仅凭退出码把原因断言为超时。之后显式设置内置模块查找路径、增加结果诊断，并要求正常 exited 状态；PowerShell 专用启动测试显式给 90 秒预算，运行器默认短任务预算和真实超时测试没有放宽。
3. 最终 run 35982777237 三平台全部通过。不要把此结果扩大为“任意 Windows 机器首次 PowerShell 模块加载必然在默认 30 秒内完成”；较慢环境可显式增加 timeout_seconds 或用 start_command。

## 模拟与尚未完成的外部验收

Git push 最后的网络发送为替身检查，只验证开关、精确远端白名单和固定 refspec；**没有使用用户凭据向真实远端推送项目**。本轮向 GitHub 提交本工具源码，是授权的 GitHub 连接器操作，不是这个新 MCP git_push 的端到端验收。

OS keystore/Codex 注册/Tunnel 配置部分仍有替身测试。用户真实 Mac/Windows 安装、系统原生凭据库、Linux Secret Service/systemd daemon、真实 Tunnel 认证和 ChatGPT 图片消费、完整 MCP 一致性测试，仍需要目标环境验收。

Shell 是显式启用的非沙箱执行，文件 deny/root 不限制任意命令实际访问的文件或网络。跨文件补丁是整批预检、逐文件原子替换、失败尽力恢复，不是多文件/崩溃原子事务。Git 安全模式明确不支持所有特殊 worktree/LFS 布局。测试通过不等于不存在漏洞。

## 历史记录

[v0.3 原始测试报告](https://github.com/macgaf/chatgpt-local-mcp-tunnel/blob/018a86dfacc4302a6dd636571f429289ae334011/TEST_REPORT.md) 保留了 112 项本地测试及此前三平台 CI 的完整结果。本次为在该版本基础上的功能扩展。
