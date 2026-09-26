# Repository work rules

## 项目变更与 GitHub 同步

除非用户特别说明，本项目的变更均针对 `macgaf/chatgpt-local-mcp-tunnel`，包括代码、README、提示词、Skill、配置样例及安装、日志、排错说明。应同步修改仓库中的相关文件，而不是只交付聊天内容或下载附件。

交付前检查目标分支与现有修改，完成适用的检查，再提交、推送并读取远端确认。报告实际分支、提交和未完成项；推送失败或尚未执行时，明确写“尚未同步 GitHub”。

文档和代码的发布状态须分别标明。尚未验收的修复继续保留在对应分支或草稿 PR；同步要求不代表自动合并、强制推送、删除分支或更新用户部署。用户明确要求仅讨论或不要提交时按该范围处理。

`docs/prompts/setup-with-computer.txt` 是电脑工具版完整提示词的仓库入口。修改提示词时，同步检查 README、安装指南和 Skill，避免保留互相矛盾的版本。

Read README.md and TEST_REPORT.md before claiming a feature is installed or verified.

Keep the stdio core dependency-free. Optional media and keyring imports must remain lazy and return actionable errors when unavailable.

Default to HOME read_only. Do not add remote tools that mutate policy, credentials, trusted adapters, installers, or this server's own runtime. Do not disguise writes as read-only tools. Never request real secrets in prompts or tests.

Use temporary HOME directories and synthetic files for tests. Run `python -m pytest -q` and the real `python -m home_readonly_mcp.cli self-test`. Do not claim mock keyring/Codex/Tunnel tests validate actual platforms or cloud connectivity.

MCP image results must contain ImageContent, not Base64 text pretending to be an image. Resource URIs are not sandbox paths. Keep source hashes, limits, EXIF/crop coordinate metadata and explicit truncation.

No blind overwrite. Preserve SHA preconditions, per-path OS lease, backups and post-write verification. Do not remove live lock files or kill foreign processes.

Installation must preserve other tools/configurations, remain rerunnable and never fall back to plaintext secret storage. System/package-manager permissions require user approval.

For v0.4 coding tools, read docs/CODING_TOOLS.md. Keep shell execution and Git push OFF by default; never claim root/deny rules sandbox an opted-in shell. Git uses fixed argv and guarded metadata, with separate push URL authorization. Run native Git/command tests in synthetic repositories, never push to the user's real remote during tests.

Cross-file patches must prevalidate all edits, lock in deterministic order, and never overwrite external changes during rollback. Preserve legacy apply_patch arguments. Batch reads must prevalidate a fixed read-only allowlist. User regex must run in the timeout-isolated worker, not in the MCP dispatcher. Verify actual exit codes, cursor exhaustion and child cleanup.
