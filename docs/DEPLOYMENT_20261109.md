# v0.6.0 发布验收摘要（2026-11-09）

版本 **0.6.0** 已合并并推送 main，发布代码提交为 [d25c111](https://github.com/macgaf/chatgpt-local-mcp-tunnel/commit/d25c111065e415d4d81692b9d918af0d032e1b7a)。[GitHub 三平台 CI](https://github.com/macgaf/chatgpt-local-mcp-tunnel/actions/runs/42550037855) 的 macOS、Ubuntu、Windows 任务均成功，完整测试范围见 [测试报告](../TEST_REPORT.md)。

用户明确授权的本机完整安装、媒体与 stdio 自检、服务切换，以及通过真实插件连接进行的合成文件读写、哈希核对、删除和范围拒绝验证均已完成。

具体本机目录、配置指纹、进程身份、运行实例和备份位置仅保存在本机受保护的详细验收记录中，不随源码分发。项目默认配置仍保持 HOME 只读和空附加目录列表，使用方法见 [附加目录访问](ADDITIONAL_ROOTS.md)。

已持有旧实例的独立 stdio 客户端需要单独重连，才能加载升级后的代码和配置；运行中的 Tunnel、客户端连接和重新登录后的自启分别核验。
