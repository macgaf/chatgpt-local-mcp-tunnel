# Repository work rules

Read README.md and TEST_REPORT.md before claiming a feature is installed or verified.

Keep the stdio core dependency-free. Optional media and keyring imports must remain lazy and return actionable errors when unavailable.

Default to HOME read_only. Do not add remote tools that mutate policy, credentials, trusted adapters, installers, or this server's own runtime. Do not disguise writes as read-only tools. Never request real secrets in prompts or tests.

Use temporary HOME directories and synthetic files for tests. Run `python -m pytest -q` and the real `python -m home_readonly_mcp.cli self-test`. Do not claim mock keyring/Codex/Tunnel tests validate actual platforms or cloud connectivity.

MCP image results must contain ImageContent, not Base64 text pretending to be an image. Resource URIs are not sandbox paths. Keep source hashes, limits, EXIF/crop coordinate metadata and explicit truncation.

No blind overwrite. Preserve SHA preconditions, per-path OS lease, backups and post-write verification. Do not remove live lock files or kill foreign processes.

Installation must preserve other tools/configurations, remain rerunnable and never fall back to plaintext secret storage. System/package-manager permissions require user approval.
