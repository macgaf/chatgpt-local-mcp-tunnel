# v0.4.1 合并、重新安装与 Tunnel 重启验收

本文是 2026-09-27 的历史部署快照，版本、工具数量和客户端待办均仅对应当时实例；不作为 v0.5.0 或当前在线状态的证明。当前源码能力见 [Git 能力说明](GIT_CAPABILITIES.md)，代码验证见 [测试报告](../TEST_REPORT.md)。

本次根据用户明确授权执行。未创建新 Tunnel/key，未更改权限或接管 FileMCP。

## 发布与安装

PR #3 已合并到 main，合并提交 `2bb42104b5091a68d1b31f6954ed157db1f299aa`；合并树与三平台通过的最终修复提交 `f6ef1641ebf690f6d435932ca02c8b63ff174560` 一致。原开发分支和工作树保留，本机 main 只做快进。

先执行安装计划并在本机私有状态目录保存旧配置、版本指针和启动器的回退备份，再运行完整 bootstrap 安装器，保留原媒体/search/keyring 组件。安装后的20个 Python 源文件与合并源码逐文件一致。没有用 core-only 降级安装，没有升级无关的 tunnel-client。

## 配置保持

新旧配置比较只有 installed_version 从0.4.0变为0.4.1；root、read_write、write_roots、文件规则、凭据来源、Tunnel绑定、日志和命令/推送开关不变。Shell与Git推送仍关闭。LaunchAgent文件、稳定启动器及Codex配置校验保持一致，Keychain原条目复用。

旧版本目录与私有回退备份保留，不把配置或凭据正文提交到仓库。

## 重启与实际验证

通过既有的 `com.macgaf.chatgpt-local-mcp-tunnel` LaunchAgent 执行 kickstart -k；主进程PID已改变，运行状态恢复，health-url由新进程刷新并可访问。没有停止或重启 FileMCP。未实际注销/重新登录，因此登录后自动启动不在本次实测范围；原 RunAtLoad / KeepAlive 配置未改变。

已安装版本的 doctor --with-tunnel 返回退出码0，日志、配置、能力、stdio握手、媒体依赖、runtime_key、tunnel_doctor等检查均pass。

ChatGPT经真实Tunnel调用：

- policy_info 返回 server_version=0.4.1、tool_count=36、file_write_enabled=true、git_branch_create_enabled=true、git_branch_switch_enabled=true；Shell和推送仍false。
- git_status 成功读取此前被 extensions.worktreeConfig 拦截的 ceb-mon-admin；没有修改该业务仓库，也未处理其中原有未跟踪文件。
- write_file 在专门临时验收目录实际创建测试文件，read_file读回内容和SHA-256一致；随后只删除自己创建且内容校验通过的两个临时文件及空目录。

这不是仅安装目录自检，也不是dry-run；上述旧入口已有真实远程调用证据。

## 客户端工具目录仍需刷新

服务端已注册36个工具，但本次聊天的App工具发现仍未列出新增的 git_branches / git_create_branch / git_switch_branch 签名，因此没有声称这三个新入口已在本聊天调用成功。当前提供的插件管理接口没有Refresh动作，也未发现可操作现有浏览器的已连接工具；没有冒充已经点击。

请在ChatGPT Plugins中打开本连接，选择Refresh，确认目录包含36个工具，再用新会话验收三个入口。这是客户端元数据更新，不需再次安装或更换Tunnel。依据：[官方Refresh流程](https://developers.openai.com/plugins/deploy/connect-chatgpt)。

运行安装版本不受本补记的文档提交影响：后续仅更新发布说明和验收记录，没有改变已测试、安装的Python代码。
