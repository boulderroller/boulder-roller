#!/usr/bin/env bash
# Hourly: alert Telegram (through the droplet's Alertmanager) when the newest
# backup in R2 is stale. The bucket deletes objects after 30 days, so backups
# that quietly stop would leave nothing within a month.
#   db       newest dump older than DB_MAX_HOURS (48)
#   storage  newest Storage copy older than STORAGE_MAX_HOURS (192: weekly + a day)
set -Eeuo pipefail
umask 077
BACKUP_JOB=freshness
ALERT_HOURS=3
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
trap 'on_error $LINENO' ERR

load_r2
WORK="$(mktemp -d /var/tmp/boulder-backup-freshness.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

newest_age_hours() {
    local listing
    # An empty prefix is "directory not found" to rclone: no backups yet, so stale.
    if ! listing="$(rclone lsjson -R --files-only --no-mimetype --use-server-modtime \
            "r2:$R2_BUCKET/$1" 2> "$WORK/lsjson.err")"; then
        grep -q 'directory not found' "$WORK/lsjson.err" || { cat "$WORK/lsjson.err" >&2; return 1; }
        listing='[]'
    fi
    python3 -c '
import json, re, sys, datetime
items = json.load(sys.stdin)
if not items: print(1e9); sys.exit()
# rclone gives nanoseconds; Python 3.10 parses at most microseconds.
parse = lambda t: datetime.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", t.replace("Z", "+00:00")))
newest = max(parse(i["ModTime"]) for i in items)
print(round((datetime.datetime.now(datetime.timezone.utc) - newest).total_seconds() / 3600, 1))' <<< "$listing"
}

stale() {  # kind age limit
    local labels="\"alertname\":\"BoulderBackupStale\",\"severity\":\"warning\",\"kind\":\"$1\""
    local ends now; now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if python3 -c "import sys; sys.exit(0 if float('$2') > float('$3') else 1)"; then
        ends="$(date -u -d "+${ALERT_HOURS} hours" +%Y-%m-%dT%H:%M:%SZ)"
        log "STALE: newest $1 backup is ${2}h old (limit ${3}h)"
    else
        ends="$now"
    fi
    local summary="Newest BoulderRoller $1 backup in R2 is ${2}h old (limit ${3}h); R2 deletes after 30 days"
    curl -fsS -m 10 -o /dev/null -H 'Content-Type: application/json' \
        -d "[{\"labels\":{$labels},\"annotations\":{\"summary\":\"$summary\"},\"endsAt\":\"$ends\"}]" \
        "$ALERTMANAGER_URL/api/v2/alerts" || log "alertmanager unreachable; alert not sent"
}

db_age="$(newest_age_hours db)"
storage_age="$(newest_age_hours storage)"
stale db "$db_age" "${DB_MAX_HOURS:-48}"
stale storage "$storage_age" "${STORAGE_MAX_HOURS:-192}"
log "newest db ${db_age}h, storage ${storage_age}h"
alert resolved "BoulderRoller backup freshness check ran"
