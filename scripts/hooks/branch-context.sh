#!/bin/bash
# branch-context.sh - Show git context at conversation start
# Usage: Called by Claude Code on conversation start

set -e

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo '.')"

echo "=== Branch Context ==="

# Current branch
BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")
echo "Branch: $BRANCH"

# Uncommitted changes
DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
if [ "$DIRTY" -gt 0 ]; then
    echo "Uncommitted: $DIRTY files"
    git status --porcelain | head -5
    [ "$DIRTY" -gt 5 ] && echo "  ... and $((DIRTY - 5)) more"
else
    echo "Working tree: clean"
fi

# Last 3 commits
echo ""
echo "Recent commits:"
git log --oneline -3 2>/dev/null || echo "  (no commits)"

# Ahead/behind
UPSTREAM=$(git rev-parse --abbrev-ref @{u} 2>/dev/null || echo "")
if [ -n "$UPSTREAM" ]; then
    AHEAD=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo "0")
    BEHIND=$(git rev-list --count HEAD..@{u} 2>/dev/null || echo "0")
    [ "$AHEAD" -gt 0 ] && echo "Ahead of $UPSTREAM: $AHEAD commits"
    [ "$BEHIND" -gt 0 ] && echo "Behind $UPSTREAM: $BEHIND commits"
fi

echo "===================="
