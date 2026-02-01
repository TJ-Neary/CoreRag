#!/bin/bash

# Configuration
PROJECT_DIR="/Users/tjneary/Documents/60_Tech_Projects/AI Projects/PKM_v1"
LOG_FILE="$PROJECT_DIR/automation.log"
DASHBOARD_URL="http://localhost:8000"

# Note: We use 'cd' to ensure relative imports work if PYTHONPATH isn't set perfectly
cd "$PROJECT_DIR" || exit 1

echo "$(date) - Triggered." >> "$LOG_FILE"

# Determine Python Interpreter
if [ -f "venv/bin/python3" ]; then
    PYTHON_CMD="venv/bin/python3"
    echo "$(date) - Using venv python." >> "$LOG_FILE"
elif [ -f ".venv/bin/python3" ]; then
    PYTHON_CMD=".venv/bin/python3"
    echo "$(date) - Using .venv python." >> "$LOG_FILE"
else
    PYTHON_CMD="python3"
    echo "$(date) - Using system python3." >> "$LOG_FILE"
fi

export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"

# 1. Start Server if not running
if ! pgrep -f "src.server" > /dev/null; then
    echo "$(date) - Starting Server..." >> "$LOG_FILE"
    # We use env to pass PYTHONPATH explicitly
    nohup env PYTHONPATH="$PROJECT_DIR" "$PYTHON_CMD" -m src.server > server.log 2>&1 &
else
    echo "$(date) - Server already running." >> "$LOG_FILE"
fi

# 2. Start Watchdog if not running
if ! pgrep -f "src.watchdog" > /dev/null; then
    echo "$(date) - Starting Watchdog..." >> "$LOG_FILE"
    nohup env PYTHONPATH="$PROJECT_DIR" "$PYTHON_CMD" -m src.watchdog > watchdog.log 2>&1 &
else
    echo "$(date) - Watchdog already running." >> "$LOG_FILE"
fi

# 3. Open Browser to Dashboard
# We wait a moment to ensure server is ready if it just started
sleep 2
open "$DASHBOARD_URL"
echo "$(date) - Opened Dashboard." >> "$LOG_FILE"
