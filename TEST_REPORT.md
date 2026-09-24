# v0.4.0 验证记录

日期：2026-09-24。基线为 PR #1 提交 018a86d；本轮增加 Git、命令执行、代码检索、批量读取及跨文件补丁。

## 本轮实际本地执行

在隔离 Linux 环境、临时 HOME 和临时仓库中运行：

| 分组 | 实际结果 |
|---|---|
| 原有 policy/protocol/service/media + 跨文件补丁 | 101 passed |
| Git 与命令会话（不含下述完整工作流个案） | 33 passed |
| 安装/凭据/Tunnel 管理回归 | 19 passed |
| 搜索/批量与完整编程工作流 | 17 passed |
| compileall 与真实 stdio self-test | 通过 |

合计 **170 个测试通过**，分组运行避免开发工具单次执行时限；不是把被工具超时中止的完整测试进程计为成功。完整 pytest 由 GitHub CI 再验证。

新增真实验证包括：本地 Git init/status/log/diff/add/commit；关闭 hooks/外部 diff；拒绝 filter/include/alternate/gitdir 及敏感暂存路径；Shell 创建文件、真实退出码、超时、取消、自有子进程/EOF 清理、输出环形缓冲与游标、去重、工作区相交门控；真实独立正则 worker 与实际超时；忽略文件和代码排序；跨文件预检、失败注入回滚、不覆盖外部修改。

完整工作流个案：仓库中有错误的 add 函数 → workspace_context/search_code/batch_read → apply_patch 修复 → run_command 执行断言测试 → git_diff/add/commit；实际完成。

**替身/边界：**Git push 的最终网络调用只检查固定 URL/refspec/权限构造，没有向真实远端发送用户项目。继承自 v0.3 的真实 Tunnel、系统 keystore、ChatGPT 图像消费、目标机安装验收仍未替代。命令不是 OS 沙箱，Git 安全模式不支持所有特殊仓库布局；跨文件补丁不是崩溃原子事务。

GitHub CI 状态将在本轮提交后按实际结果补记；此处尚未把未执行结果计为通过。

---

## 历史 v0.3 报告

# v0.3.0 测试报告

执行日期：2026-09-24。本地执行位置：隔离 Linux 开发容器；另有三平台 GitHub Hosted Runner 验证，均不是用户的目标机器。

## 实际结果

```text
python -m compileall -q src bootstrap.py        PASS
bash -n install.sh setup-tunnel.sh             PASS
PYTHONPATH=src pytest -q                       112 passed in 16.35s
python -m home_readonly_mcp.cli self-test       PASS (real subprocess)
```

环境：Linux x86_64，Python 3.13.5，pytest 9.0.2，Pillow 12.3.0，pypdfium2 5.8.0。

| 测试文件 | 用例数 | 范围 |
|---|---:|---|
| test_policy.py | 41 | HOME/项目范围、黑白名单、精确例外、凭据保护、符号链接/硬链接、读写开关 |
| test_service.py | 24 | 创建/改写、SHA 冲突、dry-run、不部分写入、备份/恢复、跨进程锁、OS 错误原因 |
| test_media.py | 15 | 图片真实 ImageContent、EXIF/crop、PDF 文本与渲染、ZIP 过滤/防炸弹、二进制资源分块和版本冲突 |
| test_protocol.py | 13 | 真实 legacy/modern stdio、真实子进程写文件、只读隐藏写工具、参数校验、资源读取 |
| test_onboarding.py | 19 | 凭据接口、防明文降级、超时/脱敏、发行包校验、Codex 幂等注册、Tunnel profile、两次真实离线安装 |

PDF 测试使用程序生成的单页样本；已渲染并目视核查标题及矩形图形，而非只检查提取文字。测试没有调用 OCR，也没有读取用户真实项目或凭据。

## 哪些是真实运行，哪些是模拟

**真实运行：**核心文件系统操作、POSIX 路径保护、跨进程 OS 锁、读写 SHA 校验、备份恢复、图片解码、PDFium 渲染、ZIP 读取、二进制内容还原、stdio 子进程、core-only venv 安装及重复安装。安装在临时 HOME 中，不是修改用户机器。

**使用替身验证：**系统 keystore 的存取接口、Codex CLI 注册（本地 fake executable）、Tunnel init 的 profile 行为、官方发行包校验（人工构造 ZIP+checksum）。systemd 凭据读取使用模拟私有文件，不是实际 systemd 加密服务。

**没有完成的外部验收：**用户目标 Mac/Windows 的部署和 OS 凭据库、Linux 原生 Secret Service/systemd daemon、真实 Codex CLI、官方 Tunnel 发行包联网安装与认证、ChatGPT 的 App 发现/图片消费、HEIC 实际解码、完整 MCP 官方 conformance suite。

本容器不能通过包下载/外部 shell 网络完成上述集成。仓库含三平台 CI 配置。首轮远程执行中 macOS、Ubuntu 的测试和 stdio self-test 通过；Windows 的真实执行揭示了 UTF-8 管道解码、测试换行及 Linux-only systemd 测试范围问题。已按日志修复并新增回归测试；修复提交 `4d9982d5d172680097c35edf11ab5f32c69942bb` 的三平台远程测试与 stdio self-test 已全部通过。README 的目标机验收步骤和 visual_probe 用于继续核验这些层级。

## 不应扩大解释的结论

112 项通过不代表没有漏洞；本地 path policy 不等于对同一 OS 用户恶意进程的完整隔离。只读模式没有注册写工具且方法再次校验，但平台是否允许调用、是否把 ImageContent 送到模型仍由宿主决定。

写入是单文件原子替换；对不遵守本服务锁的外部编辑器，没有绝对 compare-and-swap 保证。备份包含原文件真实内容，不能当公开诊断附件。

## 首轮跨平台 CI 与修复记录

首轮执行：[GitHub Actions run 35954821341](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/35954821341)。macOS、Ubuntu 通过；Windows 为 99 passed / 6 failed / 3 skipped。失败没有被隐藏或用降低权限检查解决：

- MCP 管道明确使用 UTF-8 解码，不依赖 Windows 默认 cp1252。
- 文本样本用固定 LF 字节；新增实际 CRLF 读取、精确编辑及备份恢复保持原始字节的测试。
- systemd 凭据来源明确仅限 Linux；非 Linux 明确拒绝，并按平台限定对应测试。

修复后本地 Linux 共 112 项通过。Mac/Windows 的跳过项目为平台专用测试，不代表真实原生密钥库或云端认证已测试。

## 修复后的远程 CI 实际结果

验证提交：`4d9982d5d172680097c35edf11ab5f32c69942bb`。执行：[run 35955350897](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/35955350897)。

| GitHub Hosted Runner | pytest 步骤 | 真实 stdio self-test | Job |
|---|---|---|---|
| macos-latest | success | success | 107492403108 |
| ubuntu-latest | success | success | 107492403422 |
| windows-latest | success | success | 107492403438 |

以上状态已通过 GitHub Jobs API 实际读取，非推测。pytest 包含平台限定的 skip：systemd 凭据只在 Linux 测试；Windows 跳过 POSIX shebang、POSIX 安装包装器及需要额外权限的 symlink 用例。没有通过删去安全断言或关闭编码检查来让 Windows 通过。

这证明相关代码在三种 Hosted OS 上完成了上述自动化步骤，不等于已在用户的三台机器部署，也不等于三个原生凭据库或 ChatGPT/Tunnel 云端链路已经认证。此后的报告/说明更新不改变该已验证代码。
