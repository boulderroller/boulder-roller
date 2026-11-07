#!/usr/bin/env bash
# Install the R2 backups on the droplet from this Mac (boulderroller-v2-m6rs7).
#   scripts/backup/install.sh            credentials, scripts, cron, then a check
#   scripts/backup/install.sh --run-now  also one backup, one restore test, one
#                                        Storage copy and a freshness check, now
# Reads the R2 credentials from ~/.config/boulder-r2 (a KEY=VALUE file, or a
# folder holding one; BOULDER_R2_CONFIG overrides the path) and never prints them.
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${BOULDER_R2_CONFIG:-$HOME/.config/boulder-r2}"
HOST="${BACKUP_HOST:?set BACKUP_HOST, e.g. root@your-server}"
# One multiplexed connection: the droplet's firewall rate-limits new SSH sessions.
SSH=(ssh -o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-%C" -o ControlPersist=20m "$HOST")
DEST=/root/bin/boulder-backup

[ -e "$SOURCE" ] || { echo "No R2 credentials at $SOURCE yet." >&2; exit 2; }
r2_env="$(python3 "$HERE/envfile.py" r2 "$SOURCE")"

printf '%s\n' "$r2_env" | "${SSH[@]}" 'umask 077 && install -d -m 700 /root/.secrets &&
    cat > /root/.secrets/r2.env.new && mv /root/.secrets/r2.env.new /root/.secrets/r2.env'
unset r2_env

"${SSH[@]}" "install -d -m 700 $DEST"
for file in common.sh envfile.py backup-db.sh backup-storage.sh storage_snapshot.py restore-test.sh \
        check-freshness.sh; do
    "${SSH[@]}" "cat > $DEST/$file && chmod 700 $DEST/$file" < "$HERE/$file"
done
"${SSH[@]}" 'cat > /etc/cron.d/boulder-backups && chmod 644 /etc/cron.d/boulder-backups' \
    < "$HERE/boulder-backups.cron"
echo "Installed $DEST and /etc/cron.d/boulder-backups."

"${SSH[@]}" "$DEST/backup-db.sh --check"

if [ "${1:-}" = --run-now ]; then
    run() { "${SSH[@]}" "set -o pipefail; flock -w 1800 /run/lock/boulder-backup.lock $DEST/$1 2>&1 | tee -a /var/log/boulder-backup.log"; }
    run backup-db.sh
    run restore-test.sh
    run backup-storage.sh
    run check-freshness.sh
fi
