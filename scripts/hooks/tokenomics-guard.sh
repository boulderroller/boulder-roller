#!/bin/bash
# tokenomics-guard.sh - Prevent tokenomics constant drift from docs
#
# When program constants change (distribution splits, supply caps, fees, etc.),
# FRESHEST_SPEC.md and CLAUDE.md should also be updated. These constants are
# duplicated across 25+ files — agents and developers read docs first.
#
# Runs as a pre-commit hook (both git native and Claude Code).

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "=== Tokenomics Constants Guard ==="

STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

if [ -z "$STAGED_FILES" ]; then
    echo "No staged files. OK."
    exit 0
fi

# Source of truth for tokenomics constants: every module of the program.
PROGRAM_SRC="protocol/anchor/programs/boulder_rollers/src/"

if ! echo "$STAGED_FILES" | grep -q "^$PROGRAM_SRC"; then
    echo "No tokenomics source changes. OK."
    exit 0
fi

echo "Detected changes to $PROGRAM_SRC"

# Check which key docs are also staged
DOCS_UPDATED=true
MISSING_DOCS=""

for DOC in "docs/FRESHEST_SPEC.md" "CLAUDE.md"; do
    if ! echo "$STAGED_FILES" | grep -q "$DOC"; then
        DOCS_UPDATED=false
        MISSING_DOCS="$MISSING_DOCS\n    $DOC"
    fi
done

if [ "$DOCS_UPDATED" = true ]; then
    echo "Key docs also staged. OK."
    echo "===================="
    exit 0
fi

# Check if the actual constant values changed (not just comments/formatting)
RAW_CHANGES=$(git diff --cached -U0 -- "$REPO_ROOT/$PROGRAM_SRC" 2>/dev/null | grep -vE "^(\+\+\+|---)" | grep -E "^[+-].*(pub const|leaderboard_share_bps|staker_share_bps|local_legend_share_bps|pol_share_bps|protocol_fee_bps|MINIMUM_STAKE|VAULT_CREATION|CAL_MIN_STAKE|MAX_SUPPLY|COMMUNITY_CAP|TREASURY_CAP|TEAM_CAP|INVESTOR_CAP|POL_CAP|EPOCH_DURATION|HARVEST_FEE|EXIT_FEE|LOCAL_LEGEND_TERM|LEADERBOARD_RANK|STAKER_UNLOCK|BEETLE_)" || true)
# A line removed from one module and added unchanged to another is a move.
ADDED=$(printf '%s\n' "$RAW_CHANGES" | sed -n 's/^+[[:space:]]*//p' | sort)
REMOVED=$(printf '%s\n' "$RAW_CHANGES" | sed -n 's/^-[[:space:]]*//p' | sort)
CONST_CHANGES=$({
    comm -23 <(printf '%s\n' "$REMOVED") <(printf '%s\n' "$ADDED") | sed 's/^/-/'
    comm -13 <(printf '%s\n' "$REMOVED") <(printf '%s\n' "$ADDED") | sed 's/^/+/'
} | grep -vE '^[+-]$' || true)

if [ -z "$CONST_CHANGES" ]; then
    echo "No tokenomics constants changed (comments/formatting only). OK."
    echo "===================="
    exit 0
fi

echo ""
echo "⚠  TOKENOMICS CONSTANTS CHANGED — check if docs need updating"
echo ""
echo "Changed constants detected in the program source:"
echo "$CONST_CHANGES" | head -20
echo ""
echo "These docs were NOT updated:$MISSING_DOCS"
echo ""
echo "Tokenomics values are duplicated across 25+ files. Key docs to update:"
echo "    docs/FRESHEST_SPEC.md         — internal authority"
echo "    CLAUDE.md                     — agent context"
echo "    backend/app/solana_direct.py  — Python-side distribution config"
echo ""
echo "===================="

# Warning only — not blocking
exit 0
