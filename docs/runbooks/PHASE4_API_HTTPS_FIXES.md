# Phase 4: Critical Fixes - API URLs, Auth, & Hydration

## Worker Prompt

```
You are a full-stack engineer fixing critical connectivity and auth issues for Boulder Rollers.

## Context
- Backend server is RUNNING at STAGING_IP:8080
- Both iOS and Web have WRONG hardcoded fallback URL (STAGING_LB_IP)
- This causes 503 errors and "Failed to fetch"
- Additionally: schema mismatches, hydration issues

## Tasks (Execute in Order)

### TASK 1: Fix iOS API URL (CRITICAL)
**File:** `ios/BoulderRollers/Services/APIClient.swift`
**Line 21:** Change fallback URL
```swift
// FROM:
baseURL = ProcessInfo.processInfo.environment["BR_API_URL"] ?? "http://STAGING_LB_IP"
// TO:
baseURL = ProcessInfo.processInfo.environment["BR_API_URL"] ?? "http://STAGING_IP:8080"
```

### TASK 2: Fix iOS NonceResponse Schema (HIGH)
**File:** `ios/BoulderRollers/Services/APIClient.swift`
Find `NonceResponse` struct and update to match backend response:
```swift
struct NonceResponse: Codable {
    let nonce: String
    let issuedAt: Date?
    let expiresAt: Date?

    enum CodingKeys: String, CodingKey {
        case nonce
        case issuedAt = "issued_at"
        case expiresAt = "expires_at"
    }
}
```

### TASK 3: Fix Web API URL (CRITICAL)
**File:** `web/portal/src/lib/api.ts`
**Line 72:** Change fallback URL
```typescript
// FROM:
private baseURL = process.env.NEXT_PUBLIC_API_URL || 'http://STAGING_LB_IP';
// TO:
private baseURL = process.env.NEXT_PUBLIC_API_URL || 'http://STAGING_IP:8080';
```

### TASK 4: Fix Hydration Issues (MEDIUM)

**File:** `web/portal/src/components/ui/use-mobile.ts`
```typescript
// Line 6 - Initialize with consistent value for SSR
const [isMobile, setIsMobile] = React.useState<boolean>(false);
```

**File:** `web/portal/src/lib/device.ts`
```typescript
export function getDeviceId(): string {
  if (typeof window === 'undefined') {
    return '';  // Empty string instead of 'server' for SSR consistency
  }
  // ... rest unchanged
}
```

### TASK 5: Add iOS Request Timeout (MEDIUM)
**File:** `ios/BoulderRollers/Services/APIClient.swift`
Add to each URLRequest creation (around lines 423, 435, 450, 465):
```swift
request.timeoutInterval = 30
```

### TASK 6: Verify Builds
```bash
# iOS
cd /Users/gabetemp/curahee/BoulderRollers-v2/ios
xcodebuild -scheme BoulderRollers -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build

# Web
cd /Users/gabetemp/curahee/BoulderRollers-v2/web/portal
npm run build
```

### TASK 7: Commit & Push
```bash
cd /Users/gabetemp/curahee/BoulderRollers-v2
git add -A
git commit -m "fix: Update API URLs and fix auth/hydration issues

- Fix iOS/Web API URL (STAGING_LB_IP → STAGING_IP:8080)
- Fix iOS NonceResponse schema to match backend
- Fix React hydration mismatches
- Add iOS request timeout (30s)

🤖 Generated with Claude Code"
git push
```

## Success Criteria
1. iOS app connects to correct server (no 503)
2. Web portal builds without errors
3. iOS builds without errors
4. Auth flow works (nonce → sign → verify)
```

---

## Issues Summary

| # | Severity | Component | Issue |
|---|----------|-----------|-------|
| 1 | CRITICAL | iOS/Web | Wrong API URL (old server STAGING_LB_IP) |
| 2 | HIGH | iOS | NonceResponse schema mismatch |
| 3 | MEDIUM | Web | React hydration mismatches |
| 4 | MEDIUM | iOS | No request timeout |

---

## File Paths

| File | Changes |
|------|---------|
| `ios/BoulderRollers/Services/APIClient.swift` | URL + NonceResponse + timeout |
| `web/portal/src/lib/api.ts` | URL |
| `web/portal/src/components/ui/use-mobile.ts` | Hydration fix |
| `web/portal/src/lib/device.ts` | Hydration fix |

---

## Future: HTTPS via Cloudflare

After immediate fixes, set up proper HTTPS:

1. **Add domain to Cloudflare** (boulderrollers.com)
2. **Create A record:** `api` → `STAGING_IP` (Proxied)
3. **SSL Mode:** Full
4. **Update code:** Use `https://api.boulderrollers.com`
5. **Clean up:** Remove all hardcoded IPs

See separate runbook: `PHASE5_CLOUDFLARE_HTTPS.md`
