#!/bin/bash
#
# Smoke tests for Boulder Rollers API
# Tests all major endpoints on staging or local environment
#
# Usage:
#   ./scripts/smoke.sh              # Test staging (default)
#   ./scripts/smoke.sh local        # Test local dev server
#   ./scripts/smoke.sh <base_url>   # Test custom URL
#

set -e

# Configuration
if [ "$1" = "local" ]; then
    BASE_URL="http://localhost:8000"
elif [ -n "$1" ]; then
    BASE_URL="$1"
else
    BASE_URL="http://${DROPLET_IP:?Set DROPLET_IP}:8080"
fi

echo "=== Boulder Rollers API Smoke Tests ==="
echo "Base URL: $BASE_URL"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    echo "  Response: $2"
    FAILED=1
}

warn() {
    echo -e "${YELLOW}⚠ WARN${NC}: $1"
}

FAILED=0

# -----------------------------------------------------------------------------
# 1) Health Check
# -----------------------------------------------------------------------------
echo "--- Health Check ---"
HEALTH=$(curl -s "$BASE_URL/health/db" || echo "CONNECTION_FAILED")
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    pass "Health endpoint"
else
    fail "Health endpoint" "$HEALTH"
    echo "Cannot continue without healthy API"
    exit 1
fi

# -----------------------------------------------------------------------------
# 2) Auth Nonce
# -----------------------------------------------------------------------------
echo ""
echo "--- Auth Flow ---"
DEVICE_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
WALLET="TestWallet$(date +%s)"

NONCE_RESP=$(curl -s "$BASE_URL/auth/nonce" \
    -H "Content-Type: application/json" \
    -d "{\"wallet\":\"$WALLET\",\"device_id\":\"$DEVICE_ID\"}" || echo "CONNECTION_FAILED")

if echo "$NONCE_RESP" | grep -q '"nonce"'; then
    pass "Auth nonce"
    NONCE=$(echo "$NONCE_RESP" | grep -o '"nonce":"[^"]*"' | cut -d'"' -f4)
else
    fail "Auth nonce" "$NONCE_RESP"
fi

# -----------------------------------------------------------------------------
# 3) Auth Verify (mock signature for smoke test)
# -----------------------------------------------------------------------------
if [ -n "$NONCE" ]; then
    VERIFY_RESP=$(curl -s "$BASE_URL/auth/verify" \
        -H "Content-Type: application/json" \
        -d "{\"wallet\":\"$WALLET\",\"signature\":\"smoke_test_sig_$NONCE\",\"nonce\":\"$NONCE\",\"device_id\":\"$DEVICE_ID\"}" || echo "CONNECTION_FAILED")

    if echo "$VERIFY_RESP" | grep -q '"access_token"'; then
        pass "Auth verify"
        TOKEN=$(echo "$VERIFY_RESP" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
    else
        fail "Auth verify" "$VERIFY_RESP"
    fi
fi

# -----------------------------------------------------------------------------
# 4) Auth Me (requires valid token)
# -----------------------------------------------------------------------------
if [ -n "$TOKEN" ]; then
    ME_RESP=$(curl -s "$BASE_URL/auth/me" \
        -H "Authorization: Bearer $TOKEN" || echo "CONNECTION_FAILED")

    if echo "$ME_RESP" | grep -q '"wallet"'; then
        pass "Auth me"
    else
        fail "Auth me" "$ME_RESP"
    fi
else
    warn "Skipping auth/me - no token"
fi

# -----------------------------------------------------------------------------
# 5) Rides List
# -----------------------------------------------------------------------------
echo ""
echo "--- Rides ---"
if [ -n "$TOKEN" ]; then
    RIDES_RESP=$(curl -sL "$BASE_URL/rides" \
        -H "Authorization: Bearer $TOKEN" || echo "CONNECTION_FAILED")

    # Empty array [] is valid for new user
    if echo "$RIDES_RESP" | grep -qE '^\['; then
        pass "Rides list"
    else
        fail "Rides list" "$RIDES_RESP"
    fi
else
    warn "Skipping rides - no token"
fi

# -----------------------------------------------------------------------------
# 6) Beetles My-Cards
# -----------------------------------------------------------------------------
echo ""
echo "--- Beetles ---"
if [ -n "$TOKEN" ]; then
    BEETLES_RESP=$(curl -sL "$BASE_URL/beetles/my-cards" \
        -H "Authorization: Bearer $TOKEN" || echo "CONNECTION_FAILED")

    # Empty array [] is valid for new user
    if echo "$BEETLES_RESP" | grep -qE '^\['; then
        pass "Beetles my-cards"
    else
        fail "Beetles my-cards" "$BEETLES_RESP"
    fi
else
    warn "Skipping beetles - no token"
fi

# -----------------------------------------------------------------------------
# 7) Vaults List
# -----------------------------------------------------------------------------
echo ""
echo "--- Vaults ---"
if [ -n "$TOKEN" ]; then
    VAULTS_RESP=$(curl -sL "$BASE_URL/vaults" \
        -H "Authorization: Bearer $TOKEN" || echo "CONNECTION_FAILED")

    # Response is {"vaults": [...], "total": N} or bare array
    if echo "$VAULTS_RESP" | grep -qE '"vaults"|^\['; then
        VAULT_COUNT=$(echo "$VAULTS_RESP" | grep -o '"id"' | wc -l | tr -d ' ')
        pass "Vaults list ($VAULT_COUNT vaults)"
    else
        fail "Vaults list" "$VAULTS_RESP"
    fi
else
    warn "Skipping vaults - no token"
fi

# -----------------------------------------------------------------------------
# 8) Segments List (legacy)
# -----------------------------------------------------------------------------
echo ""
echo "--- Segments ---"
if [ -n "$TOKEN" ]; then
    SEGMENTS_RESP=$(curl -sL "$BASE_URL/segments/list" \
        -H "Authorization: Bearer $TOKEN" || echo "CONNECTION_FAILED")

    # Response is {"segments": [...]}
    if echo "$SEGMENTS_RESP" | grep -qE '"segments"'; then
        SEG_COUNT=$(echo "$SEGMENTS_RESP" | grep -o '"id"' | wc -l | tr -d ' ')
        pass "Segments list ($SEG_COUNT segments)"
    else
        fail "Segments list" "$SEGMENTS_RESP"
    fi
else
    warn "Skipping segments - no token"
fi

# -----------------------------------------------------------------------------
# 9) Analytics Fitness
# -----------------------------------------------------------------------------
echo ""
echo "--- Analytics ---"
if [ -n "$TOKEN" ]; then
    ANALYTICS_RESP=$(curl -sL "$BASE_URL/analytics/fitness" \
        -H "Authorization: Bearer $TOKEN" || echo "CONNECTION_FAILED")

    if echo "$ANALYTICS_RESP" | grep -q '"form"'; then
        pass "Analytics fitness"
    else
        fail "Analytics fitness" "$ANALYTICS_RESP"
    fi
else
    warn "Skipping analytics - no token"
fi

# -----------------------------------------------------------------------------
# 10) Points Balance (if available)
# -----------------------------------------------------------------------------
echo ""
echo "--- Points ---"
if [ -n "$TOKEN" ]; then
    POINTS_RESP=$(curl -sL "$BASE_URL/points/balance" \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo "CONNECTION_FAILED")

    if echo "$POINTS_RESP" | grep -qE '"total_points"|"points"'; then
        pass "Points balance"
    elif echo "$POINTS_RESP" | grep -q "404\|Not Found"; then
        warn "Points endpoint not available (404)"
    else
        fail "Points balance" "$POINTS_RESP"
    fi
else
    warn "Skipping points - no token"
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "=== Summary ==="
if [ "$FAILED" = "0" ]; then
    echo -e "${GREEN}All smoke tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed${NC}"
    exit 1
fi
