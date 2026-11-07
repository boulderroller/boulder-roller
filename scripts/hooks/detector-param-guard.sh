#!/bin/bash
# detector-param-guard.sh - Prevent detector parameter drift from docs
#
# When climb detector code changes, DETECTOR_PARAMS.md must also be updated.
# This prevents the recurring problem where agents read stale parameter values
# from docs and reason with wrong mental models.
#
# Runs as a pre-commit hook (both git native and Claude Code).

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
PARAMS_DOC="docs/DETECTOR_PARAMS.md"

echo "=== Detector Parameter Drift Guard ==="

# Get staged files
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

if [ -z "$STAGED_FILES" ]; then
    echo "No staged files. OK."
    exit 0
fi

# Files that contain detector parameters
DETECTOR_FILES=(
    "backend/app/services/patterns/climb.py"
    "backend/app/services/pattern_engine.py"
)

DETECTOR_CHANGED=false
for DET_FILE in "${DETECTOR_FILES[@]}"; do
    if echo "$STAGED_FILES" | grep -q "$DET_FILE"; then
        DETECTOR_CHANGED=true
        echo "Detector file staged: $DET_FILE"
    fi
done

if [ "$DETECTOR_CHANGED" = false ]; then
    echo "No detector files staged. OK."
    exit 0
fi

# Check if DETECTOR_PARAMS.md is also staged
if echo "$STAGED_FILES" | grep -q "$PARAMS_DOC"; then
    echo "DETECTOR_PARAMS.md also staged. OK."
    echo "===================="
    exit 0
fi

# Detector code changed but params doc didn't — warn but don't block
# (Not all detector changes affect documented parameters)
echo ""
echo "⚠  DETECTOR CODE CHANGED — check if docs need updating"
echo ""
echo "You modified climb detector code but did NOT update:"
echo "  $PARAMS_DOC"
echo ""
echo "If you changed any tunable constants, thresholds, heuristic"
echo "behavior, or scoring logic, update DETECTOR_PARAMS.md too."
echo ""
echo "This file is the single source of truth that agents read."
echo "Stale docs = agents reasoning with wrong parameters."
echo ""
echo "If your change doesn't affect documented parameters, proceed."
echo "===================="

# Exit 0 (warning, not blocking) — this is a nudge, not a gate.
# Blocking would be too aggressive since many detector edits are
# comments, formatting, or bug fixes that don't change parameters.
exit 0
