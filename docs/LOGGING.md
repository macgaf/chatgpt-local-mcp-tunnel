# 日志：位置、查看、跟踪和导出

本项目默认把**安全事件摘要**保存为 UTF-8 JSON Lines（每行一个 JSON 对象）。退出终端或重启后仍可查看保留期内的记录。日志是本机管理功能，**不是新增的 MCP 工具**，不会改变目录、读写、命令执行或 Git 推送权限。

## 1. 日志在哪里？

在本机终端执行：

```bash
local-mcp logs path
```

没有把启动器加入 PATH 时，macOS/Linux 用 `~/.local/bin/local-mcp logs path`；Windows 使用安装器打印的 `local-mcp.cmd` 绝对路径，PowerShell 中以 `& "完整路径\local-mcp.cmd" logs path` 调用。

| 系统 | 默认目录 |
|---|---|
| macOS / Linux | `~/.local/state/chatgpt-local-mcp-tunnel/logs/` |
| macOS / Linux 设置了 XDG_STATE_HOME | `$XDG_STATE_HOME/chatgpt-local-mcp-tunnel/logs/` |
| Windows | `%LOCALAPPDATA%\chatgpt-local-mcp-tunnel\state\logs\` |

**以 `logs path` 的实际输出为准。** 同一个用户状态目录下，Codex 和 Tunnel 启动的实例共用这些日志文件；`pid` 和 `process_id` 区分运行实例。目录及文件按需创建，尚未实际运行就可能没有文件。仅更换 `--config` 不会改变状态目录。

| 文件／component | 记录什么 |
|---|---|
| `mcp.jsonl` / `mcp` | 服务启动/停止、工具名、请求 ID、耗时、成功/失败、错误类别；包含通过 MCP 调用的 Git 和补丁操作 |
| `commands.jsonl` / `commands` | 命令任务启动/结束/取消/复用、会话 ID、子进程 PID、退出码、超时预算和输出字节数；**不保存命令正文或 stdout/stderr 正文** |
| `tunnel.jsonl` / `tunnel` | Tunnel 进程状态及从输出识别到的认证/权限/DNS/TLS/重连等事件类别；**不是原始 Tunnel 日志的逐行副本** |
| `cli.jsonl` / `cli` | 本机配置、凭据检查、Codex 注册、安装 Tunnel 客户端等命令的状态；doctor 各检查项的结果 |
| `install.jsonl` / `install` | bootstrap 安装阶段、成功或失败；不收集 pip 的完整输出 |

Tunnel 的 `ready_reported` / `connected_reported` 仅表示子进程输出中报告了相应状态，不等于 ChatGPT 已成功调用。日志没有记录到某事件，也不能单独证明该操作没有发生。

## 2. 查看最近日志

```bash
# 所有分类最近 100 条，包含仍保留的轮转文件
local-mcp logs show

# 只看 MCP 调用最近 200 条
local-mcp logs show --component mcp --tail 200

# 所有分类最近的错误；level 是最低级别
local-mcp logs show --level ERROR --tail 100

# 跟踪一次工具错误：填工具返回的 request_id，不填 Tunnel ID/key
local-mcp logs show --request-id request-001

# 输出 JSON Lines，便于本机程序处理
local-mcp logs show --component commands --json
```

日志包含 UTC 时间、级别、分类、事件、进程标识，以及该事件适用的 `request_id`、`session_id`、`exit_code`、`error_code`、`cause`、`remediation`。不同 CLI 进程可用 `process_id` 区分；一次命令任务还可通过会话 ID 关联。

常见错误保留**程序定义的安全原因和建议**，例如锁冲突的持有者 PID。未知错误保留错误类别、异常类型和可获取的 OS 错误号，不持久化可能含文件内容/密钥的异常原文、堆栈源码或局部变量。具体文件差异仍需在原工具结果中核查。

## 3. 实时跟踪

```bash
local-mcp logs follow --component mcp --tail 50
local-mcp logs follow --component tunnel --level INFO
```

在独立本机终端中运行，按 **Ctrl+C** 退出查看，不会停止 MCP 或 Tunnel。支持运行后才出现的文件及正常轮转；不将文件一直打开，避免阻止 Windows 重命名轮转。若读取期间有大量日志超过保留容量、日志被外部截短或系统异常，不能保证看到已丢失的历史。

## 4. 导出用于排错的日志

```bash
local-mcp logs export --tail 500 --output ./local-mcp-logs.json
local-mcp logs export --component tunnel --level WARNING --output ./tunnel-errors.json
```

导出为重新过滤字段后的 JSON，**不是压缩整个日志目录或复制配置**；默认最近 200 条，可选 0–5000 条。已有目标文件不会覆盖。导出结果包含 `returned`、`invalid_records`、`scan_limited`；查询每个保留文件最多读取末尾 8 MiB，超过会明确说明，因此导出不保证是全部历史。导出的元数据也请先审核再分享。

`doctor --bundle` 仍只导出诊断摘要，**不会自动附带日志**；需要日志时单独运行上述命令。

## 5. 级别、大小和保留时间

默认设置：**INFO、每分类单文件 5 MiB、最多 5 个历史文件、14 天过期策略**。文件示例为 `mcp.jsonl`、`mcp.jsonl.1`…`mcp.jsonl.5`，`.1` 是最近的历史文件。五种分类全部使用时，默认日志内容容量约 150 MiB，不含极小的锁文件。

```bash
# 调试时增加事件细节；仍不记录参数、正文或原始命令输出
local-mcp logs configure --level DEBUG

# 调整大小/保留份数/过期天数；仅修改 logging 部分
local-mcp logs configure --level INFO --max-mib 5 --keep 5 --days 14

# 停止后续持久记录／重新启用，不删除既有日志
local-mcp logs configure --disable
local-mcp logs configure --enable
```

设置改变后重启长驻 MCP/Tunnel；新的 CLI 进程使用新设置。修改不会清空其他配置，也不会启用命令/推送。可直接在本机配置的 `logging` 对象中管理：

```json
{
  "logging": {
    "enabled": true,
    "level": "INFO",
    "max_bytes": 5242880,
    "backup_count": 5,
    "retention_days": 14
  }
}
```

这只是要合并进已有配置的片段，**不要用它覆盖整个配置文件**。支持 DEBUG/INFO/WARNING/ERROR；单文件上限可设 16 KiB–50 MiB，历史 0–10 份、天数 1–90。

过期清理在该分类**下一次写入时**执行，没有定时后台清理器。以文件最后写入时间判断整份文件，不承诺严格逐条保留 14 天；容量达到上限也可能更早淘汰。读日志不代表归档所有历史。

## 6. 隐私和故障边界

日志采用字段白名单，不记录完整 MCP 请求/响应、文件正文、图像/Base64、命令脚本、完整命令输出、环境变量、API key、原始配置和真实 Tunnel ID。已知凭据/ID 格式在写入与查看时再次脱敏；不应把秘密放进 `request_id` 等标识字段。日志是运行摘要，不是命令输出归档或安全防篡改审计系统。

macOS/Linux 的日志目录使用 0700、文件使用 0600；Windows 使用本用户 LOCALAPPDATA 目录及其现有 ACL，**没有额外建立 Windows ACL 沙箱**。日志目录位于文件工具保护的状态目录中，不对 MCP 直接开放；用户可用本机终端或 Codex 的原有终端工具读取，不要为查看日志而把整个私有状态目录加入 `force_allow`。开启非沙箱 Shell 后的边界仍见 README。

多进程追加与轮转使用 OS 文件锁；查看器也参与锁协调。锁等待有上限。磁盘满、权限不足、日志路径为符号链接/多硬链接或锁等待超时时，会向 **stderr** 输出 `LOG_WRITE_FAILED`，不把日志写到 MCP 的 stdout，不因日志失败重试/回滚已完成的业务操作。`doctor` 增加 logging 检查项；日志关闭时显示 warning，写入失败显示 fail。

发生日志故障时业务操作可能已执行，不能仅凭没有日志再次改写文件。日志不提供断电持久性、防篡改或记录零丢失保证。操作系统、宿主客户端、pip、原生 Tunnel 工具和终端录制的日志不由这里完全控制。

## 7. 让 Codex 在本机排查

```text
请用你已有的本机终端工具排查 chatgpt-local-mcp-tunnel，不要依赖故障中的 MCP。
先定位 local-mcp 启动器，运行 logs path，再读取相关分类最近 200 条日志和 ERROR 记录。
按 UTC 时间、process_id、request_id/session_id 关联问题，核对 doctor 的 logging 和其他检查项。
只报告相关的错误码、安全原因和修复建议，不输出 ID/key、配置全文或原始命令输出。
不要把没有日志当作操作没有发生，不因此重复执行写入，不删除未知锁文件或放宽目录权限。
需要导出时使用 logs export，保留已有文件，先审核结果再分享。
```

实现参考：Python [多进程日志说明](https://docs.python.org/3/howto/logging-cookbook.html#logging-to-a-single-file-from-multiple-processes)；MCP [stdio 传输约束](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)。
