#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
RPC_URL=${RPC_URL:-"https://api.devnet.solana.com"}
PROGRAM_ID=${DUNG_MINT_PROGRAM_ID:-""}
DECIMALS=6

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rpc)
      RPC_URL="$2"
      shift 2
      ;;
    --program)
      PROGRAM_ID="$2"
      shift 2
      ;;
    --decimals)
      DECIMALS="$2"
      shift 2
      ;;
    *)
      echo '{"status":"error","error_code":"E_USAGE","message":"Unknown argument"}' >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PROGRAM_ID" ]]; then
  echo '{"status":"error","error_code":"E_PROGRAM","message":"DUNG_MINT_PROGRAM_ID not provided"}' >&2
  exit 1
fi

AUTHORITY=$(node - <<'NODE'
const { PublicKey } = require('@solana/web3.js');
const programId = new PublicKey(process.argv[1]);
const seed = Buffer.from('mint_auth');
const [pda] = PublicKey.findProgramAddressSync([seed], programId);
process.stdout.write(pda.toBase58());
NODE
"$PROGRAM_ID")

TMP_JSON=$(mktemp)
trap 'rm -f "$TMP_JSON"' EXIT

spl-token create-token --decimals "$DECIMALS" --mint-authority "$AUTHORITY" --url "$RPC_URL" --output json >"$TMP_JSON"

MINT=$(node - <<'NODE'
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
process.stdout.write(data.token);
NODE
"$TMP_JSON")

SIG=$(node - <<'NODE'
const fs = require('fs');
const data = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));
process.stdout.write(data.signature);
NODE
"$TMP_JSON")

cat <<JSON
{
  "mint": "$MINT",
  "authority_pda": "$AUTHORITY",
  "decimals": $DECIMALS,
  "tx": "$SIG"
}
JSON
