#!/usr/bin/env bash
set -euo pipefail

BASE="http://localhost:8000"
WALLET="WALLET_TEST"
DEVICE_ID="$(uuidgen)"

jq_present() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required for this script" >&2
    exit 1
  fi
}

jq_present

echo "1) health"
curl -s "$BASE/health/db" | jq .

echo "2) auth nonce"
NONCE_RES=$(curl -s -X POST "$BASE/auth/nonce" -H 'Content-Type: application/json' \
  -d "{\"wallet\":\"$WALLET\",\"device_id\":\"$DEVICE_ID\"}")
echo "$NONCE_RES" | jq .
NONCE=$(echo "$NONCE_RES" | jq -r .nonce)
if [[ "$NONCE" == "null" || -z "$NONCE" ]]; then
  echo "Failed to obtain nonce" >&2
  exit 1
fi

echo "3) auth verify"
VERIFY_RES=$(curl -s -X POST "$BASE/auth/verify" -H 'Content-Type: application/json' \
  -d "{\"wallet\":\"$WALLET\",\"signature\":\"stub-signature\",\"nonce\":\"$NONCE\",\"device_id\":\"$DEVICE_ID\"}")
echo "$VERIFY_RES" | jq .
ACCESS_TOKEN=$(echo "$VERIFY_RES" | jq -r .access_token)
REFRESH_TOKEN=$(echo "$VERIFY_RES" | jq -r .refresh_token)
if [[ "$ACCESS_TOKEN" == "null" || -z "$ACCESS_TOKEN" ]]; then
  echo "Failed to obtain access token" >&2
  exit 1
fi

echo "4) segments list"
curl -s "$BASE/segments/list" | jq .

echo "5) ride upload"
RIDE=$(curl -s -X POST "$BASE/rides/upload" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d '{"tss":65.5,"kcals":820,"duration_sec":3600,"started_at":"2025-10-29T12:00:00Z"}')
echo "$RIDE" | jq .
RIDE_ID=$(echo "$RIDE" | jq -r .ride_id)
if [[ "$RIDE_ID" == "null" || -z "$RIDE_ID" ]]; then
  echo "Failed to obtain ride_id" >&2
  exit 1
fi

echo "6) proofs verify"
PROOF=$(curl -s -X POST "$BASE/proofs/verify" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"ride_id\":\"$RIDE_ID\",\"signature\":\"stub-proof\"}")
echo "$PROOF" | jq .
PROOF_ID=$(echo "$PROOF" | jq -r .proof_id)
EFFORT=$(echo "$PROOF" | jq -r .effort_score)
if [[ "$PROOF_ID" == "null" || -z "$PROOF_ID" ]]; then
  echo "Failed to obtain proof_id" >&2
  exit 1
fi

echo "7) mint issue (stub)"
MINT=$(curl -s -X POST "$BASE/mint/issue" \
  -H "Authorization: Bearer $ACCESS_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"proof_id\":\"$PROOF_ID\",\"amount\":$EFFORT}")
echo "$MINT" | jq .

if [[ "$REFRESH_TOKEN" != "null" && -n "$REFRESH_TOKEN" ]]; then
  echo "8) auth refresh"
  REFRESH_RES=$(curl -s -X POST "$BASE/auth/refresh" -H 'Content-Type: application/json' \
    -d "{\"refresh_token\":\"$REFRESH_TOKEN\",\"device_id\":\"$DEVICE_ID\"}")
  echo "$REFRESH_RES" | jq .
fi
