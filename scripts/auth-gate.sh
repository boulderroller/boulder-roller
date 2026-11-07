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

run_static_auth_gate() {
  cd "$ROOT_DIR"
  python3 tools/check_auth_contract.py
}

run_backend_auth_tests() {
  cd "$ROOT_DIR/backend"
  pytest tests/test_routes.py -q -k \
    "auth_flow or refresh_rotates_token or recent_refresh_rotation or refresh_reuse_after_rotation_grace or missing_refresh_record or auth_request_contract or onboarding_state_reflects_invite or invite_validate or wallet_signup or logout_revokes or privy_verify"
}

run_mobile_auth_tests() {
  cd "$ROOT_DIR/mobile"
  npm test -- \
    --runTestsByPath \
    src/lib/__tests__/api.test.ts \
    src/lib/__tests__/authState.test.ts \
    src/components/__tests__/PrivyAuthBridge.test.tsx \
    src/services/__tests__/authService.wallet.test.ts \
    src/services/wallet/__tests__/mwaWallet.test.ts \
    --runInBand
}

run_portal_auth_build() {
  cd "$ROOT_DIR/web/portal"
  npm run build
}

case "${1:-all}" in
  all)
    run_step "static auth contract" run_static_auth_gate
    run_step "backend auth routes" run_backend_auth_tests
    run_step "mobile auth tests" run_mobile_auth_tests
    run_step "portal auth build" run_portal_auth_build
    ;;
  static)
    run_step "static auth contract" run_static_auth_gate
    ;;
  backend)
    run_step "backend auth routes" run_backend_auth_tests
    ;;
  mobile)
    run_step "mobile auth tests" run_mobile_auth_tests
    ;;
  portal)
    run_step "portal auth build" run_portal_auth_build
    ;;
  *)
    echo "Usage: $0 [all|static|backend|mobile|portal]" >&2
    exit 2
    ;;
esac
