#!/bin/bash
# vault-decision MCP daemon manager
# Usage: ./daemon.sh start|stop|status|restart

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$PROJECT_DIR/.daemon.pid"
LOG_FILE="$PROJECT_DIR/.daemon.log"
HOST="${VAULT_MCP_HOST:-127.0.0.1}"
PORT="${VAULT_MCP_PORT:-8741}"

start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Daemon already running (PID $(cat "$PID_FILE"))"
        return 1
    fi

    echo "Starting vault-decision daemon on $HOST:$PORT ..."
    nohup uv --directory "$PROJECT_DIR" run python server.py --daemon --host "$HOST" --port "$PORT" \
        > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2

    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Daemon started (PID $(cat "$PID_FILE"))"
        echo "MCP URL: http://$HOST:$PORT/mcp"
    else
        echo "Failed to start daemon. Check $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "No PID file found. Daemon not running?"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping daemon (PID $PID)..."
        kill "$PID"
        sleep 2
        if kill -0 "$PID" 2>/dev/null; then
            kill -9 "$PID"
        fi
        echo "Daemon stopped"
    else
        echo "Process $PID not found"
    fi
    rm -f "$PID_FILE"
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Daemon running (PID $(cat "$PID_FILE"))"
        echo "URL: http://$HOST:$PORT/mcp"
        curl -s -o /dev/null -w "Health: HTTP %{http_code}\n" "http://$HOST:$PORT/mcp" 2>/dev/null || echo "Health: not responding"
    else
        echo "Daemon not running"
        [ -f "$PID_FILE" ] && rm -f "$PID_FILE"
    fi
}

case "${1:-}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
