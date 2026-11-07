#!/bin/bash
# Ultra-minimal watch mode - runs quick.py every 5 seconds
# Perfect for a small terminal pane

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Colors
GOLD='\033[0;33m'
NC='\033[0m'

clear
echo -e "${GOLD}"
cat << 'EOF'
 ____             _     _
| __ )  ___  _   _| | __| | ___ _ __
|  _ \ / _ \| | | | |/ _` |/ _ \ '__|
| |_) | (_) | |_| | | (_| |  __/ |
|____/ \___/ \__,_|_|\__,_|\___|_|   WATCH MODE
EOF
echo -e "${NC}"

# Check if remote flag passed
REMOTE_FLAG=""
if [[ "$1" == "--remote" ]] || [[ "$1" == "-r" ]]; then
    REMOTE_FLAG="--remote"
    echo "Monitoring: REMOTE"
else
    echo "Monitoring: LOCAL"
fi

echo "Press Ctrl+C to stop"
echo ""

# Main loop
while true; do
    # Clear previous output (but keep header)
    tput cup 10 0

    # Run quick check
    python3 "$SCRIPT_DIR/quick.py" $REMOTE_FLAG 2>/dev/null || {
        echo "Error running quick.py"
    }

    # Wait
    sleep 5
done
