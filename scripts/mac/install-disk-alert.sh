#!/bin/bash
# Install the Mac low-disk alert as a launchd job that runs every 10 minutes.
#   scripts/mac/install-disk-alert.sh
# Copies disk-alert.sh to ~/.local/libexec, writes the LaunchAgent and loads it.
# If ~/.config/boulder-telegram is missing, it is created (mode 600) from the
# droplet's Alertmanager bot token and chat ID over SSH; nothing is printed.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL=com.boulderroller.disk-alert
SCRIPT="$HOME/.local/libexec/boulder-disk-alert.sh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CREDENTIALS="$HOME/.config/boulder-telegram"
HOST="${DEPLOY_HOST:?set DEPLOY_HOST, e.g. root@your-server}"

if [ ! -s "$CREDENTIALS" ]; then
    umask 077
    mkdir -p "$(dirname "$CREDENTIALS")"
    ssh -o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-%C" -o ControlPersist=20m "$HOST" \
        'printf "TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n" "$(tr -d "[:space:]" < /root/.secrets/telegram-bot-token)" \
            "$(sed -n "s/^[[:space:]]*chat_id:[[:space:]]*//p" /root/.secrets/alertmanager.yml | head -n 1 | tr -d "\"[:space:]")"' \
        > "$CREDENTIALS.new"
    grep -q '^TELEGRAM_BOT_TOKEN=.\{20,\}$' "$CREDENTIALS.new" && grep -q '^TELEGRAM_CHAT_ID=-\{0,1\}[0-9]\{5,\}$' "$CREDENTIALS.new" \
        || { rm -f "$CREDENTIALS.new"; echo "Could not read the bot token and chat ID from the droplet" >&2; exit 1; }
    mv "$CREDENTIALS.new" "$CREDENTIALS"
    chmod 600 "$CREDENTIALS"
fi

mkdir -p "$(dirname "$SCRIPT")" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
install -m 700 "$HERE/disk-alert.sh" "$SCRIPT"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>/bin/bash</string><string>$SCRIPT</string></array>
    <key>StartInterval</key><integer>600</integer>
    <key>RunAtLoad</key><true/>
    <key>StandardOutPath</key><string>$HOME/Library/Logs/boulder-disk-alert.log</string>
    <key>StandardErrorPath</key><string>$HOME/Library/Logs/boulder-disk-alert.log</string>
</dict>
</plist>
PLIST
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Loaded $LABEL: every 10 minutes; log at ~/Library/Logs/boulder-disk-alert.log"
