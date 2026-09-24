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
