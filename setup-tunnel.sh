#!/usr/bin/env bash
set -euo pipefail
CLI="$HOME/.local/bin/local-mcp"
[[ -x "$CLI" ]] || { echo 'Run ./install.sh first.' >&2; exit 1; }
[[ $# -eq 0 ]] || { echo 'Run ./setup-tunnel.sh without arguments; enter ID/key interactively.' >&2; exit 2; }
"$CLI" tunnel configure
if ! "$CLI" key status; then
  echo 'Credential check failed. Unlock the keystore, or run local-mcp key set in your local terminal, then rerun this script.' >&2
  exit 1
fi
"$CLI" tunnel init
"$CLI" doctor --with-tunnel
echo "Start the tunnel with: $CLI tunnel run"
