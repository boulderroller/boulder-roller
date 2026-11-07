#!/bin/bash
# h3-resolution-guard.sh - CRITICAL: Prevent H3 resolution changes
# Usage: Pre-commit hook for any code touching H3 resolution
#
# All tiles in the database use H3 resolution 10 (~66m hexagons).
# Changing resolution would make all existing tiles incompatible.
# This would corrupt wallet_tile_history, activity_tile_samples, etc.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
EXPECTED_RESOLUTION="10"

echo "=== H3 Resolution Guard ==="

# Get staged file contents
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

if [ -z "$STAGED_FILES" ]; then
    echo "No staged files. OK."
    exit 0
fi

# Tracker comments cannot change tile data, and their JSONL rows are deliberately
# prose-dense. Excluding them prevents unrelated review text from matching a
# resolution expression elsewhere on the same line. The guard itself is also
# excluded so its detection patterns can be maintained without self-matching.
# Only added lines can introduce a new resolution value.
RESOLUTION_CHANGES=$(
    git diff --cached -U0 -- . \
        ':(exclude).beads/**' \
        ':(exclude)scripts/hooks/h3-resolution-guard.sh' 2>/dev/null \
        | grep '^+' \
        | grep -v '^+++' \
        | grep -E "(h3_resolution|H3_RESOLUTION|resolution.*=.*[0-9]+|h3\.(geo_to_h3|latlng_to_cell).*[0-9]+|h3o.*Resolution)" \
        || true
)

if [ -z "$RESOLUTION_CHANGES" ]; then
    echo "No H3 resolution changes detected. OK."
    exit 0
fi

echo "Detected potential H3 resolution changes:"
echo "$RESOLUTION_CHANGES"
echo ""

# Parse the numeric resolution attached to the H3 expression and reject every
# value except the canonical 10. A bounded disallow-list silently admitted
# values outside its range (for example 7 and 16).
BAD_VALUES=$(
    while IFS= read -r line; do
        VALUE=$(echo "$line" | sed -nE \
            's/.*(H3_RESOLUTION|h3_resolution|resolution)[^=]*=[[:space:]]*([0-9]+).*/\2/p')
        if [ -z "$VALUE" ]; then
            VALUE=$(echo "$line" | sed -nE \
                's/.*(H3_RESOLUTION|h3_resolution)[^0-9]*([0-9]+).*/\2/p')
        fi
        if [ -z "$VALUE" ]; then
            VALUE=$(echo "$line" | sed -nE \
                's/.*h3\.(geo_to_h3|latlng_to_cell).*[,][[:space:]]*([0-9]+)[[:space:]]*\).*/\2/p')
        fi
        if [ -z "$VALUE" ]; then
            VALUE=$(echo "$line" | sed -nE \
                's/.*h3o.*Resolution[^0-9]*([0-9]+).*/\1/p')
        fi
        if [ -n "$VALUE" ] && [ "$VALUE" != "$EXPECTED_RESOLUTION" ]; then
            echo "$line"
        fi
    done <<EOF
$RESOLUTION_CHANGES
EOF
)

if [ -n "$BAD_VALUES" ]; then
    echo ""
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo "!!! H3 RESOLUTION CHANGE DETECTED - THIS WILL CORRUPT DATA !!!"
    echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo ""
    echo "All existing data uses H3 resolution $EXPECTED_RESOLUTION."
    echo "Changing resolution will make existing tiles incompatible!"
    echo ""
    echo "Affected tables:"
    echo "  - activity_tile_samples"
    echo "  - wallet_tile_history"
    echo "  - Any tile-based caches"
    echo ""
    echo "If you're certain this is correct, use:"
    echo "  git commit --no-verify -m 'BREAKING: H3 resolution change'"
    echo ""
    echo "You will need to:"
    echo "  1. Migrate all tile data to new resolution"
    echo "  2. Update all tile generation code"
    echo "  3. Re-process all historical rides"
    echo ""
    exit 1
fi

echo "Resolution appears to be $EXPECTED_RESOLUTION. OK."
echo "===================="
