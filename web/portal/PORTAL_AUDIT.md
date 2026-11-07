# Boulder Roller Portal - Placeholder & Stub Audit
Generated: 2025-12-21

## Summary
- **23 files** contain mock data references
- **11 TODO comments** need attention
- **Only 1 page** (MyActivities.tsx) uses the real API
- **16 other pages** rely entirely on mock data

---

## Pages Status

### Using Real API
| Page | Status | Notes |
|------|--------|-------|
| MyActivities.tsx | Partial | Uses `api.getRides()`, falls back to mock |

### Using Mock Data Only
| Page | Mock Data Type | Backend Endpoint Needed |
|------|---------------|------------------------|
| Achievements.tsx | `mockAchievements[]` | `/achievements` |
| BeetleStore.tsx | Mock items | `/store/items` |
| Data.tsx | Mock analytics | `/analytics/*` |
| FindFriends.tsx | Mock users | `/social/search` |
| ItemDetail.tsx | Mock item data | `/store/items/:id` |
| Leaderboard.tsx | `mockLeaderboard[]` | `/leaderboard` |
| MySegments.tsx | Mock segments | `/segments/mine` |
| Portfolio.tsx | Mock holdings | `/portfolio` (exists but not wired) |
| Profile.tsx | Mock user data | `/auth/me` + `/users/:id` |
| RiderView.tsx | Mock rider data | `/users/:id` |
| RideView.tsx | `mockActivities{}` | `/rides/:id` (exists but not wired) |
| SegmentView.tsx | Mock segment data | `/segments/:id` |
| Settings.tsx | Mock stats | `/auth/me` |

---

## Components with Mock Data

### Feed Components
| Component | Mock Data | Status |
|-----------|-----------|--------|
| ActivityFeed.tsx | `generateMockActivity()` | Tries API first, falls back |
| ActivityFeedItem.tsx | Uses MockMap | Placeholder map |
| MockMap.tsx | Static SVG | Needs Mapbox integration |

### Layout Components
| Component | Mock Data | Status |
|-----------|-----------|--------|
| ProfileDropdown.tsx | Mock user profile | Wire to `/auth/me` |
| TopNav.tsx | Mock user data, notifications | Wire to API |

### Modal Components
| Component | Mock Data | Status |
|-----------|-----------|--------|
| RideUploadSuccessModal.tsx | Mock save logic | Wire to ride update API |
| SearchModal.tsx | `mockResults[]` | Wire to `/search` endpoint |
| SettingsModal.tsx | Mock stats | Wire to user stats API |

### Ride Components
| Component | Mock Data | Status |
|-----------|-----------|--------|
| PowerCurvePlaceholder.tsx | Static bars | Needs real chart data |

---

## TODO Comments Requiring Action

```
SetupModal.tsx:54      - Save user profile to backend
TopNav.tsx:41          - Implement export
TopNav.tsx:47          - Save to backend
TopNav.tsx:55          - Delete account
TopNav.tsx:74          - Open notifications dropdown
ShareModal.tsx:50      - Generate and download image
ActivityFeed.tsx:353-6 - Wire following/followers/activities/streak from API
ErrorBoundary.tsx:30   - Send to error tracking service
```

---

## API Endpoints (api.ts)

### Implemented & Working
| Method | Endpoint | Used By |
|--------|----------|---------|
| `getNonce()` | POST /auth/nonce | WalletConnect |
| `verifySignature()` | POST /auth/verify | WalletConnect |
| `getRides()` | GET /rides | MyActivities |
| `uploadRide()` | POST /rides/upload | UploadActivityModal |
| `getGlobalFeed()` | GET /social/feed | ActivityFeed |

### Implemented but NOT Wired to UI
| Method | Endpoint | Should Wire To |
|--------|----------|----------------|
| `getMe()` | GET /auth/me | Profile, TopNav, Settings |
| `getRide()` | GET /rides/:id | RideView |
| `getSegments()` | GET /segments | MySegments, Map |
| `getLeaderboard()` | GET /leaderboard/:id | Leaderboard |
| `getCALBalance()` | GET /cal/balance | Header, Portfolio |
| `getPortfolio()` | GET /portfolio | Portfolio |
| `getFitnessMetrics()` | GET /analytics/fitness | Data page |
| `getTrainingLoad()` | GET /analytics/training-load | Data page |
| `updateProfile()` | PUT /users/me | Settings, SetupModal |
| `followUser()` | POST /social/follow | RiderView, FindFriends |
| `unfollowUser()` | DELETE /social/follow | RiderView |

### Backend Broken (500 errors)
| Method | Endpoint | Error |
|--------|----------|-------|
| `getSuggestedRiders()` | GET /social/suggested | Missing `users.ftp` column |

---

## Non-Functional Buttons/Features

### TopNav
- Notifications bell (onClick is TODO)
- Export data
- Delete account

### RideView
- EDIT button (no handler)
- DELETE button (console.log only, no API call)
- DOWNLOAD .FIT button (placeholder)
- EXPORT .GPX button (placeholder)
- TRANSMIT TELEMETRY button (placeholder)

### Profile/Settings
- Most settings don't persist
- Theme changes work (localStorage)

### Social
- Follow/unfollow buttons exist but not wired
- Share functionality incomplete

---

## Priority Fixes for Alpha

### High Priority (Core Functionality)
1. Wire RideView to `api.getRide()` instead of mock
2. Wire Profile/Settings to `api.getMe()`
3. Fix backend `/social/suggested` (add ftp column)
4. Wire Leaderboard to `api.getLeaderboard()`

### Medium Priority (Polish)
5. Wire Portfolio to `api.getPortfolio()` and `api.getCALBalance()`
6. Wire Data page to `api.getFitnessMetrics()`
7. Add real map component (replace MockMap)
8. Wire notifications

### Low Priority (Can Wait)
9. BeetleStore - needs backend endpoints
10. Achievements - needs backend endpoints
11. Export/Download functionality
12. Social features (follow, share)

---

## Files to Clean Up

These files can eventually be removed once real APIs are wired:
- `src/components/feed/MockMap.tsx`
- Mock data generators in ActivityFeed.tsx
- Mock arrays in page files

---

## Backend Endpoints Missing

These don't exist yet and need to be created:
- `/achievements` - User achievements
- `/store/items` - Beetle store items
- `/search` - Global search
- `/notifications` - User notifications
