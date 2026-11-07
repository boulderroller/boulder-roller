# Mobile Research Audit — 2026-04-16

Compiled from 9 research agents. Mobile-focused gap analysis with cross-stack
context where it informs mobile build decisions. All checked against
`docs/PROTOCOL_TRUTHS.md`.

---

## Part 1: Code-Level Bugs (from deep-dive agents)

### Tier 1 — Corrupts Ride Data

| ID | Bug | Files | Root Cause |
|----|-----|-------|------------|
| A | **Mixed clock domains** — `performance.now()` freezes on iOS lock, `Date.now()` doesn't. After screen lock, `tOffsetMs` jumps, UI timer disagrees with sample timestamps. | `gpsRecording.ts:142,297` | Single fix: pick one clock domain for all time tracking |
| B | **Auto-pause same bug** — pause duration from frozen monotonic clock subtracted from wallclock samples. All subsequent `tOffsetMs` inflated after iOS suspension during auto-pause. | `gpsRecording.ts:179` | Same root cause as A |
| C | **GPX pause splitting fails** — `Set.has()` exact integer match between `Date.now()`-derived and `location.timestamp`-derived offsets. Never matches. Pauses don't split GPX tracks. | `gpxExporter.ts:73` | Use range/epsilon match, or store pause markers separately |
| D | **GPX regenerated on retry, hash drifts** — re-export on retry can change hash via floating-point formatting. Server sees new upload, orphaning the first. | `uploadQueue.ts:80`, `gpxExporter.ts:45` | Cache GPX output on first export |

### Tier 2 — Data Loss / Stuck State

| ID | Bug | Files | Fix Shape |
|----|-----|-------|-----------|
| E | **Non-atomic ride+upload status** — two SQLite writes, no transaction. App kill between them = ride stuck in limbo. | `uploadQueue.ts:210-217` | Wrap in SQLite transaction |
| F | **Stale auth token on Step 3** — token captured once, reused across init+PUT+complete. Long upload = expired token on /complete → orphaned upload. | `uploadQueue.ts:101` | Re-read token before Step 3 |
| G | **Crash recovery loses 9s of GPS** — buffer=10 samples at 1Hz. Force-quit loses unflushed buffer. | `gpsRecording.ts:42` | Reduce buffer or flush on AppState change |
| H | **SecureStore failure → force logout** — storage write fails → entire refresh rejected → user logged out even though tokens are valid in memory. | `secureStorage.ts:48-55` | Catch storage errors, keep in-memory tokens |

### Tier 3 — Cleanup / Resource Leaks

| ID | Issue | Files |
|----|-------|-------|
| I | Logout doesn't stop upload queue (battery drain, SQLite held) | `authService.ts:137-150` |
| J | Logout doesn't clear SQLite/rides/cache (user data leak on device switch) | `authService.ts:137-150` |
| K | GPX not deleted on permanent failure (disk leak) | `uploadQueue.ts:255` |
| L | No double-start guard (false crash recovery on next launch) | `gpsRecording.ts:338` |
| M | Privy/backend desync on sync failure (user stuck in loading) | `PrivyAuthBridge.tsx:117` |

### Tier 4 — Noted

- movingTimeMs overcounts after iOS background batching
- `isProcessing` deadlock if unhandled rejection escapes catch
- PostRideScreen polls indefinitely with no backoff
- `clearTokens` omits `SECURE_OPTIONS` on delete (Android edge case)
- Mock-location samples accepted (intentional, documented)
- Crash recovery resume disabled in v1
- `discardRecording` skips state machine transitions
- No deep linking (fine for alpha)
- Cold start flicker handled correctly (positive)
- Token refresh dedup works correctly (positive)

---

## Part 2: Protocol vs Mobile Capability Gap Matrix

Source: `docs/PROTOCOL_TRUTHS.md` checked against every mobile source file.

| # | Protocol Obligation | Status | Note |
|---|---------------------|--------|------|
| 1 | Power/sensor data for TSS | **NO** | GPS only. No BLE. TSS requires power. |
| 2 | Ride attestation (RideAttestation PDA) | **NO** | `preliminaryHash.ts` is a stub returning null. |
| 3 | On-chain reads (balances, stake, leaderboard) | **DEFERRED** | Intentionally absent. Protocol agent still shaping V4-A/V4-B. Building stubs now would lock wrong shape. |
| 4 | On-chain writes (stake, harvest, unstake) | **DEFERRED** | Same — backend-mediated per P13, but endpoints don't exist yet because protocol shape is in flight. |
| 5 | CAL/DUNG balance display | **DEFERRED** | Depends on on-chain read layer. |
| 6 | Vault discovery post-climb | **PARTIAL** | VaultsScreen lists vaults. Post-ride shows zero vault matches. |
| 7 | Post-ride economics (CAL, tributes, BeetleCard) | **PARTIAL** | Shows `calEarned` if processing completes. No tributes, climbs, BeetleCard, leaderboard notifications. |
| 8 | BeetleCard / Rider Soul UI | **DEFERRED** | Depends on V4-B ontology (RiderSoul PDA). Protocol shape in flight. |
| 9 | Staking UX | **DEFERRED** | Depends on finalized staking instructions. Protocol shape in flight. |
| 10 | Leaderboard per climb | **DEFERRED** | Depends on V4-B Climb/Vault split for correct data model. |
| 11 | Local Legend display | **DEFERRED** | Depends on finalized LocalLegend PDA shape. |
| 12 | Settlement week / epoch awareness | **DEFERRED** | Depends on settlement finalization flow being confirmed on-chain. |
| 13 | Record Board earnings (55%) | **DEFERRED** | Depends on V4-B leaderboard shape. |
| 14 | Offline-first completeness | **YES** | GPS → SQLite → GPX → upload queue → backoff → crash recovery. Works. |
| 15 | FIT file support (import) | **NO** | Mobile exports GPX only. Backend parses FIT. |
| 16 | GPS validation alignment | **PARTIAL** | Validation exists but constants not reconciled with backend `workout-parse`. |
| 17 | VerifyChip (chain truth verification) | **DEFERRED** | Designed in crosswalk, blocked on V4-A gate + on-chain read layer. |
| 18 | Vault creation | **DEFERRED** | Depends on finalized create_vault instruction shape. |
| 19 | Climb-first ontology in code | **PARTIAL** | V4-A addresses correct. Code uses pre-V4-B naming (`VaultSummary`). |

**Summary:** 3 NO (sensor data, ride attestation, FIT support), 9 DEFERRED
(intentionally waiting on protocol agent's V4-A/V4-B work — do not stub),
4 PARTIAL, 1 YES, 2 N/A.

---

## Part 3: Missing Subsystems (XL Blind Spots)

### 3A. BLE Sensor Pairing — XL

**Why it matters:** TSS is the root of CAL earning. Without power data, backend
must estimate from GPS speed/elevation — significantly less accurate.

**Recommended library:** `react-native-ble-plx` (de facto Expo standard, has
config plugin). ANT+ is a dead end (no iOS, no RN bindings).

**GATT profiles:**
| Service | UUID | Data Rate |
|---------|------|-----------|
| Cycling Power | `0x1818` | ~4Hz |
| Heart Rate | `0x180D` | ~1Hz |
| Cycling Speed & Cadence | `0x1816` | ~1Hz |

**Architecture:** BLE sensor manager runs parallel to GPS. Buffer latest sensor
readings, snapshot when each 1Hz GPS sample arrives. Merge into extended SQLite
schema (`power_w`, `heart_rate_bpm`, `cadence_rpm`). Export as FIT when sensors
present, GPX fallback for GPS-only.

**FIT recording:** Viable and recommended. Backend already parses FIT. Libraries:
`@garmin/fitsdk` (official) or `@markw65/fit-file-writer` (lightweight TS).

**iOS requirements:** Add `NSBluetoothAlwaysUsageDescription` + `bluetooth-central`
to `UIBackgroundModes`. Android permissions already declared.

**Size:** ~3-4 weeks. BLE service + GATT parsing (1wk), pairing UI (1wk),
recording integration + SQLite schema (3-4d), FIT export (3-4d), device testing (1wk).

**Key gotcha:** Cycling Power Measurement has variable-length flags field in the
binary payload. Expo SDK 52 may need community fork of ble-plx.

### 3B. On-Chain / Backend State Sync — LARGE (DEFERRED)

No mechanism to learn about server-side events. No WebSocket, SSE, polling for
wallet state, or push notifications. When CAL is earned, user only sees it if
they're on PostRideScreen. **Intentionally deferred** — the protocol agent is
still shaping V4-A/V4-B. The sync layer's shape depends on which accounts exist,
what the read model looks like, and whether we use indexer projections or direct
RPC. Do not build stubs until protocol work lands.

### 3C. Push Notification Infrastructure — LARGE

Zero push notification code. No `expo-notifications`, no APNs/FCM token
registration, no device token storage endpoint. No alerts for: ride processed,
CAL earned, settlement payout, leaderboard changes. `UIBackgroundModes` only
declares `location`, not `remote-notification`.

### 3D. GPX Extension Gap — MEDIUM

Even after BLE sensors are added, the GPX exporter has no code path to embed
sensor data in GPX extensions (`<power>`, `<hr>`, `<cad>`). The backend parser
(`workout-parse`) explicitly reads these. Separate gap from BLE pairing itself.
Resolved by switching to FIT export.

### 3E. Zustand State Not Persisted — MEDIUM

No `persist` middleware on any store. All non-SQLite state vanishes on app kill.
Last viewed vault, UI preferences, cached data — gone on every restart.

### 3F. No Certificate Pinning / Ride Tampering Protection — MEDIUM

Default TLS only. No cert pinning. GPS spoofing: Android mock locations tagged
but not rejected; iOS mock detection tracked for Phase B. `preliminary_ride_hash`
stubbed to null. Motivated attacker could fabricate rides and earn CAL.

### 3G. CI Checks Minimal — MEDIUM

TypeScript + lint + Jest only. No EAS build, no iOS/Android compile check, no
E2E tests. Test:code ratio ~32%, all unit-level. No integration test for the
record→stop→export→upload pipeline.

---

## Part 4: Fixes Already Applied This Session

These changes are in the working tree (not committed):

| Change | File | Status |
|--------|------|--------|
| Upload queue 403 → retryable | `uploadQueue.ts` | Done |
| `auth_rejected` in ApiErrorType | `api.ts`, `errors.ts` | Done |
| Buffer polyfill for Solana | `index.js`, `package.json` | Done |
| V4-A Solana addresses | `config.ts` | Done |
| console.warn gated behind `__DEV__` | `App.tsx`, `PrivyAuthBridge.tsx` | Done |
| NetInfo check in processQueue | `uploadQueue.ts` | Done |

## Part 5: Sentry Status

`@sentry/react-native` Xcode libc++ issue fixed in 6.10.0. Current version is
8.7.0. Expo SDK 52 confirmed compatible. `sentry-expo` deprecated — use
`@sentry/react-native` directly with `/expo` config plugin. Requires dev build
(already true). **Ready to un-stub.**

---

## Prioritized Action Plan (proposed, not started)

### Unblocked now (no protocol dependency)
1. **Clock domain fix** (A+B+C) — single root cause, ~1 day
2. **Upload atomicity fixes** (D+E+F) — ~1-2 days
3. **BLE sensor service** (3A) — ~3-4 weeks, enables real TSS
4. **FIT export** (3D) — ~3-4 days, unlocks power/HR in uploads
5. **Sentry un-stubbing** — blocker resolved, ready to integrate
6. **Push notification infrastructure** — independent of protocol shape
7. **Zustand persist middleware** — independent
8. **CI hardening** (EAS build, coverage thresholds)

### Blocked on protocol agent (do not stub)
9. On-chain reads (chain.ts, VerifyChip) — needs V4-A gate green + finalized IDL
10. Staking UX — needs finalized staking instructions
11. BeetleCard/Rider Soul — needs V4-B ontology (RiderSoul PDA)
12. Post-ride vault/tribute visibility — needs V4-B Climb/Vault split
13. CAL/DUNG balance display — needs on-chain read layer
14. Settlement week UI — needs settlement finalization confirmed
15. State sync layer (WebSocket/SSE) — shape depends on read model

### Track for beta (independent of protocol)
16. Cert pinning / anti-tamper hardening
17. E2E test pipeline (Detox/Maestro)
18. Deep links / universal links

---

## Part 6: Cross-Stack Context (mobile-informing takeaways only)

Findings from reading backend, portal, and Anchor code — scoped to what
affects mobile build decisions. Full audit data is in agent session history,
not reproduced here.

1. **Sensor pairing is more urgent than "nice to have"** — backend currently
   earns phantom CAL from GPS-only rides (estimated TSS). TRUTHS requires
   power data. Until mobile ships sensor pairing, every mobile ride feeds
   a broken earning path.

2. **Don't build tribute display against current backend values** — the CAL
   tribute formula has two competing implementations in the backend, neither
   matches TRUTHS. Wait for the protocol agent to fix before wiring mobile
   tribute UI.

3. **Anchor program is economically clean** — every TRUTHS parameter matches
   on-chain. When we build the mobile chain read layer (post-wdvr.6), the
   on-chain data is trustworthy. No adapter hacks needed.

4. **Don't copy portal config for addresses** — portal `.env.production` still
   has stale V3 addresses. Mobile is already fixed (this session). Always use
   `protocol/anchor/addresses.devnet.json` as source of truth.

5. **FIT export unlocks backend fidelity** — backend's `workout-parse` reads
   power/HR/cadence from FIT natively. GPX extensions exist but the mobile
   GPX exporter doesn't write them. Switching to FIT when sensors are
   connected is the clean path.

6. **Reprocess endpoint has no idempotency guard** — if a mobile ride gets
   reprocessed server-side, CAL double-mints. Not a mobile bug to fix, but
   mobile should not trigger reprocess without awareness of this risk.
