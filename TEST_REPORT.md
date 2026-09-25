# 浏览器安全转存修复：本机验证记录

本轮针对失败执行记录补充了真正的本机 `tunnel prepare` 入口；不是再次仅改安装提示词。修改在 `fix/browser-tunnel-preparation` 分支进行，基线为 `24ffe848087410b70eb3dfb2d3f1625bd237757c`。

## 已实际验证

执行位置为用户的 macOS Apple Silicon 机器，通过已授权 FileMCP；Python 3.14.6。测试使用临时 HOME、虚构资源和虚构凭据，不创建真实云端 Tunnel/key。

- 新增 37 项浏览器/准备阶段测试，全部通过；总计 260 个用例。
- 完整 pytest：**254 passed、6 skipped in 51.27s**。跳过包括五个 Windows 专用用例及 Linux-only systemd 用例，不计作通过。
- 真实 stdio 子进程 `local-mcp self-test`：通过；Python 编译检查通过。
- 在本机 native macOS Keychain 进行了虚构值写入、读回比较和测试条目删除：通过。不是内存替身。
- 官方 Chrome DevTools MCP 私有子进程能够完成 initialize 和 tools/list；实际 list_pages 返回 `CHROME_DEBUG_ENDPOINT_MISSING`。Chrome 主进程存在，但官方 autoConnect 无法找到调试端点。
- 已打开 Chrome 的 `chrome://inspect/#remote-debugging` 页面供本人确认，没有代替用户启用调试或授予系统权限。

新增测试覆盖私有 stdio 原始数据不返回模型、禁止文件转存/截图、真实选中状态与点击数区分、所有最小权限条件、无授权不提交、创建不明不重复、保存失败恢复原弹窗、无关弹窗不导入、旧绑定不覆盖、keystore 来源不迁移、返回错误不泄露凭据以及实际绑定配置。

## 发现并处理的回归问题

首次完整运行是 247 passed、6 skipped、2 failed，未记作通过：

1. 上一次文档改写遗漏了旧测试要求的“不通过工具参数转发输入”表述；两份 README 同步恢复并保留实际安全语义。
2. 本机 FileMCP 的 GUI 启动环境继承了阻塞 SIGTERM 的 POSIX 信号掩码，原有跨进程锁测试的子进程因此不能按预期退出。用独立虚构子进程复核后，完整测试仅在测试启动进程中解除 SIGTERM/SIGINT 阻塞，未修改断言、超时或宿主设置。新浏览器进程也使用自己的 exec 包装器复位这两个信号，不改变 FileMCP/Chrome。

完整 pytest 已退出成功，但后接 shell 脚本使用 zsh 只读变量名 status 使包装命令报错；随后单独执行 stdio self-test 和编译检查成功。本报告不把该 shell 包装器错误隐藏成整个命令成功。

## 仍未完成，不能宣称成功

- 当前 Chrome 调试连接批准及真实浏览器→keystore 虚构值端到端探针仍未通过；只有 native keystore 检查通过。
- 新网页布局适配器未在当前真实创建表单上完成验收。无法验证控件或权限时明确失败，不能声称“点击即成功”。
- 没有新建/修改/撤销真实 Tunnel 或 API key；没有运行使用真实 key 的认证请求；没有抢占正在运行的 FileMCP Tunnel。
- 没有替用户更改 root、只读/读写、Shell/Git 推送开关，也没有部署常驻 MCP 或添加自启动。
- 新增代码的 Linux/Windows 原生浏览器和凭据库、当前修复提交的远程 CI 尚未作为通过证据。下面原主线的测试记录只属于历史版本。

本机源码及开发虚拟环境已建立，可从项目 `.venv/bin/local-mcp` 运行新入口；这不等于全局启动器、Codex 注册或 ChatGPT 连接已完成。

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
