#!/usr/bin/env bash
# Nightly: pg_dump production Postgres and upload it to Cloudflare R2.
#   backup-db.sh           dump, verify the archive reads back, upload, prune
#   backup-db.sh --check   R2 listing plus a schema-only dump to /dev/null; no data
# Dumps land at r2:<bucket>/db/YYYY/MM/boulder-<UTC stamp>-pg<major>.dump with
# a .sha256 beside them. The bucket's lifecycle rule deletes objects after 30
# days; check-freshness.sh alerts if the newest dump is over 48 hours old.
set -Eeuo pipefail
umask 077
BACKUP_JOB=db
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
trap 'on_error $LINENO' ERR

load_r2
load_app DATABASE_URL
load_pg
WORK="$(mktemp -d /var/tmp/boulder-db-backup.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# The client must match the server's major version; any client can ask it.
num="$(pg_client 17 psql -XAtc 'show server_version_num')"
major=$((num / 10000))

excludes=()
for schema in $SUPABASE_MANAGED_SCHEMAS; do excludes+=("--exclude-schema=$schema"); done

if [ "${1:-}" = --check ]; then
    rclone lsf "r2:$R2_BUCKET" --max-depth 1 >/dev/null
    pg_client "$major" pg_dump --schema-only --no-owner --no-privileges "${excludes[@]}" --file=/dev/null
    log "check ok: R2 bucket readable; Postgres $num dumps with postgres:${major}-alpine"
    exit 0
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
name="boulder-${stamp}-pg${major}.dump"

started=$SECONDS
pg_client "$major" pg_dump --format=custom --compress=6 --no-owner --no-privileges \
    --lock-wait-timeout=120s "${excludes[@]}" --file="/work/$name"
# Reading the table of contents back proves the archive is complete and parseable.
pg_client "$major" pg_restore --list "/work/$name" > "$WORK/toc"
tables="$(grep -c ' TABLE DATA ' "$WORK/toc" || true)"
[ "$tables" -gt 0 ] || { log "dump has no table data"; false; }
(cd "$WORK" && sha256sum "$name" > "$name.sha256")
size="$(stat -c %s "$WORK/$name")"

dest="db/$(date -u +%Y/%m)"
rclone copyto "/work/$name" "r2:$R2_BUCKET/$dest/$name"
rclone copyto "/work/$name.sha256" "r2:$R2_BUCKET/$dest/$name.sha256"
log "ok: $dest/$name ($size bytes, $tables tables, server $num, $((SECONDS - started))s)"
alert resolved "BoulderRoller db backup succeeded"
