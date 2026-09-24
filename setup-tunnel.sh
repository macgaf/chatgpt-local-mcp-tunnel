#!/usr/bin/env bash
set -euo pipefail
CLI="$HOME/.local/bin/local-mcp"
[[ -x "$CLI" ]] || { echo 'Run ./install.sh first.' >&2; exit 1; }
[[ $# -eq 1 ]] || { echo 'Usage: ./setup-tunnel.sh tunnel_<32 hex characters>' >&2; exit 2; }
"$CLI" configure --tunnel-id "$1"
"$CLI" key set
"$CLI" tunnel init
"$CLI" doctor --with-tunnel
echo "Start the tunnel with: $CLI tunnel run"
