# Native Mobile App Strategy -- iOS + Android

**Date:** 2026-03-23
**Status:** Research / Proposal
**Author:** Engineering (research agent)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Tech Stack Decision](#2-tech-stack-decision)
3. [Recording MVP Spec](#3-recording-mvp-spec)
4. [Strava Integration Considerations](#4-strava-integration-considerations)
5. [Solana Mobile Considerations](#5-solana-mobile-considerations)
6. [Solana Grant Strategy](#6-solana-grant-strategy)
7. [Architecture Recommendations](#7-architecture-recommendations)
8. [Competitive Landscape](#8-competitive-landscape)
9. [Timeline and Effort Estimates](#9-timeline-and-effort-estimates)
10. [Risk Assessment](#10-risk-assessment)

---

## 1. Executive Summary

BoulderRoller currently depends on Strava imports and manual FIT/GPX/TCX uploads for ride data. A native recording app eliminates this dependency, unlocks real-time features, and is the single strongest asset for Solana grant applications. This document recommends **React Native (Expo)** as the stack, outlines a phased MVP, and maps the grant landscape.

**Core thesis:** The recording app is not a Strava replacement. It is the minimum viable bridge between physical effort and on-chain economic actions. Record the ride, detect the climbs, sign the vault completions. Everything else is progressive enhancement.

---

## 2. Tech Stack Decision

### 2.1 Trade-Off Matrix

| Criterion | React Native (Expo) | Swift (iOS Native) | Flutter | Kotlin Multiplatform |
|---|---|---|---|---|
| **Code sharing with portal** | High (React, TS, Radix, TanStack) | None | None | Partial (business logic) |
| **GPS background tracking** | Good (react-native-background-geolocation, 63% battery reduction proven at scale) | Best (CoreLocation native, lowest overhead) | Good (geolocator plugin) | Good (FusedLocation native on Android) |
| **BLE sensor support** | Good (react-native-ble-plx, react-native-cycling-sensors tested with Garmin/Tacx/Favero) | Best (CoreBluetooth native) | Fair (flutter_blue, less mature) | Fair (split native implementations) |
| **Solana wallet integration** | Excellent (Privy Expo SDK exists, @privy-io/expo, MWA React Native SDK) | Poor (no Privy Swift SDK, deeplink-only Phantom) | Poor (no official Solana SDK) | Poor (Android-only MWA, no iOS) |
| **Cross-platform path** | iOS + Android from day 1 | iOS only; Android requires separate build | iOS + Android from day 1 | iOS + Android, but newer/smaller ecosystem |
| **Battery during recording** | ~8% per 30min workout (optimized) | ~5% per 30min (native baseline) | ~7% per 30min | ~7% per 30min |
| **Team hiring pool** | Large (React devs can contribute) | Small (iOS-only specialists) | Medium | Small |
| **Time to MVP** | ~10-12 weeks | ~14-16 weeks iOS only | ~12-14 weeks | ~16-18 weeks |
| **Rust FFI for workout-parse** | Possible via UniFFI + react-native bridge (proven: github.com/mariusud/rust-react-native) | Best (UniFFI generates Swift bindings directly) | Possible via dart:ffi | Possible via JNI (Android) + UniFFI (iOS) |
| **Grant narrative** | Strong (cross-platform = wider reach) | Weak (iOS-only limits Solana's Android-heavy mobile user base) | Moderate | Moderate |

### 2.2 Recommendation: React Native with Expo

**React Native (Expo bare workflow)** is the recommended stack for the following reasons:

1. **Privy already works.** The `@privy-io/expo` SDK provides embedded wallet creation, social login (Google/Apple/Email), and transaction signing on both iOS and Android. This is the same auth system the portal uses. No new auth stack needed.

2. **Code sharing is real.** The portal is React + TypeScript + Radix + TanStack Query. API client code (`web/portal/src/lib/api.ts`), type definitions, and query hooks can be extracted into a shared package. The app and portal diverge only on UI components and native modules.

3. **Solana Mobile Wallet Adapter (MWA)** has an official React Native SDK (`@solana-mobile/mobile-wallet-adapter-protocol`). On Android, this enables full websocket-based wallet interaction with Phantom/Solflare. On iOS, Privy embedded wallets bypass the MWA limitation entirely (no deeplink dance required).

4. **GPS + BLE are production-proven.** The `react-native-background-geolocation` library from Transistor Software has been tested across 50,000+ workout sessions. The `react-native-cycling-sensors` library handles power meter, HR, and cadence BLE profiles out of the box (tested with Garmin, Tacx, Favero Assioma).

5. **Battery performance is acceptable.** The 3% delta vs native Swift (8% vs 5% per 30min) is not material for cycling rides. Adaptive accuracy (Balanced mode during steady state, High mode during climb detection) plus distance-filtered updates (5m) bring RN close to native.

6. **Cross-platform from day 1 strengthens grant applications.** Solana Mobile's user base is heavily Android (200K+ Saga/Seeker devices). An iOS-only app would miss the primary Solana mobile audience.

**When to reconsider:** If battery testing on real 4+ hour rides shows >25% drain, or if BLE sensor reconnection reliability is unacceptable, the climb detection and recording core could be rewritten as a native module (Swift/Kotlin) wrapped in RN -- this is a contained change, not a full rewrite.

### 2.3 Why NOT Swift Native

Swift would deliver the best raw GPS and BLE performance, but:
- No Privy SDK means rebuilding auth (deeplink-only Phantom is fragile on iOS)
- Android requires a completely separate codebase (Kotlin), doubling development effort
- Solana grant reviewers explicitly want Android support (Seeker/Saga ecosystem)
- The portal is React; zero code sharing with Swift

Swift is the right answer if BoulderRoller were a pure cycling app. It is not -- it is a cycling-to-chain bridge, and the chain integration is better served by React Native's ecosystem.

---

## 3. Recording MVP Spec

### 3.1 MVP Scope (What Ships First)

**Phase 1 -- Record and Upload (weeks 1-6)**

| Feature | Details |
|---|---|
| GPS recording | CoreLocation (iOS) / FusedLocationProvider (Android) via react-native-background-geolocation. 1Hz sampling in foreground, 1Hz in background with iOS background mode `location`. Distance filter: 5m. |
| Auto-pause | Speed < 1.5 m/s for >10s triggers pause. Resume at >3 m/s. Store pause/resume timestamps. |
| Local storage | SQLite (expo-sqlite) for ride state. Raw samples stored as JSON arrays: `{t, lat_e7, lon_e7, elev_m, speed_mps}`. |
| Ride summary | Distance, duration, elevation gain, avg speed -- computed locally from GPS samples. |
| Upload to backend | On ride completion: serialize samples to our internal format (not FIT), POST to new `/rides/native-upload` endpoint. Backend parses the same way as FIT but skips file detection. |
| Offline support | Full ride recording works offline. Rides queue in SQLite, upload when connectivity returns. |
| Auth | Privy Expo SDK -- same Google/Apple/Email flow as portal. Embedded wallet created automatically. |
| Map display | react-native-maps with ride polyline overlay during recording. |

**Phase 2 -- Sensors and Metrics (weeks 7-10)**

| Feature | Details |
|---|---|
| BLE heart rate | react-native-ble-plx or react-native-cycling-sensors. Standard HRM BLE profile (0x180D). |
| BLE power meter | Standard Cycling Power Service (0x1818). Parse instantaneous power. |
| BLE cadence | Standard CSC Service (0x1816). Parse crank revolutions. |
| Live metrics | Current speed, distance, elapsed time, HR, power, cadence displayed during ride. |
| NP/TSS/IF | Computed locally using extracted Rust logic (see Section 7.3) OR computed server-side on upload. MVP: server-side. |

**Phase 3 -- Chain Integration (weeks 11-14)**

| Feature | Details |
|---|---|
| Post-ride results | After server processing: show detected climbs, vault matches, earnings (labels from ProtocolModeContext). On-chain completions fire server-side during processing -- results are confirmed, not provisional. Push notification when processing completes. |
| On-chain confirmation display | Vault completions are recorded on-chain inline during ride processing. Level 3+ users see tx signatures. Level 0-2 see "Confirmed" badge. |
| Balance display | Show wallet balance and recent earnings using ProtocolModeContext labels (points mode or CAL/DUNG mode). |
| Strava push | Optional: upload completed ride to Strava as GPX (see Section 4). |

### 3.2 GPS Recording Details

**Sampling strategy:**
- Foreground: 1Hz, accuracy `kCLLocationAccuracyBest` (iOS) / `PRIORITY_HIGH_ACCURACY` (Android)
- Background: 1Hz with `distanceFilter: 5` meters. iOS requires `UIBackgroundModes: location` and `Info.plist` usage description.
- Battery optimization: Switch to `Accuracy.Balanced` when speed is steady (low jerk), switch to `Accuracy.Best` on speed changes >2 m/s^2.

**Data format per sample:**
```
{
  t: int64,       // Unix ms
  lat_e7: int32,  // latitude * 1e7 (matches ParsedActivity format)
  lon_e7: int32,  // longitude * 1e7
  elev_m: float32,// meters (barometric if available, GPS otherwise)
  speed_mps: float32,
  hr_bpm: uint8?,
  pwr_w: uint16?,
  cad_rpm: uint8?
}
```

This format is intentionally identical to the `ParsedActivity` struct in `workout-parse/src/lib.rs`. The backend can ingest it directly without FIT parsing.

**Background recording:**
- iOS: `UIBackgroundModes: location` + `allowsBackgroundLocationUpdates = true`. The app requests "Always" location permission with clear justification ("Recording your ride in the background").
- Android: Foreground service with persistent notification ("Recording ride..."). This is the standard pattern used by Wahoo, Garmin Connect, and Strava.

### 3.3 Local Storage Schema

```sql
-- Rides table (SQLite on device)
CREATE TABLE rides (
  id TEXT PRIMARY KEY,           -- UUID
  started_at INTEGER NOT NULL,   -- Unix ms
  ended_at INTEGER,
  status TEXT DEFAULT 'recording', -- recording, paused, completed, uploading, uploaded, failed
  total_distance_m REAL DEFAULT 0,
  total_elevation_m REAL DEFAULT 0,
  duration_sec INTEGER DEFAULT 0,
  sample_count INTEGER DEFAULT 0,
  upload_attempts INTEGER DEFAULT 0,
  server_ride_id TEXT,           -- Set after successful upload
  created_at INTEGER NOT NULL
);

-- GPS + sensor samples (append-only during ride)
CREATE TABLE samples (
  ride_id TEXT NOT NULL,
  t INTEGER NOT NULL,
  lat_e7 INTEGER NOT NULL,
  lon_e7 INTEGER NOT NULL,
  elev_m REAL,
  speed_mps REAL,
  hr_bpm INTEGER,
  pwr_w INTEGER,
  cad_rpm INTEGER
);

-- Upload queue for offline rides
CREATE TABLE upload_queue (
  ride_id TEXT PRIMARY KEY,
  queued_at INTEGER NOT NULL,
  last_attempt_at INTEGER,
  error TEXT
);
```

### 3.4 Auto-Pause Logic

```
IF speed < 1.5 m/s for 10 consecutive seconds:
  state = PAUSED
  store pause_timestamp
  reduce GPS sampling to 0.1Hz (save battery)

IF state == PAUSED AND speed > 3.0 m/s:
  state = RECORDING
  store resume_timestamp
  restore GPS sampling to 1Hz

Elapsed time excludes paused intervals.
Distance excludes samples during paused state.
```

Hysteresis (1.5 m/s stop vs 3.0 m/s resume) prevents rapid toggling at traffic lights.

---

## 4. Strava Integration Considerations

### 4.1 Current State

Users connect Strava via OAuth, and BoulderRoller pulls activities (FIT files) from Strava's API. The backend has full Strava integration: OAuth flow, webhook subscription for auto-import, activity listing, and selective import.

### 4.2 Coexistence Strategy

With native recording, users will have three ride sources:
1. **Native app recording** (new)
2. **Strava auto-import** via webhook (existing)
3. **Manual FIT/GPX/TCX upload** (existing)

The existing duplicate detection system (`DUPLICATE_UPLOAD_DETECTION.md` RFC, `file_hash` dedup) prevents the same ride from being processed twice. Key rule: **dedup by started_at timestamp within a 5-minute window for the same user.**

### 4.3 Pushing Rides TO Strava

Strava's Upload API (`POST /api/v3/uploads`) accepts GPX, TCX, and FIT files. Any recording app can push activities to Strava with the `activity:write` OAuth scope.

**Implementation plan:**
- After ride completion, offer "Share to Strava" button
- Generate GPX from recorded samples (trivial -- lat/lon/elev/time/hr/power/cadence to XML)
- POST to Strava Upload API
- Handle duplicate detection (Strava deduplicates by timestamp)

**Precedent:** Wahoo ELEMNT, Garmin Connect, Hammerhead Karoo, and TrainerRoad all auto-push to Strava. This is standard practice and explicitly supported by Strava's API.

### 4.4 Strava API Restrictions

Key restrictions from Strava's November 2024 API agreement update:
- **Cannot replicate Strava functionality.** BoulderRoller's value prop (climb vaults, token economics, staking) is fundamentally different from Strava's social features. This is not a risk.
- **Cannot publicly display Strava data on third-party apps.** This means we cannot show Strava segment names, Strava leaderboards, or Strava KOMs in our UI. We already don't -- our system uses independent climb detection and signatures.
- **Upload requires `activity:write` scope.** Must be requested during OAuth authorization.

### 4.5 Dual-Publishing Model

The recommended model mirrors Wahoo/Garmin:
1. Ride recorded in BoulderRoller app
2. Processed by BoulderRoller backend (climbs, vaults, points)
3. Optionally pushed to Strava (user controls this toggle)
4. If user also has Strava auto-import enabled, the webhook will fire -- dedup catches it

This gives users the best of both worlds: BoulderRoller economics + Strava social sharing.

---

## 5. Solana Mobile Considerations

### 5.1 Solana Mobile Stack (SMS)

The Solana Mobile Stack is now available to OEM Android manufacturers (announced MWC 2026). Key stats:
- 200,000+ Saga/Seeker devices in market
- 85K+ weekly active wallets
- 500+ apps on Solana dApp Store
- $5B+ in on-chain transaction volume

**Relevance to BoulderRoller:** Medium-high. The Seeker/Saga user base is crypto-native and likely to value a ride-to-earn proposition. However, SMS is Android-only. Our iOS strategy must work independently.

### 5.2 Mobile Wallet Integration

**Android (MWA):**
- `@solana-mobile/mobile-wallet-adapter-protocol` React Native SDK
- Full websocket-based connection to Phantom, Solflare, Backpack
- Transaction signing without app switches
- Works on any Android device, not just Saga/Seeker

**iOS (Privy Embedded Wallet):**
- Privy creates an embedded Solana wallet invisibly on signup
- MPC key sharding (self-custodial, not custodial)
- Transaction signing happens in-app, no wallet app switch needed
- This completely bypasses iOS's MWA limitation (no persistent background connection on iOS)

**iOS (External Wallets):**
- Phantom iOS uses deeplinks (`solana-wallet://`)
- Each transaction requires full app switch (dApp -> Phantom -> dApp)
- Fragile UX, especially for multi-step flows
- **Recommendation:** Default to Privy embedded wallet on iOS. Offer external wallet connection as optional advanced feature.

### 5.3 Transaction Signing Flows

For vault completion signing (the primary on-chain action during a ride):

```
Native App Flow:
  Ride completes -> Upload to backend -> Backend detects climbs -> Vault match found
  -> Push notification: "You completed Mount Tabor vault!"
  -> User opens notification -> App shows vault completion card
  -> User taps "Claim" -> Privy signs transaction in-app (no wallet switch)
  -> Backend submits signed tx to Solana -> Confirmation displayed
```

This is seamless because Privy embedded wallets handle signing without leaving the app. The user never sees a wallet interface unless they explicitly open their wallet settings.

### 5.4 Solana dApp Store Listing

The Solana dApp Store is an alternative distribution channel to Apple App Store / Google Play. Benefits:
- No 30% Apple/Google commission on any future in-app token purchases
- Crypto-native audience discovery
- Signal of legitimacy in Solana ecosystem

**Recommendation:** List on Solana dApp Store in addition to App Store / Play Store. The dApp Store requires the app to integrate SMS components (MWA, Seed Vault). Since we already plan MWA integration for Android, this is minimal additional work.

---

## 6. Solana Grant Strategy

### 6.1 Available Programs

| Program | Amount | Focus | Fit for BR |
|---|---|---|---|
| **Solana Foundation Grants** | $10K-$250K+ (milestone-based) | Public goods, ecosystem growth, DeFi, DePIN, consumer | Strong -- fitness + on-chain, novel climb verification |
| **Solana Foundation Convertible Grants** | $50K-$500K | Commercial projects with ecosystem value | Strong -- converts to equity investment upon milestones |
| **Solana Mobile Builder Grants** | Up to $10K per team | Mobile dApps on SMS/dApp Store | Strong -- cycling recording + on-chain perfectly fits |
| **Superteam Instagrants** | Up to $10K | Emerging market builders | Moderate -- US-based team, but usable for regional expansion |
| **Colosseum Hackathon** | Prizes + follow-on funding | Hackathon-style competition | Moderate -- if timing aligns with next hackathon |

### 6.2 Grant Application Strategy

**Tier 1: Solana Mobile Builder Grant ($10K)**
- Lowest friction, fastest turnaround
- Apply immediately with MVP spec from this document
- Deliverable: Recording app on Android with MWA + dApp Store listing
- Timeline: 10-12 weeks to demo

**Tier 2: Solana Foundation Grant ($50K-$100K)**
- Milestone-based, more rigorous review
- Apply after Mobile Builder Grant accepted (signal of momentum)
- Milestones:
  - M1: Recording MVP live on TestFlight/Play Store beta (4 weeks)
  - M2: BLE sensor integration + climb detection on device (8 weeks)
  - M3: On-chain vault completion signing from mobile (12 weeks)
  - M4: 500 rides recorded via native app (16 weeks)
  - M5: Solana dApp Store listing + 1000 rides (20 weeks)

**Tier 3: Convertible Grant ($100K-$250K)**
- Apply after M3 completion from Tier 2
- This converts to equity investment upon hitting growth milestones (e.g., 10K users, priced round)
- Position BoulderRoller as "DePIN for cycling" -- physical infrastructure (roads/climbs) mapped to on-chain vaults

### 6.3 What Strengthens the Application

1. **Existing on-chain program deployed to devnet with live protocol.** This is not a whitepaper project. 55+ Anchor tests passing. Full protocol live: on-chain Climb completions, direct CAL credit via RideAttestation, Settlement Week finalization with per-bucket direct allocation, staking/harvest, TS indexer streaming. Shadow mode removed — chain is truth.

2. **Cross-platform (iOS + Android).** Solana Mobile reviewers explicitly prefer apps that reach the Seeker/Saga user base (Android). iOS coverage doubles the addressable market.

3. **Novel verification mechanism.** 64-byte climb signatures generated from GPS + elevation data, matched deterministically to on-chain vaults. This is patentable IP that doesn't exist in any other move-to-earn app.

4. **DePIN narrative.** Physical geographic routes (climbs) are financialized as on-chain vaults. Riders stake tokens, earn yield from traffic. This fits the DePIN category that Solana Foundation is actively funding.

5. **Existing user base.** Even in alpha with invite codes, having real riders with real points demonstrates traction.

6. **Team execution evidence.** Corpus-validated climb detection across 2,893 rides, 46,758 climbs detected. Infrastructure sprint completed (NATS, atomic financial ops, replay system). This is a shipping team.

### 6.4 What Grant Reviewers Typically Want

Based on Solana Foundation grant documentation:
- **Clear milestones** with measurable deliverables
- **Public goods component** (open-source where possible, ecosystem contribution)
- **Mainnet deployment plan** (not perpetually devnet)
- **User growth metrics** (MAU, rides recorded, vaults created)
- **Sustainability plan** (how the project survives after grant money)
- **Demo/video** showing the product working

### 6.5 Solana Mobile Grant Specific Requirements

- Mobile-first UX on Android
- Integration of SMS components (MWA, Seed Vault)
- Published on Solana dApp Store
- Runs alongside Colosseum hackathon timeline

---

## 7. Architecture Recommendations

### 7.1 High-Level Architecture

```
+------------------+       +------------------+       +------------------+
|   Mobile App     |       |   Backend API    |       |   Solana         |
|   (React Native) |       |   (FastAPI)      |       |   (Devnet)       |
|                  |       |                  |       |                  |
|  GPS Recording   |------>|  /rides/native   |       |  boulder_rollers |
|  BLE Sensors     |  HTTP |  Ride Processor  |------>|  program         |
|  Local SQLite    |       |  Pattern Engine  |  RPC  |                  |
|  Privy Auth      |       |  Climb Detection |       |  Vaults          |
|  Ride Display    |<------|  Points Service  |       |  VaultStake      |
|                  |  Push |  NATS JetStream  |       |  Leaderboard     |
|  Privy Wallet    |------>|                  |       |  LocalLegend     |
|  (tx signing)    |       |  Supabase DB     |       |  BeetleCard      |
+------------------+       +------------------+       +------------------+
        |                          |
        |     +------------------+ |
        +---->|  Strava API      |<+
              |  (push/pull)     |
              +------------------+
```

### 7.2 API Contract for Native Recording

New endpoint: `POST /rides/native-upload`

```json
{
  "started_at_ms": 1711200000000,
  "total_elapsed_s": 3600,
  "sport": "cycling",
  "device_name": "BoulderRoller iOS",
  "samples": [
    {
      "t": 1711200000000,
      "lat_e7": 399528410,
      "lon_e7": -751642350,
      "elev_m": 45.2,
      "speed_mps": 7.5,
      "hr_bpm": 145,
      "pwr_w": 210,
      "cad_rpm": 88
    }
  ]
}
```

The backend constructs a `ParsedActivity` from this payload and feeds it through the identical pipeline: metrics -> tiles -> patterns -> vaults -> points. No separate code path. The only difference is skipping the FIT/GPX/TCX file detection step.

This endpoint also accepts presigned upload (same `UploadInit` / `UploadComplete` flow) for large rides. The app computes SHA-256 of the serialized payload, requests a presigned URL, uploads, then triggers processing.

### 7.3 Rust Parser on Mobile (workout-parse portability)

The `workout-parse` crate's core logic is highly portable:

| Module | PyO3 dependency | Mobile portable |
|---|---|---|
| `climb/` (detector, persistence, terrain, utils, signature_v2) | None | Yes -- pure Rust |
| `metrics/` (NP, TSS, IF, kcals) | None | Yes -- pure Rust |
| `tiles/` (H3 projection) | None | Yes -- uses h3o crate |
| `polyline/` | PyO3 wrappers in 9 lines | Yes -- strip wrappers |
| `lib.rs` | All PyO3 exports (69 occurrences) | No -- this is the Python bridge |

**Strategy:** Create a `workout-parse-core` crate that contains the pure Rust logic without PyO3. The existing `workout-parse` crate depends on `workout-parse-core` and adds PyO3 bindings. A new `workout-parse-mobile` crate depends on `workout-parse-core` and adds UniFFI bindings for Swift/Kotlin.

```
workout-parse-core/     <- pure Rust (climb, metrics, tiles, polyline)
workout-parse/          <- PyO3 bindings for backend (existing)
workout-parse-mobile/   <- UniFFI bindings for iOS/Android (new)
```

This enables on-device computation of:
- NP/TSS/IF during the ride (live metrics)
- Climb detection in real-time (alert when completing a vault)
- H3 tile projection (live map tile coverage)

**MVP recommendation:** Do NOT compile Rust for mobile in Phase 1. Upload raw samples to backend, let the server compute everything. On-device Rust is a Phase 3 optimization for live metrics and real-time climb alerts.

### 7.4 Real-Time vs Post-Ride Processing

| Processing | On-device (real-time) | Server (post-ride) | Recommendation |
|---|---|---|---|
| Distance/speed/elevation | On-device (trivial GPS math) | -- | On-device |
| NP/TSS/IF | Possible but not critical live | Post-ride | Server (MVP) |
| Climb detection | Possible with Rust FFI | Post-ride | Server (MVP), device (Phase 3) |
| Vault matching | Requires vault index | Post-ride | Server only |
| Points/CAL award | Requires backend state | Post-ride | Server only |
| H3 tile projection | Possible with h3o | Post-ride | Server (MVP), device (Phase 3) |

### 7.5 Push Notifications

Use Expo Notifications (`expo-notifications`) for:

| Event | Trigger | Priority |
|---|---|---|
| Ride processing complete | Backend finishes Phase 3 | High |
| Vault completion | Climb matched to existing vault | High |
| Leaderboard change | User bumped onto/off top 10 | Medium |
| Settlement Week finalization | Weekly DUNG distribution | Medium |
| New vault near you | Vault created in user's H3 area | Low |

Backend publishes events to NATS, a new notification worker consumes them and dispatches via Expo Push Notification Service (free tier: unlimited).

### 7.6 Offline Architecture

```
Recording (offline-capable):
  GPS + BLE samples -> SQLite (on device)
  -> Ride completes -> Add to upload queue

Sync (when online):
  Upload queue worker checks connectivity every 30s
  -> For each queued ride: upload to /rides/native-upload
  -> On success: mark as uploaded, store server_ride_id
  -> On failure: increment attempt count, exponential backoff (max 1 hour)
  -> After 10 failures: mark as failed, surface to user

Read (cached):
  TanStack Query with offline persistence (AsyncStorage)
  -> Rides list, points balance, vault completions cached locally
  -> Stale-while-revalidate when online
```

---

## 8. Competitive Landscape

### 8.1 Move-to-Earn Cycling Apps

| App | Chain | Mechanism | Recording | Cycling-specific | Status |
|---|---|---|---|---|---|
| **STEPN** | Solana/BNB | NFT sneakers, GPS walk/run | Yes (GPS) | No (walking/running only) | Active, $2.5B+ volume historically |
| **Sweatcoin / SWEAT** | Near/Ethereum | Steps -> tokens, free to start | Yes (pedometer) | Partial (tracks cycling via HR) | Active, 120M+ users |
| **Biken** | BNB | NFT bikes, ride-to-earn | Yes (GPS) | Yes | Small, early stage |
| **Ride2Earn (RD2E)** | BNB | NFT bikes, cycling focus | Yes (GPS) | Yes | Very small |
| **Cycling App (CYC)** | BNB | Token rewards for cycling | Unclear | Yes | Micro-cap |
| **BoulderRoller** | Solana | Climb vaults, effort-based staking | Import only (currently) | Yes (power meter aware) | Pre-alpha, protocol live on devnet (completions, CAL batching, epoch DUNG, staking) |

### 8.2 Traditional Cycling Recording Apps

| App | Sensors | Recording | Token/Crypto | Key Strength |
|---|---|---|---|---|
| **Strava** | GPS, HR, Power | Yes | No | Social network, segments, massive community |
| **Wahoo ELEMNT** | GPS, HR, Power, Cadence | Via head unit | No | Hardware integration, training plans |
| **Garmin Connect** | GPS, HR, Power, Cadence | Via head unit or phone | No | Ecosystem depth, watch integration |
| **Ride with GPS** | GPS | Yes (phone) | No | Route planning, navigation |
| **TrainingPeaks** | All | Import only | No | Analytics, coaching, periodization |
| **Hammerhead Karoo** | All | Via head unit | No | Best mapping/navigation |

### 8.3 BoulderRoller Differentiation

No existing app combines all three of:
1. **Phone-based ride recording** with power meter and HR support
2. **On-chain economic actions** (vault staking, CAL/DUNG tokens, Settlement Week finalizations)
3. **Deterministic climb verification** (64-byte signatures, not Strava-style GPS matching)

**vs STEPN/Sweatcoin:** They are generic move-to-earn. BoulderRoller is cycling-specific with power meter awareness, TSS-based effort scoring (not just distance), and geographic route financialization. A 200W rider and a 400W rider on the same climb have different experiences.

**vs Strava:** Strava is a social network. BoulderRoller is an economy. Strava segments are community-created vanity markers. BoulderRoller vaults are stakeable economic assets with weekly distributions. "That hill you climbed 100 times? Stake in it and earn from everyone else who climbs it."

**vs Head unit apps (Wahoo/Garmin):** These record rides to proprietary hardware. BoulderRoller records on your phone and bridges to an on-chain economy. We complement head units (import FIT files from them) rather than compete.

---

## 9. Timeline and Effort Estimates

### 9.1 Phase Breakdown

| Phase | Scope | Duration | Team |
|---|---|---|---|
| **Phase 1: Record and Upload** | GPS recording, auto-pause, offline storage, upload to backend, Privy auth, ride list, basic map | 6 weeks | 1 mobile dev + 0.25 backend |
| **Phase 2: Sensors and Metrics** | BLE HR, power, cadence; live metrics display; post-ride summary with server-computed NP/TSS/IF | 4 weeks | 1 mobile dev + 0.1 backend |
| **Phase 3: Chain Integration** | Post-ride vault matches (push notifications), vault completion signing, points balance, Strava push | 4 weeks | 1 mobile dev + 0.25 backend |
| **Phase 4: Polish and Launch** | App Store / Play Store submission, Solana dApp Store listing, TestFlight beta, onboarding flow, crash reporting (Sentry) | 3 weeks | 1 mobile dev + 0.25 backend |
| **Phase 5: Android MWA** | Mobile Wallet Adapter for Android, external wallet connection (Phantom/Solflare) | 2 weeks | 1 mobile dev |
| **Phase 6: On-Device Rust** | UniFFI bindings for workout-parse-core, on-device NP/TSS/IF, real-time climb alerts | 4 weeks | 1 mobile dev + 0.5 Rust dev |

**Total: ~23 weeks (5.5 months) from start to full feature set**
**MVP (Phase 1+2): ~10 weeks to a usable recording app**
**Grantable demo (Phase 1): ~6 weeks**

### 9.2 Backend Work Required

The backend changes are small relative to the mobile work:

| Task | Effort | Description |
|---|---|---|
| `POST /rides/native-upload` endpoint | 1 day | New route that accepts JSON samples instead of FIT file. Constructs `ParsedActivity` and feeds into existing pipeline. |
| Ride source tracking | 0.5 day | Add `source` column to rides table: `strava_import`, `manual_upload`, `native_recording`. Already exists in `RideIngestJob`. |
| Push notification worker | 2 days | NATS consumer that dispatches Expo push notifications for ride completion, vault matches, leaderboard changes. |
| Presigned upload for JSON | 0.5 day | Extend existing `UploadInit`/`UploadComplete` flow to accept `application/json` in addition to binary FIT/GPX/TCX. |

### 9.3 Team Needs

**Minimum viable team:** 1 experienced React Native developer who has shipped a GPS-tracking app.

**Ideal team:** 1 React Native dev (lead) + 1 React Native dev (junior, shared with portal). The lead handles GPS/BLE native modules and architecture. The junior handles UI screens, shared component extraction, and state management.

**Do we need a mobile hire?** Yes, almost certainly. The existing team's expertise is Python backend, Rust parser, React web portal, and Solana/Anchor. React Native GPS/BLE development requires specific experience with background modes, BLE protocol parsing, and App Store submission. This is a specialized skill set.

**Hiring profile:**
- 3+ years React Native
- Shipped a fitness/GPS/tracking app
- BLE experience preferred (not required -- can be learned)
- Crypto/Solana experience NOT required (Privy abstracts this)

**Cost estimate:** $120-180K/year for a senior RN developer in the US. $60-90K for a strong contractor. A 6-month contract for Phase 1-4 ($30-45K at contractor rates) is sufficient to reach App Store launch.

### 9.4 Android Port Timeline

With React Native, there is no separate "Android port." The same codebase runs on both platforms from day 1. Platform-specific work is limited to:

| iOS-specific | Android-specific | Effort |
|---|---|---|
| `UIBackgroundModes: location` | Foreground service notification | Built into react-native-background-geolocation |
| HealthKit integration (optional) | Google Fit integration (optional) | 1-2 days each, Phase 5+ |
| App Store review (stricter) | Play Store review (faster) | 1-2 weeks each |
| TestFlight beta distribution | Play Console internal testing | 1 day each |

The only meaningful Android-specific work is MWA integration (Phase 5, 2 weeks) and Play Store submission.

---

## 10. Risk Assessment

### 10.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **GPS battery drain exceeds 25% on 4hr rides** | Medium | High | Adaptive accuracy, distance filtering. Fallback: native GPS module in Swift/Kotlin wrapped in RN. Test on real 4hr rides in Phase 1. |
| **BLE sensor reconnection unreliable** | Medium | Medium | `react-native-cycling-sensors` handles reconnection. Fallback: manual "reconnect" button. Power meter data is enhancement, not core. |
| **iOS background location killed by OS** | Low | High | Use `startMonitoringSignificantLocationChanges` as fallback. This is a solved problem -- Strava, Wahoo, Ride with GPS all handle it. Requires proper `Info.plist` keys and Apple review justification. |
| **App Store rejection** | Medium | Medium | Apple rejects apps with crypto references. Mitigation: describe as "cycling rewards platform" not "crypto/token app." Points are points. Wallet is "account." Follow Coinbase/Phantom precedent. |
| **Privy Expo SDK bugs or limitations** | Low | High | Privy is acquired by Stripe, actively maintained, used by major projects. Fallback: custom JWT auth (we already have this for the portal). |
| **Rust UniFFI compilation fails on iOS/Android** | Low | Low | Phase 6 only. Server-side processing is always available as fallback. UniFFI is used by Mozilla Firefox on mobile -- it is production-proven. |

### 10.2 Business Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Strava API terms change to block uploads** | Low | Medium | Our recording is independent. Strava push is a convenience feature, not a dependency. Users can manually export GPX and upload to Strava. |
| **Move-to-earn fatigue (STEPN collapse)** | Medium | Medium | BoulderRoller is effort-based, not speculation-based. No NFT purchase required. Points period insulates from token volatility. Fitness-first, not crypto-first. |
| **Grant rejection** | Medium | Low | Grants accelerate but are not required. The app can be built with 1 contractor. Apply to multiple programs in parallel. |
| **Solana dApp Store delisting** | Low | Low | App Store and Play Store are primary distribution. dApp Store is supplementary. |

### 10.3 Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Ride data loss (app crash during recording)** | Medium | High | SQLite writes samples every 10 seconds. Crash recovery: on app relaunch, check for `status=recording` rides with no `ended_at`. Offer to resume or save partial. |
| **Server processing failures for native rides** | Low | Medium | Same pipeline as FIT uploads. NATS JetStream provides at-least-once delivery. Ride replay system already built. |
| **Scaling: 1000+ simultaneous recording users** | Low (for now) | Medium | Backend already handles concurrent ride processing via NATS workers. Presigned upload offloads bandwidth from API. |

---

## Appendix A: Key Files Referenced

- `/Users/gabetemp/curahee/BoulderRoller-v2/workout-parse/Cargo.toml` -- Rust crate dependencies and structure
- `/Users/gabetemp/curahee/BoulderRoller-v2/workout-parse/src/lib.rs` -- ParsedActivity struct (mobile sample format mirrors this)
- `/Users/gabetemp/curahee/BoulderRoller-v2/workout-parse/src/climb/mod.rs` -- Climb detection module (pure Rust, portable)
- `/Users/gabetemp/curahee/BoulderRoller-v2/backend/app/services/ride_processor.py` -- Multi-phase ride processing pipeline
- `/Users/gabetemp/curahee/BoulderRoller-v2/backend/app/services/ride_ingest.py` -- NATS JetStream ride ingestion
- `/Users/gabetemp/curahee/BoulderRoller-v2/backend/app/services/pattern_engine.py` -- Climb/pattern detection orchestrator
- `/Users/gabetemp/curahee/BoulderRoller-v2/backend/app/services/file_storage.py` -- Supabase file storage (presigned upload)
- `/Users/gabetemp/curahee/BoulderRoller-v2/backend/app/routes/rides.py` -- Ride upload endpoints
- `/Users/gabetemp/curahee/BoulderRoller-v2/backend/app/routes/strava.py` -- Strava integration routes
- `/Users/gabetemp/curahee/BoulderRoller-v2/backend/app/schemas.py` -- UploadInit/UploadComplete request/response schemas
- `/Users/gabetemp/curahee/BoulderRoller-v2/web/portal/package.json` -- Portal dependencies (code sharing candidates)
- `/Users/gabetemp/curahee/BoulderRoller-v2/web/portal/src/contexts/AuthContext.tsx` -- Privy auth implementation (mobile mirrors this)
- `/Users/gabetemp/curahee/BoulderRoller-v2/docker-compose.yml` -- Infrastructure topology
- `/Users/gabetemp/curahee/BoulderRoller-v2/docs/rfcs/PRIVY_AUTH_UX.md` -- Privy architecture decisions

## Appendix B: Sources

- [Solana Mobile Builder Grants](https://solanamobile.com/grants)
- [Solana Foundation Grants and Funding](https://solana.org/grants-funding)
- [Solana Mobile Stack for OEMs (MWC 2026)](https://blog.solanamobile.com/post/introducing-the-solana-mobile-stack-for-oems-and-hardware-manufacturers)
- [Solana Mobile Stack Overview](https://docs.solanamobile.com/getting-started/overview)
- [iOS Wallet Signing Limitations](https://docs.solanamobile.com/blog/ios-wallet-signing)
- [Mobile Wallet Adapter Deep Dive](https://docs.solanamobile.com/developers/mobile-wallet-adapter-deep-dive)
- [Privy Expo SDK](https://www.npmjs.com/package/@privy-io/expo)
- [Privy Documentation](https://docs.privy.io/welcome)
- [Privy Review 2026](https://cryptoadventure.com/privy-review-2026-embedded-wallet-ux-authentication-flows-and-risks/)
- [React Native vs Swift Comparison 2025](https://crustlab.com/blog/react-native-vs-swift/)
- [Swift vs React Native for iOS 2026](https://webandcrafts.com/blog/react-native-vs-swift)
- [Optimize Battery Drain in React Native Apps](https://www.callstack.com/blog/optimize-battery-drain-in-react-native-apps)
- [React Native Background Geolocation](https://github.com/transistorsoft/react-native-background-geolocation)
- [React Native Cycling Sensors](https://github.com/RespectableThieves/react-native-cycling-sensors)
- [BLE in React Native (Expo guide)](https://expo.dev/blog/how-to-build-a-bluetooth-low-energy-powered-expo-app)
- [Fixing Battery Drain: RN Location Tracking Case Study](https://www.wellally.tech/blog/react-native-fix-location-tracking-battery-drain)
- [UniFFI (Mozilla)](https://github.com/mozilla/uniffi-rs)
- [Rust React Native via UniFFI](https://github.com/mariusud/rust-react-native)
- [Building iOS App with Rust UniFFI](https://dev.to/almaju/building-an-ios-app-with-rust-using-uniffi-200a)
- [Garmin FIT SDK](https://developer.garmin.com/fit/overview/)
- [Strava Upload API](https://developers.strava.com/docs/uploads/)
- [Strava API Agreement Update (Nov 2024)](https://support.strava.com/hc/en-us/articles/31798729397773-API-Agreement-Update-How-Data-Appears-on-3rd-Party-Apps)
- [Move-to-Earn Market ($10B by 2033)](https://coinbrain.com/blog/move-to-earn-apps-and-games-2026)
- [Top Move-to-Earn Crypto Projects 2025](https://99bitcoins.com/analysis/top-move-to-earn-crypto/)
- [Superteam Grants](https://earn.superteam.fun/grants/)
- [Solana Foundation USA Grants via Superteam](https://earn.superteam.fun/grants/solana-foundation-usa-grants/)
- [Solana Foundation Convertible Grants](https://solana.com/news/solana-foundation-convertible-grants-investments)
- [Solana Grants Summary (CoinFabrik)](https://www.coinfabrik.com/web3-grants/solana-grants/)
