#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

RPC_URL=${RPC_URL:-"https://api.devnet.solana.com"}
FEE_PAYER_KEYPAIR=${FEE_PAYER_KEYPAIR:-"$HOME/.config/solana/id.json"}
EXPECTED_CLUSTER=${EXPECTED_CLUSTER:-"devnet"}
PROJECT_DIR=$(cd "$ROOT_DIR/../.." && pwd)
ADDRESSES_FILE=${ADDRESSES_FILE:-"$ROOT_DIR/addresses.devnet.json"}
BACKEND_ENV=${BACKEND_ENV:-"$PROJECT_DIR/backend/.env"}
ROOT_ENV_EXAMPLE=${ROOT_ENV_EXAMPLE:-"$PROJECT_DIR/.env.example"}
ANCHOR_TOML=${ANCHOR_TOML:-"$ROOT_DIR/Anchor.toml"}
PROGRAM_KEYPAIR=${PROGRAM_KEYPAIR:-"$ROOT_DIR/target/deploy/boulder_rollers-keypair.json"}
UPGRADE_AUTHORITY=${UPGRADE_AUTHORITY:-"$HOME/.config/solana/boulderroller-admin-upgrade-authority.json"}
PROGRAM_ID=${PROGRAM_ID:-""}
VAULT_ID=${VAULT_ID:-"1"}
UPGRADE_PREFLIGHT=false
PROGRAM_ARTIFACT=${PROGRAM_ARTIFACT:-"$ROOT_DIR/target/deploy/boulder_rollers.so"}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rpc)
      RPC_URL="$2"
      shift 2
      ;;
    --fee-payer)
      FEE_PAYER_KEYPAIR="$2"
      shift 2
      ;;
    --cluster)
      EXPECTED_CLUSTER="$2"
      shift 2
      ;;
    --addresses-file)
      ADDRESSES_FILE="$2"
      shift 2
      ;;
    --backend-env)
      BACKEND_ENV="$2"
      shift 2
      ;;
    --root-env-example)
      ROOT_ENV_EXAMPLE="$2"
      shift 2
      ;;
    --anchor-toml)
      ANCHOR_TOML="$2"
      shift 2
      ;;
    --program-keypair)
      PROGRAM_KEYPAIR="$2"
      shift 2
      ;;
    --program-id)
      PROGRAM_ID="$2"
      shift 2
      ;;
    --upgrade-authority)
      UPGRADE_AUTHORITY="$2"
      shift 2
      ;;
    --vault-id)
      VAULT_ID="$2"
      shift 2
      ;;
    --upgrade-preflight)
      UPGRADE_PREFLIGHT=true
      shift
      ;;
    *)
      echo '{"status":"error","error_code":"E_USAGE","message":"Unknown argument"}'
      exit 1
      ;;
  esac
done

# Upgrade preflight requires the exact artifact. Read-only exact validation may
# run without a local build; if a binary is present, still reject test builds.
if [[ "$UPGRADE_PREFLIGHT" == true || -f "$PROGRAM_ARTIFACT" ]]; then
  python3 "$SCRIPT_DIR/check-deployable-artifact.py" "$PROGRAM_ARTIFACT" --cluster "$EXPECTED_CLUSTER" >&2
fi

fail() {
  local code="$1"; shift
  local message="$*"
  echo "{\"status\":\"error\",\"error_code\":\"$code\",\"message\":\"$message\"}" >&2
  exit 1
}

command -v solana >/dev/null 2>&1 || fail "E_MISSING_SOLANA" "solana CLI not found on PATH"
command -v anchor >/dev/null 2>&1 || fail "E_MISSING_ANCHOR" "anchor CLI not found on PATH"
command -v node >/dev/null 2>&1 || fail "E_MISSING_NODE" "node not found on PATH"
command -v python3 >/dev/null 2>&1 || fail "E_MISSING_PYTHON" "python3 not found on PATH"

python3 "$PROJECT_DIR/protocol/scripts/check_program_version.py" \
  || fail "E_PROGRAM_VERSION" "Program version and checked-in ABI are not aligned"

SOLANA_VERSION=$(solana --version 2>/dev/null | awk '{print $2 " " $3}')
ANCHOR_VERSION=$(anchor --version 2>/dev/null | awk '{print $2}')

CURRENT_CLUSTER=$(solana config get 2>/dev/null | awk -F ': ' '/^RPC URL/{print $2}')
if [[ -z "$CURRENT_CLUSTER" ]]; then
  fail "E_NO_CONFIG" "Unable to determine current Solana RPC URL"
fi

if ! solana -u "$RPC_URL" cluster-version >/dev/null 2>&1; then
  fail "E_RPC_UNREACHABLE" "Unable to reach RPC at $RPC_URL"
fi

# A target label is not evidence of network identity. Bind it before reading
# any fee payer or authority keypair, including for private RPC endpoints.
GENESIS_HASH=$(solana --url "$RPC_URL" genesis-hash) || fail "E_GENESIS" "Cannot read RPC genesis"
# Full SDK genesis hashes (not shortened chain identifiers):
# https://github.com/solana-labs/solana/blob/v1.18.26/sdk/src/genesis_config.rs#L56-L68
case "$EXPECTED_CLUSTER" in
  devnet) [[ "$GENESIS_HASH" == "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG" ]] || fail "E_CLUSTER" "RPC is not devnet" ;;
  mainnet-beta) [[ "$GENESIS_HASH" == "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d" ]] || fail "E_CLUSTER" "RPC is not mainnet-beta" ;;
  *) fail "E_CLUSTER" "Deployable artifacts require devnet or mainnet-beta" ;;
esac

if [[ ! -f "$FEE_PAYER_KEYPAIR" ]]; then
  fail "E_NO_FEE_PAYER" "Fee payer keypair not found at $FEE_PAYER_KEYPAIR"
fi

if [[ "$EXPECTED_CLUSTER" != "" ]]; then
  case "$EXPECTED_CLUSTER" in
    devnet|localnet|mainnet-beta|testnet) ;;
    *)
      fail "E_CLUSTER" "Unsupported cluster value $EXPECTED_CLUSTER"
      ;;
  esac
fi

ARTIFACT_SHA256=""
if [[ "$UPGRADE_PREFLIGHT" == true ]]; then
  [[ -f "$UPGRADE_AUTHORITY" ]] \
    || fail "E_NO_UPGRADE_AUTHORITY" "Upgrade authority keypair not found at $UPGRADE_AUTHORITY"
  TARGET_PROGRAM_ID="$PROGRAM_ID"
  if [[ -z "$TARGET_PROGRAM_ID" ]]; then
    TARGET_PROGRAM_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["programs"]["boulder_rollers"])' "$ADDRESSES_FILE")
  fi
  UPGRADE_AUTHORITY_PUBKEY=$(solana address -k "$UPGRADE_AUTHORITY")
  FEE_PAYER_PUBKEY=$(solana address -k "$FEE_PAYER_KEYPAIR")
  [[ "$UPGRADE_AUTHORITY_PUBKEY" != "$FEE_PAYER_PUBKEY" ]] \
    || fail "E_AUTHORITY_IS_PAYER" "Upgrade authority cannot be used as the fee payer"
  PROGRAM_JSON=$(solana program show "$TARGET_PROGRAM_ID" --url "$RPC_URL" --output json) \
    || fail "E_PROGRAM_UNAVAILABLE" "Unable to read deployed program $TARGET_PROGRAM_ID"
  LIVE_UPGRADE_AUTHORITY=$(printf '%s' "$PROGRAM_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("authority", ""))')
  [[ "$LIVE_UPGRADE_AUTHORITY" == "$UPGRADE_AUTHORITY_PUBKEY" ]] \
    || fail "E_UPGRADE_AUTHORITY" "Live upgrade authority does not match $UPGRADE_AUTHORITY"
  PROGRAM_SO="$PROGRAM_ARTIFACT"
  [[ -f "$PROGRAM_SO" ]] \
    || fail "E_NO_PROGRAM_ARTIFACT" "Program artifact not found at $PROGRAM_SO"
  ARTIFACT_SHA256=$(shasum -a 256 "$PROGRAM_SO" | awk '{print $1}')
  PROGRAM_ID="$TARGET_PROGRAM_ID"
fi

cat <<JSON
{
  "status": "ok",
  "solana_version": "$SOLANA_VERSION",
  "anchor_version": "$ANCHOR_VERSION",
  "rpc_url": "$RPC_URL",
  "config_rpc_url": "$CURRENT_CLUSTER",
  "fee_payer": "$FEE_PAYER_KEYPAIR",
  "expected_cluster": "$EXPECTED_CLUSTER",
  "mode": "$([[ "$UPGRADE_PREFLIGHT" == true ]] && echo upgrade || echo exact)",
  "program_id": "$PROGRAM_ID",
  "artifact_sha256": "$ARTIFACT_SHA256"
}
JSON

VALIDATE_ARGS=(
  "--addresses-file" "$ADDRESSES_FILE"
  "--backend-env" "$BACKEND_ENV"
  "--root-env-example" "$ROOT_ENV_EXAMPLE"
  "--anchor-toml" "$ANCHOR_TOML"
  "--vault-id" "$VAULT_ID"
)

if [[ "$UPGRADE_PREFLIGHT" != true ]]; then
  VALIDATE_ARGS+=("--program-keypair" "$PROGRAM_KEYPAIR")
fi
if [[ -n "$PROGRAM_ID" ]]; then
  VALIDATE_ARGS+=("--program-id" "$PROGRAM_ID")
fi
if [[ "$UPGRADE_PREFLIGHT" == true ]]; then
  VALIDATE_ARGS+=("--configuration-only")
fi

cd "$ROOT_DIR"
SOLANA_CLUSTER="$RPC_URL" \
  NODE_OPTIONS='--loader ts-node/esm --no-warnings' \
  npx ts-node scripts/validate_deployment.ts "${VALIDATE_ARGS[@]}"
