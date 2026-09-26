# v0.4.1 分支操作与能力诊断（候选修复）

本修复对应 `fix/git-capabilities-20260927`。提交/推送不等于合并、安装、重启或 ChatGPT 工具刷新；实际验证范围见 [TEST_REPORT](../TEST_REPORT.md)。默认安装来源仍为 main，未合并前不得把候选功能描述为 main 已部署。

## 修复范围

此前 `extensions.worktreeConfig` 被按配置键名一律拒绝，连只读 Git 状态也失败；没有专用分支接口，导致 Shell 关闭时不能完成“先建分支，再编辑”。同时，诊断缺少服务端工具目录证据，容易混淆文件写入、Git 和命令权限。

v0.4.1 新增三个受控工具：

| 工具 | 权限 | 行为 |
|---|---|---|
| `git_branches(repo_path='.', offset=0, limit=100)` | 只读 | 本地分支列表、当前 HEAD、分页；不连接远端 |
| `git_create_branch(branch, repo_path='.', checkout=true, expected_head=null)` | read_write | 仅从当前 HEAD 新建分支，可同时切换；不依赖 Shell |
| `git_switch_branch(branch, repo_path='.', expected_head=null)` | read_write | 仅切换到明确存在的本地分支；不猜测远端 |

分支名接受 1–200 位 ASCII 字母、数字、点、下划线、斜线和横线，首字符须为字母或数字，并通过 Git `check-ref-format`。拒绝 `HEAD`、`@{-1}`、flags、refspec 和任意 revision。

操作顺序示例：读取 `git_status` 的 `head` → 将该完整 SHA 作为 `expected_head` 调用 `git_create_branch` → 修改文件 → `git_diff` → 在已授权执行环境运行测试 → `git_add` / `git_commit`。测试命令仍需独立的命令开关，不能将分支能力当作 Shell 授权。

创建/切换要求已有提交的本地分支、工作区和暂存区干净。未跟踪的受保护文件也会阻止操作，但错误不输出其名称或内容。拒绝未完成 merge/rebase/cherry-pick/revert/bisect、占用锁、子模块索引、skip-worktree/assume-unchanged 索引；不自动 stash、reset、clean、删除锁或覆盖已有分支。

切换先检查受影响路径的读写策略和目标对象：拒绝越权文件、符号链接、gitlink 和超大对象。Git 使用 `--no-guess` / `--no-overwrite-ignore`，不覆盖忽略文件，也不抢占其他工作树正在检出的分支。Hooks、外部 diff/textconv、签名、自动维护、隐式网络传输沿用原防护。

本服务的 lease 不约束其他 IDE/Git 进程。操作后检查 HEAD；发现并发变化报 `GIT_POSTCONDITION_FAILED`，不强制回滚外部修改。不能把这描述为对任意外部进程的原子事务或 OS 沙箱。

## 工作树配置不是链接工作树

支持普通仓库的 `.git/config` 中启用 `extensions.worktreeConfig`，并安全解析同目录 `config.worktree`。两份配置均从非仓库目录使用 `git config --file ... --no-includes` 检查，之后才运行仓库 Git 操作。按 Git 的布尔语义识别开关；开启时合并工作树配置，关闭时不应用其值，但仍审查已经存在的配置文件。

配置必须是有界普通文件，拒绝符号链接、硬链接和特殊文件。继续拒绝外部 include、filter、credential helper、HTTP 凭据路径、SSH 命令、部分克隆等危险配置。`config.worktree` 内的 `core.worktree` 只有解析后恰好等于当前授权仓库时才允许；不允许裸仓库，也不改写用户配置。配置错误不回显可能含敏感值的 Git 解析原文。

**仍不支持** `.git` 为重定向文件的 linked worktree、子模块 gitfile、外部 common dir 和 alternates；这些返回 `UNSUPPORTED_GIT_LAYOUT` 或对应元数据错误。此修复不是“支持所有 worktree 布局”，不以放宽安全边界换取兼容。

Git 官方依据：[工作树配置](https://git-scm.com/docs/git-worktree#_configuration_file)、[分支名规则](https://git-scm.com/docs/git-check-ref-format)。

## 分层诊断

`policy_info` 和 `workspace_context` 增加 `capabilities`，`diagnose(path)` 保留原锁探测并额外分别报告：

- 服务版本、当前实例随机标识（不是 Tunnel ID）、工具名列表、数量和 schema 指纹；每个被禁用工具的原因。
- 文件写入、Git 读取、分支创建、分支切换、Shell、推送各自是否已注册。
- 目标路径的文件写策略预检、Git 兼容/状态和锁状态。`file_write.disk_write_tested=false`：未试写，不代表 OS 落盘验收通过。

`write_roots=[]` 的语义为 root 范围内再减去 deny，而不是“无可写目录”。`shell_enabled=false` 不等于文件只读。Git 布局拒绝也不能推导为普通文件不可修改。

| 模式 | 命令 | 推送 | 工具数 |
|---|---|---|---:|
| read_only | 任意配置 | 任意配置 | 25 |
| read_write | 关 | 关 | 36 |
| read_write | 开 | 关 | 40 |
| read_write | 开 | 开 | 41 |

另有 read_write、命令关、推送开的组合，共 37 个工具。注册表和诊断使用同一启用条件，避免维护两套数量常量。

`client_tool_visibility_verified=false` 明确表示服务看不到 ChatGPT 的最终工具筛选结果。若服务端指纹/数量与会话发现不同，先确认版本和实例，再刷新连接元数据并用新会话验证；不能仅凭差异宣称已定位到缓存故障，也不能把写工具伪装为 read-only。

`local-mcp doctor` 的 `tool_capabilities` 来自新建的本机诊断实例，不是运行中的 Tunnel。以 ChatGPT 直接调用 `policy_info` 的结果验收实际连接。官方刷新说明：[连接并测试插件](https://developers.openai.com/apps-sdk/deploy/connect-chatgpt)。

## 部署边界

本修复不提供远程改权限、更新自身安装、重启自身或修改凭据的工具；不自动启用 Shell 或推送。安装/升级需保留原 root/mode/write_roots、凭据、日志和自启设置，由明确授权的本机流程执行。发布后重启正确的 MCP/Tunnel 实例并刷新客户端工具目录，不能用 GitHub 已更新代替实际部署证据。
