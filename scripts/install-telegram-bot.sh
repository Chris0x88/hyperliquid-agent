#!/bin/bash
# Install the HyperLiquid Telegram bot as a macOS LaunchAgent
# Starts automatically on login, restarts on crash

PLIST_NAME="com.hyperliquid.telegram-bot"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$(which python3)"
LOG_DIR="${PROJECT_DIR}/data/daemon"

mkdir -p "$LOG_DIR"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>-m</string>
        <string>cli.telegram_bot</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/telegram_bot.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/telegram_bot.stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

echo "Installed: $PLIST_PATH"
echo ""

# Load if not already loaded
launchctl bootout "gui/$(id -u)/${PLIST_NAME}" 2>/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "Telegram bot service started."
echo "  Stop:    launchctl bootout gui/\$(id -u)/${PLIST_NAME}"
echo "  Restart: launchctl kickstart -k gui/\$(id -u)/${PLIST_NAME}"
echo "  Logs:    tail -f ${LOG_DIR}/telegram_bot.stderr.log"
