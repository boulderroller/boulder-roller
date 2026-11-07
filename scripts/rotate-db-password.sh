#!/usr/bin/env bash
# Swap the production Postgres password on the droplet after a Supabase reset.
#   scripts/rotate-db-password.sh --dry-run    edit temporary copies only, then read-only checks
#   scripts/rotate-db-password.sh --apply      back up, swap, recreate, verify
#   scripts/rotate-db-password.sh --rollback   restore the backups, recreate, verify
# What it changes on the droplet:
#   /root/boulder-repo/.env                          DATABASE_URL, INDEXER_DATABASE_URL (password part)
#   /root/boulder-repo/infrastructure/monitoring/.env SUPABASE_DB_PASSWORD, POSTGRES_EXPORTER_DSN
#   /root/monitoring/.env (older copy)               the same two keys
#   Grafana's "supabase" datasource, through Grafana's API
# and recreates api, indexer, keeper, grafana and postgres-exporter. Backups go to
# /root/.secrets/*.env.$SUFFIX (mode 600) and are never overwritten by a re-run.
#
# The new password comes from ~/.config/boulder-db-password (DB_PASSWORD_FILE
# overrides). It crosses SSH on stdin, never argv, and is never printed. A dry
# run without that file uses a random stand-in.
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-}"
SUFFIX="${SUFFIX:-20261021-dbreset}"
PASSWORD_FILE="${DB_PASSWORD_FILE:-$HOME/.config/boulder-db-password}"
HOST="${DEPLOY_HOST:?set DEPLOY_HOST, e.g. root@your-server}"
# One multiplexed connection: the droplet's firewall rate-limits new SSH sessions.
SSH=(ssh -o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-%C" -o ControlPersist=20m "$HOST")

case "$MODE" in
    --dry-run|--apply|--rollback) ;;
    *) sed -n '2,4p' "$0" >&2; exit 2 ;;
esac

password=""
if [ "$MODE" != --rollback ]; then
    if [ -f "$PASSWORD_FILE" ]; then
        IFS= read -r password < "$PASSWORD_FILE" || true
    elif [ "$MODE" = --dry-run ]; then
        echo "No $PASSWORD_FILE yet; the dry run uses a random stand-in password."
        password="$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 40 || true)"
    else
        echo "No new password at $PASSWORD_FILE" >&2
        exit 2
    fi
fi

# Line 1 of stdin is the password; the rest is the program python reads.
{ printf '%s\n' "$password"; cat "$HERE/rotate_db_password_remote.py"; } |
    "${SSH[@]}" "bash -c 'IFS= read -r NEW_DB_PASSWORD; export NEW_DB_PASSWORD; exec python3 - \"\$@\"' rotate ${MODE#--} $SUFFIX"
