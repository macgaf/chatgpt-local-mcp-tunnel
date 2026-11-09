# 文件访问规则

目录授权与文件规则分别检查。`root`、`additional_roots` 决定可访问的位置，`mode`、`write_roots` 决定可写范围；`allow`、`deny`、`force_allow` 是本机明确配置的文件规则。目录授权说明见 [附加目录访问](ADDITIONAL_ROOTS.md)。

## 文件名不用于推测秘密

默认策略不再按文件名、扩展名或关键词推断文件含有秘密。授权项目中的 `credentials.py`、`secrets/module.py`、`.env.example`、`.env`、`.key`、`.pem` 等普通文件，按目录权限和明确配置的文件规则处理。项目里名为 `.ssh`、`.aws` 的目录也不会仅因同名而被拒绝。

这一语义同时适用于直接读取／写入、检索、ZIP 成员和 Git 文件操作。不新增内容扫描或自动秘密分类器，也不需要为普通源码逐个添加 `force_allow`。

默认 `deny` 只排除 Git 内部元数据、依赖／虚拟环境、Python 缓存、回收站和缓存目录：

```json
[
  "**/.git/**", "**/node_modules/**", "**/.venv/**",
  "**/__pycache__/**", ".Trash/**", "Library/Caches/**"
]
```

用户自行配置的 `deny` 继续生效；`include_ignored=true` 只跳过检索忽略规则，不能覆盖文件访问规则。

## 明确的用户级存储位置

本服务仍保护实际 HOME 下已知的用户级凭据存储位置，例如 `~/.ssh`、`~/.aws`、`~/.codex/auth.json`、系统密钥库和浏览器用户数据目录。保护绑定这些具体位置及其启动时解析的链接目标，不对任意项目、附加目录或 ZIP 成员套用同名匹配。缩小授权根或配置 `force_allow` 不能解除这些位置的保护。

`policy_info` 返回 `credential_protection="explicit_user_paths"` 和 `protected_credentials` 的具体路径列表。命中时，`POLICY_DENIED` 的 `matched_rule` 指明实际受保护位置；命中自定义 `deny` 时则返回对应配置规则。

MCP 自身配置、程序和私有状态继续不可通过文件工具访问。链接检查、普通文件限制、大小预算、SHA 前置条件、文件锁、备份与写后验证保持有效。Git 元数据仍由专用 Git 工具检查，ZIP 仍拒绝路径跳转、链接、加密条目和超限内容。

## 已有配置如何生效

新默认值不会静默覆盖已有 `config.json` 中明确保存的 `deny`。旧安装可能已经把旧默认值写入配置，因此仅升级源码仍可能拦截普通源码。

在用户授权移除此类旧规则后，由本机管理流程备份配置，检查并删除旧的文件名推测项：`.env`／`.env.*`、`*.pem`／`*.key`／`*.p12`／`*.pfx`、`*credentials*`、`secrets/**`、Shell／Python 历史文件以及 `.config` 中按 `tokens*`、`secrets*`、`auth.json` 匹配的规则。保留用户另行指定的规则和其他配置；不要用新默认列表覆盖整个已有策略。

重新安装并重启自己管理的 MCP/Tunnel 实例后，核对 `policy_info` 的实际规则，再用合成源码文件验证。Codex stdio 与 Tunnel 的运行实例需分别重连或重启；源码测试或启动器更新不表示所有旧连接已切换。
