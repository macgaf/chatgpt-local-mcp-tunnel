#!/usr/bin/env bash
set -euo pipefail
command -v python3 >/dev/null || { echo 'Python 3.11+ is required; install Python before continuing.' >&2; exit 1; }
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$HERE/bootstrap.py" "$@"
