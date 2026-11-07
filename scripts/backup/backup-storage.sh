#!/usr/bin/env bash
# Weekly: copy every Supabase Storage object (ride files, media) to Cloudflare R2.
# Each run is a full copy at r2:<bucket>/storage/YYYYMMDD/<bucket>/<path> with a
# manifest.json. The bucket's lifecycle rule deletes objects after 30 days.
set -Eeuo pipefail
umask 077
BACKUP_JOB=storage
ALERT_HOURS=170
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
trap 'on_error $LINENO' ERR

load_r2
load_app SUPABASE_URL SUPABASE_SERVICE_KEY
export SUPABASE_URL SUPABASE_SERVICE_KEY
WORK="$(mktemp -d /var/tmp/boulder-storage-backup.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

started=$SECONDS
summary="$(python3 "$BACKUP_HOME/storage_snapshot.py" "$WORK/snapshot")"
dest="storage/$(date -u +%Y%m%d)"
rclone copy /work/snapshot "r2:$R2_BUCKET/$dest" --transfers 8
rclone check /work/snapshot "r2:$R2_BUCKET/$dest" --one-way --size-only
log "ok: $dest $summary ($((SECONDS - started))s)"
alert resolved "BoulderRoller storage backup succeeded"
