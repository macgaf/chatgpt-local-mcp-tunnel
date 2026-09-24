# 提示词驱动安装与验收

适用：在用户本机运行、有终端执行权限的 Codex 或其他本地助手。不是让远程聊天凭提示词自动取得本机执行权限。

## 可直接粘贴的提示词

> 请在本机安装并配置当前仓库的 chatgpt-local-mcp-tunnel。先阅读 README、bootstrap.py、skills/local-mcp-setup/SKILL.md。授权根目录 ~/git_local，模式 read_write；不存在时报告实际路径，不猜测。执行 bootstrap.py --plan 后安装，运行真实 self-test，用 codex mcp add 注册并用 list/get 验证；已有同名相同条目则跳过，有冲突不覆盖其他配置。安装官方完整 tunnel-client（包括 cloudflared），核对 SHA256SUMS。通过本机安全方式设置我提供的 Tunnel ID，Runtime key 不得写入提示词、命令参数、项目或普通配置。没有已存凭据时，停在本机交互终端的 key set，不能要求我把 key 发到聊天。随后创建专属 profile，执行 doctor --with-tunnel；缺权限、登录或系统授权时清楚标出阻碍，不绕过。只有真正测试过的层级才能标为通过。最后提供实际启动命令及 ChatGPT App 激活步骤。

## 执行顺序

1. 定位仓库；私有仓库认证缺失时使用用户正常的 GitHub 登录方式，不能索取 token 粘贴到聊天。不要创建替代项目覆盖现有目录。
2. 检查 `python --version`，须 3.11+；Linux 缺 venv 说明发行版包名，由用户确认系统包安装。先执行 `bootstrap.py --plan`。
3. macOS/Linux 用 `./install.sh --root <实际路径> --mode read_write --register-codex --install-client`。Windows 用 `python bootstrap.py` 同参数。已有配置先读取可公开字段；不要打印含密钥的历史配置。
4. 核对安装器输出的 launcher、配置路径和版本。`local-mcp self-test` 必须返回真实进程握手结果。
5. Tunnel ID 已知时 `local-mcp configure --tunnel-id <ID>`；未创建/授权时指出缺项。ID 可以出现在配置中，Runtime key 不可以。`local-mcp key set` 只能在用户本机 TTY 隐藏输入；自动助手没有 TTY 就停这一步。Linux 无桌面使用专门的 systemd 路线。
6. `local-mcp tunnel init`；`local-mcp doctor --with-tunnel`。记录退出码、错误码及修复动作，不能将 warning/not_checked 改写成通过。
7. `local-mcp tunnel run` 是持续前台进程，不适合作为一个无期限阻塞的 Codex shell 调用。用户可在单独终端运行，或明确要求配置 OS 服务。助手不得无授权创建常驻后台任务。
8. 用户在 ChatGPT 选中 Tunnel App 后，调用 policy_info、visual_probe 和只读文件读取。写验收仅在授权后用唯一测试文件，不改现有业务文件。确认图片可见，不要求重复上传现有本机图片。

## 验证级别

| 层 | 可以报告“通过”的证据 |
|---|---|
| 安装 | launcher 实际存在，版本可运行 |
| 本机 MCP | 新子进程实际 initialize/discover、tools/list、tools/call 成功 |
| Codex 注册 | 官方 list/get 返回预期 command/args；不等于当前会话已启用 |
| Tunnel 认证 | 官方 doctor 对当前 ID/key 真实通过 |
| 在线连接 | 运行进程健康，ChatGPT 实际调用该工具 |
| 图片 | visual_probe 字符被视觉模型正确识别，或真实文件图像与用户观测一致 |
| 写入 | 新测试文件真实写入并重新读取、哈希一致 |

## 可选 Computer Use

在客户端已具备并授权 Computer Use 时，可用它导航 Platform 的 Tunnel/工作区关联页面、ChatGPT 的 Developer Mode/App 页面。密钥生成/显示/复制页面交回用户，不截取或转录 key；登录、验证码、系统授权由用户完成。脚本负责文件与配置修改，避免用坐标点击编辑配置文件。

本仓库没有内置桌面遥控组件，不会要求安装不明 Computer Use 扩展，也不会改变 ChatGPT 订阅或跳过权限。

## v0.4 补充

完整安装包含 search/pathspec。安装和升级均保持 enable_commands=false、enable_git_push=false（除非本机此前明确配置）；不要因需求里提到编程就自动开 Shell 或网络推送。获得明确授权后，再按 docs/CODING_TOOLS.md 通过本机 configure 开启。Shell 非沙箱风险确认、远端 URL 白名单与凭据库授权是独立步骤。
