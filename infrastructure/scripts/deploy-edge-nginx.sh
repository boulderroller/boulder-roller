#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <ssh-host> [remote-conf-path]" >&2
  exit 1
fi

SSH_HOST="$1"
REMOTE_CONF_PATH="${2:-/etc/nginx/sites-available/api.boulderroller.xyz.conf}"
LOCAL_CONF_PATH="$(cd "$(dirname "$0")/.." && pwd)/edge/nginx/api.boulderroller.xyz.conf"

echo "Uploading edge nginx config to ${SSH_HOST}:${REMOTE_CONF_PATH}"
scp "${LOCAL_CONF_PATH}" "root@${SSH_HOST}:${REMOTE_CONF_PATH}"

echo "Testing and reloading nginx on ${SSH_HOST}"
ssh "root@${SSH_HOST}" <<EOF
set -euo pipefail
ln -sfn "${REMOTE_CONF_PATH}" /etc/nginx/sites-enabled/api.boulderroller.xyz.conf
nginx -t
systemctl reload nginx
EOF

echo "Edge config deploy complete."
