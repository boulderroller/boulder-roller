# Shared by the R2 backup scripts (boulderroller-v2-m6rs7). Source it; don't run it.
#
# Credentials are read at run time from the droplet's own files, so a database
# password or key rotation there needs no change here:
#   /root/.secrets/r2.env     R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_ENDPOINT R2_BUCKET
#   /root/boulder-repo/.env   DATABASE_URL SUPABASE_URL SUPABASE_SERVICE_KEY
# Nothing here prints a credential: values reach containers as `-e NAME`.

BACKUP_HOME="${BACKUP_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
R2_ENV_FILE="${R2_ENV_FILE:-/root/.secrets/r2.env}"
APP_ENV_FILE="${APP_ENV_FILE:-/root/boulder-repo/.env}"
RCLONE_IMAGE="${RCLONE_IMAGE:-rclone/rclone:1.75.1}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"
# Supabase owns these; a new project recreates them. auth.users is empty
# (sign-in is Privy) and Storage files are copied by backup-storage.sh.
SUPABASE_MANAGED_SCHEMAS="auth storage realtime vault graphql graphql_public"

log() { printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${BACKUP_JOB:-backup}" "$*"; }

# `vars=$(...)` keeps a failed read fatal under `set -e`; `eval "$(...)"` would not.
load_r2() {
    local vars
    vars="$(python3 "$BACKUP_HOME/envfile.py" export "$R2_ENV_FILE" \
        R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_ENDPOINT R2_BUCKET)"
    eval "$vars"
    export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
    export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
    export RCLONE_CONFIG_R2_ENDPOINT="$R2_ENDPOINT"
}

load_app() {
    local vars
    vars="$(python3 "$BACKUP_HOME/envfile.py" export "$APP_ENV_FILE" "$@")"
    eval "$vars"
}

load_pg() {
    local vars
    vars="$(python3 "$BACKUP_HOME/envfile.py" pg)"
    eval "$vars"
}

# rclone in a container, with the work folder at /work and R2 as remote "r2:".
rclone() {
    docker run --rm \
        -e RCLONE_CONFIG_R2_TYPE=s3 -e RCLONE_CONFIG_R2_PROVIDER=Cloudflare \
        -e RCLONE_CONFIG_R2_ACCESS_KEY_ID -e RCLONE_CONFIG_R2_SECRET_ACCESS_KEY \
        -e RCLONE_CONFIG_R2_ENDPOINT -e RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true \
        -v "${WORK:?}:/work" "$RCLONE_IMAGE" --config /dev/null --retries 5 --low-level-retries 10 "$@"
}

# A Postgres client of the given major version, connected through PG* env.
pg_client() {
    local major="$1"; shift
    docker run --rm -e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGSSLMODE \
        -v "${WORK:?}:/work" "postgres:${major}-alpine" "$@"
}

# Fire (or resolve) a warning through the droplet's Alertmanager, which already
# pages Telegram. Off the droplet there is no Alertmanager; the log says so.
alert() {
    local state="$1" summary="$2" ends
    if [ "$state" = firing ]; then ends="$(date -u -d "+${ALERT_HOURS:-25} hours" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"; fi
    ends="${ends:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
    curl -fsS -m 10 -o /dev/null -H 'Content-Type: application/json' \
        -d "[{\"labels\":{\"alertname\":\"BoulderBackupFailed\",\"severity\":\"warning\",\"job\":\"${BACKUP_JOB:-backup}\"},\"annotations\":{\"summary\":\"$summary\"},\"endsAt\":\"$ends\"}]" \
        "$ALERTMANAGER_URL/api/v2/alerts" 2>/dev/null || log "alertmanager unreachable; alert not sent"
}

on_error() {
    log "FAILED at line $1"
    alert firing "BoulderRoller ${BACKUP_JOB:-backup} failed on $(hostname); see /var/log/boulder-backup.log"
}
