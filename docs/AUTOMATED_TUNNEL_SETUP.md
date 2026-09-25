# Tunnel 自动准备：实际本机入口与验收边界

## 为什么之前的提示词没有完成任务

此前文档只让 Codex 临时拼出浏览器→凭据库程序，没有交付可执行的转存入口。执行记录还出现了两个独立失败：浏览器文件输出路径被 roots 拒绝，转用 Apple Events 又遇到 macOS 授权拒绝；权限菜单虽被点击，最终仍为 `Tunnels / None`、`0 selected permissions`。Keychain 的虚构值测试反而已经通过。

因此，增加提示词长度或只批准 Apple Events 都不能保证成功。现在提供固定的本机管理入口：

```bash
local-mcp tunnel prepare --stage preflight
```

**实现与限制：**已实现私有 stdio 浏览器通道、凭据库预检、Tunnel 绑定缓存、权限实际状态检查、已准备表单的提交/保存和读取认证。不是承诺一条命令自动完成任意网站界面的账号选择、所有表单填写或权限审批。站点适配器采取保守识别，页面结构/选中状态无法证明时返回明确错误，不盲目提交。当前真实 Chrome 连接及页面适配需要在目标机验收，合成页面测试不能代替它。

## 1. 两条通道，不让模型转录密钥

```text
Codex：公开控件标签、目标名称、操作步骤、固定状态

本机 Python 程序
  ├─ 以用户已有 Codex 配置启动官方 Chrome DevTools MCP 私有子进程
  ├─ 在该子进程的 stdin/stdout 管道内处理浏览器返回值
  ├─ 在本机内存中将新 key 写入 native keystore 并读回比较
  └─ 返回固定状态字段；不返回原始 DOM、截图、网络响应或 ID/key
```

不使用 `evaluate_script.filePath`，不产生装有明文 key 的临时 JSON，不扫描调试端口，不导出 Cookie，不启用 Apple Events，不添加不受限文件路径或忽略证书的选项。调试/性能统计关闭；私有子进程的原始输出和错误不写入日志。

浏览器沿用用户已配置的官方 `chrome-devtools-mcp` 和 `--autoConnect`，保留已配置的 channel/userDataDir；npx 仅使用本机已有缓存，不偷偷升级。只有普通浏览器工具已授权，不等于新本机程序已经获得 Chrome 的调试连接批准。

**真实 ID/key 不通过工具参数转发输入或返回给模型。** 本机程序内部的读取和保存不是泄露到模型；但不能承诺浏览器、操作系统、底层依赖完全零留痕。

## 2. 先跑完整的预检，再碰创建按钮

```bash
local-mcp tunnel prepare --stage preflight
```

预检分别检查 native keystore、Chrome 实际连接，以及浏览器生成虚构值→进程内存→凭据库→读回→清理测试条目的端到端通路。一个检查失败不掩盖另外的结果。它不创建 Tunnel/key，不更改 root、读写、Shell 或 Git 推送。

主要错误：

| 错误码 | 意义和处理 |
|---|---|
| `CHROME_DEBUG_ENDPOINT_MISSING` | 官方 autoConnect 找不到 DevToolsActivePort。本人在 Chrome `chrome://inspect/#remote-debugging` 确认调试授权，然后重跑；不是给 Python/Terminal 添加 Apple Events 权限 |
| `CHROME_CONNECTION_OR_APPROVAL_REQUIRED` | Chrome 未连接或正在等本人批准。不会改端口/复制会话绕过 |
| `KEYSTORE_UNAVAILABLE` | 当前解释器缺少 keyring 或没有可用系统凭据库。使用完整安装虚拟环境；无桌面 Linux 保留原 systemd 方案 |
| `TRANSFER_PROBE_FAILED` | 虚构值的端到端传输失败，禁止继续生成真实 key |
| `BROWSER_CONFIGURATION_AMBIGUOUS` | 多个可用官方浏览器配置，需要明确选定，不自行换浏览器身份 |

没有安装全局启动器时，可以在已安装项目依赖的开发虚拟环境中运行：

```bash
python -m home_readonly_mcp.cli tunnel prepare --stage preflight
```

这里的 python 必须来自该虚拟环境。不要把开发环境中的 editable 安装称为已安装常驻 MCP、已注册 Codex 或已连接 ChatGPT。

## 3. 目标选择与 Tunnel 缓存

组织、Platform 项目和 ChatGPT 工作区是三件事，`Default project` 不证明 ChatGPT 工作区已确认。已有明确选择复用，确有歧义才按名称问一次。不抢占仍服务于 FileMCP 的 Tunnel；默认只处理名为 `chatgpt-local-mcp-tunnel` 的专用资源。

Codex 可继续使用已授权浏览器帮助用户导航/选择公开控件，但不要把包含 ID 的整页快照返回到对话。最终 ID 读取与本机保存交给本机入口：

```bash
local-mcp tunnel prepare --stage cache-tunnel --confirm-target
```

`--confirm-target` 表示操作者已确认目标组织/ChatGPT 工作区，不是让程序凭空认定当前组织正确。只有唯一同名 Tunnel 且观察到组织和工作区关联时缓存；已有不同的本机绑定不覆盖。可使用 `--tunnel-name` 指定用户确认的公开名称，参数不接受真实 ID。

不存在时，在网页准备新建 Tunnel 的名称、组织和工作区表单，确认目标后，由本机进程完成最终提交和读取：

```bash
local-mcp tunnel prepare --stage submit-tunnel --allow-create --confirm-target
```

提交前要求可观察的名称与范围字段，提交后核对关联。无法解析控件、出现多个同名资源、范围无法对应或创建结果不明时停止，不再次创建。此阶段不负责替用户授予组织权限；本版也没有不受限的自动填写入口。

绑定直接保存到运行器实际读取的 `config.json`，保留现有 root/mode/write_roots/日志/其他设置；不再仅生成运行器不会读取的临时 status.json。

## 4. Runtime key：实际选中状态，不是点击计数

先在正确组织/项目下打开创建 Runtime key 表单。需要权限仅为 Restricted → Tunnels Read + Use，其他资源为 None。可让本机入口选择并检查 Tunnels 权限：

```bash
local-mcp tunnel prepare --stage permissions
```

它在每次点击后重新获取控件；菜单关闭时重新打开，不复用过期元素。提交门槛同时要求：

- Restricted 实际选中；Read 和 Use 都有明确 checked/selected 状态。
- 选择总数为 2，其他资源权限均为 None，项目已选。
- 界面可观察且字段唯一。

`permissionOptionsClicked=2` 不满足任何提交门槛；实际仍为 None/0 时返回 `PERMISSION_SELECTION_NOT_APPLIED` 或 `PERMISSION_PROOF_INCOMPLETE`，不会尝试全权限 key，也不会宣称配置成功。

最终创建、捕获、保存和读回在同一个本机程序内进行：

```bash
local-mcp tunnel prepare --stage submit-key --allow-create
```

默认专用名称为 `chatgpt-local-mcp-tunnel-runtime`，可用 `--key-name` 提供另一个已确认的公开名称。没有 `--allow-create` 不提交创建。不会把 key 返回给 Codex 再调用另一个工具保存。

程序先做 Keychain/Credential Manager/Secret Service 的虚构值探针，保存一份无 key 正文的创建进度记录，再提交一次。浏览器内的临时标记只绑定这次创建的结果弹窗；重试不应收集随后打开的无关密钥弹窗。新 key 正文只进入系统凭据库，保存后读回比较；弹窗不被自动关闭。

原有 `systemd`/`environment` 来源不会自动迁移为 keyring。旧 key 只有掩码且本机没有完整值时不能恢复；也不扫描其他应用的整个凭据库。

## 5. 恢复、复用及认证

创建状态写在受保护的 `browser-preparation.json`，不含 key 正文。已有创建未完成先恢复同一结果弹窗；没有对应所有权标记、页面已刷新或结果不明时返回 `CREATION_OUTCOME_UNCERTAIN`，不再次点击创建、不自动撤销资源。保存失败时保留原配置，不因 Keychain 锁定、网络超时或 403 重新生成 key。

本机已有 key 时不会覆盖。与本工具保存的创建记录和凭据指纹一致时可复用，返回 `permission_verification=saved_creation_receipt`；这不是当前网页权限的新检查。外部改过权限或记录不匹配时，需要重新核查，不伪称已验证最小权限。

```bash
local-mcp tunnel prepare --stage verify
```

读取认证使用本机存储的值请求官方单个 Tunnel 元数据端点，拒绝重定向，不调用付费模型 API。成功最多证明此请求的 Read 认证和目标对应；**Use 认证和 ChatGPT 连接仍标为未检查**。安装 MCP 后继续 `tunnel init` 和 `doctor --with-tunnel`，再做 ChatGPT 实际工具调用验收。

## 6. 给本机 Codex 的执行指令

```text
在当前修复版本的 chatgpt-local-mcp-tunnel 中完成 Tunnel 准备，使用已实现的本机入口，不再临时拼接 AppleScript/明文文件转存。

1. 保留已有目录/模式/凭据来源。使用项目完整虚拟环境实际运行 tunnel prepare --stage preflight；必须核对每项状态。Chrome 调试连接等待本人授权时，只暂停该项；不要把 Keychain 已通过说成浏览器也已通过。
2. 目标组织、Platform 项目和 ChatGPT 工作区分别确认；已有选择复用，不占用正在运行的 FileMCP Tunnel。浏览器非敏感控件可由你导航，最终 ID/key 值只能走本机私有进程。
3. 专用 Tunnel 已有时用 cache-tunnel 缓存；没有时准备正确网页表单，再用 submit-tunnel --allow-create --confirm-target 提交并缓存。没有真实目标确认不能加 confirm-target。
4. 为缺失的专用 key 准备 Restricted 表单，运行 permissions。只有 Read/Use 真实选中、总数2且其他权限None才继续 submit-key --allow-create；点击次数不是证据。
5. 记录或保存失败后恢复原创建，不重复创建；已有可用缓存优先复用。所有值不通过工具参数转发输入，不返回原始 DOM、截图、API 响应或密钥。
6. 最后分别报告绑定、权限证据、保存/读回、Read认证、Use认证和客户端调用，不把局部通过当成整体完成。页面适配器不识别时报告具体阶段，不能关闭验证硬凑成功。
```

## 本轮验证范围

单元/进程测试覆盖私有 stdout、不用文件转存、权限点击无效、整套权限门槛、保存失败后不重复创建、未知错误不泄露凭据、设置保留和已有缓存复用。目标机的 native Keychain 虚构值测试已执行。

实际 Chrome 预检若返回 `CHROME_DEBUG_ENDPOINT_MISSING`，说明网站状态还没有读取验证，不能声称表单适配器、真实资源创建和认证已验收。以 `TEST_REPORT.md` 和当前预检输出为准，不沿用旧 CI 代替新增代码验证。
