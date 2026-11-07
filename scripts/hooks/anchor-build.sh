#!/bin/bash
# anchor-build.sh - Auto-build Anchor programs after Rust edits
# Usage: Called by Claude Code after editing .rs files in protocol/anchor/

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
ANCHOR_DIR="$REPO_ROOT/protocol/anchor"

# Check if the edited file is in the Anchor directory
# $1 is the file that was edited (passed by hook)
EDITED_FILE="${1:-}"

if [ -n "$EDITED_FILE" ]; then
    if [[ ! "$EDITED_FILE" =~ protocol/anchor ]]; then
        # Not an Anchor file, skip
        exit 0
    fi
fi

echo "=== Anchor Build ==="

cd "$ANCHOR_DIR"

# Check if anchor is installed
if ! command -v anchor &> /dev/null; then
    echo "WARNING: anchor CLI not found. Install with: cargo install --git https://github.com/coral-xyz/anchor anchor-cli"
    exit 1
fi

# Run anchor build
echo "Building Anchor programs..."
if anchor build 2>&1; then
    echo "Build: SUCCESS"

    # Show program IDs
    echo ""
    echo "Program IDs:"
    grep -r "declare_id!" programs/*/src/lib.rs 2>/dev/null | sed 's/.*declare_id!("\([^"]*\)").*/  \1/'
else
    echo "Build: FAILED"
    echo "Check errors above and fix before committing"
    exit 1
fi

echo "===================="
