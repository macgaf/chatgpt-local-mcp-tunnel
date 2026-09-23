#!/usr/bin/env bash
set -euo pipefail

TUNNEL_ID="${1:-}"
PROFILE="${2:-home-readonly-mcp}"
LAUNCHER="$HOME/.local/bin/home-readonly-mcp"

if [[ -z "$TUNNEL_ID" ]]; then
  echo "Usage: $0 tunnel_xxx [profile-name]" >&2
  exit 2
fi
if ! command -v tunnel-client >/dev/null 2>&1; then
  echo "ERROR: tunnel-client not found. Install OpenAI tunnel-client first." >&2
  exit 1
fi
if [[ ! -x "$LAUNCHER" ]]; then
  echo "ERROR: $LAUNCHER not found. Run ./install.sh first." >&2
  exit 1
fi
if [[ -z "${CONTROL_PLANE_API_KEY:-}" ]]; then
  echo "ERROR: export CONTROL_PLANE_API_KEY before running this script." >&2
  exit 1
fi

tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile "$PROFILE" \
  --tunnel-id "$TUNNEL_ID" \
  --mcp-command "$LAUNCHER"

tunnel-client doctor --profile "$PROFILE" --explain

echo
echo "Profile created and checked. Start it with:"
echo "  tunnel-client run --profile $PROFILE"
