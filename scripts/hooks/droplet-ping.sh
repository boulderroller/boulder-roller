#!/bin/bash
# droplet-ping.sh - Quick health check for staging droplet
# Usage: Called by Claude Code on conversation start

DROPLET_IP="${DROPLET_IP:?Set DROPLET_IP}"
HEALTH_ENDPOINT="http://$DROPLET_IP:8080/health"
TIMEOUT=5

echo "=== Droplet Status ==="

# Quick TCP check first (faster than HTTP)
if ! nc -z -w2 "$DROPLET_IP" 22 2>/dev/null; then
    echo "DROPLET DOWN - SSH unreachable at $DROPLET_IP"
    echo "===================="
    exit 1
fi

# Check API health endpoint
HEALTH=$(curl -s --max-time $TIMEOUT "$HEALTH_ENDPOINT" 2>/dev/null)
if [ $? -eq 0 ] && [ -n "$HEALTH" ]; then
    echo "API: UP"
    # Parse health response if JSON
    if echo "$HEALTH" | grep -q "status"; then
        echo "Response: $HEALTH"
    fi
else
    echo "API: DOWN or not responding"
    echo "SSH is reachable, but API health check failed"
    echo "Try: ssh root@$DROPLET_IP 'docker ps -a'"
fi

# Quick docker status
CONTAINERS=$(ssh -o ConnectTimeout=3 -o BatchMode=yes root@$DROPLET_IP "docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null | head -3" 2>/dev/null)
if [ -n "$CONTAINERS" ]; then
    echo ""
    echo "Containers:"
    echo "$CONTAINERS"
fi

echo "===================="
