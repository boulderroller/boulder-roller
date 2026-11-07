# Boulder Rollers - Master Audit Coordination

## Quick Status

### Immediate Bugs (COMPLETED ✅)
| Bug | Status | Files Changed |
|-----|--------|---------------|
| Profile 404 | ✅ Fixed | `AppState.swift`, `BoulderRollersApp.swift` |
| Map Flashing | ✅ Fixed | `MapView.swift`, `LocationManager.swift` |
| Signin Skip | ✅ Fixed | `AppState.swift`, `BoulderRollersApp.swift` |

### Audit Summary
| Area | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| iOS | 0 | 4 | 5 | 2 | 11 |
| Backend | 6 | 4 | 3 | 0 | 13 |
| Web Portal | 3 | 7 | 4 | 0 | 14 |
| **Total** | **9** | **15** | **12** | **2** | **38** |

---

## Runbook Files Created

1. **`docs/runbooks/AUDIT_IOS_FIXES.md`** - 11 iOS issues with code solutions
2. **`docs/runbooks/AUDIT_BACKEND_FIXES.md`** - 13 backend issues with code solutions
3. **`docs/runbooks/AUDIT_WEB_FIXES.md`** - 14 web portal issues with code solutions

---

## Recommended Sub-Agent Allocation

### Agent 1: iOS Engineer
**Focus:** iOS app feature completion
**Runbook:** `docs/runbooks/AUDIT_IOS_FIXES.md`
**Priority Items:**
1. Implement GPX/FIT file parsing (`APIClient.swift:304-317`)
2. Hook STAKE DUNG button (`MapView.swift:249`)
3. Add error feedback UX (`EditProfileView`, `FitnessSettingsView`)

**Prompt Template:**
```
You are an iOS engineer working on Boulder Rollers. Your task is to fix the issues documented in docs/runbooks/AUDIT_IOS_FIXES.md.

Start by reading the runbook, then work through items by priority. The codebase is at /Users/gabetemp/curahee/BoulderRollers-v2/ios/BoulderRollers.

Key context:
- SwiftUI app targeting iOS 17+
- Uses Mapbox for maps
- Uses TweetNacl for Solana signing
- Backend API at http://STAGING_LB_IP (debug) or https://api.boulderrollers.com (prod)

After each fix, verify the build compiles with xcodebuild.
```

---

### Agent 2: Backend Engineer
**Focus:** Backend security and core functionality
**Runbook:** `docs/runbooks/AUDIT_BACKEND_FIXES.md`
**Priority Items:**
1. Add rate limiting to auth endpoints
2. Fix AUTH_SIGNATURE_BYPASS for production
3. Implement real effort score calculation
4. Add CAL rollback on failure

**Prompt Template:**
```
You are a backend engineer working on Boulder Rollers. Your task is to fix the issues documented in docs/runbooks/AUDIT_BACKEND_FIXES.md.

Start by reading the runbook, then work through items by priority. The codebase is at /Users/gabetemp/curahee/BoulderRollers-v2/backend.

Key context:
- Python FastAPI backend
- Supabase for database
- Solana RPC for blockchain operations
- Deployed at STAGING_IP

Test changes locally before deploying. The server can be accessed via:
ssh root@STAGING_IP
```

---

### Agent 3: Web Portal Engineer
**Focus:** Web portal feature implementation
**Runbook:** `docs/runbooks/AUDIT_WEB_FIXES.md`
**Priority Items:**
1. Implement CreatePileModal with map drawing
2. Fix uploadRide to actually upload
3. Replace all mock data with API calls
4. Add real Mapbox map integration

**Prompt Template:**
```
You are a frontend engineer working on Boulder Rollers web portal. Your task is to fix the issues documented in docs/runbooks/AUDIT_WEB_FIXES.md.

Start by reading the runbook, then work through items by priority. The codebase is at /Users/gabetemp/curahee/BoulderRollers-v2/web/portal.

Key context:
- React/TypeScript
- Uses Tailwind CSS
- Backend API at same endpoints as iOS
- Mapbox for maps

Many components currently use mock data - replace with real API calls.
```

---

## Cross-Cutting Concerns

### API Alignment
All three platforms need consistent API integration:
- iOS: `APIClient.swift`
- Web: `lib/api.ts`
- Backend: `routes/*.py`

**Ensure endpoints match:**
| Endpoint | iOS | Web | Backend |
|----------|-----|-----|---------|
| GET /users/me | ✅ | ✅ | ✅ |
| POST /rides/upload | ✅ | ❌ Need | ✅ |
| GET /piles/mine | ❌ | ❌ Need | ❌ Need |
| GET /feed | ❌ | ❌ Need | ❌ Need |
| POST /piles | ❌ | ❌ Need | ❌ Need |

### Missing Backend Endpoints
Before web portal can be fully functional, backend needs:
- `GET /piles/mine` - User's created piles
- `POST /piles` - Create new pile
- `GET /feed` - Activity feed
- `GET /users/:id/following` - Following list
- `GET /users/:id/followers` - Followers list
- `GET /stats/weekly` - Weekly ride stats
- `GET /achievements` - User achievements

---

## Deployment Checklist

After all fixes complete:

### Backend
```bash
ssh root@STAGING_IP
cd /root/boulder-repo/backend
git pull
pip install -r requirements.txt
docker restart boulder-api
docker logs boulder-api --tail 20
```

### iOS
1. Build in Xcode
2. Archive for TestFlight
3. Submit to App Store Connect

### Web Portal
```bash
cd /Users/gabetemp/curahee/BoulderRollers-v2/web/portal
npm run build
# Deploy to hosting (Vercel/Netlify/etc)
```

---

## Progress Tracking

Use this to track completion:

### iOS Fixes
- [ ] GPX/FIT file parsing
- [ ] STAKE DUNG button
- [ ] RIDE THIS SEGMENT button
- [ ] Error feedback in EditProfileView
- [ ] Error feedback in FitnessSettingsView
- [ ] FTP info button content
- [ ] BIP39 import (optional)
- [ ] Mapbox fallback improvement
- [ ] Remove debug prints
- [ ] Remove commented code

### Backend Fixes
- [ ] Restrict AUTH_SIGNATURE_BYPASS
- [ ] Rate limiting on auth
- [ ] Real effort score calculation
- [ ] DUNG mint status tracking
- [ ] Proof validation before mint
- [ ] CAL rollback on failure
- [ ] Remove silent Solana stubbing
- [ ] Fix device_id in AuthenticatedUser
- [ ] Apply all migrations
- [ ] LP token formula
- [ ] Remove mock signatures
- [ ] Session token hash

### Web Portal Fixes
- [ ] CreatePileModal implementation
- [ ] uploadRide function
- [ ] "Your Piles" filter
- [ ] FeedTab with real data
- [ ] MapView with Mapbox
- [ ] RideUploadModal file handling
- [ ] ProfileTab real rides
- [ ] GovernanceTab real proposals
- [ ] TradingTab real balances
- [ ] PortfolioTab yield calculation
- [ ] FollowingModal real users
- [ ] AchievementsTab real data
- [ ] StatsTab real data
- [ ] SwannyTab real data





