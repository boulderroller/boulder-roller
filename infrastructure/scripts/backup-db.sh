#!/usr/bin/env bash
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/boulder}"
DATE=$(date +%Y%m%d_%H%M%S)
FILE="${BACKUP_DIR}/db_backup_${DATE}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "Dumping database to ${FILE}"
pg_dump "${DATABASE_URL}" | gzip > "${FILE}"

if [ -n "${SPACES_BUCKET:-}" ]; then
  echo "Uploading backup to ${SPACES_BUCKET}"
  aws s3 cp "${FILE}" "s3://${SPACES_BUCKET}/"
fi

# Keep only last 7 backups locally
ls -1t "${BACKUP_DIR}"/db_backup_*.sql.gz | tail -n +8 | xargs -r rm -f
