#!/bin/bash
# pytest-runner.sh - Run relevant pytest tests after Python edits
# Usage: Called by Claude Code after editing .py files in backend/

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
BACKEND_DIR="$REPO_ROOT/backend"
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"

# Check if the edited file is in the backend directory
EDITED_FILE="${1:-}"

if [ -n "$EDITED_FILE" ]; then
    if [[ ! "$EDITED_FILE" =~ backend/ ]]; then
        # Not a backend file, skip
        exit 0
    fi
fi

echo "=== Pytest Runner ==="

cd "$BACKEND_DIR"

# Check for venv
if [ ! -f "$VENV_PYTHON" ]; then
    echo "WARNING: venv not found at $VENV_PYTHON"
    echo "Create with: python -m venv $BACKEND_DIR/venv && pip install -r requirements.txt"
    exit 1
fi

# Determine which tests to run based on edited file
TEST_TARGET="tests/"
if [ -n "$EDITED_FILE" ]; then
    # Extract the module name from the file path
    MODULE=$(echo "$EDITED_FILE" | sed 's|backend/app/||' | sed 's|\.py$||' | tr '/' '.')

    # Look for corresponding test file
    if [[ "$EDITED_FILE" =~ services/ ]]; then
        TEST_TARGET="tests/test_services.py"
    elif [[ "$EDITED_FILE" =~ routes/ ]]; then
        TEST_TARGET="tests/test_routes.py"
    elif [[ "$EDITED_FILE" =~ repositories ]]; then
        TEST_TARGET="tests/test_repositories.py"
    fi
fi

echo "Running: pytest $TEST_TARGET"
echo ""

# Run pytest with useful options
$VENV_PYTHON -m pytest "$TEST_TARGET" \
    --tb=short \
    -q \
    --no-header \
    2>&1 | tail -20

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "Tests: PASSED"
else
    echo ""
    echo "Tests: FAILED (exit code $EXIT_CODE)"
    echo "Run full output with: cd backend && venv/bin/python -m pytest $TEST_TARGET -v"
fi

echo "===================="
exit $EXIT_CODE
