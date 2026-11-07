#!/usr/bin/env bash
# Shared backend release path for staging operations and GitHub Actions.

set -euo pipefail

DEPLOY_SHA="${1:-${DEPLOY_SHA:-${APP_VERSION:-}}}"
if [ -z "$DEPLOY_SHA" ]; then
    DEPLOY_SHA="$(git rev-parse HEAD)"
fi

export APP_VERSION="$DEPLOY_SHA"

SQL_BASELINE_THROUGH="${SQL_BASELINE_THROUGH:-101}"
API_HEALTH_URL="${API_HEALTH_URL:-http://localhost:8080/health/db}"
API_CHAIN_HEALTH_URL="${API_CHAIN_HEALTH_URL:-http://localhost:8080/health/chain}"
API_STATUS_URL="${API_STATUS_URL:-http://localhost:8080/status}"
API_HEALTH_ATTEMPTS="${API_HEALTH_ATTEMPTS:-30}"
API_HEALTH_SLEEP_SECONDS="${API_HEALTH_SLEEP_SECONDS:-2}"
API_LOG_TAIL="${API_LOG_TAIL:-80}"
INDEXER_HOST_PORT="${INDEXER_HOST_PORT:-3002}"
INDEXER_HEALTH_URL="${INDEXER_HEALTH_URL:-http://localhost:${INDEXER_HOST_PORT}/health}"
INDEXER_OBSERVATORY_URL="${INDEXER_OBSERVATORY_URL:-http://localhost:${INDEXER_HOST_PORT}/v1/observatory}"
INDEXER_HEALTH_ATTEMPTS="${INDEXER_HEALTH_ATTEMPTS:-60}"
INDEXER_HEALTH_SLEEP_SECONDS="${INDEXER_HEALTH_SLEEP_SECONDS:-2}"
INDEXER_LOG_TAIL="${INDEXER_LOG_TAIL:-120}"
INDEXER_IMAGE="${INDEXER_IMAGE:-boulder-repo-indexer}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"

# A release that fails after it replaced the running one puts the previous
# release back: the API and indexer images it ran, and the keeper if it was
# running. The run still fails, and Alertmanager pages Telegram. A failure
# before the switch only restarts the keeper this script paused.
PREVIOUS_SHA="$(docker compose ps -a --format '{{.Image}}' api 2>/dev/null | head -n 1 | sed 's/.*://' || true)"
if [[ ! "$PREVIOUS_SHA" =~ ^[0-9a-f]{40}$ ]] || [ "$PREVIOUS_SHA" = "$DEPLOY_SHA" ]; then
    PREVIOUS_SHA=""
fi
PREVIOUS_INDEXER_ID="$(docker inspect -f '{{.Image}}' "$(docker compose ps -a -q indexer 2>/dev/null | head -n 1 || true)" 2>/dev/null || true)"
KEEPER_WAS_RUNNING="$(docker compose ps --status running -q keeper 2>/dev/null | head -n 1 || true)"
if [ -n "$PREVIOUS_INDEXER_ID" ]; then
    docker tag "$PREVIOUS_INDEXER_ID" "$INDEXER_IMAGE:rollback"
fi
switched=0

alert_release() {
    local summary="$1" ends
    ends="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v+1H +%Y-%m-%dT%H:%M:%SZ)"
    curl -fsS -m 10 -o /dev/null -H 'Content-Type: application/json' \
        -d "[{\"labels\":{\"alertname\":\"BoulderDeployRolledBack\",\"severity\":\"critical\"},\"annotations\":{\"summary\":\"$summary\"},\"endsAt\":\"$ends\"}]" \
        "$ALERTMANAGER_URL/api/v2/alerts" || echo "Alertmanager unreachable; no page sent"
}

restore_previous_release() {
    local status=$?
    trap - EXIT
    if [ "$status" -eq 0 ]; then
        exit 0
    fi
    set +e
    if [ -z "$PREVIOUS_SHA" ]; then
        echo "Release $DEPLOY_SHA failed and no previous release is recorded to restore"
        alert_release "Deploy ${DEPLOY_SHA:0:9} failed; no previous release to restore"
        exit "$status"
    fi
    export APP_VERSION="$PREVIOUS_SHA"
    if [ "$switched" -eq 1 ]; then
        echo "Release $DEPLOY_SHA failed after the switch; restoring $PREVIOUS_SHA..."
        if docker image inspect "$INDEXER_IMAGE:rollback" > /dev/null 2>&1; then
            docker tag "$INDEXER_IMAGE:rollback" "$INDEXER_IMAGE:latest"
        fi
        docker compose up -d --no-build --no-deps api indexer
        local restored=no i
        for i in $(seq 1 "$API_HEALTH_ATTEMPTS"); do
            if curl -fsS "$API_HEALTH_URL" > /dev/null; then
                restored=yes
                break
            fi
            sleep "$API_HEALTH_SLEEP_SECONDS"
        done
        echo "Previous release $PREVIOUS_SHA healthy after restore: $restored"
    fi
    if [ -n "$KEEPER_WAS_RUNNING" ]; then
        docker compose up -d --no-build --no-deps keeper || echo "Stage 1 keeper did not restart"
    fi
    if [ "$switched" -eq 1 ]; then
        alert_release "Deploy ${DEPLOY_SHA:0:9} failed its health checks; rolled back to ${PREVIOUS_SHA:0:9} (healthy: ${restored:-no})"
    fi
    exit "$status"
}
trap restore_previous_release EXIT

echo "Building backend and indexer images at $DEPLOY_SHA..."
docker compose build api indexer

# The keeper writes its own tables; pause it so migrations never wait on it.
echo "Pausing the Stage 1 keeper..."
docker compose stop keeper || true

echo "Applying backend SQL migrations..."
docker compose run --rm --no-deps api python scripts/apply_sql_migrations.py --sql-dir sql --baseline-through "$SQL_BASELINE_THROUGH" --reload-postgrest

echo "Checking backend schema invariants..."
docker compose run --rm --no-deps api python scripts/check_schema_invariants.py

echo "Starting backend services at $DEPLOY_SHA..."
switched=1
docker compose stop api indexer || true
docker compose rm -f api indexer || true
docker compose up -d api indexer
docker compose ps api nats indexer caddy

echo "Verifying backend health..."
i=0
until curl -fsS "$API_HEALTH_URL"; do
    i=$((i + 1))
    if [ "$i" -ge "$API_HEALTH_ATTEMPTS" ]; then
        echo "Health check failed after $((API_HEALTH_ATTEMPTS * API_HEALTH_SLEEP_SECONDS)) seconds"
        docker compose logs api --tail="$API_LOG_TAIL" || true
        exit 1
    fi
    sleep "$API_HEALTH_SLEEP_SECONDS"
done
echo ""

echo "Verifying backend chain compatibility..."
i=0
until curl -fsS "$API_CHAIN_HEALTH_URL"; do
    i=$((i + 1))
    if [ "$i" -ge "$API_HEALTH_ATTEMPTS" ]; then
        echo "Backend chain health check failed after $((API_HEALTH_ATTEMPTS * API_HEALTH_SLEEP_SECONDS)) seconds"
        docker compose logs api --tail="$API_LOG_TAIL" || true
        exit 1
    fi
    sleep "$API_HEALTH_SLEEP_SECONDS"
done
echo ""

status_payload="$(curl -fsS "$API_STATUS_URL")"
echo "$status_payload"
STATUS_PAYLOAD="$status_payload" EXPECTED_COMMIT="$DEPLOY_SHA" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["STATUS_PAYLOAD"])
expected = os.environ["EXPECTED_COMMIT"]
errors = []

if payload.get("version") != expected:
    errors.append(f"running version {payload.get('version')} does not match deploy SHA {expected}")

if payload.get("environment_public") and payload.get("auth_signature_bypass_effective"):
    errors.append("public environment has effective AUTH_SIGNATURE_BYPASS")

if payload.get("environment_public") and payload.get("dev_routes_enabled"):
    errors.append("public environment has dev routes enabled")

if payload.get("environment_public") and payload.get("invite_required") is not True:
    errors.append("public environment requires invite_required=true")

if errors:
    for error in errors:
        print(error)
    raise SystemExit(1)
PY

echo "Verifying indexer health..."
i=0
while true; do
    indexer_health_payload="$(curl -fsS "$INDEXER_HEALTH_URL" || true)"
    if INDEXER_HEALTH_PAYLOAD="$indexer_health_payload" python3 - <<'PY'
import json
import os

errors = []
try:
    payload = json.loads(os.environ["INDEXER_HEALTH_PAYLOAD"])
except (KeyError, json.JSONDecodeError) as exc:
    payload = {}
    errors.append(f"indexer health response is not valid JSON: {exc}")

if payload.get("status") != "ok":
    errors.append(f"indexer status is {payload.get('status')!r}, not 'ok'")

snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
if not isinstance(snapshot, dict):
    errors.append("indexer health response has no snapshot outcome")
else:
    if snapshot.get("status") != "succeeded":
        errors.append(f"snapshot status is {snapshot.get('status')!r}, not 'succeeded'")
    for field in ("decode_failures", "write_failures", "fetch_failures"):
        value = snapshot.get(field)
        if value != 0:
            errors.append(f"snapshot {field.replace('_', ' ')} is {value!r}, not 0")

if errors:
    for error in errors:
        print(error)
    raise SystemExit(1)
PY
    then
        echo "$indexer_health_payload"
        break
    fi

    i=$((i + 1))
    if [ "$i" -ge "$INDEXER_HEALTH_ATTEMPTS" ]; then
        echo "Indexer health check failed after $((INDEXER_HEALTH_ATTEMPTS * INDEXER_HEALTH_SLEEP_SECONDS)) seconds"
        docker compose logs indexer --tail="$INDEXER_LOG_TAIL" || true
        exit 1
    fi
    sleep "$INDEXER_HEALTH_SLEEP_SECONDS"
done
echo ""

echo "Verifying canonical DUNG circulating supply..."
i=0
while true; do
    # The observatory payload carries every canon centerline; it is far too large for an
    # environment variable, so it goes through a temp file.
    indexer_payload_file="$(mktemp)"
    curl -fsS "$INDEXER_OBSERVATORY_URL" -o "$indexer_payload_file" || : > "$indexer_payload_file"
    if INDEXER_PAYLOAD_FILE="$indexer_payload_file" python3 - <<'PY'
import json
import os

U64_MAX = 2**64 - 1
errors = []

try:
    with open(os.environ["INDEXER_PAYLOAD_FILE"], encoding="utf-8") as handle:
        payload = json.load(handle)
except (KeyError, OSError, json.JSONDecodeError) as exc:
    payload = {}
    errors.append(f"indexer observatory response is not valid JSON: {exc}")

supply = payload.get("supply") if isinstance(payload, dict) else None
if not isinstance(supply, dict):
    errors.append("indexer observatory response has no supply object")
else:
    source = supply.get("circulating_source")
    if source != "spl_mint_supply":
        errors.append(
            f"circulating source {source!r} is not canonical spl_mint_supply"
        )

    circulating = supply.get("circulating")
    if not isinstance(circulating, str) or not circulating.isdigit():
        errors.append("circulating supply is not an exact decimal base-unit string")
    elif int(circulating) > U64_MAX:
        errors.append("circulating supply exceeds the SPL u64 range")

    slot = supply.get("spl_mint_supply_slot")
    if isinstance(slot, bool) or not str(slot).isdigit():
        errors.append("SPL mint supply slot is missing or invalid")

if errors:
    for error in errors:
        print(error)
    raise SystemExit(1)
PY
    then
        python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps({"vault_count": d.get("vault_count"), "supply": d.get("supply")}))' "$indexer_payload_file" || true
        rm -f "$indexer_payload_file"
        break
    fi
    rm -f "$indexer_payload_file"

    i=$((i + 1))
    if [ "$i" -ge "$INDEXER_HEALTH_ATTEMPTS" ]; then
        echo "Canonical DUNG supply was unavailable after $((INDEXER_HEALTH_ATTEMPTS * INDEXER_HEALTH_SLEEP_SECONDS)) seconds"
        docker compose logs indexer --tail="$INDEXER_LOG_TAIL" || true
        exit 1
    fi
    sleep "$INDEXER_HEALTH_SLEEP_SECONDS"
done

echo "Backend and indexer release verified at $DEPLOY_SHA"
# From here on the new release stays: nothing below rolls it back.
trap - EXIT

# The keeper runs this verified image only after the API and indexer pass.
# It exits at once unless STAGE1_KEEPER_ENABLED=true; a failed start is
# reported, not fatal, because the API and indexer are already live.
echo "Starting the Stage 1 keeper at $DEPLOY_SHA..."
docker compose rm -f keeper || true
docker compose up -d --no-deps keeper || echo "Stage 1 keeper did not start"

# Every release builds a backend image of about 1.4 GB tagged by commit, and
# nothing removed old ones: on 14 Oct 2026 the droplet held 69 of them and its
# disk was 89% full. Keep this release plus the newest others for rollback.
# Docker refuses to remove an image a container still uses, and a failed
# cleanup never fails a verified release.
BACKEND_IMAGE_REPOSITORY="${BACKEND_IMAGE_REPOSITORY:-boulder-repo-backend}"
BACKEND_ROLLBACK_IMAGES="${BACKEND_ROLLBACK_IMAGES:-2}"
echo "Removing backend images beyond this release and $BACKEND_ROLLBACK_IMAGES rollback images..."
kept=0
# docker images lists the newest first.
for tag in $(docker images "$BACKEND_IMAGE_REPOSITORY" --format '{{.Tag}}' || true); do
    if [ "$tag" = "$DEPLOY_SHA" ] || [ "$tag" = "<none>" ]; then
        continue
    fi
    if [ "$kept" -lt "$BACKEND_ROLLBACK_IMAGES" ]; then
        kept=$((kept + 1))
        continue
    fi
    docker rmi "$BACKEND_IMAGE_REPOSITORY:$tag" > /dev/null || echo "Kept $BACKEND_IMAGE_REPOSITORY:$tag"
done
docker image prune -f > /dev/null || true
docker builder prune -f --filter until=168h > /dev/null || true

# Alert rules ship with each release; Prometheus reads them from the checkout.
if docker ps --format '{{.Names}}' | grep -qx prometheus; then
    if curl -fsS -X POST "${PROMETHEUS_RELOAD_URL:-http://127.0.0.1:9090/-/reload}" > /dev/null; then
        echo "Prometheus rules reloaded"
    else
        echo "Prometheus reload failed; the rules update on its next restart"
    fi
fi
