# Changelog

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
- 108 项隔离测试通过；外部客户端/OS 原生凭据库验收状态见 TEST_REPORT.md。
