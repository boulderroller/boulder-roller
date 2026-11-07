#!/bin/bash
# env-var-audit.sh - Find undocumented environment variables
#
# Compares os.getenv/os.environ usage in backend code against the
# Environment Variables section in CLAUDE.md. Reports any env vars
# used in code but not documented.
#
# Usage: bash scripts/hooks/env-var-audit.sh
#
# Not a pre-commit hook — run periodically or when debugging
# "why isn't staging working?" issues.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "=== Environment Variable Audit ==="
echo ""

# Extract env vars from Python code (excluding venv)
CODE_VARS=$(grep -rhoE "(os\.getenv|os\.environ\.get|os\.environ\[)\s*\(?\s*['\"]([A-Z_][A-Z0-9_]*)['\"]" \
    "$REPO_ROOT/backend/" \
    --include="*.py" \
    --exclude-dir="venv" --exclude-dir="__pycache__" --exclude-dir=".venv" \
    2>/dev/null \
    | grep -oE "[A-Z_][A-Z0-9_]{2,}" \
    | sort -u)

# Also check config.py for settings. pattern
CONFIG_VARS=$(grep -oE 'settings\.\s*[a-z_]+' "$REPO_ROOT/backend/app/config.py" 2>/dev/null \
    | sed 's/settings\.//' | tr 'a-z' 'A-Z' | sort -u || true)

ALL_CODE_VARS=$(echo -e "$CODE_VARS\n$CONFIG_VARS" | sort -u | grep -v '^$')

# Extract documented vars from CLAUDE.md
CLAUDE_VARS=$(grep -oE '[A-Z_][A-Z0-9_]{2,}' "$REPO_ROOT/CLAUDE.md" | sort -u)

# Find undocumented vars
echo "Environment variables used in backend code but NOT in CLAUDE.md:"
echo "----------------------------------------------------------------"

UNDOCUMENTED=0
for VAR in $ALL_CODE_VARS; do
    # Skip common false positives
    case "$VAR" in
        PATH|HOME|USER|PYTHONPATH|VIRTUAL_ENV|LC_*|LANG|TERM|SHELL|PWD|OLDPWD) continue ;;
        GET|SET|KEY|URL|SECRET|TRUE|FALSE|NONE|NULL|DEFAULT) continue ;;
    esac

    if ! echo "$CLAUDE_VARS" | grep -qw "$VAR"; then
        # Find where it's used
        LOCATION=$(grep -rl "$VAR" "$REPO_ROOT/backend/" --include="*.py" --exclude-dir="venv" --exclude-dir="__pycache__" --exclude-dir=".venv" 2>/dev/null | head -1 | sed "s|$REPO_ROOT/||")
        echo "  $VAR  ($LOCATION)"
        UNDOCUMENTED=$((UNDOCUMENTED + 1))
    fi
done

echo ""
echo "----------------------------------------------------------------"
echo "Total: $UNDOCUMENTED undocumented env vars"
echo ""

if [ "$UNDOCUMENTED" -gt 0 ]; then
    echo "Consider adding these to CLAUDE.md under '## Environment Variables'"
    echo "so agents and developers know what to configure on new deployments."
fi

echo "===================="
