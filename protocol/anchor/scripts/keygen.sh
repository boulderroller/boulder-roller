#!/usr/bin/env bash
set -euo pipefail

FEE_PAYER_KEYPAIR=${FEE_PAYER_KEYPAIR:-"$HOME/.config/solana/id.json"}
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path)
      FEE_PAYER_KEYPAIR="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    *)
      echo '{"status":"error","error_code":"E_USAGE","message":"Unknown argument"}' >&2
      exit 1
      ;;
  esac
done

if [[ -f "$FEE_PAYER_KEYPAIR" && $FORCE -eq 0 ]]; then
  PUBKEY=$(solana-keygen pubkey "$FEE_PAYER_KEYPAIR")
  echo "{\"status\":\"ok\",\"action\":\"existing\",\"path\":\"$FEE_PAYER_KEYPAIR\",\"pubkey\":\"$PUBKEY\"}"
  exit 0
fi

mkdir -p "$(dirname "$FEE_PAYER_KEYPAIR")"
solana-keygen new --no-passphrase --silent --outfile "$FEE_PAYER_KEYPAIR" >/dev/null
PUBKEY=$(solana-keygen pubkey "$FEE_PAYER_KEYPAIR")

echo "{\"status\":\"ok\",\"action\":\"created\",\"path\":\"$FEE_PAYER_KEYPAIR\",\"pubkey\":\"$PUBKEY\"}"
