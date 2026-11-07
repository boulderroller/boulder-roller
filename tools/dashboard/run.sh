#!/bin/bash
# Quick runner for the BoulderRollers dashboard

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"

# Check if we're in a venv
if [[ -z "$VIRTUAL_ENV" ]]; then
    if [[ -f "$PROJECT_ROOT/backend/venv/bin/activate" ]]; then
        source "$PROJECT_ROOT/backend/venv/bin/activate"
    fi
fi

# Check dependencies
python3 -c "import textual" 2>/dev/null || {
    echo "Installing dependencies..."
    pip install -q textual httpx rich
}

# Run the dashboard
cd "$PROJECT_ROOT"
python -m tools.dashboard "$@"
