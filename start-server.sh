#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

UV_BIN="${UV_BIN:-/Users/jeonghyunjun/.local/bin/uv}"
if [[ ! -x "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi

if [[ -z "${UV_BIN:-}" || ! -x "$UV_BIN" ]]; then
  echo "ERROR: uv executable not found. Set UV_BIN=/path/to/uv." >&2
  exit 1
fi

exec "$UV_BIN" --directory "$SCRIPT_DIR" run python -m vault_decision.server
