#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.user.corerag.plist"
SOURCE="$PROJECT_DIR/scripts/$PLIST_NAME"
DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "Installing Automation..."

# 1. Copy Plist
cp "$SOURCE" "$DEST"
echo "Copied plist to $DEST"

# 2. Unload previous if exists
launchctl unload "$DEST" 2>/dev/null

# 3. Load new
launchctl load "$DEST"
echo "Loaded Launch Agent."

echo "Automation Installed! Drop a file in ~/Desktop/Inbox to test."
