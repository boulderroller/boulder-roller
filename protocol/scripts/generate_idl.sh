#!/usr/bin/env bash
set -euo pipefail

# Regenerates the Anchor workspace artifacts that this repo keeps checked in:
# - anchor/idl/boulder_rollers.json
# - anchor/clients/typescript/boulder_rollers.ts
# - ../backend/idl/boulder_rollers.json
# - ../web/portal/public/idl/boulder_rollers.json
#
# Requires the Anchor CLI to be installed and configured.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
ANCHOR_DIR="$ROOT_DIR/anchor"
REPO_ROOT="$(cd "$ROOT_DIR/.." && pwd)"

cd "$ANCHOR_DIR"
anchor build --program-name boulder_rollers

cp target/idl/boulder_rollers.json idl/boulder_rollers.json
cp target/types/boulder_rollers.ts clients/typescript/boulder_rollers.ts
cp target/idl/boulder_rollers.json "$REPO_ROOT/backend/idl/boulder_rollers.json"
cp target/idl/boulder_rollers.json "$REPO_ROOT/web/portal/public/idl/boulder_rollers.json"

python3 "$ROOT_DIR/scripts/check_program_version.py"

echo "Synced the canonical IDL, generated TypeScript client, backend IDL, and portal IDL from Anchor build output."
