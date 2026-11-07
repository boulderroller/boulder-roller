#!/bin/bash
# staging-ops.sh - Staging droplet operations helper
# Usage: bash scripts/hooks/staging-ops.sh <command> [args...]
#
# Commands:
#   health          - Full health check (API + status + repo + containers + disk + SOL balance)
#   logs [n]        - Tail API logs (default 50 lines)
#   exec <cmd>      - Run python command inside API container
#   deploy          - Git pull + rebuild backend services + runtime verification
#   migrate-sql     - Apply backend/sql migrations through DATABASE_URL
#   schema-preflight - Verify critical schema objects match the migration ledger
#   repo-clean      - Backup and remove untracked repo junk on staging
#   docker-prune    - Reclaim unused Docker images and build cache on staging
#   env-list        - List env vars (redacted)
#   env-set K=V     - Append env var
#   db-query <sql>  - Run SQL via psql
#   containers      - Show container status
#   restart         - Restart backend services
#   disk            - Check disk usage

set -euo pipefail

DROPLET="root@${DROPLET_IP:?Set DROPLET_IP}"
REPO="/root/boulder-repo"
API_PORT=8080
SSH_OPTS="-o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=no"

status_json() {
    curl -s --max-time 5 "http://${DROPLET_IP:?Set DROPLET_IP}:$API_PORT/status" 2>/dev/null || true
}

print_status_summary() {
    STATUS_JSON="$1" python3 - <<'PY'
import json
import os

raw = (os.environ.get("STATUS_JSON") or "").strip()
if not raw:
    print("  unavailable")
    raise SystemExit(0)

try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    print(f"  raw={raw}")
    raise SystemExit(0)

print(
    "  env={env} public={public} version={version} "
    "bypass_requested={requested} bypass_effective={effective} "
    "cookie_secure={cookie_secure} dev_routes={dev_routes}".format(
        env=payload.get("environment"),
        public=payload.get("environment_public"),
        version=payload.get("version"),
        requested=payload.get("auth_signature_bypass_requested"),
        effective=payload.get("auth_signature_bypass_effective"),
        cookie_secure=payload.get("auth_cookie_secure"),
        dev_routes=payload.get("dev_routes_enabled"),
    )
)
PY
}

verify_status_against_commit() {
    STATUS_JSON="$1" EXPECTED_COMMIT="$2" python3 - <<'PY'
import json
import os
import sys

raw = (os.environ.get("STATUS_JSON") or "").strip()
expected = (os.environ.get("EXPECTED_COMMIT") or "").strip()
if not raw:
    print("No /status payload received")
    raise SystemExit(1)

payload = json.loads(raw)
errors = []

if not expected:
    errors.append("missing expected commit")
elif payload.get("version") != expected:
    errors.append(f"running version {payload.get('version')} does not match repo HEAD {expected}")

if payload.get("environment_public") and payload.get("auth_signature_bypass_effective"):
    errors.append("public environment still has effective AUTH_SIGNATURE_BYPASS")

if payload.get("environment_public") and payload.get("dev_routes_enabled"):
    errors.append("public environment still has dev routes enabled")

if errors:
    for error in errors:
        print(error)
    raise SystemExit(1)

print(
    "Runtime verified: version={version} env={env} bypass_effective={bypass} dev_routes={dev_routes}".format(
        version=payload.get("version"),
        env=payload.get("environment"),
        bypass=payload.get("auth_signature_bypass_effective"),
        dev_routes=payload.get("dev_routes_enabled"),
    )
)
PY
}

run_sql_migrations() {
    APP_VERSION_VALUE="${1:-}"
    APP_VERSION_PREFIX=""
    if [ -n "$APP_VERSION_VALUE" ]; then
        APP_VERSION_PREFIX="APP_VERSION=$APP_VERSION_VALUE "
    fi
    ssh $SSH_OPTS $DROPLET "cd $REPO && ${APP_VERSION_PREFIX}docker compose run --rm --no-deps api python scripts/apply_sql_migrations.py --sql-dir sql --baseline-through 101 --reload-postgrest" 2>&1
}

run_schema_preflight() {
    APP_VERSION_VALUE="${1:-}"
    APP_VERSION_PREFIX=""
    if [ -n "$APP_VERSION_VALUE" ]; then
        APP_VERSION_PREFIX="APP_VERSION=$APP_VERSION_VALUE "
    fi
    ssh $SSH_OPTS $DROPLET "cd $REPO && ${APP_VERSION_PREFIX}docker compose run --rm --no-deps api python scripts/check_schema_invariants.py" 2>&1
}

cmd="${1:-health}"
shift 2>/dev/null || true

case "$cmd" in
    health)
        echo "=== Staging Health Check ==="
        # API
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://${DROPLET_IP:?Set DROPLET_IP}:$API_PORT/health" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
            echo "API: UP (HTTP $HTTP_CODE)"
            curl -s --max-time 5 "http://${DROPLET_IP:?Set DROPLET_IP}:$API_PORT/health" 2>/dev/null
        else
            echo "API: DOWN (HTTP $HTTP_CODE)"
        fi
        echo ""
        echo "Status:"
        STATUS_JSON="$(status_json)"
        print_status_summary "$STATUS_JSON"
        echo ""
        echo "Repo:"
        ssh $SSH_OPTS $DROPLET "cd $REPO && printf '  HEAD %s\n' \"\$(git rev-parse HEAD)\" && DIRTY=\$(git status --short | wc -l | tr -d ' ') && printf '  dirty_entries %s\n' \"\$DIRTY\"" 2>/dev/null || echo "  SSH failed"
        echo ""
        # Containers
        echo "Containers:"
        ssh $SSH_OPTS $DROPLET "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'" 2>/dev/null || echo "  SSH failed"
        echo ""
        # Disk
        echo "Disk:"
        ssh $SSH_OPTS $DROPLET "df -h / | tail -1" 2>/dev/null || echo "  SSH failed"
        echo ""
        # SOL balance
        echo "SOL Balance:"
        ssh $SSH_OPTS $DROPLET "cd $REPO && docker compose exec -T api python -c \"
import os, json
from solders.keypair import Keypair
from solana.rpc.api import Client
secret = json.loads(os.environ.get('SOLANA_PAYER_SECRET', '[]'))
if secret:
    kp = Keypair.from_bytes(bytes(secret))
    client = Client(os.environ.get('SOLANA_RPC_URL', 'https://api.devnet.solana.com'))
    bal = client.get_balance(kp.pubkey())
    print(f'  {kp.pubkey()}: {bal.value / 1e9:.4f} SOL')
else:
    print('  No SOLANA_PAYER_SECRET configured')
\"" 2>/dev/null || echo "  Could not check"
        echo "===================="
        ;;

    logs)
        LINES="${1:-50}"
        ssh $SSH_OPTS $DROPLET "cd $REPO && docker compose logs api --tail=$LINES 2>&1"
        ;;

    exec)
        PYCMD="$*"
        ssh $SSH_OPTS $DROPLET "cd $REPO && docker compose exec -T api python -c \"
import os, sys
sys.path.insert(0, '/app')
$PYCMD
\""
        ;;

    deploy)
        echo "=== Deploying to Staging ==="
        BRANCH=$(git branch --show-current 2>/dev/null || echo "main")
        echo "Pushing $BRANCH..."
        ssh $SSH_OPTS $DROPLET "cd $REPO && git fetch origin && git checkout $BRANCH && git pull origin $BRANCH" 2>&1
        REMOTE_HEAD=$(ssh $SSH_OPTS $DROPLET "cd $REPO && git rev-parse HEAD" 2>/dev/null || true)
        echo ""
        echo "Running shared backend release at $REMOTE_HEAD..."
        ssh $SSH_OPTS $DROPLET "cd $REPO && scripts/deploy-backend-release.sh $REMOTE_HEAD" 2>&1
        echo ""
        COMMIT=$(ssh $SSH_OPTS $DROPLET "cd $REPO && git log --oneline -1" 2>/dev/null)
        echo "Deploy SUCCESS - backend release path verified"
        echo "Deployed commit: $COMMIT"
        echo "===================="
        ;;

    migrate-sql)
        echo "=== Applying Staging SQL Migrations ==="
        REMOTE_HEAD=$(ssh $SSH_OPTS $DROPLET "cd $REPO && git rev-parse HEAD" 2>/dev/null || true)
        run_sql_migrations "$REMOTE_HEAD"
        echo ""
        echo "Checking backend schema invariants..."
        run_schema_preflight "$REMOTE_HEAD"
        echo "===================="
        ;;

    schema-preflight)
        echo "=== Checking Staging Schema Invariants ==="
        REMOTE_HEAD=$(ssh $SSH_OPTS $DROPLET "cd $REPO && git rev-parse HEAD" 2>/dev/null || true)
        run_schema_preflight "$REMOTE_HEAD"
        echo "===================="
        ;;

    repo-clean)
        echo "=== Cleaning Staging Repo Junk ==="
        ssh $SSH_OPTS $DROPLET "cd $REPO && python3 - <<'PY'
from datetime import datetime
from pathlib import Path
import json
import subprocess
import tarfile

repo = Path('.').resolve()
status = subprocess.run(
    ['git', 'status', '--porcelain'],
    capture_output=True,
    text=True,
    check=True,
)
untracked = []
for line in status.stdout.splitlines():
    if line.startswith('?? '):
        rel = line[3:]
        target = repo / rel
        if target.exists():
            untracked.append(rel)

print(f'untracked_count={len(untracked)}')
if not untracked:
    raise SystemExit(0)

timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
backup = Path('/root') / f'boulder-repo-untracked-backup-{timestamp}.tgz'
with tarfile.open(backup, 'w:gz') as tar:
    for rel in untracked:
        tar.add(repo / rel, arcname=rel)

print(f'backup={backup}')
print('sample=' + json.dumps(untracked[:10]))
PY
git clean -fd" 2>&1
        echo "===================="
        ;;

    docker-prune)
        echo "=== Pruning Staging Docker Cache ==="
        ssh $SSH_OPTS $DROPLET "docker system df && echo '' && docker image prune -af && echo '' && docker builder prune -af && echo '' && docker system df" 2>&1
        echo "===================="
        ;;

    env-list)
        echo "=== Staging Environment (redacted) ==="
        ssh $SSH_OPTS $DROPLET "python3 - <<'PY'
from pathlib import Path

env_path = Path('$REPO/.env')
secret_name_parts = ('SECRET', 'KEY', 'PASSWORD', 'TOKEN')
secret_names = {'DATABASE_URL', 'INDEXER_DATABASE_URL'}
secret_value_markers = ('api-key=', 'apikey=', 'access_token=', 'refresh_token=', 'password=')

for raw in env_path.read_text().splitlines() if env_path.exists() else []:
    if not raw or raw.lstrip().startswith('#') or '=' not in raw:
        print(raw)
        continue

    key, value = raw.split('=', 1)
    upper_key = key.upper()
    lower_value = value.lower()
    credential_url = '://' in value and '@' in value
    secret_value = any(marker in lower_value for marker in secret_value_markers)

    if upper_key in secret_names or any(part in upper_key for part in secret_name_parts) or credential_url or secret_value:
        print(f'{key}=***REDACTED***')
    else:
        print(raw)
PY" 2>/dev/null
        ;;

    env-set)
        if [ -z "${1:-}" ]; then
            echo "Usage: staging-ops.sh env-set KEY=VALUE"
            exit 1
        fi
        KEY_VAL="$1"
        KEY=$(echo "$KEY_VAL" | cut -d= -f1)
        # Remove existing key if present, then append
        ssh $SSH_OPTS $DROPLET "cd $REPO && sed -i '/^${KEY}=/d' .env && echo '$KEY_VAL' >> .env && echo 'Set $KEY in .env'"
        echo "Restart backend services to apply: bash scripts/hooks/staging-ops.sh restart"
        ;;

    containers)
        ssh $SSH_OPTS $DROPLET "docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'" 2>/dev/null
        ;;

    restart)
        echo "Restarting backend services..."
        ssh $SSH_OPTS $DROPLET "cd $REPO && APP_VERSION=\$(git rev-parse HEAD) docker compose up -d api" 2>&1
        sleep 5
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://${DROPLET_IP:?Set DROPLET_IP}:$API_PORT/health" 2>/dev/null || echo "000")
        echo "API health: HTTP $HTTP_CODE"
        STATUS_JSON="$(status_json)"
        print_status_summary "$STATUS_JSON"
        ;;

    disk)
        ssh $SSH_OPTS $DROPLET "df -h / && echo '' && docker system df" 2>/dev/null
        ;;

    db-query)
        SQL="$*"
        ssh $SSH_OPTS $DROPLET "cd $REPO && docker compose exec -T api python -c \"
import os, sys
sys.path.insert(0, '/app')
from app.supabase_client import create_backend_supabase_client
db = create_backend_supabase_client(
    os.environ['SUPABASE_URL'],
    os.environ['SUPABASE_SERVICE_KEY'],
)
result = db.rpc('exec_sql', {'sql': '''$SQL'''}).execute()
import json
print(json.dumps(result.data, indent=2))
\"" 2>/dev/null
        ;;

    *)
        echo "Unknown command: $cmd"
        echo "Available: health, logs, exec, deploy, migrate-sql, repo-clean, docker-prune, env-list, env-set, containers, restart, disk, db-query"
        exit 1
        ;;
esac
