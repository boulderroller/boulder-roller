#!/usr/bin/env bash
# Restore a dump from R2 into a throwaway local Postgres and prove every row arrived.
#   restore-test.sh                     the newest dump under r2:<bucket>/db
#   restore-test.sh db/2026/10/<x>.dump that dump
#   restore-test.sh ./<x>.dump          a local archive (its .sha256 is checked if present)
# The scratch database runs in a container with no published port and is removed
# afterwards; production is never contacted. Runs on the droplet or on a Mac
# with Docker. Passes when the archive's checksum matches and every table holds
# exactly as many rows as the archive's own COPY data. Restore errors outside the
# data (Supabase-only extensions such as supabase_vault) are listed, not fatal.
set -Eeuo pipefail
umask 077
BACKUP_JOB=restore-test
ALERT_HOURS=750
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
trap 'on_error $LINENO' ERR

WORK="$(mktemp -d "${TMPDIR:-/var/tmp}/boulder-restore-test.XXXXXX")"
box="boulder-restore-test-$$"
trap 'docker rm -f "$box" >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT

key="${1:-}"
if [ -n "$key" ] && [ -f "$key" ]; then
    name="$(basename "$key")"
    cp "$key" "$WORK/$name"
    if [ -f "$key.sha256" ]; then cp "$key.sha256" "$WORK/$name.sha256"; fi
else
    load_r2
    if [ -z "$key" ]; then
        newest="$(rclone lsf -R --files-only "r2:$R2_BUCKET/db" | grep '\.dump$' | sort | tail -1 || true)"
        [ -n "$newest" ] || { log "no dump under r2:$R2_BUCKET/db"; false; }
        key="db/$newest"
    fi
    name="$(basename "$key")"
    rclone copyto "r2:$R2_BUCKET/$key" "/work/$name"
    rclone copyto "r2:$R2_BUCKET/$key.sha256" "/work/$name.sha256"
fi
if [ -f "$WORK/$name.sha256" ]; then
    if command -v sha256sum >/dev/null; then (cd "$WORK" && sha256sum -c --quiet "$name.sha256")
    else (cd "$WORK" && shasum -a 256 -c --quiet "$name.sha256"); fi
fi

major="$(sed -n 's/.*-pg\([0-9][0-9]*\)\.dump$/\1/p' <<<"$name")"
[ -n "$major" ] || { log "cannot read the Postgres major version from $name"; false; }
# Production uses PostGIS, so the scratch server needs it installed (not enabled).
image="${RESTORE_IMAGE:-postgis/postgis:${major}-3.5-alpine}"
docker run -d --name "$box" --memory 1g -e POSTGRES_PASSWORD=restore-test-only \
    -v "$WORK:/work" "$image" >/dev/null
# TCP readiness: the image's first-boot server listens on a socket only.
for _ in $(seq 90); do
    docker exec "$box" pg_isready -h 127.0.0.1 -U postgres -q && break
    sleep 1
done
docker exec "$box" pg_isready -h 127.0.0.1 -U postgres -q
sql() { docker exec -i "$box" psql -h 127.0.0.1 -U postgres -v ON_ERROR_STOP=1 -XAtq "$@"; }

# A clean database (the image enables PostGIS in "postgres"), plus the Supabase
# roles that row-level policies name.
sql -d postgres -c 'CREATE DATABASE restore_test TEMPLATE template0'
sql -d restore_test <<'SQL'
DO $$ DECLARE r text; BEGIN
  FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role','authenticator','supabase_admin',
    'supabase_auth_admin','supabase_storage_admin','supabase_realtime_admin','dashboard_user','pgbouncer']
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN EXECUTE format('CREATE ROLE %I NOLOGIN', r); END IF;
  END LOOP;
END $$;
SQL

started=$SECONDS
docker exec "$box" pg_restore -h 127.0.0.1 -U postgres -d restore_test --no-owner --no-privileges \
    "/work/$name" 2> "$WORK/restore.err" || true
restore_seconds=$((SECONDS - started))

# Expected rows per table, counted from the archive's own COPY blocks.
docker exec "$box" pg_restore --data-only -f - "/work/$name" \
    | awk '/^COPY / { table = $2; rows = 0; inside = 1; next }
           inside && $0 == "\\." { print table, rows; inside = 0; next }
           inside { rows++ }' > "$WORK/expected"
# Extension-owned tables (PostGIS's spatial_ref_sys) are dumped with only the
# rows users added; CREATE EXTENSION refills the rest, so they may only grow.
sql -d restore_test -c "SELECT quote_ident(n.nspname) || '.' || quote_ident(c.relname) FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_depend d ON d.objid = c.oid
    AND d.classid = 'pg_class'::regclass AND d.deptype = 'e' WHERE c.relkind = 'r'" > "$WORK/extension-tables"
tables=0 rows=0 mismatched=0
while read -r table expected; do
    actual="$(sql -d restore_test -c "SELECT count(*) FROM $table" </dev/null 2>/dev/null || echo missing)"
    tables=$((tables + 1)); rows=$((rows + expected))
    if grep -qxF "$table" "$WORK/extension-tables" && [[ "$actual" =~ ^[0-9]+$ ]] && [ "$actual" -ge "$expected" ]; then
        continue
    fi
    if [ "$actual" != "$expected" ]; then
        mismatched=$((mismatched + 1))
        log "mismatch: $table archive=$expected restored=$actual"
    fi
done < "$WORK/expected"

errors="$(grep -c '^pg_restore: error:' "$WORK/restore.err" || true)"
if [ "$errors" -gt 0 ]; then
    log "restore errors outside the row check ($errors):"
    grep '^pg_restore: error:' "$WORK/restore.err" | cut -c1-200 | sort | uniq -c | sed 's/^/    /'
fi
[ "$tables" -gt 0 ] && [ "$mismatched" -eq 0 ] || { log "FAILED: $mismatched of $tables tables differ"; false; }
log "ok: $key restored into a scratch database in ${restore_seconds}s; $tables tables, $rows rows, all present"
alert resolved "BoulderRoller restore test passed"
