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

exec uv --directory "$SERVER_DIR" run server.py
