#!/bin/bash

# Configuration
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/automation.log"
DASHBOARD_URL="http://localhost:8000"
INBOX_DIR="${INBOX_PATH:-$HOME/Desktop/Inbox}"

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

# Check inbox file count
FILE_COUNT=$(find "$INBOX_DIR" -maxdepth 1 -not -name '.*' -type f 2>/dev/null | wc -l | tr -d ' ')

if [ "$FILE_COUNT" -eq 0 ]; then
    osascript -e 'display notification "Inbox is empty, nothing to process." with title "CoreRag"'
    echo "$(date) - Inbox empty, exiting." >> "$LOG_FILE"
    exit 0
fi

echo "$(date) - $FILE_COUNT files in inbox." >> "$LOG_FILE"

# Start Server if not running
if ! pgrep -f "src.server" > /dev/null; then
    echo "$(date) - Starting Server..." >> "$LOG_FILE"
    nohup env PYTHONPATH="$PROJECT_DIR" "$PYTHON_CMD" -m src.server > server.log 2>&1 &
    sleep 2
else
    echo "$(date) - Server already running." >> "$LOG_FILE"
fi

# Open Browser to Dashboard
open "$DASHBOARD_URL"
echo "$(date) - Opened Dashboard ($FILE_COUNT files ready)." >> "$LOG_FILE"
