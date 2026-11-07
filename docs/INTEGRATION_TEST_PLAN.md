# Integration Test Plan - Session 3

**Date:** 2024-11-28
**Status:** Ready for Execution
**Goal:** Validate end-to-end functionality of deployed MVP

---

## Test Environment

### Backend API
- **URL:** http://STAGING_LB_IP:8080
- **Health Check:** http://STAGING_LB_IP/health/db
- **Status:** ✅ Deployed and responding

### Solana Programs (Devnet)
- **boulder_rollers:** EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH
- **dung_mint:** A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ *(archived)*
- **proof_verifier:** Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC *(archived)*
- **CAL Mint:** 4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh
- **DUNG Mint:** CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk

### Database
- **Type:** Supabase PostgreSQL
- **Schema:** v1 (5 tables: user_state, claims, swanny_seats, epochs, leaderboard_entries)

### iOS App
- **Project:** ios/BoulderRollers.xcodeproj
- **API Configured:** http://STAGING_LB_IP:8080
- **Build Status:** ✅ Compiles successfully

---

## Test Suite 1: Backend API (curl/Postman)

### Test 1.1: Health Check ✅ BASELINE
**Priority:** P0 - Must pass before other tests

**Steps:**
```bash
curl -v http://STAGING_LB_IP/health/db
```

**Expected Result:**
```json
{
  "status": "healthy"
}
```
- HTTP 200 OK
- Response time < 500ms

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 1.2: Nonce Generation
**Priority:** P0 - Required for authentication

**Steps:**
```bash
curl -X POST http://STAGING_LB_IP:8080/auth/nonce \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "tU573Uwg8WSB1Sopwb1h2UCFXQAchiqZ6aCtmtK1JkR"}'
```

**Expected Result:**
```json
{
  "nonce": "random-string-here"
}
```
- HTTP 200 OK
- Nonce is non-empty string
- Nonce is different each time

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 1.3: Signature Verification
**Priority:** P0 - Required for authentication

**Prerequisites:**
- Have a test Solana wallet keypair
- Get nonce from Test 1.2
- Sign nonce with wallet

**Steps:**
```bash
# Get nonce
NONCE=$(curl -s -X POST http://STAGING_LB_IP:8080/auth/nonce \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "YOUR_WALLET_ADDRESS"}' | jq -r '.nonce')

# Sign nonce (use solana CLI or script)
# SIGNATURE=$(echo -n "$NONCE" | solana-keygen sign --keypair wallet.json)

# Verify signature
curl -X POST http://STAGING_LB_IP:8080/auth/verify \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_address": "YOUR_WALLET_ADDRESS",
    "signature": "BASE64_SIGNATURE",
    "nonce": "'"$NONCE"'"
  }'
```

**Expected Result:**
```json
{
  "access_token": "jwt-token-here",
  "refresh_token": "jwt-token-here",
  "user": {
    "id": "uuid",
    "wallet_address": "YOUR_WALLET_ADDRESS",
    "created_at": "timestamp"
  }
}
```
- HTTP 200 OK
- Tokens are non-empty strings
- User object contains correct wallet address

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 1.4: Protected Endpoint (GET /auth/me)
**Priority:** P0 - Validates JWT authentication

**Prerequisites:**
- Valid JWT access_token from Test 1.3

**Steps:**
```bash
curl -X GET http://STAGING_LB_IP:8080/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Expected Result:**
```json
{
  "id": "uuid",
  "wallet_address": "YOUR_WALLET_ADDRESS",
  "created_at": "timestamp"
}
```
- HTTP 200 OK
- User data matches authenticated wallet

**Test with invalid token:**
```bash
curl -X GET http://STAGING_LB_IP:8080/auth/me \
  -H "Authorization: Bearer invalid-token"
```
- HTTP 401 Unauthorized

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 1.5: CAL Balance Check
**Priority:** P1 - Validates CAL system

**Prerequisites:**
- Valid JWT access_token

**Steps:**
```bash
curl -X GET http://STAGING_LB_IP:8080/cal/balance \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Expected Result:**
```json
{
  "cal_balance": 0,
  "can_mint_today": true,
  "last_mint": null
}
```
- HTTP 200 OK
- Balance is 0 for new user
- can_mint_today is true

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 1.6: CAL Minting
**Priority:** P0 - Core functionality

**Prerequisites:**
- Valid JWT access_token
- can_mint_today: true

**Steps:**
```bash
curl -X POST http://STAGING_LB_IP:8080/cal/mint \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Expected Result:**
```json
{
  "cal_balance": 2500,
  "transaction_signature": "solana-tx-signature",
  "last_mint": "2024-11-28T..."
}
```
- HTTP 200 OK
- Balance increased by 2500
- Transaction signature is non-empty
- Verify transaction on Solana explorer: https://explorer.solana.com/tx/{signature}?cluster=devnet

**Test daily limit:**
```bash
# Try minting again immediately
curl -X POST http://STAGING_LB_IP:8080/cal/mint \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```
- HTTP 400 Bad Request (already minted today)

**Status:** [ ] Pass [ ] Fail
**Transaction Signature:**
**Notes:**

---

### Test 1.7: Segments Nearby
**Priority:** P1 - Geographic search

**Steps:**
```bash
# Boston coordinates
curl -X GET "http://STAGING_LB_IP:8080/segments/nearby?lat=42.3601&lon=-71.0589&radius_km=10"
```

**Expected Result:**
```json
{
  "segments": []
}
```
- HTTP 200 OK
- Returns empty array (no segments created yet)

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 1.8: Staking Claims
**Priority:** P1 - Staking system

**Prerequisites:**
- Valid JWT access_token

**Steps:**
```bash
curl -X GET http://STAGING_LB_IP:8080/staking/claims \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Expected Result:**
```json
{
  "claims": []
}
```
- HTTP 200 OK
- Returns empty array for new user

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

## Test Suite 2: iOS App (Manual Testing)

### Test 2.1: App Launch
**Priority:** P0 - Baseline

**Steps:**
1. Open `ios/BoulderRollers.xcodeproj` in Xcode
2. Select iPhone 15 simulator
3. Build and Run (Cmd+R)

**Expected Result:**
- App builds without errors
- App launches successfully
- Shows onboarding or sign-in screen

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 2.2: Wallet Creation
**Priority:** P0 - Core functionality

**Steps:**
1. Tap "Create Wallet"
2. App generates new Solana keypair
3. Show seed phrase (12/24 words)
4. Confirm seed phrase

**Expected Result:**
- Wallet created successfully
- Public key displayed
- Seed phrase stored securely in Keychain

**Status:** [ ] Pass [ ] Fail
**Wallet Address:**
**Notes:**

---

### Test 2.3: Sign In Flow
**Priority:** P0 - Authentication

**Steps:**
1. Tap "Sign In"
2. App requests nonce from backend
3. App signs nonce with wallet
4. App sends signature to backend
5. App receives JWT tokens

**Expected Result:**
- Nonce request succeeds
- Signature generated
- JWT tokens received
- User logged in (shows main interface)

**Debug Output to Check:**
- Network request to POST /auth/nonce
- Network request to POST /auth/verify
- Token stored in Keychain

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 2.4: CAL Balance Display
**Priority:** P1 - UI integration

**Prerequisites:**
- User logged in

**Steps:**
1. Navigate to Profile tab
2. Check CAL balance display

**Expected Result:**
- Balance shows 0 (or 2500 if previously minted)
- "Mint CAL" button visible

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 2.5: CAL Minting (iOS)
**Priority:** P0 - End-to-end flow

**Prerequisites:**
- User logged in
- Can mint today (24 hours since last mint)

**Steps:**
1. Tap "Mint CAL" button
2. App sends POST /cal/mint request
3. Backend calls Solana program
4. App displays transaction status

**Expected Result:**
- Loading indicator appears
- Success message displayed
- Balance updates to 2500
- Transaction signature shown

**Verify on Solana Explorer:**
- Open https://explorer.solana.com/?cluster=devnet
- Search for transaction signature
- Verify program logs show mint_daily_cal instruction

**Status:** [ ] Pass [ ] Fail
**Transaction Signature:**
**Notes:**

---

### Test 2.6: Map View
**Priority:** P2 - Map functionality

**Steps:**
1. Navigate to Map tab
2. Grant location permissions
3. Map loads

**Expected Result:**
- Map displays (Mapbox or placeholder)
- User location shown (if permissions granted)
- No segments visible (none created yet)

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 2.7: Location Permissions
**Priority:** P2 - iOS permissions

**Steps:**
1. Fresh install of app
2. Navigate to Map tab
3. System prompts for location permission
4. Tap "Allow While Using App"

**Expected Result:**
- Permission prompt appears with correct text:
  "Boulder Rollers needs your location to show nearby segments and record rides."
- After granting, user location appears on map

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

## Test Suite 3: End-to-End Flows

### Test 3.1: Complete User Journey
**Priority:** P0 - MVP validation

**Steps:**
1. ✅ Launch iOS app
2. ✅ Create new wallet
3. ✅ Sign in
4. ✅ Check CAL balance (0)
5. ✅ Mint 2500 CAL
6. ✅ Verify transaction on devnet
7. ✅ Check balance (2500)
8. ✅ Try minting again (should fail - already minted)
9. ✅ Navigate to Map tab
10. ✅ Navigate to Profile tab

**Expected Result:**
- All steps complete successfully
- No errors or crashes
- Data persists across app restarts

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 3.2: Token Refresh Flow
**Priority:** P1 - Session management

**Steps:**
1. Sign in
2. Wait 15 minutes (access token expiration)
3. Make API request (should auto-refresh)

**Expected Result:**
- App automatically refreshes access token
- Request succeeds
- No user intervention required

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 3.3: Logout and Re-login
**Priority:** P1 - Session management

**Steps:**
1. Sign in
2. Logout
3. Sign in again

**Expected Result:**
- Logout clears tokens from Keychain
- Re-login works successfully
- Previous CAL balance persists

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

## Test Suite 4: Negative Tests

### Test 4.1: Invalid Signature
**Priority:** P1 - Security

**Steps:**
```bash
curl -X POST http://STAGING_LB_IP:8080/auth/verify \
  -H "Content-Type: application/json" \
  -d '{
    "wallet_address": "tU573Uwg8WSB1Sopwb1h2UCFXQAchiqZ6aCtmtK1JkR",
    "signature": "invalid-signature",
    "nonce": "valid-nonce"
  }'
```

**Expected Result:**
- HTTP 401 Unauthorized
- Error message: "Invalid signature"

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 4.2: Expired Nonce
**Priority:** P1 - Security

**Steps:**
1. Get nonce
2. Wait 6 minutes (TTL is 5 minutes)
3. Try to verify with expired nonce

**Expected Result:**
- HTTP 401 Unauthorized
- Error message: "Nonce expired"

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 4.3: Unauthorized Access
**Priority:** P0 - Security

**Steps:**
```bash
curl -X POST http://STAGING_LB_IP:8080/cal/mint
```

**Expected Result:**
- HTTP 401 Unauthorized
- Error message: "Not authenticated"

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

### Test 4.4: Duplicate Minting
**Priority:** P0 - Business logic

**Steps:**
1. Mint CAL successfully
2. Try to mint again immediately

**Expected Result:**
- HTTP 400 Bad Request
- Error message: "Already minted today" or similar

**Status:** [ ] Pass [ ] Fail
**Notes:**

---

## Bug Tracking

### Bug Report Template

**Bug ID:** BUG-001
**Severity:** Critical / High / Medium / Low
**Test:** Test X.Y
**Description:** 
**Steps to Reproduce:**
1. 
2. 
3. 
**Expected Result:**
**Actual Result:**
**Screenshots/Logs:**
**Environment:** iOS Simulator / Device, Backend version
**Status:** Open / In Progress / Fixed / Won't Fix

---

## Bugs Found

### BUG-001: [Title]
**Severity:** 
**Test:** 
**Description:** 
**Status:** 

---

## Test Execution Log

**Tester:** 
**Date:** 2024-11-28
**Environment:** iOS Simulator 17.5, Backend @ STAGING_LB_IP

| Test ID | Status | Duration | Notes |
|---------|--------|----------|-------|
| 1.1 | [ ] | | |
| 1.2 | [ ] | | |
| 1.3 | [ ] | | |
| 1.4 | [ ] | | |
| 1.5 | [ ] | | |
| 1.6 | [ ] | | |
| 1.7 | [ ] | | |
| 1.8 | [ ] | | |
| 2.1 | [ ] | | |
| 2.2 | [ ] | | |
| 2.3 | [ ] | | |
| 2.4 | [ ] | | |
| 2.5 | [ ] | | |
| 2.6 | [ ] | | |
| 2.7 | [ ] | | |
| 3.1 | [ ] | | |
| 3.2 | [ ] | | |
| 3.3 | [ ] | | |
| 4.1 | [ ] | | |
| 4.2 | [ ] | | |
| 4.3 | [ ] | | |
| 4.4 | [ ] | | |

**Total:** 0/24 tests passed

---

## Sign-Off

- [ ] All P0 tests passing
- [ ] All P1 tests passing or documented bugs filed
- [ ] No critical bugs remain
- [ ] MVP functionality validated

**Approved By:**
**Date:**

---

## Next Steps After Testing

1. Document all bugs in GitHub Issues
2. Prioritize bug fixes for Session 3
3. Update SESSION_3_TASKS.md with bug fixes
4. Begin CI/CD pipeline testing
5. Plan production deployment
