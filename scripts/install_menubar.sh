#!/usr/bin/env bash
# =============================================================================
# Install CoreRag Menu Bar App as Login Item
# =============================================================================
# Copies the launchd plist to ~/Library/LaunchAgents and loads it.
# The menu bar app will start automatically at login.
#
# Usage:
#   ./scripts/install_menubar.sh           # Install
#   ./scripts/install_menubar.sh --remove  # Uninstall
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_NAME="com.user.corerag-menubar.plist"
PLIST_SRC="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"
LOG_DIR="$HOME/.corerag/logs"

if [ "${1:-}" = "--remove" ]; then
    echo "Uninstalling CoreRag menu bar app..."
    if launchctl list | grep -q "com.user.corerag-menubar"; then
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
    fi
    rm -f "$PLIST_DEST"
    echo "Removed. The menu bar app will no longer start at login."
    exit 0
fi

echo "Installing CoreRag menu bar app..."

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Generate icons if needed
if [ ! -f "$PROJECT_ROOT/assets/menubar_icon.png" ]; then
    echo "Generating menu bar icons..."
    cd "$PROJECT_ROOT"
    if [ -d "$PROJECT_ROOT/venv" ]; then
        source "$PROJECT_ROOT/venv/bin/activate"
    fi
    python "$PROJECT_ROOT/scripts/generate_icons.py"
fi

# Copy plist and substitute paths
sed -e "s|CORERAG_PROJECT_ROOT|$PROJECT_ROOT|g" \
    -e "s|CORERAG_LOG_DIR|$LOG_DIR|g" \
    "$PLIST_SRC" > "$PLIST_DEST"

# Unload if already loaded
if launchctl list | grep -q "com.user.corerag-menubar"; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Load the agent
launchctl load "$PLIST_DEST"

echo ""
echo "Installed: $PLIST_DEST"
echo "The CoreRag menu bar app will start automatically at login."
echo "To start it now: launchctl start com.user.corerag-menubar"
echo "To uninstall: $0 --remove"
