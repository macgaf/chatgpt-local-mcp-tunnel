# Changelog

## v0.5.2 Tunnel 日志证据与分类修复 — 2026-09-30

- 认证／权限分类改用明确 HTTP 状态字段及完整错误语法，修复任意文本包含 401/403 的误判；非零退出与 HTTP 拒绝分别记录。
- Tunnel 输出在重定向前持久化有界安全诊断，沿用日志轮转／保留设置；保留请求哈希、已报告层级、白名单错误片段与未知项，丢弃认证头和完整负载。
- 安装及排错说明、Skill 统一按请求、到达层级、原始错误、无法确认事项给出结论。版本从 0.5.1 提升至 0.5.2，源码变更不代表现有实例已更新。

## v0.5.1 macOS 原生媒体验收修复 — 2026-09-28

- macOS 完整安装校验官方 PyPI wheel SHA256 与安装后的原生库字节，仅定向处理新环境内原生库的 quarantine；不修改系统安全策略。
- 新增 `media-self-test`，实际 JPEG 解码、PDF 渲染／文字提取和 ImageContent 校验，完整安装通过后才切换版本；doctor 同步检查。
- 媒体按需加载前检测隔离标记，区分缺失、被隔离和加载失败；完善错误日志、安装说明和 Skill。版本从 0.5.0 提升至 0.5.1；不改变现有权限默认值。
- Tunnel 包装器处理 SIGTERM／SIGINT 并清理本次启动的进程组，避免升级重启后旧实例继续接收请求；补充新旧实例核验和独立客户端重连说明。

## v0.5.0 说明同步 — 2026-09-28

- 修正安装 Skill、排错表及 Git 说明中的旧 linked worktree 限制／候选状态；对齐当前主线。
- 安装提示词改为读取实际主线版本；补齐会话导入默认值、显式关闭保留及 Skill 不随 MCP 自动安装的说明。
- 工具数量以注册表和当前配置为依据，历史部署单独标识；补齐删除、导入与 Python Gatekeeper 的排错入口。
- 修正会话导入禁用时的过期 opt-in 错误原因；执行条件不变。版本继续为 0.5.0，不重装或重启现有服务。

## v0.5.0 linked worktree 与 FileMCP 能力补齐 — 2026-09-28

- Git 解析并验证标准 linked worktree，common dir 共享锁，当前工作树状态检查和配置解析；root/write_roots 不扩大。
- 新增带备份及哈希前置条件的 delete_file/delete_directory；文本追加保留并发保护。
- 搜索增加类型、跨行、独立前后上下文、单文件范围和不区分大小写的 brace glob。
- 新增默认开启、可独立关闭的 Codex 会话导入（仍要求 read_write；显式 false 配置继续保留）；新建会话、读回验证、持久 request_id 去重，不调用模型。
- Windows 子进程先挂起、加入 Job Object 再恢复，修复快速 Git 子进程退出早于 Job 绑定的时序问题。
- POSIX 安装 venv 使用已安装 Python 的符号链接，避免 Chrome 宿主给新建可执行副本附加 quarantine 后反复弹出 macOS Gatekeeper 提示；Windows 保留复制方式，不修改系统安全设置。
- 版本从 0.4.1 提升至 0.5.0；源码更新不自动升级现有部署。完整差异和验收边界见 docs/FILEMCP_PARITY.md、TEST_REPORT.md。

## v0.4.1 分支操作与能力诊断 — 2026-09-27

- 已通过 PR #3 合并至 main（`2bb42104b5091a68d1b31f6954ed157db1f299aa`），并完成本次授权机器的安装和服务重启；客户端新增工具目录刷新仍需单独完成，详见 docs/DEPLOYMENT_20260927.md。

- 新增 git_branches / git_create_branch / git_switch_branch；分支创建和切换不依赖 Shell，不提供 force/reset/远端猜测。
- 普通仓库支持经安全检查的 extensions.worktreeConfig 和 config.worktree；保留 include/filter/凭据、链接、裸仓库、外部对象库等限制，linked worktree gitfile 仍未支持。
- 分支切换检查干净工作区、进行中的 Git 操作、索引隐藏标记、子模块、受影响路径与目标对象，保护忽略文件并核查最终 HEAD。
- policy_info / diagnose / workspace_context / CLI doctor 提供分层能力证据；工具注册和诊断共用启用条件，返回目录指纹并明确客户端可见性未验证。
- 工具数变为只读 25、读写且命令/推送关闭 36、全部显式开启 41。默认权限、运行配置、凭据和用户安装不变。
- 真实合成 Git 与 stdio 验证记录见 TEST_REPORT.md；源码候选分支同步不代表已合并、部署或完成云端验收。

## v0.4.0 提示词与 GitHub 同步约定 — 2026-09-26

- 补交电脑工具版完整提示词至 docs/prompts/setup-with-computer.txt，并同步两份 README 第 3.1 节、安装细则、自动准备说明和安装 Skill。
- AGENTS.md 记录默认要求：本项目相关变更须落库、提交、推送并核对远端，不能只交付聊天或附件；明确不自动合并未验收的草稿 PR。
- 文档标明 tunnel prepare 候选程序在 PR #2，与 main 的文档同步、实机验收及部署分开；不修改运行代码、版本或权限。

## v0.4.0 主线整合 — 2026-09-25

- 将 `feat/local-mcp-v0.3` 的编程、媒体、交互配置与持久日志修订整合到 `main`，安装入口统一为主线；保留功能分支历史。
- 两份 README、安装细则、安装 Skill 和排错说明统一更新；增加安全切换 main、快进更新及重新安装提示词。
- 合并及文档修改不改变程序版本、38 个 MCP 接口、权限默认值或用户本机安装。
- 运行代码基线 `3850b34` 已通过 macOS／Ubuntu／Windows CI（run 36024605104）；本次文档核验与该代码测试分开记录，见 TEST_REPORT.md。

## v0.4.0 日志修订 — 2026-09-24

- 新增五分类 JSONL 持久日志、跨进程锁协调、大小轮转与按文件过期清理。
- 增加本机 logs path/show/follow/export/configure；支持级别/请求 ID 筛选、轮转跟踪和不覆盖导出。
- 接入 MCP、命令任务、Tunnel 事件分类、CLI/doctor 和 bootstrap；不记录正文/命令原文/原始输出或凭据。
- 日志写入失败单独告警，不使已完成业务操作重试；doctor 显示日志设置与写入状态。
- README 增加第 3.6 节及 docs/LOGGING.md；未新增远程日志工具，不改变 38 个工具与现有权限。

## v0.4.0 交互安装修订 — 2026-09-24

- README/安装提示词不再指定个人项目目录；以 ~/ 为默认候选，用户先选择目录及只读/读写和可写范围。
- 新增本机 `tunnel configure`，隐藏录入 Tunnel ID；key set 共用严格隐藏输入，无法关闭回显时停止。
- 本工具输出脱敏 ID/key 及含 ID 尾号的 profile 名称；ID仍按需存本地受保护配置，不承诺底层系统无痕。
- 同步中文 README、安装 Skill、Linux 凭据与故障说明；不改 38 个 MCP 接口和权限默认值。
- 本地回归 188 passed、5 Windows 专用 skipped；实机凭据/云端认证未测试。

## 0.4.0 — 2026-09-24

- 共178项用例，三平台 pytest 与真实 stdio 自检通过；详见 TEST_REPORT.md。
- 根据真实 Windows CI 保留原生命令退出码，显式设置内置 PowerShell 模块路径，并区分正常失败与超时。

- 新增七个固定 Git 接口；安全参数、元数据检查和路径过滤，push 独立授权及远端白名单。
- 新增默认关闭的命令执行、去重请求、长任务/输出游标/取消/超时与自有子进程清理；仅相交工作区门控，不使用全局活动命令锁。
- 新增 glob/grep/search_code/repo_overview/workspace_context；Python re 在超时隔离进程中运行，pathspec 遵循忽略规则。
- 新增最多 16 项 batch_read，固定只读白名单、预校验、逐项错误与响应预算。
- apply_patch 扩展跨文件 changes，原 SHA 必填、整批预检、确定序多锁、备份和尽力回滚；保留旧参数。
- 更新安装依赖、权限开关、工具清单和完整编程接口文档。
- 不将 Shell 冒充 OS 沙箱；不宣称跨文件/崩溃原子性或已真实远端 push 验收。

## 0.3.0 — 2026-09-24

- HOME 默认只读，支持项目 root、read_write、write_roots；配置/密钥管理不作为远程 MCP 工具暴露。
- 新增文本/二进制写入、精确编辑、单文件 patch、目录创建、备份与恢复；原 SHA 校验、单文件原子替换、写后验证。
- 新增 ImageContent、EXIF/裁剪、PDF 文本/页面预览、ZIP 成员读取、EmbeddedResource 分块和视觉链路探针。
- 新增 macOS/Windows/Linux native keyring 后端及显式 systemd credential 来源，失败不明文回退。
- 新增结构化错误、按文件跨进程 lease、原因/修复步骤/请求 ID；不沿用 FileMCP 的全局活动命令门控。
- 新增三平台 bootstrap、稳定 launcher、版本化安装、旧配置迁移、Codex 幂等注册、官方完整 Tunnel 发行包校验与 profile 隔离。
- 新增分层 doctor、诊断 bundle、安装提示词/Skill、Linux 服务与非文本适配器设计文档。
- 核心 stdio 改为标准库实现，移除未在旧容器完成运行验收的 MCP SDK 依赖。Python 最低要求升为 3.11。
- 旧 .env.example 等通配符 force_allow 不再自动放行；迁移只保留具体文件例外。敏感文件保护与路径约束收紧。
- 112 项隔离测试通过；外部客户端/OS 原生凭据库验收状态见 TEST_REPORT.md。

- 根据实际 Windows CI 修复 UTF-8 子进程解码、跨平台换行样本与 systemd 平台范围；保留原文件 CRLF，不通过文本规范化破坏哈希/内容。
- 修复提交在 GitHub Hosted macOS、Ubuntu、Windows 的测试与真实 stdio 自检均通过，目标机及原生凭据/云端验收边界不变。
