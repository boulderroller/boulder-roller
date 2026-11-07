# Worker 3: iOS App Engineer - START HERE

## Your Role
You are the iOS App Engineer for Boulder Rollers V2.

## Your Mission
Complete the SwiftUI iOS app with backend integration and prepare for TestFlight beta.

---

## MVP SCOPE - What to Focus On

Focus on these core features:
- ✅ Wallet creation/import (already working!)
- ✅ Authentication with backend
- ✅ Map view with segments
- ✅ CAL balance display and minting
- ✅ Staking UI (view stakes, stake/unstake)
- ✅ Profile view with user stats
- ✅ Ride upload (simple file upload)

You do NOT need to implement:
- ❌ Swanny Seats UI
- ❌ Leaderboards and epochs
- ❌ Live GPS ride recording (just file upload for MVP)
- ❌ Advanced segment matching

---

## Quick Start - Your First 3 Tasks

### Task 1: Read Your Documentation (10 minutes)
1. Read `/docs/WORKER_3_IOS_APP.md` - Your detailed task breakdown
2. Read `/docs/INTEGRATION_REGISTRY.md` - Coordination document (UPDATE THIS as you work)
3. Read the API contract in integration registry - this is what backend provides

### Task 2: Create Xcode Project & Add Dependencies (30 minutes)
```bash
cd /Users/gabetemp/curahee/BoulderRollers-v2/ios

# Open Xcode and create project
# File → New → Project
# iOS → App
# Product Name: BoulderRollers
# Organization: [your org]
# Interface: SwiftUI
# Language: Swift
# Save to: /Users/gabetemp/curahee/BoulderRollers-v2/ios/

# Add existing Swift files to project:
# Drag these folders into Xcode navigator:
# - Services/
# - Views/
# - ViewModels/
# - Utilities/

# Add Swift Package Dependencies:
# File → Add Package Dependencies → Enter URLs:
1. https://github.com/portto/solana-web3.swift (Solana.swift)
2. https://github.com/onevcat/Kingfisher (image loading)
3. https://github.com/mapbox/mapbox-maps-ios (Mapbox - optional)

# Build project (Cmd+B)
# Fix any import/compilation errors
```

### Task 3: Update APIClient for Backend Auth Flow (1 hour)
The backend uses a nonce-challenge flow, not the simple wallet auth flow iOS currently has.

Update `/ios/BoulderRollers/Services/APIClient.swift`:

```swift
// Current flow iOS has:
// POST /api/v1/auth/wallet with signature

// Backend's actual flow:
// 1. POST /auth/nonce with wallet address
// 2. Sign the nonce with wallet
// 3. POST /auth/verify with wallet address, signature, and nonce

func authenticate(wallet: Account) async throws -> AuthResponse {
    // Step 1: Get nonce
    let nonceRequest = ["wallet_address": wallet.publicKey.base58EncodedString]
    let nonceResponse = try await post("/auth/nonce", body: nonceRequest)
    let nonce = nonceResponse["nonce"] as! String

    // Step 2: Sign nonce
    let messageData = Data(nonce.utf8)
    let signature = try wallet.sign(message: messageData)

    // Step 3: Verify and get JWT
    let verifyRequest = [
        "wallet_address": wallet.publicKey.base58EncodedString,
        "signature": signature.base64EncodedString(),
        "nonce": nonce
    ]
    let authResponse = try await post("/auth/verify", body: verifyRequest)

    // Extract tokens
    let accessToken = authResponse["access_token"] as! String
    let refreshToken = authResponse["refresh_token"] as! String

    // Store tokens in keychain
    try KeychainHelper.save(accessToken, key: "access_token")
    try KeychainHelper.save(refreshToken, key: "refresh_token")

    return AuthResponse(accessToken: accessToken, user: ...)
}
```

---

## Your Complete Task List

### Phase 1: Project Setup & Auth (Days 1-2)

**Priority 1 - Project Setup**:
1. Create Xcode project (BoulderRollers.xcodeproj)
2. Add Swift Package dependencies (Solana.swift, Kingfisher, Mapbox)
3. Add existing Swift files to project
4. Fix compilation errors
5. Verify app builds successfully

**Priority 2 - Backend Integration**:
6. Update APIClient baseURL to Worker 4's dev server URL (check integration registry)
7. Implement nonce-challenge auth flow (replace simple wallet auth)
8. Test authentication end-to-end with live backend
9. Handle JWT token storage and refresh

**Priority 3 - Info.plist Configuration**:
10. Add Mapbox token (if using maps): `MBXAccessToken`
11. Add location permission: `NSLocationWhenInUseUsageDescription`
12. Add network security for local testing: `NSAllowsLocalNetworking`

### Phase 2: Feature Implementation (Days 3-4)

**Priority 4 - CAL System**:
13. Update ProfileView to show real CAL balance from `GET /cal/balance`
14. Add "Mint Daily CAL" button that calls `POST /cal/mint`
15. Show success/error messages for minting
16. Handle "already minted today" gracefully

**Priority 5 - Staking UI**:
17. Update MapView segment cards to show staking info
18. Add "Stake" button/modal with amount input
19. Call `POST /staking/stake` with segment_id and amount
20. Show user's claims from `GET /staking/claims`
21. Add "Unstake" functionality with `POST /staking/unstake`

**Priority 6 - Segments & Map**:
22. Update segment fetching to use `GET /segments/nearby?lat={}&lon={}&radius_km={}`
23. Display segments on map (use Mapbox or placeholder)
24. Show segment details (name, distance, elevation)
25. Handle segment card tap to show details

### Phase 3: Polish & Testing (Day 5)

26. Test all flows on simulator
27. Test on physical device
28. Polish UI/UX (loading states, error handling)
29. Add placeholder states (empty lists, no data)
30. Prepare TestFlight build (when ready)

---

## Success Criteria

By end of your work, you should have:
- [ ] Xcode project builds successfully
- [ ] All Swift package dependencies added
- [ ] App runs on iOS simulator without crashes
- [ ] Authentication works with live backend
- [ ] CAL balance displays correctly
- [ ] CAL minting works end-to-end
- [ ] Staking UI complete (view, stake, unstake)
- [ ] Segments load and display on map
- [ ] Profile view shows user stats
- [ ] App tested on physical device
- [ ] Integration registry updated with status

---

## Coordination with Other Workers

### You DEPEND on:
- **Worker 2 (Backend)**: Need live API URL to test against (check integration registry)
- **Worker 4 (DevOps)**: Need dev server URL (same as Worker 2's API URL)

### Your Integration Registry Updates:
Update `/docs/INTEGRATION_REGISTRY.md`:

```markdown
## iOS App (Worker 3)

### Configuration
- **Dev API URL**: `http://[IP]:8080` ← FROM INTEGRATION REGISTRY
- **Mapbox Token**: `pk.ey...` (optional) ← YOUR UPDATE IF USING

### Current Status
- Xcode project created: ✅ ← YOUR UPDATE
- Dependencies added: ✅ ← YOUR UPDATE
- Auth flow updated: ✅ ← YOUR UPDATE
- App builds: ✅ ← YOUR UPDATE
```

Commit with: `git commit -m "chore(integration): Worker 3 - iOS app functional"`

---

## API Endpoints You'll Use

All endpoints documented in `/docs/INTEGRATION_REGISTRY.md` under "Backend API Contract"

### Authentication (YOU MUST IMPLEMENT THIS)
```
POST /auth/nonce
→ { "wallet_address": "..." }
← { "nonce": "..." }

POST /auth/verify
→ { "wallet_address": "...", "signature": "...", "nonce": "..." }
← { "access_token": "...", "refresh_token": "...", "user": {...} }

GET /auth/me (with JWT)
← { "id": "...", "wallet_address": "...", ... }
```

### CAL System
```
GET /cal/balance (with JWT)
← { "cal_balance": 2500, "can_mint_today": false, ... }

POST /cal/mint (with JWT)
← { "cal_balance": 2500, "transaction_signature": "...", ... }
```

### Staking
```
POST /staking/stake (with JWT)
→ { "segment_id": 1, "amount": 1000000000 }
← { "claim_id": "...", "lp_tokens": 1000000000, ... }

GET /staking/claims (with JWT)
← { "claims": [{ "segment_id": 1, "amount": 1000000000, ... }] }

POST /staking/unstake (with JWT)
→ { "segment_id": 1, "lp_amount": 1000000000 }
← { "dung_returned": 1000000000, ... }
```

### Segments
```
GET /segments/nearby?lat={lat}&lon={lon}&radius_km={r}
← { "segments": [{ "id": 1, "name": "...", ... }] }
```

---

## Key Implementation Notes

### Handling JWT Tokens
```swift
// Already implemented in KeychainHelper
try KeychainHelper.save(token, key: "access_token")
let token = try KeychainHelper.load(key: "access_token")

// APIClient should add Authorization header
private func headers() -> [String: String] {
    var headers = ["Content-Type": "application/json"]
    if let token = try? KeychainHelper.load(key: "access_token") {
        headers["Authorization"] = "Bearer \(token)"
    }
    return headers
}
```

### Error Handling
```swift
do {
    let balance = try await apiClient.getCALBalance()
    self.calBalance = balance.cal_balance
} catch APIError.unauthorized {
    // Token expired, refresh or re-authenticate
} catch APIError.serverError(let message) {
    // Show error to user
    self.errorMessage = message
} catch {
    // Network error
    self.errorMessage = "Network error. Please try again."
}
```

### Loading States
```swift
@Published var isLoading = false
@Published var errorMessage: String?

func fetchBalance() async {
    isLoading = true
    defer { isLoading = false }

    do {
        let balance = try await apiClient.getCALBalance()
        self.calBalance = balance.cal_balance
        self.errorMessage = nil
    } catch {
        self.errorMessage = error.localizedDescription
    }
}
```

---

## Testing Checklist

### On Simulator
- [ ] App launches without crashes
- [ ] Onboarding flow works
- [ ] Wallet creation creates new keypair
- [ ] Wallet import validates seed phrase
- [ ] Authentication succeeds with backend
- [ ] Profile loads user data
- [ ] Map displays (or shows placeholder)
- [ ] Segments load and display
- [ ] CAL balance updates
- [ ] Staking modal opens and submits

### On Physical Device
- [ ] All simulator tests pass
- [ ] Location permission request appears
- [ ] Network requests succeed (not blocked by localhost)
- [ ] App doesn't crash on real GPS data
- [ ] Performance acceptable

---

## Configuration Files

### Info.plist Required Keys
```xml
<!-- Location -->
<key>NSLocationWhenInUseUsageDescription</key>
<string>We need your location to show nearby cycling segments</string>

<!-- Mapbox (optional) -->
<key>MBXAccessToken</key>
<string>pk.eyJ1...</string>

<!-- Local networking (for dev) -->
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
</dict>
```

### Update Base URL
```swift
// Services/APIClient.swift
init() {
    #if DEBUG
    // Get from integration registry:
    baseURL = "http://[WORKER_4_IP]:8080"
    #else
    baseURL = "https://api.boulderrollers.com"
    #endif
}
```

---

## Need Help?

### Documentation Resources:
- SwiftUI: https://developer.apple.com/documentation/swiftui
- Solana.Swift: https://github.com/portto/solana-web3.swift
- Mapbox iOS: https://docs.mapbox.com/ios/maps/guides/
- URLSession: https://developer.apple.com/documentation/foundation/urlsession

### Debug Issues:
- Check Xcode console for errors
- Use breakpoints in async functions
- Test API calls with `curl` first
- Verify backend is accessible from device
- Check Info.plist permissions

---

## Communication Protocol

**Daily Update** - Post to integration registry:
```
Worker 3 Status:
✅ Completed: [list]
⏳ In Progress: [current task]
❌ Blocked By: [waiting for Worker 2 API URL]
```

**When app is functional** - Alert in integration registry:
```
🚨 WORKER 3: iOS app builds and runs! Auth + CAL + Staking working.
```

---

**Ready? Start with Task 1: Read your documentation. Good luck! 🚀**
