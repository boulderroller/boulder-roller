#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: $0 <ssh-host> <image-tag> [compose-path]" >&2
  exit 1
fi

SSH_HOST="$1"
IMAGE_TAG="$2"
COMPOSE_PATH="${3:-/opt/boulder/docker-compose.yml}"
IMAGE_REPO="${IMAGE_REPO:-boulderrollers/api}"

echo "Deploying ${IMAGE_REPO}:${IMAGE_TAG} to ${SSH_HOST}"

ssh "root@${SSH_HOST}" <<EOF
set -euo pipefail
export IMAGE_TAG="${IMAGE_TAG}"
export IMAGE_REPO="${IMAGE_REPO}"

docker pull "\${IMAGE_REPO}:\${IMAGE_TAG}"
docker tag "\${IMAGE_REPO}:\${IMAGE_TAG}" "\${IMAGE_REPO}:current"

cd "$(dirname "${COMPOSE_PATH}")"
IMAGE_TAG="\${IMAGE_TAG}" IMAGE_REPO="\${IMAGE_REPO}" docker compose -f "${COMPOSE_PATH}" up -d --no-deps api
EOF

echo "Deployment complete."
