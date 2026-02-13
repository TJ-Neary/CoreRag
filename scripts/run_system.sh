#!/bin/bash
# =============================================================================
# CoreRag System Launcher
# =============================================================================
# Ensures the server is running and opens the dashboard.
# Triggered by launchd WatchPaths when files appear in Inbox,
# or can be run manually to start everything.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$HOME/.corerag/logs"
LOG_FILE="$LOG_DIR/automation.log"
PORT_FILE="$HOME/.corerag/server.port"
DEFAULT_PORT="${CORERAG_SERVER_PORT:-8000}"
INBOX_DIR="${INBOX_PATH:-$HOME/Desktop/Inbox}"

get_dashboard_url() {
    local port="$DEFAULT_PORT"
    if [ -f "$PORT_FILE" ]; then
        port=$(cat "$PORT_FILE" 2>/dev/null || echo "$DEFAULT_PORT")
    fi
    echo "http://localhost:$port"
}

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR" || exit 1

echo "$(date) - Triggered." >> "$LOG_FILE"

# Determine Python Interpreter
if [ -f "venv/bin/python3" ]; then
    PYTHON_CMD="venv/bin/python3"
elif [ -f ".venv/bin/python3" ]; then
    PYTHON_CMD=".venv/bin/python3"
else
    PYTHON_CMD="python3"
fi

export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"

# Always ensure server is running
if ! pgrep -f "src.server" > /dev/null; then
    echo "$(date) - Starting Server..." >> "$LOG_FILE"
    nohup env PYTHONPATH="$PROJECT_DIR" "$PYTHON_CMD" -m src.server >> "$LOG_DIR/server.log" 2>&1 &

    # Wait for server to be ready (up to 10 seconds)
    for i in $(seq 1 20); do
        if curl -s "$(get_dashboard_url)/api/progress" > /dev/null 2>&1; then
            echo "$(date) - Server ready." >> "$LOG_FILE"
            break
        fi
        sleep 0.5
    done
else
    echo "$(date) - Server already running." >> "$LOG_FILE"
fi

# Check inbox file count
FILE_COUNT=$(find "$INBOX_DIR" -maxdepth 1 -not -name '.*' -type f 2>/dev/null | wc -l | tr -d ' ')

if [ "$FILE_COUNT" -gt 0 ]; then
    osascript -e "display notification \"$FILE_COUNT file(s) ready for review.\" with title \"CoreRag\" subtitle \"Inbox\""
    echo "$(date) - $FILE_COUNT files in inbox." >> "$LOG_FILE"
    # Open dashboard to review files
    open "$(get_dashboard_url)"
    echo "$(date) - Opened Dashboard ($FILE_COUNT files ready)." >> "$LOG_FILE"
else
    echo "$(date) - Inbox empty, server running." >> "$LOG_FILE"
fi
