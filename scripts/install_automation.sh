#!/bin/bash
PROJECT_DIR="/Users/tjneary/Documents/60_Tech_Projects/AI Projects/PKM_v1"
PLIST_NAME="com.user.pkm.plist"
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
