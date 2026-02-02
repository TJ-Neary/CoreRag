#!/usr/bin/env bash
# =============================================================================
# CoreRag Menu Bar Launcher
# =============================================================================
# Starts the dashboard server (if not already running) and launches the
# menu bar app. Intended to be called by launchd at login.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Activate virtual environment
VENV_DIR="$PROJECT_ROOT/venv"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
else
    echo "Virtual environment not found at $VENV_DIR"
    exit 1
fi

cd "$PROJECT_ROOT"

# Start the dashboard server if not already running
if ! curl -s http://localhost:8000/api/progress > /dev/null 2>&1; then
    echo "Starting CoreRag server..."
    python -m src.server &
    SERVER_PID=$!

    # Wait for server to be ready (up to 15 seconds)
    for i in $(seq 1 30); do
        if curl -s http://localhost:8000/api/progress > /dev/null 2>&1; then
            echo "Server ready."
            break
        fi
        sleep 0.5
    done
fi

# Generate icons if they don't exist
if [ ! -f "$PROJECT_ROOT/assets/menubar_icon.png" ]; then
    echo "Generating menu bar icons..."
    python "$PROJECT_ROOT/scripts/generate_icons.py"
fi

# Launch the menu bar app (this blocks until the app quits)
echo "Starting CoreRag menu bar app..."
exec python -m src.menubar
