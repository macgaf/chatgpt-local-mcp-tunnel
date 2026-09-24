# v0.3.0 测试报告

执行日期：2026-09-24。执行位置：隔离 Linux 开发容器，不是用户的 Mac。

## 实际结果

```text
python -m compileall -q src bootstrap.py        PASS
bash -n install.sh setup-tunnel.sh             PASS
PYTHONPATH=src pytest -q                       108 passed in 16.22s
python -m home_readonly_mcp.cli self-test       PASS (real subprocess)
```

环境：Linux x86_64，Python 3.13.5，pytest 9.0.2，Pillow 12.3.0，pypdfium2 5.8.0。

| 测试文件 | 用例数 | 范围 |
|---|---:|---|
| test_policy.py | 41 | HOME/项目范围、黑白名单、精确例外、凭据保护、符号链接/硬链接、读写开关 |
| test_service.py | 23 | 创建/改写、SHA 冲突、dry-run、不部分写入、备份/恢复、跨进程锁、OS 错误原因 |
| test_media.py | 15 | 图片真实 ImageContent、EXIF/crop、PDF 文本与渲染、ZIP 过滤/防炸弹、二进制资源分块和版本冲突 |
| test_protocol.py | 12 | 真实 legacy/modern stdio、真实子进程写文件、只读隐藏写工具、参数校验、资源读取 |
| test_onboarding.py | 17 | 凭据接口、防明文降级、超时/脱敏、发行包校验、Codex 幂等注册、Tunnel profile、两次真实离线安装 |

PDF 测试使用程序生成的单页样本；已渲染并目视核查标题及矩形图形，而非只检查提取文字。测试没有调用 OCR，也没有读取用户真实项目或凭据。

## 哪些是真实运行，哪些是模拟

**真实运行：**核心文件系统操作、POSIX 路径保护、跨进程 OS 锁、读写 SHA 校验、备份恢复、图片解码、PDFium 渲染、ZIP 读取、二进制内容还原、stdio 子进程、core-only venv 安装及重复安装。安装在临时 HOME 中，不是修改用户机器。

**使用替身验证：**系统 keystore 的存取接口、Codex CLI 注册（本地 fake executable）、Tunnel init 的 profile 行为、官方发行包校验（人工构造 ZIP+checksum）。systemd 凭据读取使用模拟私有文件，不是实际 systemd 加密服务。

**没有完成的外部验收：**真实 Mac/Windows 文件系统与 OS 凭据库、Linux 原生 Secret Service/systemd daemon、真实 Codex CLI、官方 Tunnel 发行包联网安装与认证、ChatGPT 的 App 发现/图片消费、HEIC 实际解码、完整 MCP 官方 conformance suite。

本容器不能通过包下载/外部 shell 网络完成上述集成。仓库含三平台 CI 配置，但在本报告写入时没有把尚未观察到的 CI 状态计作通过。README 的目标机验收步骤和 visual_probe 用于继续核验这些层级。

## 不应扩大解释的结论

108 项通过不代表没有漏洞；本地 path policy 不等于对同一 OS 用户恶意进程的完整隔离。只读模式没有注册写工具且方法再次校验，但平台是否允许调用、是否把 ImageContent 送到模型仍由宿主决定。

写入是单文件原子替换；对不遵守本服务锁的外部编辑器，没有绝对 compare-and-swap 保证。备份包含原文件真实内容，不能当公开诊断附件。
