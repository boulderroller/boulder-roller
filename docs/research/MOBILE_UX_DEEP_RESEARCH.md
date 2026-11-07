# Mobile UX Deep Research: Cycling Recording App

**Date:** 2026-03-23
**Purpose:** Competitive intelligence across 5 UX domains for BoulderRoller React Native cycling app
**Apps studied:** Strava, Wahoo ELEMNT, Garmin Connect/Edge, Hammerhead Karoo, RWGPS, Komoot, STEPN, Sweatcoin, Helium Mobile, Zwift, TrainerRoad, AllTrails

---

## Table of Contents

1. [Recording UX Flow](#1-recording-ux-flow)
2. [Sensor Pairing UX](#2-sensor-pairing-ux)
3. [Offline-First Architecture](#3-offline-first-architecture)
4. [Wallet UX for Non-Crypto Riders](#4-wallet-ux-for-non-crypto-riders)
5. [iOS vs Android Visual Identity](#5-ios-vs-android-visual-identity)
6. [Steal This / Avoid This](#6-steal-this--avoid-this)
7. [BoulderRoller v1 Recommendations](#7-boulderroller-v1-recommendations)

---

## 1. Recording UX Flow

### Pre-Ride Screen Comparison

| App | Route Preview | Weather | Sensor Status | Goal Setting | Other |
|-----|:---:|:---:|:---:|:---:|------|
| **Strava** | Yes (load route button, bottom-right) | No (premium: heatmap layers) | HR only (BLE HR monitors) | No | Sport type selector, map centered on location |
| **Wahoo ELEMNT** | Yes (route sync from companion) | No | Full (HR/power/cadence/speed) | Workout targets | Sensor dashboard shows connection state per device |
| **Garmin Edge** | Yes (course loading) | Yes (on newer Edge 1050) | Full (color-coded icons) | Structured workouts | ClimbPro pre-loads climb profiles for loaded route |
| **Hammerhead Karoo** | Yes (auto-sync from dashboard) | No | Full | Workout integration | CLIMBER settings (All/Medium/Large climbs filter) |
| **RWGPS** | Yes (detailed elevation profile, zoomable) | No | Basic | No | Waypoints with audio alerts, cue sheets |
| **Komoot** | Yes (surface type overlay, difficulty rating) | No | No | No | Elevation profile with high/low points, voice nav |

**Key pattern:** Every serious cycling app shows a map centered on current GPS location as the primary pre-ride view. Sensor status and route loading are secondary affordances accessed via icons/buttons overlaid on the map.

### During-Ride Screen Comparison

| App | Default View | Data Fields | Map + Data | Climb Detection | Customization |
|-----|-------------|-------------|:---:|:---:|:---:|
| **Strava (2025 redesign)** | Map with metrics overlaid | Time, distance, pace/speed, elevation | Yes (unified -- key 2025 change) | Live Segments: approaching/in-segment/complete with audio cues, PR/KOM ghost avatars | Subscriber: map layers (3D terrain, heatmap, winter) |
| **Wahoo ELEMNT** | Data fields (bike computer paradigm) | Up to 10 per page, 5 custom pages | Separate pages | Strava Live Segments integration | Full drag-and-drop field layout via companion app |
| **Garmin Edge** | Data fields | 8-12 screens, 6-12 fields each | Separate screens, swipe to switch | ClimbPro: elevation profile with gradient breakdown per 100m, distance to top, VAM | Full customization via device or Garmin Connect app |
| **Hammerhead Karoo** | Map + data hybrid | Configurable | Yes | CLIMBER: auto-detects climbs even without pre-planned route, gradient per 100m, distance to top, VAM | Sensitivity filter (All/Medium/Large) |
| **RWGPS** | Map with route overlay | Speed, distance, elevation, time | Yes | Elevation profile awareness, waypoint audio alerts | GPS recording interval (1-10 sec) |
| **Komoot** | Map with navigation | Speed, distance, distance remaining | Yes | Elevation profile visible during ride, voice guidance | Scroll through data points while riding |

**Critical insight from Strava's 2025 redesign:** The old pattern of separate "map view" and "data view" screens that users toggled between is dead. Strava's new Record experience overlays key metrics directly on the map, eliminating screen-switching during rides. This is the new standard.

### Strava Live Segments Flow (the competitive benchmark)

```
APPROACHING SEGMENT:
  Audio cue (chime or voice) + visual notification
  Segment name displayed
  Only triggers if crossing start line in correct direction

DURING SEGMENT:
  Bird's-eye view with ghost avatars (your PR + KOM/QOM)
  Halfway mark displayed at 50%
  Real-time position updates
  Haptic cues on supported devices

SEGMENT COMPLETE:
  Completion alert with provisional time
  Audio notification (voice: "You finished [segment name]")
  Shows if fastest/2nd/3rd fastest
  Returns to normal recording view

AUDIO OPTIONS:
  Off / Voice / Chimes
  Settings: Record > Customize > Audio Cues > Live Segment Performance
```

### Auto-Pause Comparison

| App | Trigger | Visual Indicator | Audio/Haptic | Resume |
|-----|---------|-----------------|:---:|--------|
| **Strava** | GPS movement stops (cycling) / accelerometer (running); 10-sec stationary threshold | Pause icon on screen, screen dims | Audio cue if split announcements enabled | Automatic on movement detected |
| **Garmin Edge** | Speed drops below threshold OR complete stop (configurable) | Pause icon overlay, screen dims significantly | Beep (configurable) | Automatic |
| **Wahoo** | Configurable speed threshold | Timer stops, visual indicator | Beep | Automatic |

**Engineering note from Strava:** Their auto-pause implementation adapts server-side moving-time calculation for real-time phone use. Key challenge: iOS and Android only send location updates reliably when the phone is moving, making stationary detection difficult. Cycling uses GPS-based detection; running uses accelerometer-based.

### Post-Ride Summary Flow

**Strava's post-ride flow (the standard):**
```
1. TAP "FINISH" (or long-press stop)
   |
2. SAVE SCREEN (immediate)
   - Title (auto-generated: "Afternoon Ride")
   - Add photos
   - Description field
   - Privacy controls
   - Sport type confirmation
   |
3. UPLOAD (automatic, immediate on connectivity)
   |
4. ACTIVITY DETAIL (after sync complete)
   - Map with route trace
   - Summary stats (distance, time, elevation, speed)
   - "Top Results" section if achievements exist
   - Segment list with times + achievement badges
   - Achievement types:
     * PR medal (new personal record on segment)
     * Crown (fastest overall on segment)
     * Trophy (2nd-10th place all-time)
   - Heart rate / power analysis (if sensor data)
   - Splits breakdown
   - Social sharing: Strava feed (automatic), export to other platforms
```

**Key timing observation:** Segment matching and achievement calculation happen server-side after upload. On good connectivity, results appear within seconds. On slow connections, the activity page loads first with basic stats, then segment results populate asynchronously. Users do NOT see achievements during the save screen -- only after the activity is fully processed.

### Background Behavior

| App | Screen Lock | Lock Screen Display | Mid-Ride Notifications |
|-----|-------------|--------------------|-----------------------|
| **Strava** | Continues recording via background GPS | Live Activity on iOS lock screen + Dynamic Island (elapsed time, distance, pace) | Audio cues for segments and splits |
| **Garmin Edge** | N/A (dedicated hardware, always-on display) | N/A | Audible alerts for segments, power zones, HR zones |
| **Wahoo** | Continues via companion app background mode | Push notifications for milestones | Configurable alerts |

**Strava Live Activities (iOS):**
- Auto-appears on lock screen when recording starts
- Shows on Dynamic Island (iPhone 14 Pro+)
- Displays: elapsed time, distance, pace
- Tap to return to full Strava app
- Requires iOS 16.1+, settings: Face ID & Passcode > Allow Live Activities

### BoulderRoller Implications: Climb Detection Timing

**Should we show real-time climb detection or post-ride results?**

| Approach | Pros | Cons |
|----------|------|------|
| **Real-time** (like Strava Live Segments) | Dopamine hit during effort; gamification motivation; "I'm earning right now" feeling | Requires pre-loaded vault database; GPS matching mid-ride is error-prone; battery drain; false positives kill trust |
| **Post-ride** (like Strava segment matching) | More reliable matching; canonical_v2 runs both momentum + persistence with corroboration scoring (90.8% recall, F1=0.777); DCT-II signature matching is deterministic; simpler v1 | Delayed gratification; less "magic moment" during ride; users may not care about results after shower |
| **Hybrid** (recommended for v1) | Best of both: lightweight during, authoritative after | More engineering work |

**Recommended v1 hybrid approach:**
```
DURING RIDE:
  - Show elevation profile building in real-time (visual interest)
  - When sustained climbing detected (simple gradient threshold):
    "Climb in progress" indicator with live vert gain
  - NO vault matching during ride (too unreliable on-device)
  - NO earning display during ride (server-side processing required)

POST-RIDE (on-chain completions fire inline during server processing):
  - Upload triggers server-side canonical_v2 climb detection
    (runs both momentum + persistence with corroboration scoring;
     90.8% recall, F1=0.777 on holdout corpus)
  - Vault matching via GPS-gated DCT-II signature matching against indexed_vaults
  - On-chain vault completions fire IMMEDIATELY during processing
    (send_record_vault_completion for each matched activated vault)
  - Results are CONFIRMED on-chain, not provisional
  - Display: "3 climbs detected, 2 vault matches (confirmed), +847 CAL tributed"
  - Each climb expandable: name, vert, time, grade, on-chain confirmation
  - Animate CAL flowing to vaults (post-ride "reveal" moment)
  - Level 3+ users: tx signature link on each confirmed completion
```

---

## 2. Sensor Pairing UX

### Pairing Flow Comparison

| App | Supported Sensors | Discovery Method | Pairing Steps | Multi-Sensor |
|-----|-------------------|-----------------|:---:|:---:|
| **Strava** | HR monitors only (BLE) | Bluetooth scan | 3-4 taps | No (HR only) |
| **Wahoo** | HR, power, cadence, speed, trainers | BLE scan from Devices tab | 3 taps (Devices > Pair > Select) | Yes, full management |
| **TrainerRoad** | HR, power, cadence, speed, trainers | BLE + ANT+ (via Wahoo SDK) | Click "Pair" > wait > auto-detect | Yes, PowerMatch for dual power |
| **Zwift** | HR, power, cadence, speed, steering | BLE + ANT+ | Pairing screen at launch | Yes, dedicated slot per type |

### Wahoo Sensor Management (Best-in-Class)

Wahoo's sensor UX is the gold standard for cycling apps:

```
DEVICES TAB (central hub):
  My Sensors list:
    [Heart Rate]     Connected    [battery icon 85%]
    [Power Meter]    Searching... [spinning indicator]
    [Cadence]        Not Found    [grayed out]

  Each sensor panel shows:
    - Sensor name + Bluetooth ID
    - Connection status: Searching / Connecting / Connected / Not Found
    - Battery level (fuel gauge icon + percentage)
    - Live data preview when connected
    - Color coding: full color = connected, grayed = disconnected

  Data Source Priority:
    - Tap "data source panel" at top
    - Select which sensor provides each data type
    - Handles conflict: two power meters in range

PAIRING FLOW:
  1. Tap "Pair Sensor" (or + icon)
  2. App scans BLE (shows spinner)
  3. Discovered sensors appear in list
  4. Tap to select and pair
  5. Sensor appears in My Sensors
  6. Done

CRITICAL LIMITATION:
  BLE sensors can only connect to ONE app/device at a time.
  Must close other apps before pairing.
  This is a fundamental BLE constraint.
```

### Zwift Pairing Screen (Multi-Sensor UX)

```
PAIRING SCREEN (shown at app launch):
  +----------------------------------+
  | Power Source    [   Search   ]    |
  | Cadence         [   Search   ]   |
  | Heart Rate      [   Search   ]   |
  | Steering        [   Search   ]   |
  +----------------------------------+

  Each row: sensor type > discovered devices > signal strength meter
  BLE icon or ANT+ icon in upper right
  Green = paired, searching = spinning
  Signal bars indicate connection quality

LIMITATION:
  Most BLE devices allow only ONE connection
  Exception: Wahoo KICKR/TICKR allow multiple BLE connections
```

### Sensor Disconnect Handling

| App | Auto-Reconnect | Visual Indicator | Data Gap Handling |
|-----|:-:|---|---|
| **Wahoo** | Yes (continuous retry) | Grayed-out sensor panel, status changes to "Searching" | Gaps in data stream, no interpolation |
| **Garmin Edge** | Yes | Alert banner, data field shows "---" | Records gap, fills with zeros in FIT file |
| **Zwift** | Manual (avatar stops) | Pairing screen signal bars drop | Activity pauses effectively |
| **TrainerRoad** | Yes for power, partial for others | PowerMatch recalibrates offset on reconnect | Workout may auto-pause |

**Common disconnect causes:**
- BLE interference from buildings, electronic signals
- Group rides with many ANT+ signals
- Device moving out of range
- Another app stealing the BLE connection

### BoulderRoller v1 Minimum Viable Sensor UX

**Recommended for v1: HR + Power**

```
SENSOR SCREEN (accessible from pre-ride and settings):
  +------------------------------------------+
  | Sensors                           [Scan] |
  |                                          |
  | Heart Rate                               |
  |   [Wahoo TICKR]  Connected  [87%]        |
  |                                          |
  | Power Meter                              |
  |   [Stages L]     Searching...            |
  |                                          |
  | + Add Sensor                             |
  +------------------------------------------+

DURING RIDE:
  - Small icons in status bar: heart=green, bolt=green (or red/gray)
  - If disconnect: brief toast "Power meter disconnected"
  - Auto-reconnect in background (no user action needed)
  - Data field shows "---" during gap

POST-RIDE:
  - Note any data gaps in ride summary
  - TSS calculation flags if power data incomplete

V2 ADDITIONS:
  - Cadence sensor
  - Speed sensor (for indoor/trainer)
  - Sensor priority/conflict resolution
  - Battery level monitoring with low-battery warnings
```

**Why HR + Power for v1:**
- TSS requires power (or HR-based estimation)
- CAL earning is TSS-based -- power data makes it accurate
- Cadence and speed are "nice to have" for v1
- Most serious cyclists (our target) already have these two sensors

---

## 3. Offline-First Architecture

### How Competitors Handle Connectivity

| App | Records Offline | Offline Maps | Sync Method | Conflict Handling |
|-----|:-:|:-:|---|---|
| **Strava** | Yes (GPS stored locally) | No (map blank, but GPS records) | Auto-upload on connectivity (WiFi or cellular) | Duplicate detection via timestamp + metadata ID |
| **Wahoo** | Yes (bike computer is offline-first) | Preloaded on device | Auto-sync via companion app BLE | Device is source of truth |
| **Garmin** | Yes (hardware is fully offline) | Preloaded on device | Auto-sync via Garmin Connect app | Device is source of truth |
| **RWGPS** | Yes | Yes (downloadable offline maps, premium) | Auto-upload | Manual resolution |
| **Komoot** | Partial (3km strip around route + 5.5x5.5km around start) | Premium only | Auto-sync | Route-based, not full offline |
| **AllTrails** | Recording works offline | Yes (park/region downloads, premium) | Auto-sync on connectivity | Last-write-wins |

### Strava Offline Behavior (Detailed)

```
OFFLINE RECORDING:
  - GPS recording continues normally using device sensors
  - All raw GPS points + timestamps stored locally
  - Map may show blank/cached tiles only
  - Timer, distance, speed all calculated locally

WHAT DOES NOT WORK OFFLINE:
  - Live Segments (requires server for segment matching)
  - Beacon (live location sharing)
  - Social features (kudos, comments)
  - Heatmap layers

SYNC WHEN BACK ONLINE:
  - Automatic: app detects WiFi/cellular and initiates upload
  - Activity file transmitted to servers
  - Processing: segment matching, achievements, leaderboards run server-side
  - If upload fails: activity stays in queue, user can retry manually
  - Export option: save as .GPX to device storage as backup

DUPLICATE DETECTION:
  - Checks date stamp, metadata ID tags
  - Overlapping timestamps within tolerance = duplicate
  - No merge capability -- user must manually delete duplicate
  - Common issue: recording on phone + Garmin simultaneously
```

### AllTrails Offline Map Caching (Best Reference for Download UX)

```
DOWNLOAD FLOW:
  1. Browse to park/region page
  2. Tap "Download" button
  3. Download happens in background (continues even if app backgrounded)
  4. Large parks may take several minutes
  5. Stored locally, accessible only through app

STORAGE DETAILS:
  - Each downloaded area: up to 500 trails (prioritizes popular)
  - Area size limited (too large = "Zoom in" prompt)
  - 10 most recent reviews per trail cached
  - Storage depends on device capacity + Mapbox provider limits
  - iOS can randomly delete cached data to free space (OS-level, app cannot prevent)

OFFLINE BEHAVIOR:
  - Downloaded maps render normally
  - Recording works fully offline
  - Park page refreshes when back in service
  - Synced routes (from desktop) are NOT the same as downloaded maps
  - Downloads cannot be shared between devices
```

### BoulderRoller v1 Minimum Viable Offline Strategy

```
CORE PRINCIPLE: Recording must NEVER fail due to connectivity.

TIER 1 (v1 -- MUST HAVE):
  - GPS recording is fully local, zero server dependency
  - Tile samples, metrics, timestamps all stored in local SQLite/Realm
  - Auto-upload queue when connectivity returns
  - Deduplication: hash of (start_time + duration + distance) as activity fingerprint
  - Show "Pending upload" badge on unsynced activities

TIER 2 (v1.1 -- SHOULD HAVE):
  - Offline map tiles for common riding areas (vector tiles, ~50-200MB per region)
  - Download prompt: "Download maps for [region]?" on first ride in area
  - Cache last 5 ride areas automatically
  - Pre-cache vault locations for offline climb matching hints

TIER 3 (v2 -- NICE TO HAVE):
  - Full offline climb detection via workout-parse Rust FFI
    (FIT/GPX/TCX parsing, terrain classification, 0D persistent homology,
     DCT-II 64-byte signatures -- all run natively via UniFFI bridge)
  - Offline vault matching against cached indexed_vaults with GPS-gated matching
  - "Provisional" results shown offline, confirmed on-chain after sync
  - Route planning offline
  - H3 tile projection (res 10, ~66m hexagons) computed on-device

DATA STORED LOCALLY DURING RIDE:
  - GPS coordinates (lat/lon at 1-sec intervals)
  - Timestamps
  - Sensor data (HR, power, cadence if available)
  - Elevation (from barometer if available, GPS altitude as fallback)
  - H3 tile IDs (can compute locally)
  - Activity metadata (sport type, start time, device info)

SYNC PROTOCOL:
  1. Ride completes -> saved to local DB with unique activity fingerprint
  2. App checks connectivity
  3. If online: POST activity payload to API immediately
  4. If offline: add to upload queue (FIFO)
  5. Background task monitors connectivity
  6. When online: process queue (oldest first)
  7. Server processes ride: canonical_v2 climb detection, vault matching,
     ON-CHAIN vault completions fire inline (send_record_vault_completion),
     CAL allocations staged for Merkle-batched claiming
  8. Local activity updated with server results (confirmed on-chain)
  9. Push notification: "Your ride has been processed: 3 climbs, +847 CAL"

IDEMPOTENCY (critical for on-chain operations):
  - Offline uploads may retry on timeout -- mobile app must include
    idempotency key (activity fingerprint = start_time + duration + distance hash)
  - Server-side: vault_completions table dedup prevents double on-chain
    completions for same (vault_signature, activity_id) pair
  - CAL allocation staging is also idempotent (keyed by activity_id + wallet)
  - On-chain tx failures are stored in on_chain_tx_error for later reconciliation

CONFLICT RESOLUTION:
  - Same ride uploaded via phone recording + Strava import:
    Check: abs(start_time_diff) < 5min AND abs(distance_diff) < 10%
    If match: keep the richer data source (more sensor channels)
    Alert user: "Duplicate ride detected. Kept version with power data."
```

---

## 4. Wallet UX for Non-Crypto Riders

### Move-to-Earn / DePIN App Comparison

| App | Blockchain Visibility | Wallet Terminology | Token Display | Onboarding Friction | Gas Fees |
|-----|----------------------|-------------------|---------------|--------------------:|----------|
| **Sweatcoin** | Minimal (opt-in Web3) | "Sweat Wallet" (built-in) | Sweatcoins (in-app) + SWEAT (crypto, opt-in) | Very low -- steps just earn coins | Hidden entirely |
| **STEPN** | Medium (blockchain selection required) | "Spending" + "Wallet" (two accounts) | GST + GMT prominently displayed | High -- buy NFT sneaker, fund wallet with SOL/ETH | Visible but low on Solana |
| **Helium Mobile** | Low for consumers | Phantom Wallet (external) | MOBILE tokens | Medium -- buy hotspot device | Visible when claiming rewards |
| **Axie Infinity** | High (initially) | "Ronin Wallet" (custom) | AXS + SLP tokens | Was 60 steps/2 hours; reduced to 19 steps/12 min | Sponsored by studios (Ronin Waypoint) |
| **Reddit Points** | Hidden (used "Vault") | "Vault" (in-app) | "Community Points" (MOON, BRICK) | Zero -- auto-created on Reddit account | Meta-transactions (hidden from user) |

### Key Lessons from Each App

**Sweatcoin (best abstraction model):**
- Two-tier system: in-app "Sweatcoins" (no crypto knowledge needed) + optional SWEAT token (for crypto-curious)
- Gradual introduction to DeFi: staking, swapping, transfers introduced over time as opt-in features
- Marketplace for spending coins without ever touching crypto
- Result: 120M+ users, most never interact with blockchain

**STEPN (cautionary tale):**
- Exposed too much crypto too early: blockchain selection (Solana/BSC/ETH), NFT purchase required before first step
- Dual wallet system (Spending + Wallet) confused non-crypto users
- Token volatility visible in-app -- GST/GMT price drops killed motivation
- Lesson: requiring crypto purchase before earning is a massive funnel killer

**Reddit Community Points (best wallet abstraction):**
- Called it "Vault" not "Wallet" -- felt like a feature, not crypto infrastructure
- Created automatically with Reddit account, no seed phrase ceremony
- Used meta-transactions to handle gas -- users never saw transaction fees
- Points displayed as simple numbers, no token price shown
- Lesson: the wallet should be invisible until the user asks for it

**Axie Infinity (onboarding improvement case study):**
- Initial: 60 steps, 2 hours, multiple mainnet transactions -- massive churn
- After optimization: 19 steps, 12 minutes (90% reduction)
- Key fix: fiat on-ramp directly in app (Ramp Network), social login (Google/Apple/Facebook)
- Sponsored transactions for new users (studio covers gas)
- Lesson: every additional step before "earning" loses 30-50% of users

### Blockchain Language Exposure Spectrum

```
FULLY HIDDEN                                              FULLY EXPOSED
|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|
Sweatcoin                Reddit       Helium    STEPN   MetaMask
                                                Axie

BoulderRoller positioning (protocol is live, disclosure is progressive):

  Level 0-2 users (here):           Level 3-4 users (here):
  |-----|-----|                      |-----|-----|-----|-----|
        ^                                              ^
    "Sweatcoin-plus"                            "Reddit-plus"

  Level 0-2:                         Level 3-4:
  - See: Earnings, Balance           - See: CAL/DUNG, wallet address
  - Labels from ProtocolModeContext  - On-chain tx confirmations
  - Protocol runs silently           - Export to Phantom/Solflare
  - Gas fully sponsored              - Epoch distribution details
```

### Token Earning Display Patterns

| Pattern | Used By | Description | Best For |
|---------|---------|-------------|----------|
| **Real-time counter** | STEPN (GST ticks up while walking) | Live token increment during activity | High engagement, but creates volatility anxiety |
| **Post-activity summary** | Sweatcoin (daily step summary) | Earnings shown after activity completes | Clean, reliable, less addictive |
| **Daily digest** | Sweatcoin (daily notification) | Aggregated earnings once per day | Low-engagement, easy to ignore |
| **Milestone alerts** | Reddit Points (periodic awards) | Notification at key thresholds | Good for retention, not continuous |

### Gas / Transaction Fee Handling

| Approach | Used By | Implementation | Cost to Platform |
|----------|---------|---------------|-----------------|
| **Fully sponsored** | Reddit, Axie (for new users) | Platform pays all gas via meta-transactions or paymasters | $0.001-0.01/tx on Solana |
| **Hidden in-token fee** | Sweatcoin | Deduct small amount from earnings, never show "gas" | Built into tokenomics |
| **Visible but low** | STEPN | Show fee but Solana is cheap (~$0.00025) | User pays |
| **Account abstraction** | Modern apps (2025+) | EIP-4337 paymasters, smart wallets | Platform sponsors or batches |

### Progressive Disclosure: When Users WANT Crypto Knowledge

> **Context:** The protocol is LIVE on devnet -- on-chain completions, CAL batch pipeline,
> epoch DUNG minting, staking/harvest, indexer streaming are all operational. The question
> is not "when do we turn on crypto" but "how much of the live protocol does each user see."
>
> **April 2026 Update:** `ProtocolModeContext` and the points system have been removed.
> CAL/DUNG labels are now static. Progressive disclosure still applies -- it controls
> how much of the live protocol each user sees, not mode-switching between points/tokens.

```
LEVEL 0: "I ride bikes" (90% of users, 100% at onboarding)
  Shows: Earnings, total balance, simple leaderboard
  Hides: All blockchain mechanics (protocol runs silently underneath)
  Implementation: Simplified labels -- "earned", "back this climb" (static, not mode-switched)

LEVEL 1: "What do my earnings do?" (after 5-10 rides)
  Introduces: Climb vaults as a concept ("your favorite climbs have economies")
  Introduces: Leaderboard position ("top 10 riders on this climb earn weekly rewards")
  Introduces: Local Legend role ("most completions = elected curator, earns 3% of vault")
  Still hides: Wallet addresses, transaction details, CAL/DUNG distinction

LEVEL 2: "I want to do more with my earnings" (after 20+ rides)
  Introduces: Staking ("back your favorite climb to earn weekly rewards")
  Introduces: Epoch rewards ("rewards distribute every 7 days: Sun 12:00 UTC")
  Introduces: Staker unlock curve ("more backers = more rewards unlocked")
  Still hides: On-chain details, token mechanics

LEVEL 3: "I'm crypto-curious" (self-selected, ~10% of users)
  Unlocks: Wallet view, export to Phantom/Solflare, token swap options
  Shows: CAL/DUNG distinction, on-chain vault details, tx confirmations
  Shows: On-chain completion signatures, epoch distribution history

LEVEL 4: "I'm a degen" (self-selected, ~2% of users)
  Full access: Transaction history, on-chain explorer links (BoulderScan)
  Advanced: LP token details, Merkle batch claims, epoch distribution breakdowns
  Shows: Vault PDA addresses, CAL/DUNG mint addresses, program ID
  Access: Settings > Advanced > Developer Options
```

### BoulderRoller v1 Wallet UX Recommendations

> **Implementation note (April 2026):** `ProtocolModeContext` has been removed.
> CAL/DUNG labels are now static. The progressive disclosure still applies via
> user-facing terminology that scales with rider engagement level.

```
TERMINOLOGY (static labels, progressive disclosure by level):
  Level 0-2 (most riders):          Level 3+ (crypto-curious):
  - "Balance" not "Wallet"          - "Wallet" available
  - "CAL" as earning token          - CAL/DUNG distinction shown
  - "back" / "back this climb"      - "stake" / "stake in vault"
  - "earned"                        - "harvested"
  - "Climbs" preferred              - "Vaults" shown
  - "Weekly rewards"                - "Epoch distributions"

  Always use:
  - "Earn" not "Mine" or "Farm"
  - "Back this climb" / "Stake in this vault" (mode-dependent)

LOCAL LEGEND / SOIGNEUR:
  - 1 elected seat per vault, 8-epoch term (~56 days)
  - Most completions in term wins election
  - Earns 3% of vault distributions
  - Vault creator is automatically first Local Legend
  - Surface in app: "Legend" badge on vault detail, leaderboard callout
  - Level 0-1: "Top rider on this climb earns a bonus"
  - Level 2+: "Local Legend: elected curator, earns 3% of weekly rewards"

EARNING DISPLAY (post-ride summary):
  +----------------------------------------------------+
  |  YOUR RIDE                                         |
  |  42.3 km | 1:45:12 | 687m gained                   |
  |                                                    |
  |  CLIMBS DETECTED                                   |
  |  [mountain icon] Col de la Madone  +312 {token}    |
  |    14.2 km | 687m | 4.8% avg                       |
  |    Confirmed | Your 4th completion                  |
  |                                                    |
  |  [mountain icon] Petit Col        +127 {token}     |
  |    3.1 km | 142m | 4.6% avg                        |
  |    New climb! No vault yet                          |
  |                                                    |
  |  {labels.token} EARNED         +439                |
  |  Total Balance               12,847                |
  +----------------------------------------------------+

  {token} = "CAL" (static label)
  "Confirmed" = on-chain vault completion was recorded successfully
  No token price, no USD equivalent, no blockchain jargon at Level 0-2.
  Level 3+ sees: tx signature link on "Confirmed" badge.

GAS FEES:
  - Fully sponsored by platform on Solana (~$0.00025/tx)
  - Never shown to user at any level
  - Budget: $25/day covers 100K transactions
  - Revenue model: 5% harvest fee on DUNG claims (already implemented on-chain)

PRIVY INTEGRATION (already built):
  - Social login creates embedded Solana wallet (user never sees it)
  - "Sign in with Google" -> wallet exists, user doesn't know
  - Wallet export available in Settings > Advanced > Developer Options
  - Seed phrase backup prompt only for Level 3+ users who opt in
```

---

## 5. iOS vs Android Visual Identity

### Platform Design Conventions for Fitness Apps

| Element | iOS (HIG) | Android (Material 3) | Impact on Cycling App |
|---------|-----------|---------------------|----------------------|
| **Navigation** | Bottom tab bar (max 5 tabs), centered icons | Bottom nav bar (3-5 destinations) + FAB for primary action | Unified: bottom tabs work on both. Record button = center tab (Strava pattern). |
| **Typography** | SF Pro (Text for body, Display for headlines), dynamic sizing | Roboto, Material type scale | Use system fonts per platform. Cross-platform: Inter as fallback. |
| **Back Navigation** | Edge swipe (left-to-right), no hardware back button | System back gesture (Android 11+) OR hardware button | Use `react-navigation` gestureEnabled for iOS, BackHandler API for Android |
| **Status Bar** | Varies: standard, large title, transparent | Standard, can be transparent | Use `react-native-safe-area-context` v5.6+ for both platforms |
| **Notch / Dynamic Island** | 44px top inset (14 Pro), 58px with active notifications | DisplayCutout API (8.1+), punch-hole cameras | SafeAreaProvider handles automatically |
| **FAB** | Not a native iOS pattern | Primary circular action button | Consider only for Android, or skip FAB entirely (Strava doesn't use one) |
| **Haptics** | UIImpactFeedbackGenerator (light/medium/heavy) | VibrationEffect (one-shot/waveform) | Use for: segment start/end, auto-pause, achievements |
| **Workout UX (HIG)** | "Distinct visual appearance for active workout"; easy-to-find pause/resume/stop | Bold CTAs, limit to 3 steps, progress bars/haptics | Active ride screen should look visually distinct from non-ride screens |
| **Live Activity** | Lock screen + Dynamic Island (iOS 16.1+) | Ongoing notification with expandable view | Both should show: elapsed time, distance, current speed |

### How Strava Handles Platform Differences

Strava uses a **unified design** across iOS and Android with minor platform adaptations:

- Same bottom tab bar layout on both platforms (Feed, Maps/Explore, Record, Groups, You)
- Record button is center tab with distinctive appearance on both
- 2025 redesign rolled out on Android first, iOS later -- same design, staggered release
- Map rendering engine (MRE) is shared across platforms
- Navigation gestures follow platform defaults (iOS swipe-back, Android system back)
- Typography uses system fonts (SF Pro on iOS, Roboto on Android)

### React Native UI Library Comparison for Cycling App

| Library | Approach | Performance | Best For | Concern for Us |
|---------|----------|:-----------:|----------|---------------|
| **NativeWind** | Tailwind CSS classes | Excellent (zero-runtime, AOT compiled) | Rapid development, Tailwind familiarity | Industry standard for 2026 RN styling. **Version note:** v5 requires RN 0.81+; our scaffold is RN 0.76.7/Expo 52. Pin v4 or upgrade RN. |
| **Tamagui** | Optimizing compiler, platform-specific code | Best (flattens component tree) | Maximum performance | Steeper learning curve, more opinionated |
| **Gluestack UI v3** | Modular + NativeWind engine | Very Good | Enterprise, accessibility, copy-paste components | Flexible but more setup |
| **React Native Paper** | Material Design components | Good | Quick Material Design prototyping | Less flexible for custom brand, Material-only |
| **Custom** | Hand-built components | Variable | Unique brand identity | Most effort, but total control |

### Safe Area and Notch Handling (2025 Best Practice)

```
RECOMMENDED LIBRARY: react-native-safe-area-context v5.6+

WHY NOT built-in SafeAreaView:
  - Only supports iOS 10+ (no Android support)
  - Causes jumpy behavior during animations
  - No hook API for granular control

IMPLEMENTATION:
  import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';

  // Wrap app root
  <SafeAreaProvider>
    <App />
  </SafeAreaProvider>

  // In screens (prefer hook over component)
  const insets = useSafeAreaInsets();
  <View style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}>

PLATFORM DETAILS:
  iOS: Dynamic Island = ~44px top inset (14 Pro), ~58px when notifications active
  Android: DisplayCutout API (8.1+), detects notches + punch-holes + folding screens
  Android 15: edge-to-edge enforcement (SafeAreaProvider handles automatically)
```

### BoulderRoller v1 Platform Strategy

**Recommendation: Unified design with platform-adaptive details**

```
UNIFIED (same on both, matching portal BottomTabBar):
  - Bottom tab navigation (5 tabs: Feed, Map, Record/Upload (center action), Vaults, Settings)
  - Record/Upload button: center tab, elevated, visually prominent (not a FAB)
  - Color scheme, brand identity, iconography
  - Data visualization components (charts, maps, elevation profiles)
  - Ride recording screen layout
  - Card-based UI for climb results, leaderboards, Local Legend status

PLATFORM-ADAPTIVE (automatic via RN):
  - System fonts (SF Pro / Roboto) via react-native defaults
  - Back navigation (swipe / system back) via react-navigation
  - Safe areas via react-native-safe-area-context
  - Status bar appearance
  - Haptic feedback intensity
  - Share sheet (native on each platform)

RECOMMENDED STACK:
  - Styling: NativeWind (Tailwind for RN, zero-runtime, industry standard)
  - Navigation: React Navigation 7 (with native stack)
  - Safe Area: react-native-safe-area-context v5.6+
  - Maps: react-native-maps (or Mapbox RN SDK for custom styling)
  - Charts: react-native-skia (for custom elevation profiles)
  - GPS: react-native-background-geolocation (Transistor Software)
  - BLE: react-native-ble-plx (for sensor pairing)

WHY NOT React Native Paper:
  - Material Design aesthetic doesn't match our brand ("clean, minimal, utilitarian")
  - Less flexible for custom brand elements
  - Our UI should feel like a premium cycling app, not a Material template
  - NativeWind gives us full design control with great DX
```

---

## 6. Steal This / Avoid This

### Steal This (Best Patterns to Adopt)

| Pattern | From | Why |
|---------|------|-----|
| **Map + metrics overlay (no screen switching)** | Strava 2025 redesign | Eliminates the #1 UX complaint of older cycling apps. Users see map AND data simultaneously. |
| **Live Activity on iOS lock screen** | Strava | Essential for phone-in-pocket cycling. Shows time/distance without unlocking. |
| **CLIMBER auto-detection (no pre-planned route needed)** | Hammerhead Karoo | Detects climbs even on spontaneous rides. Aligns with our canonical_v2 detector (momentum + persistence fusion). |
| **Sensor management hub with color-coded status** | Wahoo ELEMNT | Clear, at-a-glance sensor health. Green/gray with battery level. |
| **Post-ride "reveal" animation for achievements** | Strava | Delayed gratification creates dopamine hit. Our version: "3 climbs detected, 2 vaults matched". |
| **Progressive crypto disclosure (hidden by default)** | Sweatcoin + Reddit Points | 90% of users never need to see blockchain. Points feel native, not crypto. |
| **"Vault" as wallet name (then hide it)** | Reddit Community Points | "Vault" resonates with our climb vault concept AND avoids "wallet" crypto connotation. |
| **Sponsored gas (invisible to user)** | Reddit, Axie (Ronin Waypoint) | Solana gas is $0.00025/tx. Sponsor it. Never break flow asking users about fees. |
| **Social login -> embedded wallet** | STEPN Go, Privy (already built) | Google/Apple sign-in creates Solana wallet invisibly. Zero crypto friction. |
| **Audio cues for segment events** | Strava Live Segments | Chime or voice when approaching/completing a climb. Phone in pocket, ears open. |
| **Offline-first recording with auto-sync queue** | Strava, Garmin | GPS recording must NEVER fail. Queue uploads, process async, notify on completion. |
| **Waypoint audio alerts** | RWGPS | Adaptable for us: audio when entering/exiting a vault zone. |
| **Gradient breakdown per 100m** | Hammerhead, Garmin ClimbPro | Granular climb data. We have this in canonical_v2 climb detection. Surface it. |
| **Data field customization** | Wahoo, Garmin | Let power users choose their 4-6 visible metrics during ride. |
| **Elevation profile building in real-time** | Garmin ClimbPro | Visual interest during ride. Show the climb growing as they ride it. |

### Avoid This (Common Mistakes)

| Anti-Pattern | Seen In | Why It Fails |
|-------------|---------|-------------|
| **Requiring crypto purchase before first activity** | STEPN (buy NFT sneaker first) | Massive funnel killer. 80%+ drop-off before first earning experience. |
| **Showing token prices in-app** | STEPN (GST/GMT price ticker) | Price drops destroy motivation. Users see earnings "worth less" each day. |
| **Separate "Spending" and "Wallet" accounts** | STEPN | Confuses non-crypto users. One balance, period. |
| **60-step onboarding** | Axie Infinity (original) | Every step loses 30-50% of funnel. Get to first ride in <5 taps. |
| **Blockchain network selection during signup** | STEPN (Solana/BSC/ETH choice) | Users don't know what this means. Pick Solana for them. |
| **Showing transaction hashes in main UI** | Various DeFi apps | Means nothing to 98% of users. Hide in developer settings. |
| **Map view and Data view as separate screens** | Strava (pre-2025), many others | Users constantly switching = frustration. Overlay metrics on map. |
| **Auto-pause without audio/visual feedback** | Various | User doesn't know if ride is recording or paused. Must be obvious. |
| **Requiring BLE sensor to start a ride** | None (but tempting for us) | Many riders don't have sensors yet. GPS-only must be first-class. |
| **Real-time token earning counter during exercise** | STEPN | Creates anxiety ("am I earning enough?"), battery drain, unreliable data. |
| **Complex multi-token system explained at onboarding** | Various crypto apps | "You earn CAL which converts to DUNG at 1000:1..." = instant user confusion. |
| **Seed phrase ceremony during signup** | Old crypto apps | Privy handles this. Never show a seed phrase unless user explicitly requests export. |
| **Cartoonish gamification UI** | STEPN (sneaker levels, gems) | Conflicts with our brand: "clean, minimal, utilitarian", "fitness-first not crypto-first". |
| **Showing on-chain tx status to casual users** | Various DeFi apps | "Confirming on-chain..." spinners or tx signatures mean nothing to Level 0-2 users. Completions are either "Confirmed" or silently reconciled. Only Level 3+ sees tx hashes. |

---

## 7. BoulderRoller v1 Recommendations

### Recording UX: Summary Architecture

```
RECORDING STATE MACHINE:

  [Pre-Ride] -> [Recording] -> [Paused] -> [Recording] -> [Finishing] -> [Processing] -> [Results]
       |                           |                            |
       v                           v                            v
  (Sensor scan)              (Auto or manual)           (Upload + detect)


PRE-RIDE SCREEN:
  - Map centered on current location (full screen)
  - Bottom sheet (collapsed): "Start Ride" button (prominent, green)
  - Pull up bottom sheet: sensor status, sport type, route (if loaded)
  - Top bar: GPS signal indicator, battery level
  - If sensors paired: small green icons (heart, bolt) in top bar
  - If no sensors: no warning (GPS-only is valid)

DURING RIDE SCREEN:
  - Map view with real-time trace (primary)
  - Metrics overlay on map (Strava 2025 style):
    * Time (top-left, large)
    * Distance (top-right, large)
    * Speed (bottom-left)
    * Elevation gain (bottom-right)
  - Heart icon + power icon in status area (if sensors connected)
  - When climbing detected: subtle gradient overlay, "Climbing" badge, live vert counter
  - Swipe up: additional metrics (HR, power, cadence, avg speed)
  - Pause button: bottom-center, visible but not dominant

AUTO-PAUSE:
  - Trigger: GPS stationary for 10 seconds (cycling)
  - Visual: screen dims slightly, "PAUSED" banner appears
  - Audio: subtle chime (configurable)
  - Resume: automatic on movement, chime on resume
  - iOS Live Activity: shows "Paused" state on lock screen

POST-RIDE:
  - "Finish" -> Save screen (title, photos, privacy)
  - Upload immediately (or queue if offline)
  - Processing screen: "Analyzing your ride..." (brief spinner)
  - Server runs canonical_v2 detection, fires on-chain completions inline
  - Results reveal (animated, all results are on-chain confirmed):
    1. Route map with climb highlights
    2. Summary stats (distance, time, elevation, TSS)
    3. Climbs detected (expandable cards, "Confirmed" badge)
    4. Vault matches + {labels.token} earned (the money moment)
    5. Local Legend status if applicable ("You're leading this climb!")
    6. Share button

iOS LOCK SCREEN:
  - Live Activity: elapsed time, distance, speed
  - Dynamic Island: compact view with timer
  - Tap to return to app
```

### Sensor Strategy: Phased

```
V1.0: HR + Power (optional, ride works without)
V1.1: Cadence + Speed sensor support
V1.2: Smart trainer integration (indoor riding)
V2.0: Advanced: power zones, structured workouts, dual-sided power
```

### Offline Strategy: Layered

```
V1.0: Local GPS recording + auto-sync queue (non-negotiable)
      Idempotency keys prevent double on-chain completions on retry
V1.1: Offline map tile caching for ride areas
V1.2: Offline vault location cache (for provisional climb matching)
V2.0: Full offline climb detection via workout-parse UniFFI bridge
      (canonical_v2: momentum + persistence fusion, DCT-II signatures,
       GPS-gated matching -- all Rust, runs on-device)
```

### Crypto Abstraction: Progressive (Protocol is LIVE)

> **Current state:** Shadow mode is GONE. All env var gates removed (CAL_BATCH_LIVE,
> EPOCH_DIST_LIVE, STAKING_LIVE, USE_INDEXED_TABLES). The protocol runs end-to-end
> on devnet staging: on-chain completions, Merkle-batched CAL claiming, epoch DUNG
> minting, staking/harvest, TS indexer streaming, API reads from indexed_* tables.
> Chain is truth, Supabase is read cache.

```
CURRENT STATE (protocol live on devnet, all 6 activation days deployed):
  - On-chain completions fire inline during ride processing
  - CAL batch pipeline: rides staged -> Merkle tree -> on-chain claims
  - Epoch DUNG minting: weekly distribution (55% leaderboard, 27% stakers,
    3% Local Legend, 10% protocol, 5% POL)
  - Staking/harvest: LP tokens, 5% harvest fee, all on-chain
  - Indexer: streams on-chain state to indexed_* tables in real-time
  - API reads: USE_INDEXED_TABLES=True (hardcoded, no toggle)
  - CAL_ALLOCATION_MODE=batch (Merkle-batched claiming, default)

  Labels are static CAL/DUNG (ProtocolModeContext removed April 2026).
  Progressive disclosure controls HOW MUCH users see, not WHETHER
  the protocol runs. It is always running. The UI layer abstracts it.

MAINNET LAUNCH (future):
  - Same protocol, same code, different RPC endpoint + program deployment
  - No "conversion event" -- protocol already runs end-to-end
  - Key concern: real economic value means higher stakes for error handling,
    idempotency, and reconciliation of failed on-chain transactions
  - Settings > Advanced > "Show token details" toggle for early adopters
  - Export to Phantom/Solflare available in Advanced settings
```

### Platform Visual Strategy: Unified + Adaptive

```
STACK:
  - NativeWind for styling (Tailwind classes, zero runtime overhead)
    NOTE: NativeWind v5 requires RN 0.81+. Our mobile scaffold is RN 0.76.7
    (Expo ~52). Either upgrade RN or pin NativeWind v4. Flag for resolution
    before build begins.
  - React Navigation 7 for navigation (native stack, platform back gestures)
  - react-native-safe-area-context v5.6+ for safe areas
  - System fonts (SF Pro / Roboto automatically)
  - Custom elevation profile component (react-native-skia)
  - Mapbox RN SDK for maps (custom style, offline tiles, route rendering)
  - workout-parse via UniFFI bridge (future: on-device FIT/GPX/TCX parsing,
    terrain classification, 0D persistent homology, DCT-II signature generation,
    GPS-gated vault matching, H3 tile projection -- all Rust, all deterministic)

DESIGN SYSTEM:
  - 5 bottom tabs matching portal: Feed, Map, Record/Upload (center action),
    Vaults, Settings
    (Portal: BottomTabBar.tsx uses Home/Map/PlusCircle/Mountain/User icons)
  - Record button: center tab, elevated, visually prominent (not a FAB)
  - Dark mode support from day 1 (cyclists ride at dawn/dusk)
  - High contrast data fields (readable in bright sunlight)
  - Touch targets: minimum 44x44pt (Apple HIG) / 48x48dp (Material)
  - Haptic feedback: climb start/end, auto-pause, vault match confirmation
  - ProtocolModeContext shared with portal (same labels, same mode logic)
```

---

## Sources

### Recording UX
- [Strava Recording an Activity](https://support.strava.com/hc/en-us/articles/216917397-Recording-an-Activity)
- [Strava Live Segments](https://support.strava.com/hc/en-us/articles/207343830-Live-Segments)
- [Strava Redesigned Record Experience](https://press.strava.com/articles/strava-launches-redesigned-record-experience)
- [Strava App Redesign Analysis](https://the5krunner.com/2025/07/16/strava-app-redesign/)
- [Strava Live Activities on iOS](https://support.strava.com/hc/en-us/articles/39508401687693-Strava-Live-Activities-on-iOS)
- [Strava Auto-Pause](https://support.strava.com/hc/en-us/articles/216919277-Auto-Pause)
- [Strava Auto-Pause Engineering](https://medium.com/strava-engineering/improving-auto-pause-for-everyone-13f253c66f9e)
- [Strava Ride Activity Pages](https://support.strava.com/hc/en-us/articles/216919577-Ride-Activity-Pages)
- [Strava Audio Announcements](https://support.strava.com/hc/en-us/articles/216917237-Audio-Announcements)
- [Wahoo Customize ELEMNT Pages](https://support.wahoofitness.com/hc/en-us/articles/21043803163154-Customize-Pages-on-an-ELEMNT-GPS-Computer)
- [Hammerhead Karoo CLIMBER](https://support.hammerhead.io/hc/en-us/articles/25602163627163-Karoo-OS-Climber)
- [Hammerhead CLIMBER Feature (DC Rainmaker)](https://www.dcrainmaker.com/2021/06/hammerhead-karoos-new-climber-feature-heres-how-it-works.html)
- [RWGPS 2025 Feature Roundup](https://bikepacking.com/news/2025-ride-with-gps-feature-roundup/)
- [Komoot Complete Guide (BikeRadar)](https://www.bikeradar.com/advice/buyers-guides/guide-to-using-komoot)
- [Garmin Edge Data Fields](https://www.garmin.com/en-GB/blog/coachs-corner-what-data-fields-to-have-on-your-garmin-edge-bike-computer/)
- [Strava Design Critique (Pratt)](https://ixd.prattsi.org/2026/02/design-critique-strava-ios-app-3/)
- [Strava Simplified Activity Tracking (BikeRadar)](https://www.bikeradar.com/news/strava-redesigned-record-feature)

### Sensor Pairing
- [Strava Sensor Pairing](https://support.strava.com/hc/en-us/articles/360049550432-Pairing-Sensors-with-the-Strava-app)
- [Strava BLE Support Reintroduced (BikeRadar)](https://www.bikeradar.com/news/strava-sensor-pairing)
- [Wahoo Sensor Management](https://support.wahoofitness.com/hc/en-us/articles/14467671524114-Sensor-management-Wahoo-app)
- [Wahoo Pair a Sensor](https://support.wahoofitness.com/hc/en-us/articles/14836035381778-Pair-a-sensor-to-the-Wahoo-app)
- [Wahoo Connecting BLE Sensors](https://support.wahoofitness.com/hc/en-us/articles/4402702687378-Connecting-Bluetooth-Sensors)
- [TrainerRoad BLE Connectivity](https://support.trainerroad.com/hc/en-us/articles/201377504-Bluetooth-Smart-Connectivity)
- [TrainerRoad How to Pair Devices](https://support.trainerroad.com/hc/en-us/articles/360023678392-How-to-Pair-Your-Devices)
- [TrainerRoad PowerMatch](https://support.trainerroad.com/hc/en-us/articles/204631294-PowerMatch-Using-Power-Meters-with-Smart-Trainers)
- [Zwift Connecting Devices for Cycling](https://support.zwift.com/en_us/connecting-your-devices-for-cycling-HJIFDrw5S)

### Offline Architecture
- [Strava Offline Functionality (Fitro)](https://fitro.info/strava-offline-functionality)
- [Strava Troubleshooting Syncing](https://support.strava.com/hc/en-us/articles/216919037-Troubleshooting-Syncing)
- [AllTrails Offline Map Downloads](https://support.alltrails.com/hc/en-us/articles/37213318235028-How-to-download-maps-to-your-phone-for-offline-use)
- [AllTrails Custom Areas for Offline](https://support.alltrails.com/hc/en-us/articles/37758009767444-Download-custom-areas-for-offline-use)
- [Komoot Offline Maps (DC Rainmaker)](https://www.dcrainmaker.com/2026/01/komoots-offline-routing.html)
- [RWGPS App Features](https://ridewithgps.com/app)
- [Offline Sync Architecture Guide](https://www.alphasoftware.com/blog/offline-sync-architecture-tutorial-examples-tools-for-field-operations)
- [RN Background Geolocation (Transistor Software)](https://www.transistorsoft.com/shop/products/react-native-background-geolocation)
- [RN Background Geolocation Guide](https://www.cyberangles.org/blog/can-you-track-background-geolocation-with-react-native/)
- [RN Battery Drain Fix Case Study](https://www.wellally.tech/blog/react-native-fix-location-tracking-battery-drain)
- [Strava Duplicate Activities](https://communityhub.strava.com/strava-features-chat-5/how-to-stop-rides-being-duplicated-539)

### Wallet UX / Crypto Abstraction
- [Sweatcoin Walking Into Crypto (Spartan Group)](https://medium.com/the-spartan-group/sweatcoin-sweat-economy-walking-into-crypto-b507630b8ab6)
- [Sweatcoin Overview (Cypherock)](https://www.cypherock.com/blogs/what-is-sweatcoin)
- [STEPN Beginners Guide (101 Blockchains)](https://101blockchains.com/stepn-app/)
- [STEPN Apple Pay Integration](https://nftnow.com/news/stepn-becomes-first-blockchain-gaming-app-to-integrate-apple-pay/)
- [STEPN Whitepaper](https://whitepaper.stepn.com/getting-started)
- [Reddit Community Points (Consensys)](https://consensys.io/blog/everything-you-need-to-know-about-reddits-new-blockchain-based-community-points)
- [Axie Infinity 90% Faster Onboarding (Ramp)](https://ramp.network/blog/axie-infinity-success-story)
- [Helium DePIN Case Study (Medium)](https://medium.com/@hilary.h.brown/from-hype-to-fundamentals-helium-depin-4bc466e868d4)
- [Web3 UX in 2026 (DEV Community)](https://dev.to/wildanzr/web3-ux-finally-feels-normal-in-2026-smart-wallets-account-abstraction-and-the-end-of-seed-2okf)
- [Crypto Wallet UX Best Practices](https://www.spacekayak.xyz/blogs/5-ux-design-principles-for-the-best-crypto-wallet-experience)
- [Gas Abstraction 2025 (Reown)](https://reown.com/blog/three-flavors-of-gas-abstraction-users-will-experience-in-2025)
- [Account Abstraction Gas Fees (Thirdweb)](https://blog.thirdweb.com/account-abstraction-gas-fees-paymasters-bundlers-cost-optimization/)
- [Crypto UX Biggest Barrier (CoinDesk)](https://www.coindesk.com/opinion/2025/04/12/crypto-s-biggest-barrier-to-adoption-it-s-not-regulation-it-s-ux)

### iOS vs Android
- [Apple HIG Workouts Pattern](https://developers.apple.com/design/human-interface-guidelines/patterns/workouts/)
- [Apple HIG HealthKit](https://developer.apple.com/design/human-interface-guidelines/healthkit)
- [Apple HIG Designing for iOS](https://developer.apple.com/design/human-interface-guidelines/designing-for-ios)
- [Material 3 Expressive for Wear OS](https://android-developers.googleblog.com/2025/08/introducing-material-3-expressive-for-wear-os.html)
- [Fitness App UI Design Best Practices](https://stormotion.io/blog/fitness-app-ux/)
- [React Native Safe Area Context (Expo)](https://docs.expo.dev/develop/user-interface/safe-areas/)
- [React Native Safe Area Context 2026 Guide](https://copyprogramming.com/howto/react-native-safe-area-context)
- [React Native BackHandler](https://reactnative.dev/docs/backhandler)
- [React Navigation Preventing Going Back](https://reactnavigation.org/docs/preventing-going-back/)
- [Top React Native UI Libraries 2026 (LogRocket)](https://blog.logrocket.com/best-react-native-ui-component-libraries/)
- [NativeWind vs Tamagui vs Gluestack (Kellton)](https://www.kellton.com/kellton-tech-blog/15-best-react-native-ui-libraries-dominating-mobile-app-development)
- [React Native Responsive Design 2025](https://reactnativeexample.com/react-native-responsive-design-tutorial-2025-complete-guide/)
- [SF Pro vs Roboto Comparison](https://zoeji.github.io/SFvsRoboto/)
