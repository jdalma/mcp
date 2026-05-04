#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$SCRIPT_DIR/vault-decision-mcp"
PORT="${MCP_PORT:-8765}"

# 포트 선점 확인
if lsof -i "TCP:$PORT" -sTCP:LISTEN -t &>/dev/null; then
  echo "ERROR: Port $PORT is already in use." >&2
  echo "  Set MCP_PORT=<other port> to use a different port." >&2
  echo "  To stop the existing process: kill \$(lsof -i TCP:$PORT -sTCP:LISTEN -t)" >&2
  exit 1
fi

UV_BIN="${UV_BIN:-/Users/jeonghyunjun/.local/bin/uv}"
if [[ ! -x "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi

if [[ -z "${UV_BIN:-}" || ! -x "$UV_BIN" ]]; then
  echo "ERROR: uv executable not found. Set UV_BIN=/path/to/uv." >&2
  exit 1
fi

exec "$UV_BIN" --directory "$SERVER_DIR" run server.py
