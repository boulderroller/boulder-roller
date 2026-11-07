#!/bin/bash
# Page Telegram when this Mac's data volume runs low. launchd runs it every 10
# minutes (scripts/mac/install-disk-alert.sh). One page on dropping under
# WARN_GB, another under CRIT_GB; it resets once space is back above WARN_GB + 2.
# The disk filled on 21 Oct 2026 and crashed runs.
#
# Credentials: ~/.config/boulder-telegram (mode 600, never in the repo) with
# TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, the same bot and chat Alertmanager
# pages. DRY_RUN=1 prints the page instead of sending it.
set -u
CREDENTIALS="${BOULDER_TELEGRAM_CREDENTIALS:-$HOME/.config/boulder-telegram}"
STATE="${BOULDER_DISK_ALERT_STATE:-$HOME/Library/Caches/boulder-disk-alert.level}"
VOLUME="${VOLUME:-/System/Volumes/Data}"
WARN_GB="${WARN_GB:-15}"
CRIT_GB="${CRIT_GB:-5}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# Free space in decimal GB, as Finder reports it.
free_gb="$(df -k "$VOLUME" | awk 'NR == 2 { printf "%.1f", $4 * 1024 / 1e9 }')"
[ -n "$free_gb" ] || { log "cannot read free space on $VOLUME"; exit 1; }
below() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a < b) }'; }

level=0
if below "$free_gb" "$CRIT_GB"; then level=2; elif below "$free_gb" "$WARN_GB"; then level=1; fi
previous="$(cat "$STATE" 2>/dev/null || echo 0)"
case "$previous" in 0|1|2) ;; *) previous=0 ;; esac

if [ "$level" -le "$previous" ]; then
    # Recovered: forget the old level only with some margin, so it cannot flap.
    if [ "$level" -lt "$previous" ] && ! below "$free_gb" "$((WARN_GB + 2))"; then
        echo "$level" > "$STATE"
        log "recovered: $free_gb GB free on $VOLUME"
    fi
    exit 0
fi

if [ "$level" -eq 2 ]; then
    text="Mac disk critical: $free_gb GB free on the data volume (under $CRIT_GB GB). Builds and test runs will fail; clear space now."
else
    text="Mac disk low: $free_gb GB free on the data volume (under $WARN_GB GB). It filled on 21 Oct and crashed runs."
fi
if [ "${DRY_RUN:-}" = 1 ]; then
    log "dry run, would page: $text"
    exit 0
fi

TELEGRAM_BOT_TOKEN="" TELEGRAM_CHAT_ID=""
# shellcheck disable=SC1090
. "$CREDENTIALS" || { log "no Telegram credentials at $CREDENTIALS"; exit 1; }
# The token goes to curl as config on stdin, never in argv.
if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TELEGRAM_BOT_TOKEN" |
    curl -fsS -m 20 -o /dev/null -K - --data-urlencode "chat_id=$TELEGRAM_CHAT_ID" --data-urlencode "text=$text"; then
    echo "$level" > "$STATE"
    log "paged: $text"
else
    log "Telegram send failed; retrying next run"
    exit 1
fi
