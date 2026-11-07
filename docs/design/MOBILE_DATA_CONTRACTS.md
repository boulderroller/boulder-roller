# Mobile App Data Contracts

> Research spec for React Native cycling recording app.
> Generated 2026-03-28 from actual backend route handlers.

---

## Table of Contents

1. [API Endpoints the Mobile App Touches](#part-1-api-endpoints)
2. [Post-Ride Response (The Critical Contract)](#part-2-post-ride-response)
3. [Minimum Viable Screen Set](#part-3-minimum-viable-screens)
4. [What NOT to Build in v1](#part-4-what-not-to-build)
5. [New Endpoints Needed](#part-5-new-endpoints-needed)
6. [Recommendation Summary](#recommendation)

---

## Part 1: API Endpoints

### Authentication

#### `POST /auth/privy/verify`
**Primary mobile auth path.** Privy handles social login (Google, Apple, Email) and creates embedded Solana wallets. The mobile app should use Privy SDK natively.

Request:
```json
{
  "wallet": "string (Solana pubkey)",
  "privy_token": "string (Privy access token)",
  "device_id": "UUID",
  "invite_code": "string (optional, for new signups)"
}
```

Response (`VerifyResponse`):
```json
{
  "user_id": "UUID",
  "wallet": "string",
  "access_token": "string (JWT)",
  "access_expires_at": "datetime",
  "refresh_token": "string (JWT)",
  "refresh_expires_at": "datetime"
}
```

Tokens are also set as HttpOnly cookies. **Mobile note:** React Native does not use cookies -- the mobile app must store `access_token` and `refresh_token` from the JSON body and pass them as `Authorization: Bearer <token>` headers.

**Mobile relevance:** Essential. This is the only auth endpoint the app needs.

#### `POST /auth/verify`
**Wallet-native auth** (Phantom, Solflare). SIWS flow: `POST /auth/nonce` then `POST /auth/verify` with signed message.

**Mobile relevance:** Only if supporting native wallet connect. Privy is simpler for v1.

#### `POST /auth/refresh`
Refresh tokens. Currently reads refresh from HttpOnly cookie.

**Mobile relevance:** Essential, but needs a code change -- the mobile app sends the refresh token in the request body or Authorization header, not a cookie. Currently the endpoint reads `request.cookies.get("refresh_token")` and will 401 if no cookie. **This is a blocker.**

#### `GET /auth/bootstrap`
Single-request startup state: auth status, profile, points config, onboarding state.

Response (`AuthBootstrapResponse`):
```json
{
  "authenticated": true,
  "invite_required": true,
  "invite_validated": false,
  "needs_profile_setup": false,
  "auth_method_hint": "privy",
  "user": { /* UserProfilePrivate - full profile */ },
  "points_config": null  // Points system removed April 2026. This field is deprecated/absent.
}
```

**Mobile relevance:** Essential. Call on app open to determine entry flow.

#### `POST /auth/invite/validate`
Validate invite code before sign-up.

Response:
```json
{ "valid": true, "message": "Invite code valid", "code_id": "uuid-or-null" }
```

**Mobile relevance:** Essential for gated alpha.

---

### User Profile

#### `GET /users/me`
Full private profile with aggregated stats.

Response (`UserProfilePrivate`):
```json
{
  "id": "UUID",
  "wallet": "string",
  "username": "string | null",
  "display_name": "string | null",
  "bio": "string | null",
  "avatar_url": "string | null",
  "email": "string | null",
  "weight_kg": 75.0,
  "ftp_w": 200,
  "preferred_units": "metric | imperial",
  "is_public": true,
  "created_at": "datetime",
  "theme_id": "hoo-breddin",
  "is_dark_mode": true,
  "rider_type": "climber",
  "location": "string | null",
  "total_rides": 42,
  "total_distance_km": 3200.5,
  "total_elevation_m": 85000,
  "total_tss": 12500.0,
  "total_kcals": 95000,
  "total_duration_sec": 432000,
  "total_dung_earned": 0,
  "cal_earned_today": 150.0,
  "dung_earned_today": 0.0
}
```

**Mobile relevance:** Essential. Powers the profile tab and post-ride header.

#### `PUT /users/me`
Update profile. Accepts partial updates.

Request (`UserProfileUpdate`):
```json
{
  "username": "string",
  "display_name": "string",
  "weight_kg": 75.0,
  "ftp_w": 250,
  "preferred_units": "metric",
  "rider_type": "climber",
  "location": "Philadelphia, PA"
}
```

**Mobile relevance:** v1 SKIP. Minimal profile editing on mobile. Use web portal.

#### `GET /users/{identifier}`
Public profile by wallet or @username.

**Mobile relevance:** Only needed for social features (viewing other riders). v1 SKIP.

---

### Rides

#### `GET /rides`
List current user's rides.

Response: array of `RideRecord`:
```json
[{
  "id": "UUID",
  "riderId": "UUID",
  "startedAt": "datetime",
  "completedAt": "datetime",
  "patterns": [/* raw pattern dicts */],
  "calories": 850.0,
  "status": "completed",
  "distanceM": 65000.0,
  "elevationM": 1200.0,
  "durationS": 7200,
  "tss": 180.0,
  "dungEarned": 0,
  "calEarned": 180,
  "title": "Morning Ride",
  "avgPowerW": 220.0,
  "normalizedPowerW": 245.0,
  "vaultCompletions": [{
    "vaultId": 42,
    "vaultName": "Manayunk Wall",
    "vaultSignature": "abc123...",
    "timeSeconds": 312
  }],
  "hasGps": true,
  "hasPatterns": true,
  "hasLeaderboards": true,
  "hasAchievements": true
}]
```

**Mobile relevance:** Essential. Powers ride history list and recent activity.

#### `GET /rides/{ride_id}`
Single ride detail. Same fields as list plus `is_owner` bool and vault completions enriched from indexed_vaults.

**Mobile relevance:** Essential. Post-ride detail screen.

#### `GET /rides/{ride_id}/status`
Polling endpoint for progressive ride processing status.

Response:
```json
{
  "ride_id": "UUID",
  "status": "metrics_ready | enriched | completed | failed",
  "error_message": null,
  "phase1_completed_at": "datetime",
  "phase2_completed_at": "datetime",
  "phase3_completed_at": "datetime",
  "phase1_duration_ms": 1200,
  "phase2_duration_ms": 45000,
  "phase3_duration_ms": 3000,
  "metrics": {
    "tss": 180.0,
    "kcals": 850.0,
    "distance_m": 65000.0,
    "elevation_gain_m": 1200.0,
    "duration_sec": 7200,
    "avg_power_w": 220.0,
    "normalized_power_w": 245.0
  },
  "has_gps": true,
  "has_patterns": true,
  "has_leaderboards": true,
  "cal_earned": 180,
  "has_achievements": true
}
```

**Mobile relevance:** Critical for the post-ride reveal. Poll this after upload to show progressive loading (metrics first, then climbs, then CAL earned).

#### `GET /rides/{ride_id}/patterns`
Detected patterns (climbs, steady, exploration) for a ride.

Response:
```json
{
  "ride_id": "UUID",
  "patterns": {
    "climb_patterns": [{
      "name": "Manayunk Wall",
      "vert_m": 85.0,
      "time_s": 312,
      "duration_s": 312,
      "vam": 980.8,
      "distanceM": 1200.0,
      "avgGradientPct": 7.1,
      "avgSpeedMps": 3.8,
      "signatureHex": "abc123...",
      "roadName": "Manayunk Wall",
      "persistenceM": 82.0,
      "significancePercentile": 0.95,
      "vaultMatch": { /* vault match info */ },
      "startOffsetS": 1800,
      "endOffsetS": 2112
    }],
    "steady_pattern": {
      "duration_s": 3600,
      "avg_power_w": 180,
      "intensity_index": 0.72
    },
    "exploration_pattern": {
      "new_tiles_wallet": 45,
      "total_tiles": 230
    }
  },
  "summary": "1200m climbed, 60min steady, 45 new areas explored",
  "total_count": 5
}
```

**Mobile relevance:** Essential. This is the "gold cascade" post-ride reveal data. Each climb is a card showing name, vert, time, gradient, and whether it matched a vault.

#### `GET /rides/{ride_id}/gps`
GPS track for map rendering.

Response:
```json
{
  "gps_points": [
    { "timestamp": "datetime", "latitude": 40.0, "longitude": -75.0, "elevation": 50.0, "distance": 0.0 }
  ]
}
```

**Mobile relevance:** Essential for post-ride map. Also used during recording (but native GPS, not this endpoint).

#### `POST /rides/upload`
Legacy inline upload (base64-encoded file body).

Request:
```json
{ "file_data_b64": "base64-string", "file_type": "fit" }
```

Response:
```json
{ "ride_id": "UUID", "status": "processing", "message": "Ride uploaded. Processing in background." }
```

**Mobile relevance:** Works but inefficient for large FIT files. Presigned upload is better.

#### `POST /rides/upload/init` + `POST /rides/upload/complete`
**Presigned upload flow** (preferred for mobile):

1. `POST /rides/upload/init` with `{ file_type, file_hash, file_size }` -- returns `{ uploadId, signedUrl, expiresIn }`
2. Client PUTs file bytes directly to `signedUrl` (Supabase Storage)
3. `POST /rides/upload/complete` with `{ upload_id }` -- triggers processing

**Mobile relevance:** This is the correct upload path for native recording. After recording, the app saves a FIT/GPX file locally, hashes it, inits the upload, PUTs to the signed URL, then completes.

#### `GET /rides/{ride_id}/streams`
Time-series data (power, heart_rate, cadence, speed) for chart rendering.

**Mobile relevance:** v1 SKIP. Charts are better on the web portal.

#### `GET /rides/{ride_id}/tiles`
H3 tile samples for a ride.

**Mobile relevance:** v1 SKIP. Territory visualization is web-only.

---

### ~~Points (Removed April 2026)~~

> **April 2026:** The points system has been fully removed. The following endpoints no longer exist:
> - `GET /points/balance` — deleted
> - `GET /points/events` — deleted
> - `GET /points/leaderboard` — deleted
>
> The mobile app should use `GET /cal/onchain` for CAL balance and `GET /portfolio` for aggregate balances.

---

### Portfolio / CAL Balance

#### `GET /portfolio`
Aggregate balance summary.

Response:
```json
{
  "dung_balance": 0.0,
  "cal_balance": 2500.0,
  "staked_positions": [/* vault stakes */],
  "pending_claims": [/* claims */],
  "total_claims": 0,
  "total_staked": 0.0,
  "weekly_yield": 0.0,
  "total_yield": 0.0,
  "claims": []
}
```

**Mobile relevance:** The `cal_balance` and `dung_balance` fields are useful for the home screen. The staking details are web-only.

#### `GET /cal/onchain`
CAL balance only.

Response:
```json
{ "calBalance": 2500.0, "canMintToday": false }
```

**Mobile relevance:** Use this or `GET /portfolio` for CAL balance.

---

### Vaults

#### `GET /vaults`
List vaults with pagination and filters.

Response:
```json
{
  "vaults": [{
    "id": 42,
    "signature_hex": "string",
    "name": "Manayunk Wall",
    "vert_m": 85.0,
    "distance_m": 1200,
    "avg_gradient_pct": 7.1,
    "total_completions": 156,
    "total_staked": 5000,
    "kom_holder": "wallet-address",
    "kom_time_s": 285,
    "minter": "wallet-address",
    "start_lat": 40.025,
    "start_lon": -75.221,
    "on_chain_active": true
  }],
  "total": 862,
  "offset": 0,
  "limit": 50
}
```

**Mobile relevance:** v1 SKIP for browsing. Vault data surfaces through post-ride pattern matching only.

#### `GET /vaults/{vault_id}`
Full vault detail with leaderboard.

**Mobile relevance:** Useful for post-ride "tap on matched vault" navigation. Could be a simple webview link to portal for v1.

#### `GET /vaults/{vault_id}/leaderboard`
Top 10 leaderboard for a vault.

Response:
```json
{
  "vault_id": 42,
  "vault_name": "Manayunk Wall",
  "leaderboard": [{
    "vault_signature": "string",
    "rank": 1,
    "wallet": "string",
    "best_time_seconds": 285,
    "avg_power_w": null,
    "completion_id": null,
    "achieved_at": null
  }],
  "kom_holder": "string",
  "kom_time_s": 285
}
```

**Mobile relevance:** Could show after a vault match in post-ride. "You're #7 on Manayunk Wall!" But can also defer to web.

#### `GET /vaults/my/completions`
User's vault completions across all vaults.

**Mobile relevance:** v1 SKIP.

#### `GET /vaults/my/stakes`
User's active stakes.

**Mobile relevance:** v1 SKIP. Staking is web-only.

---

### Feed

#### `GET /feed`
Activity feed from followed users.

Response:
```json
{
  "activities": [{
    "id": "UUID",
    "type": "ride",
    "title": "Morning Ride",
    "createdAt": "datetime",
    "user": {
      "id": "UUID",
      "username": "alpha-code-3",
      "display_name": "Gabe",
      "avatar_url": "url",
      "wallet": "3boUdo..."
    },
    "distance_m": 65000,
    "elevation_gain_m": 1200,
    "duration_sec": 7200,
    "dung_minted": 0
  }],
  "has_more": true
}
```

**Mobile relevance:** Essential for home/feed screen. This is what the rider sees on app open.

#### `GET /feed/global`
Public global feed. Same shape.

**Mobile relevance:** Fallback for new users with no follows.

---

### Notifications

#### `GET /notifications`
User notifications with unread count.

Response:
```json
{
  "notifications": [{
    "id": "UUID",
    "type": "kom_beaten",
    "title": "KOM Beaten!",
    "message": "Your KOM on Manayunk Wall was beaten by @rider",
    "data": {},
    "read": false,
    "created_at": "datetime"
  }],
  "unread_count": 3
}
```

**Mobile relevance:** Essential. Badge count on notification tab. Push notification registration is separate (see Part 5).

#### `POST /notifications/{id}/read` and `POST /notifications/read-all`
Mark read.

**Mobile relevance:** Essential.

---

### Social

#### `POST /social/follow/{user_id}` / `DELETE /social/follow/{user_id}`
Follow/unfollow.

**Mobile relevance:** v1 SKIP. Social is web-only initially.

---

### Territory

#### `GET /territory/tiles` / `GET /territory/stats` / `GET /territory/heatmap`
H3 tile exploration data.

**Mobile relevance:** v1 SKIP. Map exploration visualization is web-only.

---

### Segments

#### `GET /segments/popular`
Popular segments for discovery.

**Mobile relevance:** v1 SKIP. Vault/segment browsing is web-only.

---

### Leaderboard Positions

#### `GET /users/me/leaderboard-positions`
Cross-vault leaderboard summary for current user.

Response:
```json
{
  "wallet": "string",
  "stats": {
    "total_positions": 8,
    "kom_count": 1,
    "podium_count": 3,
    "top10_count": 8,
    "total_vaults_completed": 24,
    "best_percentile": 0.95
  },
  "positions": [{
    "vault_id": 42,
    "vault_name": "Manayunk Wall",
    "vault_signature": "string",
    "rank": 3,
    "best_time_seconds": 298,
    "is_kom": false,
    "total_riders": 45,
    "percentile": 0.93,
    "achieved_at": "datetime"
  }]
}
```

**Mobile relevance:** Nice-to-have for profile tab. Shows "1 KOM, 3 podiums, 8 top-10s."

---

## Part 2: Post-Ride Response

This is the most important data flow. Here is exactly what happens after a ride file is uploaded and processed.

### Processing Pipeline (3 Phases)

**Phase 1** (target <5s): Parse file, calculate metrics (TSS, NP, IF, distance, elevation, kcals), store GPS + streams. Status becomes `metrics_ready`.

**Phase 2** (target 30-60s): Project GPS to H3 tiles, detect climb/steady/exploration patterns, match climbs to vaults, update leaderboards. Status becomes `enriched`.

**Phase 3** (background): Allocate CAL from TSS, detect achievements, stage on-chain operations. Status becomes `completed`.

### What the App Should Do

1. Upload file via presigned flow (`/rides/upload/init` + PUT + `/rides/upload/complete`)
2. Get back `ride_id` and status `"processing"`
3. Poll `GET /rides/{ride_id}/status` every 2-3 seconds
4. **When `metrics_ready`:** Show map + basic stats (distance, elevation, duration, TSS, calories)
5. **When `enriched`:** Show detected climbs, vault matches, leaderboard positions
6. **When `completed`:** Show CAL earned, achievements

### Data Available at Each Phase

| Phase | Status | Available Data |
|-------|--------|---------------|
| 1 | `metrics_ready` | tss, kcals, distance_m, elevation_gain_m, duration_sec, avg_power_w, normalized_power_w, GPS track |
| 2 | `enriched` | All Phase 1 + climb patterns, vault matches, leaderboard updates |
| 3 | `completed` | All Phase 2 + cal_earned, dung_minted, tx_signature, achievements |

### Post-Ride Climb Data Shape

From `GET /rides/{ride_id}/patterns`, each climb in `patterns.climb_patterns`:

```json
{
  "name": "Manayunk Wall",
  "vert_m": 85.0,
  "time_s": 312,
  "duration_s": 312,
  "vam": 980.8,
  "distanceM": 1200.0,
  "avgGradientPct": 7.1,
  "avgSpeedMps": 3.8,
  "avg_power_w": 310.0,
  "signatureHex": "abc123...",
  "roadName": "Manayunk Wall",
  "persistenceM": 82.0,
  "significancePercentile": 0.95,
  "significanceConfidenceTier": 2,
  "startOffsetS": 1800,
  "endOffsetS": 2112,
  "vaultMatch": {
    "vault_climb_id": "uuid",
    "vault_climb_name": "Manayunk Wall",
    "similarity": 0.92,
    "is_strong_match": true
  }
}
```

### Is There Enough Data for the "Gold Cascade" Reveal?

**Yes.** The data supports a rich post-ride reveal:

1. **Metrics card:** distance, elevation, duration, TSS, NP, calories, CAL earned
2. **Climb cards:** Each detected climb with name, vert, time, gradient, VAM. If vault-matched: vault name, leaderboard rank
3. **Exploration card:** New tiles discovered count
4. **CAL earned:** Total CAL from TSS
5. **Achievement badges:** From the achievements system

### What is MISSING for an ideal post-ride reveal?

1. **Climb elevation profile polyline** -- The climb has `startOffsetS` and `endOffsetS` which can index into the GPS track, but there is no pre-rendered elevation profile. The mobile app would need to render this from GPS points filtered by time offset.
2. **Leaderboard rank for this ride's climbs** -- The leaderboard is updated during processing, but the rank is not returned directly on the pattern data. The app would need a separate `GET /vaults/{vault_id}/leaderboard` call per matched vault to show "You're #7!"
3. **Before/after comparison** -- No endpoint returns "your previous best was X, this effort was Y" inline. The `GET /vaults/{vault_id}/my-completions` endpoint has effort history with `isPR` and `improvement` fields, but it requires a separate call.

---

## Part 3: Minimum Viable Screens

### The Core Loop

```
Open app -> Feed -> Record -> Ride -> Stop -> Upload -> Post-ride reveal -> Done
```

### Screen 1: Home / Feed

**What it shows:** Recent rides from followed users (or global feed if new).

**Data source:**
- `GET /auth/bootstrap` (startup: auth state, profile, points config)
- `GET /feed` or `GET /feed/global`
- `GET /cal/onchain` (header CAL balance display)

**Available today:** Yes, all endpoints exist.

**What to SKIP for v1:**
- Suggested riders
- Social interactions (likes, comments)
- Territory map

### Screen 2: Record (Map + Controls)

**What it shows:** Full-screen map with GPS tracking. Start/Stop/Pause buttons. Live stats overlay (duration, distance, speed, elevation, HR if connected).

**Data source:** Native GPS + device sensors. No API calls during recording.

**Available today:** N/A (native functionality, no backend dependency).

**What to SKIP for v1:**
- Live segment detection ("You're on Manayunk Wall!")
- Bluetooth sensor pairing UI (use phone GPS + accelerometer only)
- Route planning / navigation

### Screen 3: Post-Ride Summary

**What it shows:** Progressive reveal as processing completes.

**Phase 1 (immediate):** Map with GPS trace, basic stats (distance, elevation, duration, TSS, calories).

**Phase 2 (30-60s later):** Detected climbs appear as cards. Each card: name, vert, gradient, time. Vault-matched climbs show vault name.

**Phase 3 (background):** CAL earned animation. Achievement badges.

**Data source:**
- `POST /rides/upload/init` + PUT + `POST /rides/upload/complete` (upload)
- `GET /rides/{ride_id}/status` (polling for progressive data)
- `GET /rides/{ride_id}/patterns` (climb detail when enriched)
- `GET /rides/{ride_id}/gps` (map trace)

**Available today:** Yes, all endpoints exist.

**What to SKIP for v1:**
- Animated "gold cascade" (just show a list)
- Leaderboard rank per climb (requires extra API calls per vault)
- Achievement detail screens
- Social sharing

### Screen 4: Ride History

**What it shows:** List of past rides with date, distance, elevation, duration, CAL earned.

**Data source:**
- `GET /rides` (paginated list)

**Available today:** Yes.

**What to SKIP for v1:**
- Filtering by date range
- Sorting options
- Ride search

### Screen 5: Ride Detail

**What it shows:** Tap a ride from history. Map + stats + climb list. Same data as post-ride but for any past ride.

**Data source:**
- `GET /rides/{ride_id}` (ride record with vault completions)
- `GET /rides/{ride_id}/patterns` (climb patterns)
- `GET /rides/{ride_id}/gps` (map)

**Available today:** Yes.

**What to SKIP for v1:**
- Power/HR/cadence charts (streams)
- Tile heatmap overlay
- Edit ride metadata

### Screen 6: Profile (Minimal)

**What it shows:** Username, avatar, weight/FTP, total stats (rides, distance, elevation, CAL).

**Data source:**
- `GET /users/me` (profile + stats)
- `GET /cal/onchain` (CAL balance)

**Available today:** Yes.

**What to SKIP for v1:**
- Profile editing (web-only)
- Session management
- Leaderboard positions detail
- Achievement gallery
- Notification preferences

### Screen 7: Notifications

**What it shows:** Badge count on tab icon. List of notifications (KOM beaten, new follower, tier unlocked).

**Data source:**
- `GET /notifications` (list with unread count)
- `POST /notifications/{id}/read`

**Available today:** Yes.

**What to SKIP for v1:**
- Push notifications (requires new endpoint, see Part 5)
- Notification preferences
- In-app notification sounds

---

## Part 4: What NOT to Build in v1

### Definitely Web-Only (Do Not Port)

| Feature | Reason |
|---------|--------|
| **Vault browsing / detail pages** | Complex UI, staking context. Post-ride vault matches are sufficient. |
| **Staking / deposit / unstake / harvest UI** | Financial operations belong on web with full wallet context. |
| **Profile editing** | Weight, FTP, username, avatar -- set once on web. Rare operation. |
| **Map exploration / territory view** | H3 tile visualization is desktop-grade. 50K tiles crushes mobile. |
| **Leaderboard browsing** | Global leaderboard, per-vault leaderboard -- web portal features. |
| **BeetleCard** | Soulbound NFT viewing/upgrading -- web-only. Not even fully implemented. |
| **Settings** | Theme, dark mode, notification prefs, privacy zones -- web-only. |
| **Vault creation** | Complex on-chain operation. Web-only. |
| **Power/HR/cadence charts** | TrainingPeaks-style analysis. Desktop-grade visualization. |
| **Social features** | Follow/unfollow, suggested riders, comments, likes. Web-only for v1. |
| ~~**Points history / events**~~ | Removed April 2026 (no points system). |
| **Admin features** | Obviously. |

### Gray Area (Defer to v1.1)

| Feature | Why Defer |
|---------|-----------|
| **Bluetooth sensor pairing** | ANT+/BLE for power meters, HR straps. Adds complexity. Start with phone-only. |
| **Live segment detection** | "You're on Manayunk Wall!" during recording. Requires pre-loading vault GPS data and matching in real-time. Cool but complex. |
| **Ride editing** | Title, description, visibility. Can do on web. |
| **Social feed interactions** | Likes, comments on rides. v1 feed is read-only. |
| **Strava import** | Already exists on web (`POST /strava/import`). Mobile import can wait. |

---

## Part 5: New Endpoints Needed

### 1. Token Refresh for Mobile (BLOCKER)

**Problem:** `POST /auth/refresh` currently reads the refresh token from an HttpOnly cookie (`request.cookies.get("refresh_token")`). React Native does not send cookies.

**Fix:** Accept refresh token from either:
- Cookie (existing web behavior)
- `Authorization` header
- Request body `refresh_token` field (the schema already has this field but it's marked deprecated)

**Effort:** Small backend change. Restore body/header fallback in the refresh endpoint.

### 2. Push Notification Device Registration

**Problem:** No endpoint exists to register a device token (APNs for iOS, FCM for Android) for push notifications.

**New endpoint needed:**

```
POST /notifications/devices
{
  "device_token": "string (APNs or FCM token)",
  "platform": "ios | android",
  "device_id": "UUID"
}

DELETE /notifications/devices/{device_id}
```

**Effort:** New endpoint + new DB table `notification_devices`. Push delivery service (Firebase Cloud Messaging) needs to be integrated.

### 3. Native Ride Recording Upload

**Problem:** The presigned upload flow (`/rides/upload/init` + PUT + `/rides/upload/complete`) works for uploading FIT/GPX files, but the mobile app records GPS natively and produces its own data format.

**Options:**
- **Option A (recommended):** Record natively, export to GPX format locally, upload via existing presigned flow. The Rust parser already handles GPX. No new endpoint needed.
- **Option B:** New endpoint accepting raw GPS + sensor arrays directly. More efficient but requires a new parser path.

**Recommendation:** Option A for v1. The app writes a GPX file after recording and uploads it through the existing pipeline. Zero backend changes.

### 4. Ride Status WebSocket (Nice to Have)

**Problem:** Polling `GET /rides/{ride_id}/status` every 2-3 seconds is wasteful. NATS events are already published internally (`rides.events.metrics_ready`, `rides.events.enriched`, `rides.events.completed`).

**New endpoint:** `WS /rides/{ride_id}/ws` that streams processing status updates.

**Effort:** Medium. WebSocket upgrade handler that subscribes to NATS subjects. Not needed for v1 -- polling works fine.

### 5. Batch Notification Fetch

**Problem:** On app open, need both unread count (for badge) and recent notifications. Current endpoint returns both in one call, which is fine.

**No new endpoint needed.** `GET /notifications?limit=20` already returns `{ notifications, unread_count }`.

---

## Recommendation

### Build These 7 Screens

1. **Home / Feed** -- Global feed, CAL balance header, record button center-bottom
2. **Record** -- Full-screen map, start/stop, live stats (phone GPS only)
3. **Post-Ride Summary** -- Progressive reveal: map, stats, climbs, CAL earned
4. **Ride History** -- Scrollable list of past rides
5. **Ride Detail** -- Tap any ride: map, stats, climbs
6. **Profile** -- Read-only stats, CAL balance, username
7. **Notifications** -- Badge + list

### Call These 12 Endpoints

| # | Endpoint | Screen |
|---|----------|--------|
| 1 | `GET /auth/bootstrap` | App open |
| 2 | `POST /auth/privy/verify` | Login |
| 3 | `POST /auth/refresh` | Token refresh (needs fix) |
| 4 | `POST /auth/invite/validate` | Signup gate |
| 5 | `GET /feed/global` | Home |
| 6 | `POST /rides/upload/init` | Post-ride upload |
| 7 | `POST /rides/upload/complete` | Post-ride upload |
| 8 | `GET /rides/{id}/status` | Post-ride polling |
| 9 | `GET /rides/{id}/patterns` | Post-ride climbs |
| 10 | `GET /rides/{id}/gps` | Post-ride map |
| 11 | `GET /rides` | Ride history |
| 12 | `GET /cal/onchain` | Profile + home header |

Plus `GET /notifications`, `POST /notifications/{id}/read`, `GET /users/me` as supplementary.

### Fix 1 Blocker Before Starting

The token refresh endpoint must accept the refresh token from the request body or Authorization header, not just cookies. Without this, the mobile app cannot maintain auth sessions.

### Skip Everything Else

No vault browsing. No staking. No profile editing. No territory maps. No social. No charts. No BeetleCard. The mobile app is a **recording device that shows you what you earned (CAL)**. Everything else lives on the web portal.

---

### Data Flow Diagram

```
[App Open]
    |
    v
GET /auth/bootstrap --- authenticated? --no--> [Login Screen]
    |                                              |
    | yes                                  POST /auth/privy/verify
    v                                              |
[Home / Feed]                                      v
    |                                     [Home / Feed]
    |
    +--- GET /feed/global (feed items)
    +--- GET /cal/onchain (header balance)
    |
    |--- tap Record button
    v
[Record Screen]
    |
    | (native GPS recording, no API)
    |
    |--- tap Stop
    v
[Save & Upload]
    |
    +--- write GPX file locally
    +--- POST /rides/upload/init
    +--- PUT to signed_url
    +--- POST /rides/upload/complete
    |
    v
[Post-Ride Summary]
    |
    +--- poll GET /rides/{id}/status every 2-3s
    |       |
    |       +-- metrics_ready: show map + stats
    |       +-- enriched: show climb cards
    |       +-- completed: show CAL earned
    |
    +--- GET /rides/{id}/gps (map)
    +--- GET /rides/{id}/patterns (climbs)
    |
    v
[Done - return to Feed]
```
