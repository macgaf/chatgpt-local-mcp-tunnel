# Changelog

## 0.4.0 — 2026-09-24

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
