#!/bin/bash
# devnet-address-guard.sh - Detect stale devnet addresses after redeployment
#
# When addresses.devnet.json changes (program redeployment), the old addresses
# may still be hardcoded in 48+ files across the repo. This hook greps for
# the old addresses and reports files that need updating.
#
# Runs as a pre-commit hook (both git native and Claude Code).

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
ADDRESSES_FILE="protocol/anchor/addresses.devnet.json"

echo "=== Devnet Address Guard ==="

STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

if [ -z "$STAGED_FILES" ]; then
    echo "No staged files. OK."
    exit 0
fi

if ! echo "$STAGED_FILES" | grep -q "$ADDRESSES_FILE"; then
    echo "No address changes. OK."
    exit 0
fi

echo "Detected changes to $ADDRESSES_FILE"
echo ""

# Extract old addresses from the pre-change version
OLD_CONTENT=$(git show HEAD:"$ADDRESSES_FILE" 2>/dev/null || echo "")
if [ -z "$OLD_CONTENT" ]; then
    echo "New file (no previous version). OK."
    echo "===================="
    exit 0
fi

# Extract address values from old JSON (program ID, mint addresses)
OLD_ADDRESSES=$(echo "$OLD_CONTENT" | grep -oE '"[A-HJ-NP-Za-km-z1-9]{32,44}"' | tr -d '"' | sort -u)

if [ -z "$OLD_ADDRESSES" ]; then
    echo "Could not parse old addresses. OK."
    echo "===================="
    exit 0
fi

# Extract new addresses
NEW_CONTENT=$(git show :0:"$ADDRESSES_FILE" 2>/dev/null || cat "$REPO_ROOT/$ADDRESSES_FILE" 2>/dev/null || echo "")
NEW_ADDRESSES=$(echo "$NEW_CONTENT" | grep -oE '"[A-HJ-NP-Za-km-z1-9]{32,44}"' | tr -d '"' | sort -u)

# Find addresses that changed
CHANGED=""
for OLD_ADDR in $OLD_ADDRESSES; do
    if ! echo "$NEW_ADDRESSES" | grep -q "$OLD_ADDR"; then
        CHANGED="$CHANGED $OLD_ADDR"
    fi
done

if [ -z "$CHANGED" ]; then
    echo "No addresses actually changed (metadata only). OK."
    echo "===================="
    exit 0
fi

echo "⚠  DEVNET ADDRESSES CHANGED — checking for stale references"
echo ""

for ADDR in $CHANGED; do
    SHORT="${ADDR:0:8}...${ADDR: -4}"
    # Search for the old address in the repo (excluding the addresses file itself and .git)
    STALE_FILES=$(grep -rl "$ADDR" "$REPO_ROOT" \
        --include="*.ts" --include="*.tsx" --include="*.js" \
        --include="*.py" --include="*.rs" --include="*.toml" \
        --include="*.json" --include="*.md" --include="*.html" \
        --include="*.env*" --include="*.yml" --include="*.yaml" \
        2>/dev/null | grep -v ".git/" | grep -v "$ADDRESSES_FILE" | head -30 || true)

    if [ -n "$STALE_FILES" ]; then
        COUNT=$(echo "$STALE_FILES" | wc -l | tr -d ' ')
        echo "OLD ADDRESS $SHORT still found in $COUNT files:"
        echo "$STALE_FILES" | sed 's|^|    |' | head -15
        if [ "$COUNT" -gt 15 ]; then
            echo "    ... and $((COUNT - 15)) more"
        fi
        echo ""
    fi
done

echo "Update these files to use the new addresses from $ADDRESSES_FILE"
echo "Or have code load from the registry: protocol/anchor/addresses.devnet.json"
echo "===================="

# Warning only — not blocking
exit 0
