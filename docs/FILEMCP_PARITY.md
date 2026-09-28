# FileMCP 能力对照与本轮补齐

核对日期：2026-09-28。Tunnel 基于 `origin/main`，FileMCP 对照本机源码提交 `3e015fe1e5199df01cfdefe7f2028adcb0316756` 的 macOS 工具注册表、实现，以及当前连接器工具清单。不是仅按工具名称推测功能，也不是两者所有平台 GUI 的逐项复刻。

本轮版本：0.5.0。Codex 会话导入默认开启，显式关闭的配置继续保留；只读模式仍不注册该写入工具。源码更新不自动安装或重启现有服务。工具参数及限制见 [CODING_TOOLS.md](CODING_TOOLS.md)，测试证据见 [TEST_REPORT.md](../TEST_REPORT.md)。

## MCP 能力映射

| FileMCP | Tunnel | 处理结果 |
|---|---|---|
| list_files | list_directory | 已有分页目录、大小及修改时间；不增加同义工具 |
| read_file / read_file_range | read_file(start_line, end_line) | 已有整文件／行范围、原 SHA、截断信息 |
| write_file | write_file | 补 append；已有文件仍强制 SHA，不复制盲写行为 |
| delete_file | delete_file | 新增；原 SHA、备份、预览和恢复 |
| delete_directory | delete_directory | 新增；有界清单、预览 SHA、整批预检和备份，明确部分失败 |
| edit_file / apply_patch | 同名工具 | 已有唯一替换、跨文件预检和尽力回滚；保留强制原 SHA |
| glob | glob | 补大小写不敏感、单组 brace 扩展、单文件路径 |
| grep | grep | 补 type、多行、独立前后上下文及单文件搜索 |
| search_code / repo_overview / workspace_context | 同名工具 | 已有启发式代码检索、项目结构、适用 AGENTS.md 和 Git 状态 |
| batch_read | batch_read | 已有 1–16 个固定只读操作、全批参数校验、输出预算 |
| git_init / status / log / diff / add / commit | 同名工具 | 本轮打通 linked worktree；固定 argv、配置审查、文件规则仍生效 |
| git_push | git_push | 已有独立开关和 URL 白名单；保留当前分支→同名分支，不自动改成任意上游 |
| run_command / start_command / read_command_output / cancel_command | 同名工具 | 已有；Shell 仍默认关闭，输出游标和子进程清理仍生效 |
| save_conversation_to_codex | 同名工具 | 新增；默认开启、可独立关闭，新建会话、验证读回、持久请求去重 |

Tunnel 另有图片/PDF/ZIP/二进制、备份恢复、文件信息、权限诊断，以及专用 Git 分支接口，不需要从 FileMCP 重复增加。

## linked worktree 的具体支持范围

标准布局的 `.git` 文件指向主仓库 `.git/worktrees/<id>`；其 `commondir` 指向主 `.git`，`gitdir` 反向指向当前工作树的 `.git`。支持绝对及相对指针，但不接受链接组件、硬链接指针、特殊文件、无效双向关联或 root 外目标。以主仓库 common dir 加服务锁，防止不同工作树并发改共享引用时绕过互斥。

读取要求当前工作树、主仓库均可访问；写 Git 还要求两处仓库范围可写。例如 root 为两者共同父目录，write_roots 可以为 `["main/**", "linked/**"]`。只授权 linked 子目录不隐含对外部主仓库写权限；工具不会自动扩大 root/write_roots。

每个工作树使用自身 index、HEAD、merge/rebase 标记及 config.worktree，共享 config/objects/refs。分支切换继续拒绝抢占其他工作树正在使用的分支。子模块、任意 separate git dir、alternates 和外部 common dir 尚不支持。

## 有意保留的语义差异

- 搜索仍使用有界 Python 扫描和隔离 Python re；不是 Rust regex。`type` 提供文档列出的 22 种常用类型，不声称覆盖 ripgrep 的完整类型表；复杂多组 brace、完整 gitignore 风格 glob 也不作完全等价承诺。默认 fixed_strings=true 保持旧调用兼容。
- 文件删除不是无备份的任意递归删除。超预算、受保护条目、链接及冲突会拒绝；目录中途失败返回备份和已删路径，不宣称多文件原子性。
- 原 SHA 是写入前置条件；不会因对齐 FileMCP 而变成可选。可执行命令和网络推送仍各自独立授权。
- Codex 历史适配创建新会话并写其 legacy rollout；它依赖内部历史格式。公开 app-server 生命周期不等于官方稳定导入 API，失败保留准确阶段及可能创建的 thread_id，不静默删除或重复创建。只支持 user/assistant 文本，不能伪造原工具执行历史。
- FileMCP 的桌面 GUI、应用图标、打包器和界面日志不是本次 MCP 工具能力补齐范围；Tunnel 已有自己的 CLI、安装、日志与 Tunnel 管理方式。

## 部署与授权

只读 25 个工具；读写默认 39 个（含 Codex 历史导入）；Shell +4、推送 +1，关闭历史导入减 1，最多 44 个。独立开关必须在本机修改后重启才生效，模型无远程改开关接口。

主线源码更新后，上线仍需安装、重启正确实例和刷新客户端目录；当前运行服务不会自动获得这些能力。
