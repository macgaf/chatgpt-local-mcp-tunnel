# 提示词驱动安装与验收

完整可复制提示词见 [README 第 3.2 节](../README.md#install)，网站、排错和客户端验收见第 3.1、3.3、3.4、3.5 节。本文补充执行规则，不另维护一份固定个人目录和权限的安装模板。

## 源码来源与已有安装升级

安装与升级统一使用 `main`；v0.4.0 的编程能力、交互安装和日志修订已纳入主线。`feat/local-mcp-v0.3` 仅保留为开发历史，不再要求用户回退到它。

优先复用现有仓库，核对 origin、当前分支、HEAD 和工作区状态。仅在没有未提交修改、未完成合并且本地 main 可快进时更新；脏工作区或本地分叉先让用户处理，不自动 stash、reset、clean 或删除分支。源码更新后要重新运行完整安装器，再由用户重启自己管理的运行实例；不能把 git pull 当成已安装版本更新。记录源码 SHA，因为这些修订仍使用同一 `0.4.0` 版本号。

首次安装先确认下面的目录／权限选项；升级复用已确认的配置、凭据和日志设置，不打印配置全文、不自动开关现有权限。README [第 3.7 节](../README.md#upgrade) 提供升级提示词。

## 先交互选择，再执行安装

目录默认候选是 `~/`（等同 `~/.`），也可由用户指定其他目录。模式在 `read_only`、`read_write` 之间由用户选择；已在对话中明确的选项不重复问。读写模式下再确认 write_roots；HOME 全范围可写需要明确确认。命令执行和 Git 推送保持关闭。

用户确认后，检查现有仓库、脏工作区、Python 3.11+、Git和Codex。以同样的非敏感 root/mode 参数先运行 `bootstrap.py --plan`，再用 macOS/Linux 的 `install.sh` 或 Windows 的 `python bootstrap.py` 安装完整组件。权限不足或缺系统依赖时说明并征求授权，不自行 sudo，不覆盖已有修改和其他 MCP 配置。

## ID 和 key：独立终端交互，不进入聊天

安装器给出的 local-mcp 绝对路径加以下子命令即可；实际值不拼进任何命令：

```text
local-mcp tunnel configure
local-mcp key status
local-mcp key set
```

`tunnel configure` 是本机管理入口，不是远程 MCP 工具。用户亲自隐藏输入 ID，已有正确值可回车保留；只改变 Tunnel 关联，不改变 root/mode/write_roots。`key status` 只检查凭据状态；只有缺少凭据且用户选择录入时才运行 `key set`，将 key 隐藏录入系统凭据库。

不要让模型读取值后通过 write_stdin/工具参数、echo、环境变量赋值或生成的脚本源码中转。Codex 有 PTY 不等于允许把凭据送入其对话记录；本人应使用不由助手记录输入的独立终端。无 TTY 或隐藏输入失败就停止这一步，不回退明文。

ID 必须保存在受保护的本地配置/profile，key 按 keystore 策略保存；本工具输出会脱敏 ID/key，但不保证第三方 Tunnel 工具、OS审计或终端录制不留痕。不要打印原始配置或提交这些文件。Linux 无桌面路线见 [Linux 凭据](LINUX_CREDENTIALS.md)。

## 用户输入后继续完成

运行 `self-test`，ID及凭据就绪后运行 `tunnel init` 和 `doctor --with-tunnel`；没有凭据时先完成可独立进行的本机自检、Codex 注册和媒体依赖检查。真实错误或未检查项目不得报告为通过。

`tunnel run` 在初始化、诊断通过后由独立终端运行，不自动添加常驻服务或开机启动。实例不在线时 ChatGPT 不能访问；Codex stdio 本地连接不依赖 Tunnel。

## 验收证据

| 层级 | 通过条件 |
|---|---|
| 安装 | 启动器实际存在，版本可运行 |
| 本机 MCP | 实际 stdio 握手、工具发现和读取成功 |
| Codex | list/get 注册正确，新会话实际调用 policy_info |
| Tunnel | 对本机保存的 ID/key 运行官方诊断并通过，不显示其正文 |
| ChatGPT | 选中相应 App 后实际调用工具 |
| 图片 | 当前视觉模型正确识别 visual_probe，而非仅返回 Base64 |
| 写入 | 仅在用户选择读写且授权验收后，新建测试文件并读回校验 |

## 可选 Computer Use

仅在本机助手确实有获授权的浏览器/Computer Use 时用于页面导航。会显示或复制真实 ID/key 的步骤交由本人完成，不截图、不转录、不输出到聊天。登录、验证码和系统权限确认也由本人完成。无界面工具时不要假称已代办。


## 安装后的日志入口

安装器会打印日志目录；无论成功还是失败，都可用实际启动器执行 `local-mcp logs path`、`logs show --component install` 和 `logs show --level ERROR`。安装前的 `--plan` 不建立日志；Python/脚本未能启动的错误仍看终端原始报错，不能假称已有持久记录。最后报告应包含实际日志位置和查看命令，不附 ID/key。详见 [日志说明](LOGGING.md)。
