# v0.4 编程接口与权限

## 可调用工具

v0.4 保留 v0.3 的图片、PDF、ZIP、二进制和安全写入接口，并补齐：

| 类别 | 接口 | 关键语义 |
|---|---|---|
| Git | git_init, git_status, git_log, git_diff, git_branches, git_create_branch, git_switch_branch, git_add, git_commit, git_push | 固定参数，不接收任意 Git flags；push 独立授权 |
| 命令 | run_command, start_command, read_command_output, cancel_command | 默认关闭；非 OS 沙箱；退出状态、游标、超时与子进程清理 |
| 检索 | glob, grep, search_code, repo_overview, workspace_context | 忽略规则、扫描预算、代码声明/标识符启发式排序 |
| 批量读取 | batch_read | 1–16 个固定只读操作，全批校验，逐项结果和错误 |
| 跨文件补丁 | apply_patch(changes=[...]) | 1–64 个跨文件有序精确替换，原 SHA 必填、全批预检、确定序锁、尽力回滚 |

当前候选：只读模式 25 个工具；读写模式下，命令、推送和 Codex 会话导入均关闭时 38 个；命令增加 4 个，推送增加 1 个，会话导入增加 1 个，最多 44 个。禁用的工具不会注册，服务实现也检查本地权限，不能靠提示词开启。

## 本机开启命令

```bash
# root/mode 须先由用户选择；这里不预设个人目录或读写权限。
local-mcp configure --enable-commands --acknowledge-unsandboxed-commands
# 关闭：
local-mcp configure --disable-commands
```

配置变化后重启 MCP/Tunnel 并刷新客户端工具列表。安装/升级不会自动开启 Shell 或推送。

**警告：Shell 不是 OS 沙箱。** 只验证 cwd 位于授权可写范围；代码、命令和它启动的子进程拥有登录用户权限，能够访问其他目录/网络，也可能访问凭据。文件工具的 deny/root 规则不能约束任意 Shell。不要把此功能与“模型永远不能修改本服务配置/读取敏感文件”的保证同时宣传。需要强隔离时应在容器/独立 OS 用户/VM 中运行整个命令环境；本版未提供这层隔离。子进程不继承已知 API key、BASH_ENV、PYTHONPATH 等注入环境变量，但这不是对不可信命令的沙箱。

### 短任务

```json
{"command":"python3 -m pytest -q","cwd":"demo","timeout_seconds":30,"request_id":"verify-demo-001"}
```

传给 `run_command`。必须检查 `completed`、`state`、`exit_code` 和 `succeeded`。`ok=true` 只表示工具成功返回了任务状态，**不表示命令通过**。输出过大时根据 `session_id/next_cursor/has_more` 继续读取。

Windows PowerShell 的包装器会保留最终原生命令的非零退出码，而不是一律折成 1；纯 PowerShell 错误返回失败，显式 `exit N` 保留 N。清理后的子进程环境显式使用所选 PowerShell 自带的 Modules 目录，避免继承不受信任的模块搜索路径。自定义模块需要明确导入。与普通 shell 一样，后续成功语句可能清除前一步失败；多步骤构建应显式检查每一步，不能只看末尾的 `echo`/`Write-Output`。

### 长任务

```json
{"request_id":"build-demo-001","command":"npm test","cwd":"demo","timeout_seconds":600}
```

传给 `start_command`，接着反复调用：

```json
{"session_id":"上一步返回的ID","cursor":0,"limit":65536}
```

工具为 `read_command_output`；下次用 `next_cursor`。只有终止状态且 `has_more=false` 才读完；`exit_code=0` 才可认定命令成功。`truncated=true` 表示旧输出已经淘汰，不代表完整日志。默认每个任务保留最近 1 MiB，支持增配至 8 MiB；单次读取最多 256 KiB。游标是原始字节偏移；UTF-8 边界/无效字节显示替换字符，不影响真实文件字节。

`cancel_command(session_id)` 只控制本运行实例启动的任务，不接受外部 PID。默认同时最多两个活动任务，最多保留八个已终止任务附近的输出；最多记录 10,000 个 request_id。相同 request_id+相同参数返回原会话，不重复执行；参数不同拒绝；输出过期也不会自动重跑。去重记录不跨 MCP 重启，重启后重试修改型命令前必须检查实际结果。

本服务退出/收到 EOF/SIGTERM 时清理自己持有的任务。POSIX 使用自有进程组，Windows 使用 Job Object。正常任务不允许留下常驻后代；主动脱离进程组等恶意行为不属于非沙箱环境的隔离保证。

活动命令仅阻止**与其 cwd 相交工作区**的文件/Git 修改，不阻止读取或无关项目写入。错误返回 session_id/cwd/开始时间；不是 FileMCP 式任何命令占用都会锁住整个服务。此门控只在同一个 MCP runtime 内生效；其他 runtime、IDE 或外部命令不受它协调。

## Git 安全模式与限制

Git 不依赖 Shell 开关；只读有 status/log/diff/branches，read_write 才有 init/add/commit/create_branch/switch_branch。分支操作和能力诊断详见 [v0.4.1 修复说明](GIT_CAPABILITIES.md)。工具使用固定 argv，禁用 hooks、fsmonitor、外部 diff/textconv、签名、自动维护、隐式 lazy fetch；忽略全局/系统 Git 配置。路径按字面量处理，不能注入 flags/pathspec magic。

支持普通 `.git` 目录，以及同一授权 root 内、Git 双向注册关系完整的 linked worktree（`.git` 文件、`commondir`、反向 `gitdir`）。读取须允许访问主仓库和当前工作树；写操作要求两处仓库范围均可写，因为引用与对象共享。所有工作树以 common dir 获取同一服务锁。支持经双配置安全检查的 `extensions.worktreeConfig` / `config.worktree`。submodule、任意 separate git dir、root 外的 common dir、object alternates、符号链接或多硬链接元数据，以及外部 include/filter/HTTP 凭据配置仍拒绝。**不会为了兼容自动取消这些检查**。Git LFS filter 等配置需要在本机单独处理，本版不宣称完整支持所有 Git 布局。

Git 文件操作仍受 root/deny/write_roots 检查；`git_add` 或提交含未授权、敏感、链接或超限文件会整次拒绝。`git_diff`/`git_status` 过滤拒绝路径。若仅授权某个仓库的部分子目录可写，仓库级索引/提交可能被范围检查拒绝；请明确授权需要维护 Git 索引的仓库。

提交身份使用本机配置的 `git_user_name`/`git_user_email`，或仓库级 user.name/user.email，不凭空冒充用户，也不读取全局配置来执行扩展。

### 推送

本机配置示例（合并到已有配置，不要覆盖 Tunnel 设置）：

```json
{
  "enable_git_push": true,
  "git_push_remotes": ["https://github.com/OWNER/REPO.git"],
  "git_credential_helper": "osxkeychain",
  "git_user_name": "YOUR NAME",
  "git_user_email": "YOUR EMAIL"
}
```

credential helper 只能为空或 `osxkeychain` / `manager` / `libsecret` 这几种本机 native helper 名称，不能填 shell 命令。认证仍需用户在本机正常配置，密钥不放提示词。SSH 可使用本机已配置的密钥/agent，忽略用户 SSH 配置中的扩展命令，禁止交互式认证；不能登录时明确失败，不自动弹出或绕过。

`git_push(repo_path="demo",remote="origin")` 只向 exact URL 白名单中的 HTTPS/SSH 远端推送**当前分支到同名分支**；没有 force、mirror、删除、任意 refspec 参数，不自动推标签或子模块。repo remote URL 必须唯一，无内嵌密码。与 FileMCP 的“上游分支”语义并非完全相同。

推送发送 Git 提交历史，不仅仅发送当前文件工具能读取的文件。文件黑名单不能清除历史中已提交的秘密。开启推送前必须审查仓库及历史；Git 安全模式也不替代操作系统沙箱。当前自动测试验证真实本地 init/add/commit/status/diff/log，推送的网络发送为替身检查，**没有使用用户凭据向远端真实推送的验收**。

## 代码检索

完整安装现在包含 `pathspec`；pip 安装使用 `.[search]`。新检索工具使用路径策略及逐层 `.gitignore/.ignore`，默认跳过 build/dist；`include_ignored=true` 仅忽略搜索忽略规则，不能跳过安全 deny。core-only 环境遇到忽略文件而没有 pathspec 时会明确报依赖缺失，不静默扩大扫描。

- `glob(pattern,path,head_limit,offset,include_ignored)`：不区分大小写的路径查询，支持单组 `{ts,tsx}`（最多 32 项）；按修改时间排序，返回 next_offset/has_more。
- `grep(pattern,path,glob,fixed_strings,case_sensitive,output_mode,context,head_limit,offset,include_ignored)`：模式为 files_with_matches/content/count。默认字面匹配；正则采用 Python re（**不是 ripgrep/Rust regex**），在超时可终止的独立进程中执行，避免阻塞主 MCP。支持 `multiline=true`（跨行且点号匹配换行）、`type` 文件类型和独立 `context_before/context_after`。count 统计匹配行数，跨行命中的各行分别计入。
- `search_code(queries,...)`：最多六个字面查询，完整标识符、声明行优先，返回得分依据。不是语言服务器或语义引用图；长行仅返回预览，结论前继续 read_file。
- `repo_overview`：顶层条目、manifest、扩展名统计和实际扫描范围，不编造架构。
- `workspace_context`：沿 root 到目标目录读取适用 AGENTS.md，以及目标 manifest 和 Git 状态。不会执行其中的命令/指令。

每文件搜索文本最多 1 MiB，累计 50 MiB，遍历受本机数量与时间预算约束；正则执行另有八秒预算。搜索响应有截断原因和跳过数，不能将被截断的搜索当作完整扫描。分页不是跨并发修改的稳定快照。

## 批量读取

```json
{"operations":[
  {"tool":"read_file","arguments":{"path":"demo/src/main.py","start_line":1,"end_line":120}},
  {"tool":"git_status","arguments":{"repo_path":"demo"}},
  {"tool":"search_code","arguments":{"queries":["run"],"path":"demo/src"}}
],"stop_on_error":false}
```

每批 1–16 项，返回 index/tool/ok/result，支持遇错停止。禁止写操作、Shell、嵌套 batch_read 或任意反射。全批工具名称与参数先验证，再开始读取。总响应预算 512 KiB，操作间检查时间预算；超限明确提供 next_index，提示当前读取是否已执行。图像/二进制块不打包进这个文本批量接口，继续使用各自原生工具。

## 跨文件补丁

```json
{"changes":[
  {"path":"demo/a.py","old_text":"return a-b","new_text":"return a+b","expected_sha256":"<a.py 的原始64位SHA256>"},
  {"relative_path":"demo/b.py","old_text":"OLD_NAME","new_text":"NEW_NAME","expected_sha256":"<b.py 的原始64位SHA256>"}
],"dry_run":true}
```

`path` 和 FileMCP 风格的 `relative_path` 二选一。每项必须有原文件哈希；同一文件的多项哈希都指整批操作前的原版本，文本替换按顺序执行。继续兼容旧的 `apply_patch(path,edits,expected_sha256,dry_run)`；两种形式不能混用。

先确定序获取所有文件锁，读取全部原文，校验整批 SHA、唯一匹配、大小和权限，然后才开始写入。默认原文件/结果总预算均 32 MiB；每文件沿用 max_file_size。每文件覆盖仍有备份与读回验证。

中途失败按逆序尝试恢复，只恢复仍等于本次写入结果的文件；外部新修改不会被强行覆盖。返回 PATCH_FAILED_ROLLED_BACK 或 PATCH_ROLLBACK_INCOMPLETE，并逐文件给出 restored/unchanged/external_change_not_overwritten/restore_failed。私有 transaction journal 记录阶段和哈希，不把源码写入普通日志。

**这不是文件系统级多文件原子事务，也不是断电/崩溃自动回滚保证。** 跨文件读者可能观察到中间状态；外部非合作编辑器仍存在竞态。崩溃后的 journal/备份需用户在本机核查；本版没有自动崩溃恢复工具。


## FileMCP 差异补齐

完整对照与保留差异见 [FILEMCP_PARITY.md](FILEMCP_PARITY.md)。`grep` 和 `glob` 接受单文件或目录；`grep.type` 支持 py/js/ts/rust/swift/csharp/go/java/c/cpp/json/yaml/toml/md/html/css/xml/sh/ruby/php/sql/text，未知类型明确报错。类型是扩展名／文件名过滤，不进行语言推断；不是 ripgrep 的完整动态类型表。

### 追加和删除

- `write_file(path, content, expected_sha256, append=true)`：在同一文件锁内读旧值再追加，已有文件必须提供原 SHA；保留大小限制、备份及写后校验。
- `delete_file(path, expected_sha256, dry_run=false)`：普通文件删除，原 SHA 必填，删除前完整备份；用返回的 backup_id 和 `restore_file(..., expected_sha256="MISSING")` 恢复。
- `delete_directory(path, expected_sha256=null, dry_run=true)`：默认只预览，返回目录清单哈希；明确 `dry_run=false` 并提交匹配哈希后才删除。最多 1000 条目、10 秒预检、累计内容沿用 max_patch_bytes。任意受保护、越权、Git 元数据、链接或特殊条目让整批预检失败，不静默跳过后继续删。

目录先预检、按路径加锁、再次验证，然后为全部文件建立备份。外部修改或删除失败返回 `DELETE_INCOMPLETE`、已删路径和备份；不是原子事务。恢复时先按 `removed_directories` 的逆序用 create_directory 重建父目录，再逐文件 restore_file。外部非合作写入仍可能与文件操作竞争，不能把本服务的锁描述为 OS 沙箱。

### 可选 Codex 会话导入

此功能通过本机 Codex app-server 创建新会话，并将给定 user/assistant 消息写入新建的 legacy rollout，再由新 app-server 读取所有消息核对。不会发起 `turn/start` 或调用模型，不修改既有会话；历史格式是内部适配，不属于稳定的官方导入 API。

独立授权后在本机开启：

```bash
local-mcp configure --enable-codex-history --acknowledge-codex-history
# 关闭
local-mcp configure --disable-codex-history
```

需要 mode=read_write 和 PATH 上的 codex。默认写入当前 HOME/.codex；本机配置 `codex_history_home` 可以指定其他 Codex home，MCP 参数不能更改它。该权限允许在项目 root 之外创建 Codex 历史，并启动读取对应 Codex 配置的本机进程；文件黑名单不是此适配器的沙箱。安装不会自动启用它。

调用 `save_conversation_to_codex(title, messages, request_id, repo_path=".")`；messages 为 1–500 项、最多 2 MB 文本、首项必须为 user。request_id 必填且持久去重：相同输入返回已验证结果，参数变化拒绝，未完成请求也不会自动创建第二份。失败时保留 phase/thread_id，供本机核查；不自动删除可能已创建的会话。工具不用于复制工具调用、图片或完整执行状态。

官方连接生命周期参考：[Codex App Server](https://learn.chatgpt.com/docs/app-server)。新建／读取接口与自行追加 legacy rollout 是两层实现；不能把后者宣称为官方稳定接口。真实安装的 Codex 版本不兼容时明确失败，不静默改为只导出 Markdown。
