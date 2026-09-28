# 分层故障排查

## 先确认 Tunnel 进程正常启动

ChatGPT 无法连接时，先检查本项目的运行实例，再排查 App 绑定：

1. 核对实际启动器、配置/profile 与进程身份，确认本项目 Tunnel 是否启动、是否立即退出或反复重启。仅发现名为 tunnel-client 的进程不足以证明是本项目；不要输出含凭据的完整命令行或环境变量。
2. 已配置登录自启时，检查当前用户的自启服务是否启用、加载，启动路径是否仍有效，以及最近退出状态。使用该服务机制核验启动，避免另开手工进程掩盖自启故障或产生重复实例。
3. 通过客户端实际提供的健康/就绪检查和连接状态确认正在运行并可接收请求。有 PID、服务已加载或自启文件存在，都不等于 Tunnel 在线；自检通过也不能替代 ChatGPT 端调用。
4. 查看 `local-mcp logs show --component tunnel --tail 200`，结合系统服务的脱敏错误信息定位退出原因。区分未启动、路径或依赖错误、凭据不可读、认证/权限失败、网络断连及本机 MCP 启动失败；缺少日志不等于正常。
5. 只处理已确认属于本项目的实例，不终止未知进程、不抢占 FileMCP 的 Tunnel。修复后重新确认进程、健康/就绪及 ChatGPT 实际调用。未实际重新登录时，标记“重新登录后的自动启动待验证”，不自行注销或重启电脑。

## 文件可写、Git 失败、Shell 关闭必须分别判断

`policy_info.capabilities` 返回工具目录、数量、指纹、运行实例和独立权限状态，`diagnose(path)` 分别返回文件写策略、Git 状态及锁。详见 [能力诊断](GIT_CAPABILITIES.md)。`write_roots=[]` 不表示没有可写目录；`shell_enabled=false` 不表示文件只读；`UNSUPPORTED_GIT_LAYOUT` 不表示文件不可写。

若服务端工具目录与 ChatGPT 发现的目录不一致（v0.5.0 读写默认 39 个、只读 25 个，实际数量还取决于开关），先核对源码/已安装版本、运行实例和连接工具刷新；没有证据不能断言是缓存。服务不能直接观察或修复宿主侧的工具筛选，`client_tool_visibility_verified` 始终为 false。CLI doctor 的能力检查是新诊断实例，不替代真实 Tunnel 上的 `policy_info`。

## 诊断命令与错误码

先执行 `local-mcp doctor`。需要查认证与网络时执行 `local-mcp doctor --with-tunnel --network`。网络探针是直连 DNS/TLS，代理路线可能不同；以实际 Tunnel doctor 输出为准，不为了“通过”关闭 TLS。

| 错误码/现象 | 含义 | 处理 |
|---|---|---|
| CONFIG_MISSING / INVALID_ROOT | 未配置/目录不存在 | configure，使用真实 root |
| ROOT_TOO_BROAD | root 是 HOME 上级 | 改为 HOME/项目/明确外部数据目录 |
| READ_ONLY_MODE | 本地只读；提示词不能提升 | 本机 configure --mode read_write，重启并刷新工具列表 |
| POLICY_DENIED | 命中具体 deny 或凭据保护 | 看 matched_rule；只在本机审核规则，不扩大 HOME 来绕过 |
| PROTECTED_RUNTIME | 访问 MCP 自身配置、安装、私有状态 | 用本机 CLI 管理，不通过模型自改权限 |
| OUTSIDE_ROOT / PATH_TRAVERSAL | 越界或 ../ | 使用授权范围内真实路径 |
| SYMLINK_WRITE_DENIED / REPARSE_POINT_DENIED | 写路径含链接 | 使用真实路径；不要禁用检查 |
| HARDLINK_DENIED | 多硬链接可能绕过路径过滤 | 对普通授权数据创建正常副本，不链接凭据 |
| PRECONDITION_REQUIRED | 文件修改／删除缺少原文件 SHA | 先 read_file 或 file_info |
| HASH_CONFLICT | 文件已被 IDE/另一 agent 修改 | 重新读、比较、合并；不能仅替换 expected_sha256 强行覆盖 |
| AMBIGUOUS_EDIT | old_text 匹配零次或多次 | 使用更充分且唯一的上下文 |
| FILE_LOCKED | 本服务其他操作持有目标写锁 | 看 holder.pid/operation/started_at/path/request_id；等待或核查持有者 |
| OS_FILE_BUSY | 操作系统共享锁或执行中的文件 | 已知应用保存/关闭后重试；holder=unknown 表示无法确认，不猜 |
| OS_PERMISSION_DENIED | OS 权限、macOS 隐私授权、安全软件等 | 检查文件权限/挂载/TCC；不自动 sudo |
| DISK_FULL / READ_ONLY_FILESYSTEM | 目标或备份卷满/只读 | 释放空间或换可写目录；MCP 开关不能覆盖 OS 挂载 |
| POST_WRITE_CONFLICT | 提交后外部程序又改文件 | 本次已可能写入，停止并核查当前内容与 backup_id |
| FILE_CHANGED / FILE_GREW | 读取过程中变化 | 等原写入结束后重新读取 |
| FILE_TOO_LARGE / IMAGE_RESPONSE_TOO_LARGE | 数据/传输预算上限 | 缩小范围、裁剪、分块，或本机调整允许的上限 |
| BINARY_CONTENT / FORMAT_NEEDS_ADAPTER | 用了不适用的读取器 | 图片/PDF/ZIP 用对应工具；其他二进制用资源/专用适配器 |
| INVALID_ARCHIVE / UNSAFE_ARCHIVE_MEMBER | ZIP 损坏/危险成员路径 | 不解压到 HOME；重新生成安全包 |
| ARCHIVE_BOMB_LIMIT / DUPLICATE_ARCHIVE_MEMBER | 压缩炸弹阈值/名称歧义 | 拆包或去除重复；不忽略校验 |
| INTERACTIVE_SECRET_REQUIRED | 无 TTY，不能安全录入 key | 在本机终端 key set，不粘贴到聊天 |
| UNSUPPORTED_CREDENTIAL_SOURCE | 在非 Linux 上选择了 systemd | macOS/Windows 改用 native keyring；不是放宽 POSIX 权限位检查 |
| KEYSTORE_UNAVAILABLE / KEYSTORE_READ_FAILED | 无 backend、库锁定、D-Bus/session 等 | 安装依赖、解锁；Linux server 明确配置 systemd；不降级明文 |
| DEPENDENCY_NOT_FOUND / TUNNEL_CLIENT_NOT_FOUND | 程序缺失或 PATH 错 | 使用安装器/输出的绝对路径 |
| CHECKSUM_MISMATCH / RELEASE_COMPANION_MISSING | 发行包校验失败/缺 cloudflared | 停止，使用官方完整包，不跳过校验 |
| CODEX_CONFIG_CONFLICT | 同名 MCP 配置不同 | 人工比较；安装器不覆盖其他配置 |
| TUNNEL_PROFILE_CONFLICT | 现有 profile 不匹配所有权信息 | 核对 ID/launcher，不能对不明配置直接 --force |
| TUNNEL_AUTHENTICATION_FAILED | 401/key 无效或组织不匹配 | 本机更新 Runtime key；不要发到聊天 |
| TUNNEL_PERMISSION_DENIED | 403/缺 Read+Use 等 | 核对 Platform 权限、工作区关联；不自动提权 |
| DNS_FAILURE / TLS_FAILURE | 域名解析/证书/代理问题 | 检查网络、系统时间及 CA；不要关闭验证 |
| COMMAND_TIMEOUT / COMMAND_OUTPUT_LIMIT | 验证命令超时/异常持续输出 | 该步未通过；只停止本次子进程，不杀外部进程 |
| Tunnel healthy，但 ChatGPT 看不到 | 未关联当前工作区/App 未启用 | 检查账号/工作区及聊天工具选择，不反复重装本机 |
| visual_probe 返回了但看不到图 | 宿主未向模型提供 ImageContent | 确认具备视觉的模型和支持图片结果的客户端；不是改 Base64 字符串就能解决 |

## 编程接口错误

| 错误码 | 原因和动作 |
|---|---|
| COMMANDS_DISABLED / COMMAND_RISK_ACK_REQUIRED | 命令未授权或缺风险确认；只能在本机开启，不通过提示词提升 |
| REQUEST_ID_CONFLICT / SESSION_EXPIRED | 重试键参数不一致或输出过期；不要重复执行未知结果的修改任务 |
| WORKSPACE_COMMAND_ACTIVE | 相交目录有任务；查看返回 session_id/cwd，读完或取消自己的任务 |
| COMMAND_CONCURRENCY_LIMIT | 活动任务达到配置上限；不擅自杀其他任务 |
| PROCESS_ISOLATION_FAILED | Windows 无法建立 Job Object 隔离或恢复挂起的自有进程；停止命令，不降级为无隔离执行 |
| UNSAFE_GIT_CONFIG / UNSAFE_GIT_METADATA | 不安全扩展、链接或对象库；本机审核，不能关闭防护强行执行 |
| UNSUPPORTED_GIT_LAYOUT | 支持普通 .git 目录及标准、已双向注册的 linked worktree；子模块 gitfile、任意 separate git dir 等仍拒绝。按 [Git 布局说明](GIT_CAPABILITIES.md) 核查，不能取消校验 |
| INVALID_GIT_CONFIG | 配置格式、布尔值或大小不合法；错误不会回显配置值 |
| INVALID_BRANCH_NAME / GIT_BRANCH_EXISTS / GIT_BRANCH_NOT_FOUND | 只接受安全本地分支名；不覆盖已有分支或猜测远端 |
| GIT_DIRTY_WORKTREE / GIT_OPERATION_IN_PROGRESS | 先完成已有修改或 Git 操作；不自动 stash/reset/abort |
| GIT_HEAD_CHANGED / GIT_POSTCONDITION_FAILED | 并发改变了预期状态；核查真实结果，不强制回退 |
| GIT_INDEX_FLAGS_UNSUPPORTED / GIT_SUBMODULE_UNSUPPORTED | 分支操作拒绝隐藏修改的索引标记及子模块索引 |
| GIT_CHECKOUT_PATH_DENIED | 目标分支含符号链接、gitlink 或超限对象；不绕过文件策略 |
| GIT_PATH_DENIED / GIT_LOCKED | 文件权限/策略拒绝，或 Git 自己的锁；不自动删锁 |
| GIT_PUSH_DISABLED / GIT_REMOTE_NOT_APPROVED | 开关或精确 URL 白名单不足；只在本机审核配置 |
| GIT_TRANSPORT_DENIED / GIT_IDENTITY_MISSING | 非 HTTPS/SSH、含密码 URL 或缺提交身份；本机配置，不向聊天提供密码 |
| SEARCH_IGNORE_DEPENDENCY_MISSING | 缺 pathspec；安装 search 组件，不静默无视忽略规则 |
| SEARCH_TIMEOUT / INVALID_SEARCH_PATTERN | 正则无效或超时；缩小范围/改用字面搜索；主 MCP 不受阻塞 |
| BATCH_TOOL_DENIED | batch_read 出现写操作、命令或递归批量；先修正整个请求 |
| DELETE_PATH_DENIED / DELETE_BUDGET | 删除目标包含受保护／特殊条目，或清单／备份超过预算；预检未通过，先核查目标或拆小范围 |
| DELETE_INCOMPLETE / DELETE_POSTCONDITION_FAILED | 部分条目可能已删除，或删除后目标被外部进程重建；核查已删路径与 backup_id，按需恢复，不盲目重试 |
| CODEX_HISTORY_DISABLED | 当前为只读模式或导入开关显式关闭；导入在读写模式默认开启，本机可使用 --enable-codex-history 恢复，无需额外确认参数 |
| CODEX_HISTORY_FAILED | 核查 cause、phase、thread_id、request_id；可能是 Codex 缺失／版本不兼容／请求冲突／读回不一致。保留已创建会话，不换请求 ID 盲目重试 |
| PATCH_BUDGET_EXCEEDED | 多文件原文/结果超过总量限制；拆分修改 |
| PATCH_FAILED_ROLLED_BACK / PATCH_ROLLBACK_INCOMPLETE | 中途失败；检查逐文件 rollback 和备份，不覆盖外部新内容 |

## FileMCP 的“活动命令锁”与本项目的区别

FileMCP 原作可能报 `Command session is active; finish or cancel it before file mutations or Git operations`：这通常是原作的活动命令会话门控，不等同于 OS 文件锁。本工具提供显式开启的命令会话，但仅对相交 cwd 的修改门控；按目标文件的 OS lease 协调文件写入。不会因项目 A 的任务阻止无关项目 B 写入。

`diagnose(path)` 的锁检查只探测本服务的锁，未持有的旧元数据不算活锁；文件不删除，避免另一个进程在新 inode 上取得第二把锁。外部 FileMCP 实例和本工具不会共享应用内的锁；同时修改时仍需哈希冲突保护。

同一个 Tunnel ID 不应同时启动 FileMCP 和本工具两个 runtime。切换时先明确退出旧客户端；本工具不会擅自杀掉旧客户端。

## 提交诊断信息

`doctor --bundle ./diagnostic-local-mcp.json` 生成脱敏报告。不要附上 Tunnel ID、key、.env、整个 HOME、浏览器 Cookie 或 Keychain。工具日志只有 tool、request_id、耗时、错误码，不记录文件内容。备份文件是真实原始内容，不能当作普通日志公开。

本报告中的 pass 表示对应探针真实执行通过；warning 是可选项不足，not_checked 是未执行。尤其不能把 core-only 的成功改写成图片、凭据库和云端连接全部正常。

## 本机交互配置

目录默认候选为 ~/，模式由用户选只读或读写，不把示例目录/模式当成授权。Tunnel ID 在 `local-mcp tunnel configure` 中隐藏录入，key 在 `local-mcp key set` 中隐藏录入；不可发到聊天或命令参数。`INTERACTIVE_SECRET_REQUIRED` 表示没有本机 TTY，`HIDDEN_INPUT_UNAVAILABLE` 表示不能关闭回显，`INTERACTIVE_INPUT_CANCELLED` 表示输入已结束。遇到这些错误换用本人独立终端，不 echo/管道传值，不用工具参数中转。ID格式错误不会显示实际输入值；已有正确ID可回车保留。原始配置与第三方日志仍可能含真实ID，不公开或整份输出。


## 访问持久日志

先运行 `local-mcp logs path`，再用 `logs show --level ERROR`、`logs show --component mcp --tail 200` 查看；独立终端用 `logs follow --component tunnel` 跟踪。`logs export --output ./local-mcp-logs.json` 导出筛选后的事件，不覆盖已有文件。详见 [日志说明](LOGGING.md)。

`LOG_CONFIG_INVALID`：logging 配置无效，回退默认日志设置记录启动故障；请在本机修正配置。`LOG_WRITE_FAILED`：可能是磁盘满、权限不足、锁超时或不安全日志路径；stderr 会单独告警，doctor 的 logging 检查会显示失败。**业务操作可能已经完成，不能因为日志缺失直接重试写入。**

日志关闭只停止后续记录，不删除既有记录。DEBUG 也不会持久保存命令/文件正文或凭据。不要为了读取日志解除私有状态目录的 MCP 保护；使用 Codex 原有终端工具。

## macOS 提示“未打开 python”

先核对被拦截的具体路径；Chrome 宿主创建的 Python 副本可能带 quarantine，不能仅凭弹窗认定基础 Python 损坏。当前 POSIX 安装器使用符号链接复用已有解释器。停止重复运行受阻副本，按 [安装说明](INSTALL_WITH_CODEX.md#macos-python-验证弹窗) 检查并验证安装／重装，不关闭系统安全检查。

## main 已更新，但本机仍是旧功能

先确认本机仓库的 origin、分支和 HEAD。安装来源应为 `main`；不要再按旧文档回退到功能分支。工作区有未提交修改或本地 main 分叉时停止更新，不强制覆盖。

`git pull` 只更新仓库，不更新已复制到版本化安装目录的 MCP。按 README [第 3.7 节](../README.md#upgrade) 重新执行完整安装器，再重启由用户管理的 MCP／Tunnel 实例并刷新客户端工具发现。v0.4.0 的交互安装和日志修订沿用相同版本号，需同时核对源码提交、安装器结果及 `logs path`，不能只看 `--version`。

排查时保留现有 root/mode/write_roots、凭据、日志配置和其他 Codex 条目。v0.5.0 的 enable_codex_history 缺省为 true，显式 false 保留；它在读写模式下允许新建项目 root 外的 Codex 历史。除已说明的版本默认值变化，不借重新安装改写其他权限，也不要求用户把 ID/key 发到聊天。
