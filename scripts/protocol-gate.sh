#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/boulder_pycache}"
export PYTHONPYCACHEPREFIX

run_step() {
  local label="$1"
  shift
  printf '\n== %s ==\n' "$label"
  "$@"
}

run_backend_gate() {
  cd "$ROOT_DIR/backend"
  python3 -m compileall -q \
    app/client_contracts.py \
    app/solana_direct.py \
    app/services/nats_consumer.py \
    app/routes/rides.py \
    scripts/smoke_devnet_economics.py \
    scripts/smoke_wallet_signed_economics.py \
    tests/repositories/test_vault_completion_idempotency.py \
    tests/scripts/test_smoke_receipt_backed_completion.py \
    tests/services/test_nats_consumer_ride_ingest.py \
    tests/services/test_ride_processor_client_contract_smoke.py \
    tests/truths/alignment/test_client_contract_integration_gate.py \
    tests/truths/alignment/test_client_surface_requirements_gate.py
  pytest \
    tests/routes/test_client_contracts.py \
    tests/routes/test_ride_attestation_handshake.py \
    tests/repositories/test_vault_completion_idempotency.py \
    tests/scripts/test_smoke_receipt_backed_completion.py \
    tests/services/test_nats_consumer_ride_ingest.py \
    tests/services/test_ride_processor_client_contract_smoke.py \
    tests/services/test_ride_processor_preliminary_review_flow.py \
    tests/truths/alignment/test_client_contract_integration_gate.py \
    tests/truths/alignment/test_client_surface_requirements_gate.py \
    tests/truths/alignment/test_product_path_registry_gate.py \
    tests/truths/alignment/test_ride_hash_symmetry_gate.py \
    -q
}

run_mobile_contract_gate() {
  cd "$ROOT_DIR/mobile"
  npm test -- \
    --runTestsByPath \
    src/lib/__tests__/api.test.ts \
    src/lib/__tests__/attestation.test.ts \
    src/lib/__tests__/canonicalize.test.ts \
    src/lib/__tests__/preliminaryHash.test.ts \
    src/services/__tests__/uploadQueue.test.ts \
    --runInBand
}

run_scan_gate() {
  cd "$ROOT_DIR/web/scan"
  npm run typecheck
  npm test -- --run
}

run_portal_gate() {
  cd "$ROOT_DIR/web/portal"
  npm run build
}

case "${1:-all}" in
  all)
    run_step "backend protocol contracts" run_backend_gate
    run_step "mobile contract seams" run_mobile_contract_gate
    run_step "BoulderScan typecheck and tests" run_scan_gate
    run_step "portal build" run_portal_gate
    ;;
  backend)
    run_step "backend protocol contracts" run_backend_gate
    ;;
  mobile)
    run_step "mobile contract seams" run_mobile_contract_gate
    ;;
  scan)
    run_step "BoulderScan typecheck and tests" run_scan_gate
    ;;
  portal)
    run_step "portal build" run_portal_gate
    ;;
  *)
    echo "Usage: $0 [all|backend|mobile|scan|portal]" >&2
    exit 2
    ;;
esac
