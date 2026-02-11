#!/usr/bin/env bash
# =============================================================================
# CoreRag Menu Bar Launcher
# =============================================================================
# Launches the menu bar app, which handles server lifecycle automatically.
# Intended to be called by launchd at login.
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

# Generate icons if they don't exist
if [ ! -f "$PROJECT_ROOT/assets/menubar_icon.png" ]; then
    echo "Generating menu bar icons..."
    python "$PROJECT_ROOT/scripts/generate_icons.py"
fi

# Launch the menu bar app (this blocks until the app quits)
# The app handles starting/restarting the server automatically.
echo "Starting CoreRag menu bar app..."
exec python -m src.menubar
