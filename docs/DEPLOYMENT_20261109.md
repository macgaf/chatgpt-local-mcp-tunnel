# v0.6.0 发布验收摘要（2026-11-09）

## 文件访问规则修订

文件名误拦截修复 [473a7aa](https://github.com/macgaf/chatgpt-local-mcp-tunnel/commit/473a7aad87dd2c98aca9263bcf218c7f5af99a0c) 已合入并推送 main，基础版本保持 **0.6.0**。该代码提交的 [三平台 CI](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/42582123571) 全部通过；规范与需求两轴独立复核均无阻塞发现，完整结果见 [测试报告](../TEST_REPORT.md)。

用户授权的本机完整安装与服务切换已完成；27 个安装源码文件与已测试源码逐字节一致，配置内容完全保留。媒体与 stdio 自检通过，10 项 doctor 检查全通过，服务的回环健康端点返回 200。已核实的旧服务进程及其受控后代全部退出，新服务运行更新后的安装。

实际安装启动器的 stdio 验收覆盖四种此前被误拦截的合成源码名称：读取、SHA 保护写入与回读、搜索、ZIP 成员、新建删除均通过，合成文件已清理。当前会话的 ChatGPT Tunnel 连接器不可调用，因此本修订未完成 ChatGPT 端回调复测；本机 stdio、doctor 和健康检查不替代该项验收。独立持有旧进程的客户端仍需重连。

规则与已有显式 deny 的处理见 [文件访问规则](FILE_ACCESS_POLICY.md)。具体目录、配置指纹、进程、运行实例和备份记录仅存本机受保护位置，不随源码分发。

## 附加目录首次发布记录

以下保留本日较早发布的验收范围：版本 **0.6.0** 已合并并推送 main，发布代码提交为 [d25c111](https://github.com/macgaf/chatgpt-local-mcp-tunnel/commit/d25c111065e415d4d81692b9d918af0d032e1b7a)。[GitHub 三平台 CI](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/42550037855) 的 macOS、Ubuntu、Windows 任务均成功，完整测试范围见 [测试报告](../TEST_REPORT.md)。

用户明确授权的本机完整安装、媒体与 stdio 自检、服务切换，以及通过真实插件连接进行的合成文件读写、哈希核对、删除和范围拒绝验证均已完成。

具体本机目录、配置指纹、进程身份、运行实例和备份位置仅保存在本机受保护的详细验收记录中，不随源码分发。项目默认配置仍保持 HOME 只读和空附加目录列表，使用方法见 [附加目录访问](ADDITIONAL_ROOTS.md)。

已持有旧实例的独立 stdio 客户端需要单独重连，才能加载升级后的代码和配置；运行中的 Tunnel、客户端连接和重新登录后的自启分别核验。
