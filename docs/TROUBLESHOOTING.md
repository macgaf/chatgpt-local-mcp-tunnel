# 分层故障排查

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
| PRECONDITION_REQUIRED | 覆盖缺原文件 SHA | 先 read_file 或 file_info |
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

## FileMCP 的“活动命令锁”与本项目的区别

FileMCP 原作可能报 `Command session is active; finish or cancel it before file mutations or Git operations`：这通常是原作的活动命令会话门控，不等同于 OS 文件锁。本项目不提供任意 shell/命令会话，不复制这个全局门控；用按目标文件的 OS lease 避免无关文件被锁。

`diagnose(path)` 只探测本服务的锁，未持有的旧元数据不算活锁；文件不删除，避免另一个进程在新 inode 上取得第二把锁。外部 FileMCP 实例和本工具不会共享应用内的锁；同时修改时仍需哈希冲突保护。

同一个 Tunnel ID 不应同时启动 FileMCP 和本工具两个 runtime。切换时先明确退出旧客户端；本工具不会擅自杀掉旧客户端。

## 提交诊断信息

`doctor --bundle ./diagnostic-local-mcp.json` 生成脱敏报告。不要附上 key、.env、整个 HOME、浏览器 Cookie 或 Keychain。工具日志只有 tool、request_id、耗时、错误码，不记录文件内容。备份文件是真实原始内容，不能当作普通日志公开。

本报告中的 pass 表示对应探针真实执行通过；warning 是可选项不足，not_checked 是未执行。尤其不能把 core-only 的成功改写成图片、凭据库和云端连接全部正常。
