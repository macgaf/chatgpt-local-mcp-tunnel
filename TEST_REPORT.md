# Test report

## Result

- Policy/service unit tests: **22 passed**
- Python compile check: passed
- `install.sh` shell syntax: passed
- `setup-tunnel.sh` shell syntax: passed

Run locally with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Covered cases

- HOME boundary enforcement
- `../` path traversal rejection
- absolute path escape rejection
- symlink escape rejection
- symlink-to-HOME target acceptance
- listing/search safely skips symlinks that resolve outside HOME
- deny / allow / force_allow precedence
- `.ssh` denial
- `.env` denial
- `.env.example` force-allow
- denied files hidden from directory listing
- denied files excluded from text search
- binary file content rejection
- UTF-8 text reads
- line-range reads
- filename search
- text search
- SHA-256 metadata

## MCP runtime validation note

The execution container used to build this package has no outbound package-network access, so it could not install `mcp==2.2.0` and perform a live MCP handshake here. The server is written against the current official MCP Python SDK v2 API (`MCPServer`, `ToolAnnotations`, `mcp.run()`), and the package pins `mcp==2.2.0` for installation on the target Mac.
