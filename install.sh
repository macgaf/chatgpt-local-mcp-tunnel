#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found" >&2
  exit 1
fi

PY_VER="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required")
PY

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/share/home-readonly-mcp"
CFG_DIR="$HOME/.config/home-readonly-mcp"
BIN_DIR="$HOME/.local/bin"

mkdir -p "$APP_DIR" "$CFG_DIR" "$BIN_DIR"
rm -rf "$APP_DIR/app"
cp -R "$SRC_DIR" "$APP_DIR/app"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/python" -m pip install --upgrade pip >/dev/null
"$APP_DIR/venv/bin/pip" install "$APP_DIR/app" >/dev/null

if [[ ! -f "$CFG_DIR/config.json" ]]; then
  cp "$SRC_DIR/config.example.json" "$CFG_DIR/config.json"
  echo "Created: $CFG_DIR/config.json"
else
  echo "Preserved existing: $CFG_DIR/config.json"
fi

cat > "$BIN_DIR/home-readonly-mcp" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
export HOME_READONLY_MCP_CONFIG="\${HOME_READONLY_MCP_CONFIG:-$CFG_DIR/config.json}"
exec "$APP_DIR/venv/bin/home-readonly-mcp"
LAUNCHER
chmod +x "$BIN_DIR/home-readonly-mcp"

echo
echo "Installed home-readonly-mcp"
echo "Python: $PY_VER"
echo "Launcher: $BIN_DIR/home-readonly-mcp"
echo "Config:   $CFG_DIR/config.json"
echo
echo "If ~/.local/bin is not on PATH, use the absolute launcher path above."
