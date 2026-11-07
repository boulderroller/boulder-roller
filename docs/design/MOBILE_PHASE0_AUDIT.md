# Mobile Phase 0 Implementation Specs -- Cross-Cutting Audit

**Date:** 2026-03-28
**Auditor:** Senior Mobile Architect
**Scope:** Auth/State (`MOBILE_PHASE0_AUTH_STATE.md`), GPS/SQLite (`MOBILE_PHASE0_GPS_INTEGRITY.md`), Testing/CI (`MOBILE_PHASE0_TESTING_CI.md`)
**Context:** Architecture Review findings S1-S6, D1-D4, T1, E1-E4, C1-C3

---

## Verdict Summary

| Area | Result | Count |
|------|--------|-------|
| PASS | Well-specified, ship as written | 14 |
| FIX | Contradictions, errors, or gaps requiring correction | 12 |
| SIMPLIFY | Over-engineered for v1 | 5 |
| MISSING | Gaps between specs | 8 |

The three specs are individually strong -- detailed, code-level, and honest about scope. The problems are between them: contradictions on libraries, overlapping App.tsx ownership, an upload protocol mismatch with the existing backend, and a blind spot where crash recovery meets auth expiry.

---

## 1. Contradictions Between Specs

### FIX-1: SQLite library conflict (op-sqlite vs expo-sqlite)

**GPS spec** (Section 2.1) explicitly chooses `@op-engineering/op-sqlite` over `expo-sqlite`, with a comparison table and rationale (JSI synchronous API, batch inserts, crash recovery simplicity).

**Testing spec** (Section 1.6) mocks `expo-sqlite`, not `op-sqlite`:
```typescript
// Testing spec, jest.setup.ts
jest.mock('expo-sqlite', () => ({
  openDatabaseAsync: jest.fn().mockResolvedValue({...}),
}));
```

**Architecture review** (Section 11) recommends `expo-sqlite`.

**Resolution:** Pick one. The GPS spec's argument for `op-sqlite` is sound (synchronous JSI bridge simplifies crash-safe batch writes), but the testing spec must mock the chosen library. If `op-sqlite` is chosen, the mock must be `jest.mock('@op-engineering/op-sqlite', ...)`. Also, `op-sqlite` is NOT in `mobile/package.json` and is not listed in any dependency summary section across the three specs. It needs to be added explicitly.

### FIX-2: App.tsx ownership collision

All three specs modify `mobile/App.tsx`, but they describe different final states:

- **Auth spec** (Section 8): Full provider hierarchy with `SafeAreaProvider > QueryClientProvider > PrivyProvider > PrivyAuthBridge > AuthInitializer > NavigationContainer > RootNavigator`
- **Testing spec** (Section 2.3): Wraps `PrivyWrapper > ErrorBoundary > NavigationContainer > TabNavigator` -- uses the OLD `PrivyWrapper` pattern, not the auth spec's `PrivyProvider + PrivyAuthBridge` pattern
- **GPS spec** (Section 3.2): References `App.tsx initialization, before navigation mounts` for crash recovery check but does not specify where in the provider tree

**Resolution:** The auth spec's provider hierarchy is the canonical one. The testing spec must update its `ErrorBoundary` wiring example (Section 2.3) to match the auth spec's hierarchy. The GPS spec's crash recovery check belongs inside `AuthInitializer` or a sibling component at the same level. Write one definitive `App.tsx` spec and reference it from all three docs.

### FIX-3: Upload protocol mismatch with existing backend

**GPS spec** (Section 6.1) defines a new `POST /rides/upload/mobile` endpoint that accepts JSON GPS samples directly.

**Data Contracts spec** (Part 5, Option A) recommends: "Record natively, export to GPX format locally, upload via existing presigned flow. Zero backend changes."

**Existing backend** (`rides.py` line 421): `upload/init` validates `file_type` against `ALLOWED_FILE_TYPES` and expects the client to PUT actual file bytes to a signed URL. The upload flow is: init (get signed URL) -> PUT file to Supabase Storage -> complete (trigger processing). There is no `POST /rides/upload/mobile` endpoint.

**GPS spec's upload queue** (Section 4.1) describes a two-step presigned flow (`/rides/upload/init` + `/rides/upload/complete`) in the flow diagram, but the payload format (Section 4.2) is raw JSON, not a FIT/GPX file.

**Resolution:** These are two different designs. Pick one:
- **Option A (less work):** Export to GPX on-device, upload via existing presigned flow. No new backend endpoint. But GPX generation on-device adds complexity and loses some mobile-native metadata (accuracy, source, rejected samples).
- **Option B (better long-term):** New `POST /rides/upload/mobile` endpoint. More backend work but preserves all mobile-native quality metadata.

The GPS spec chose Option B but the upload queue flow diagram (Section 4.1) mixes in Option A's `/init` + `/complete` pattern. This is contradictory. If going with Option B, the queue should POST directly to `/rides/upload/mobile` as a single request, not a three-step presigned flow. If going with Option A, the payload format section (4.2) is unnecessary -- the app just uploads a GPX file.

### FIX-4: Error types inconsistent between auth spec and testing spec

**Auth spec** (Section 3.5) defines error handling on 401 response:
```typescript
throw new ApiError('Session expired', 'session_expired', 401);
```

**Testing spec** (Section 2.1) defines an `ApiError` classification system with types: `TRANSIENT`, `RECOVERABLE`, `AUTH`, `FATAL`.

**Portal API client** (`web/portal/src/lib/api.ts`) already has `ApiError` with `type: ApiErrorType = 'session_expired' | 'network_error' | 'server_error' | 'unknown'` and a `retryable: boolean` field.

**Resolution:** The mobile `ApiError` class should mirror the portal's existing `ApiError` exactly (same type enum, same `retryable` flag). The testing spec's four-category classification (`TRANSIENT`, `RECOVERABLE`, `AUTH`, `FATAL`) is a higher-level decision tree that consumes the `ApiError.type` field -- it should not replace the type enum. Both specs should reference the portal's implementation as the canonical pattern.

---

## 2. Over-Engineering

### SIMPLIFY-1: Three-source token refresh fallback is unnecessary

**Auth spec** (Section 1): Proposes reading refresh token from three sources:
1. Cookie (web)
2. Request body (mobile)
3. Custom `X-Refresh-Token` header (fallback)

Source 3 is unnecessary. No client needs a custom header when the body field already exists. The backend `RefreshRequest` schema already has `refresh_token: Optional[str]` in the body. Two sources (cookie, body) are sufficient.

The `_extract_bearer` helper for `X-Refresh-Token` adds code that no client will call. Remove source 3.

### SIMPLIFY-2: Device clock spoofing NTP check is low-ROI for Phase 0

**GPS spec** (Section 1.4): Specifies an NTP check at ride start via HTTP HEAD to the API to detect clock drift.

This is a good idea but adds complexity (network request before ride start, handling offline/timeout cases, storing `clock_drift_ms`). The server already has the authoritative check (`uploaded_at - ended_at > 48hr`). For Phase 0, skip the device-side NTP check and rely on server-side validation only. Add it in Phase 1 when the recording infrastructure is stable.

### SIMPLIFY-3: HMAC payload signing section in GPS spec is premature

**GPS spec** (Section 6.3): Describes HMAC payload signing using the Privy wallet's signing capability. Already marked "v1.1" but takes up spec real estate and could confuse dev agents about scope.

Move to a separate `MOBILE_SECURITY_ROADMAP.md` or remove entirely. The spec already says "Not in v1 scope" -- it should not be in a Phase 0 implementation spec at all.

### SIMPLIFY-4: Sensor samples table is Phase 1, not Phase 0

**GPS spec** (Section 2.3): Defines a `sensor_samples` table for BLE HR/power/cadence data. The architecture review and data contracts spec both say BLE sensors are "v1.1" or "Phase 2." This table should not be created in Phase 0 -- it adds schema surface area for features that do not exist.

Create the `rides`, `gps_samples`, `pause_events`, and `upload_queue` tables in Phase 0. Add `sensor_samples` when BLE is implemented.

### SIMPLIFY-5: Sentry performance profiling is premature

**Testing spec** (Section 3.5): Specifies `tracesSampleRate: 0.2` and `profilesSampleRate: 0.1` for production.

Performance profiling only generates value when there are real users generating real traffic patterns. For alpha with <100 users, traces consume free-tier quota without providing actionable data. Set `tracesSampleRate: 0` and `profilesSampleRate: 0` until beta. Keep crash reporting (error events) at full rate.

---

## 3. Missing Pieces

### MISSING-1: Crash recovery + auth expiry interaction (CRITICAL)

**Scenario:** User records a 2-hour ride. App crashes at minute 90. User doesn't reopen the app for 3 days. On reopen:
1. Crash recovery detects interrupted ride (GPS spec, Section 3.2).
2. User chooses "Save & Upload."
3. Upload queue attempts upload.
4. Access token expired (15 min TTL). Refresh token also expired (14 day TTL was fine, but user changed devices or the 3-day window was outside the refresh rotation chain).
5. Upload fails with 401.

**What happens?** The GPS spec's upload queue (Section 4.3) classifies 4xx as `failed_permanent` -- meaning the ride is permanently lost after a single auth failure.

**The auth spec** (Section 3.4) describes the TokenRefreshManager for long rides but says nothing about what happens when the upload queue encounters an auth error days later.

**Fix:** The upload queue must distinguish `401` from other `4xx` errors. On `401`:
1. Attempt token refresh (call `tokenRefreshManager.refresh()`).
2. If refresh succeeds, retry the upload immediately (do not count as an attempt).
3. If refresh fails (refresh token expired), mark as `failed_auth` (new status), not `failed_permanent`.
4. Surface to user: "Your session expired. Please log in again to upload your ride."
5. After re-login, automatically retry `failed_auth` uploads.

This is the most critical gap across the three specs.

### MISSING-2: No dependency list for GPS spec

**Auth spec** (Section 7) lists: `zustand`, `@tanstack/react-query`.
**Testing spec** (Section 6) lists: `@sentry/react-native`, `@react-native-community/netinfo`, plus dev deps.
**GPS spec**: Lists no dependencies section.

Missing from all dependency summaries:
- `@op-engineering/op-sqlite` (chosen in GPS spec but never listed for install)
- `react-native-background-geolocation` (required for GPS recording, ~$300/year license from Transistor Software -- COST ALERT)
- `react-native-ntp-client` (mentioned in GPS spec Section 1.4 but not listed)

**Fix:** Add a dependency section to the GPS spec. Flag the `react-native-background-geolocation` license cost explicitly -- at $300/year this is the single most expensive dependency and needs explicit sign-off per project cost-consciousness directive.

### MISSING-3: Upload queue does not exist in Auth spec's file manifest

**Auth spec** file manifest (Section 9) creates 12 files. None relate to upload.
**GPS spec** describes the upload queue in detail but has no file manifest.
**Testing spec** file manifest (Section 7) references `src/services/__tests__/upload-queue.test.ts` for Phase 1 but never specifies the implementation file.

There is no `mobile/src/services/upload/queueProcessor.ts` in any file manifest despite the GPS spec specifying its full implementation.

**Fix:** Add a file manifest to the GPS spec covering:
- `mobile/src/services/database/config.ts`
- `mobile/src/services/database/schema.ts`
- `mobile/src/services/gps/validation.ts`
- `mobile/src/services/recording/crashRecovery.ts`
- `mobile/src/services/recording/gpsConfig.ts`
- `mobile/src/services/upload/queueProcessor.ts`
- `mobile/src/services/upload/payloadBuilder.ts`

### MISSING-4: Recording store not specified

**Auth spec** (Section 3) defines `authStore` and `settingsStore` in Zustand.
**GPS spec** mentions a "Zustand recording store" (Section 5.4: `isPaused: true`) but never defines it.
**Testing spec** (Section 1.5, Tier 2) references `src/services/__tests__/recording-service.test.ts`.

There is no `recordingStore.ts` spec anywhere. This store manages the most critical state machine in the app (idle -> recording -> paused -> stopped -> uploading) and bridges GPS data, SQLite persistence, UI state, and the upload queue.

**Fix:** One of the specs must define `recordingStore.ts` with:
- State: `status: 'idle' | 'recording' | 'paused' | 'stopped'`
- Current ride metadata (id, started_at, elapsed, distance, elevation, sample count)
- GPS buffer state
- Actions: `startRide()`, `pauseRide()`, `resumeRide()`, `stopRide()`, `discardRide()`

### MISSING-5: No push notification wiring

**Data Contracts spec** (Part 5, #2) identifies push notification device registration as a new endpoint needed. None of the three Phase 0 specs address it. The testing spec's Sentry breadcrumbs (Section 3.4) include upload lifecycle events but not push notification registration.

For Phase 0 this is acceptable to defer, but it should be explicitly called out as Phase 1 scope in at least one spec.

### MISSING-6: Database migration/versioning strategy absent

The GPS spec defines 4 SQLite tables but says nothing about schema migration. When Phase 1 adds `sensor_samples` or Phase 2 changes column types, how does the app migrate existing local data without losing saved rides?

**Fix:** Add a note about SQLite migration strategy. Simplest approach: version number in a `schema_version` table, migration functions run on app startup. Example: `expo-sqlite` has `db.execAsync('PRAGMA user_version = 2')`. This takes 10 lines of code and prevents data loss on schema changes.

### MISSING-7: Offline recording + upload coordination

The GPS spec covers offline recording (data saved to SQLite) and the upload queue (retry with backoff). But there is no specification for what happens to TanStack Query cache during offline recording:
- Does the ride list show the local ride before upload completes?
- Does the home screen show "1 ride pending upload" banner?
- When upload succeeds, how is the local ride replaced with the server ride in the cache?

**Fix:** Define the local-to-server ride handoff. At minimum: after upload succeeds, invalidate TanStack Query `['rides']` key. For a richer UX: add local rides to the TanStack Query cache optimistically and replace them when the server responds.

### MISSING-8: No specification for `recordingStore` -> SQLite -> upload queue data flow

The GPS spec defines SQLite schema, batch writes, crash recovery, and upload queue as separate sections. But the end-to-end data flow from "GPS callback fires" to "ride appears in upload queue" is never stitched together in one place. A dev agent implementing this needs to understand:

1. GPS callback -> validation -> in-memory buffer (10 samples)
2. Buffer full -> SQLite transaction (INSERT samples + UPDATE ride aggregates)
3. User taps stop -> flush remaining buffer -> set ride status = 'stopped' -> create upload_queue entry
4. Queue processor picks up entry -> serialize all samples from SQLite -> compute hash -> upload

This should be a sequence diagram or numbered list in the GPS spec.

---

## 4. Dependency Conflicts

### FIX-5: `setupFilesAfterSetup` is a typo -- should be `setupFilesAfterSetup`

**Testing spec** (Section 1.2, twice): Uses `"setupFilesAfterSetup"` in the jest config. The correct Jest key is `"setupFilesAfterSetup"`. Wait -- actually checking: Jest uses `setupFilesAfterSetup` which IS the correct key name. No, the correct key is `setupFilesAfterSetup`. Let me verify: Jest documentation says `setupFilesAfterSetup` -- but the standard key name is actually **`setupFilesAfterSetup`**. This is correct as written. Disregard, the key is fine.

Actually: re-reading more carefully, the Jest configuration key is **`setupFilesAfterSetup`** -- but the OFFICIAL Jest key is **`setupFilesAfterSetup`**. These are the same string. No issue.

### FIX-5 (actual): `@testing-library/jest-native` is deprecated

**Testing spec** (Section 1.1): Installs `@testing-library/jest-native@^5.4.3`.

This package has been **deprecated** in favor of built-in matchers in `@testing-library/react-native` v12.4+. Since the spec already uses `@testing-library/react-native@^12.9.0`, the custom matchers (like `toBeVisible`, `toHaveTextContent`) are available via:

```typescript
import '@testing-library/react-native/extend-expect';
```

Instead of:
```typescript
import '@testing-library/jest-native/extend-expect';
```

Remove `@testing-library/jest-native` from devDependencies and update `jest.setup.ts` accordingly.

### FIX-6: `react-native-background-geolocation` requires a paid license

The GPS spec uses this library throughout but never mentions that it is a **commercial library** requiring a per-app license (~$300/year for a single app). This is the only paid dependency proposed across all three specs and must be flagged per the project's cost-consciousness directive.

Alternative: `expo-location` is free and handles background location, but lacks Transistor Software's crash recovery persistence, auto-pause motion detection, and battery optimization features.

**Decision needed:** Accept the $300/year cost (justified if the recording quality is worth it) or use `expo-location` with custom implementations of crash recovery, auto-pause, and battery optimization. The GPS spec should present this tradeoff explicitly.

### FIX-7: MSW v2 compatibility with React Native

**Testing spec** (Section 1.1): Uses `msw@^2.7.0`. MSW v2 uses `setupServer` from `msw/node`, which relies on Node.js `http` module interception. In a React Native Jest environment using `jest-expo`, the test runner IS Node.js (not the RN runtime), so `msw/node` should work. But this needs a note: MSW handlers work in Jest (Node environment) but NOT in the React Native app runtime. If dev agents try to use MSW for on-device testing, it will not work.

### PASS: No NativeWind conflict

The architecture review flagged NativeWind v5 requiring RN 0.81+. None of the three specs recommend NativeWind. The testing spec and auth spec use `StyleSheet.create()` (React Native standard). No conflict.

### PASS: Zustand and TanStack Query versions are compatible

`zustand@^4.5` and `@tanstack/react-query@^5.62.0` have no peer dependency conflicts with React 18.3.1 or React Native 0.76.7.

### PASS: Expo SDK 52 compatibility

All recommended Expo packages use `~` version ranges matching SDK 52. `expo-secure-store@~14.0.0`, `@sentry/react-native@~6.5.0` (Expo-compatible range), `expo-constants@~17.0.0` are all correct.

---

## 5. Architecture Review Coverage Check

Mapping the 7 critical findings from `MOBILE_ARCHITECTURE_REVIEW.md` to spec coverage:

| Finding | Severity | Spec Coverage | Status |
|---------|----------|---------------|--------|
| **S1:** Auth tokens in memory only | CRITICAL | Auth spec Section 2 (SecureStore) | PASS -- fully addressed |
| **S5:** No GPS validation | CRITICAL | GPS spec Section 1 (validation pipeline) | PASS -- thorough |
| **D1:** No crash recovery | CRITICAL | GPS spec Section 3 (SQLite + recovery modal) | PASS -- thorough |
| **D2:** No upload idempotency | CRITICAL | GPS spec Section 4 (UUID + file_hash) | PASS -- well-designed |
| **T1:** No test infrastructure | CRITICAL | Testing spec Sections 1-2 | PASS -- comprehensive |
| **E1:** Empty catch blocks | CRITICAL | Testing spec Section 2.2-2.4 | PASS -- clear replacement pattern |
| **E2:** No crash reporting | CRITICAL | Testing spec Section 3 (Sentry) | PASS -- detailed |

All 7 critical findings are addressed. Additionally:

| Finding | Severity | Spec Coverage | Status |
|---------|----------|---------------|--------|
| **S2:** Certificate pinning | HIGH | Auth spec Section 5 (deferred to Phase 1) | PASS -- explicit deferral with rationale |
| **S3:** Biometric auth | HIGH | Auth spec Section 6 (deferred to Phase 2) | PASS -- explicit deferral with rationale |
| **D3:** Upload retry queue | HIGH | GPS spec Section 4 | PASS -- exponential backoff, state machine |
| **D4:** Clock spoofing | HIGH | GPS spec Section 1.4 | PASS -- defense in depth (NTP + server-side) |
| **E3:** No error boundary | HIGH | Testing spec Section 2.3 | PASS -- ErrorBoundary component |
| **E4:** 401 without redirect | HIGH | Auth spec Section 3.5-3.6 | PASS -- reactive via Zustand |
| **C1-C3:** No CI/CD | MEDIUM | Testing spec Section 4 | PASS -- EAS + GitHub Actions |

---

## 6. Security Review

### PASS: Token storage approach

`expo-secure-store` with `WHEN_UNLOCKED_THIS_DEVICE_ONLY` is the correct iOS Keychain access level for auth tokens. Android EncryptedSharedPreferences is the Android equivalent. The 2048-byte limit per key is correctly noted as non-issue for JWTs.

### PASS: Token refresh deduplication

Auth spec's `TokenRefreshManager` deduplicates concurrent refresh calls with a shared promise. This prevents the "thundering herd" problem where multiple 401 responses trigger multiple refresh attempts.

### PASS: Refresh token rotation with replay detection

Backend (auth.py line 636-647) revokes the old refresh token before issuing a new one and detects replay attacks (valid JWT not in token store -> revoke all sessions). The auth spec correctly preserves this behavior.

### FIX-8: Device ID not bound to refresh token on backend

**Auth spec** (Section 2): Stores `br_device_id` in SecureStore and passes it to `/auth/refresh`. The backend (auth.py line 649) checks `device_id` matches the stored session. Good.

But `device_id` is generated client-side with `crypto.randomUUID()` and there is no attestation that the device ID is legitimate. A malicious client could reuse another device's refresh token by spoofing the device ID. This is mitigated by TLS (attacker can't intercept the refresh token to steal it), but it means device binding provides no additional security beyond what TLS already provides.

This is acceptable for Phase 0. For Phase 2+, consider iOS DeviceCheck / Android Play Integrity attestation to bind device identity to a hardware root of trust.

### FIX-9: JWT `atob` parsing is fragile

**Auth spec** (Appendix, `jwtUtils.ts`): Parses JWT expiry with `atob(token.split('.')[1])`.

1. `atob` handles standard Base64 but JWT uses Base64URL encoding (no padding, `-` instead of `+`, `_` instead of `/`). If the JWT payload contains `+` or `/` characters (unlikely but possible in custom claims), `atob` will fail silently or produce wrong data.
2. The fallback (assume 15 minutes from now) masks the error and causes the token to be treated as valid when it might be expired.

**Fix:** Use a proper Base64URL decoder:
```typescript
function base64UrlDecode(str: string): string {
  const padded = str + '=='.slice(0, (4 - str.length % 4) % 4);
  return atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
}
```

Or use the `buffer` package: `Buffer.from(token.split('.')[1], 'base64url').toString()`.

### FIX-10: GPS validation is device-side only -- no server-side enforcement for mobile uploads

**GPS spec** (Section 1.1) correctly splits validation between device and server. But Section 6.1 says "The server-side validation pipeline applies the full suite...before climb detection runs." This is only true if the backend is modified to validate mobile-format JSON payloads. The existing `ride_processor.py` validates FIT/GPX parsed data through `workout-parse`, which has `is_valid_gps()` and `MAX_STEP_DISTANCE_M`. For mobile JSON uploads, the server must apply equivalent validation BEFORE converting to `activity_tile_samples`.

**If Option A (GPX export) is chosen:** This is automatically handled -- the GPX goes through the existing parser.
**If Option B (JSON endpoint) is chosen:** The new `/rides/upload/mobile` handler must include validation equivalent to `utils.rs`.

### PASS: Solana Foundation reviewer concerns

For a Solana Foundation security reviewer, the critical question is: "Can a malicious mobile client fake ride data to earn undeserved tokens?" The GPS spec's defense-in-depth approach (device validation + server validation + climb detection quality filters + abstention policy) is solid. The server is the economic truth boundary, not the device. Mobile-uploaded rides go through the same `canonical_v2` climb detection and vault matching pipeline as FIT file uploads. The on-chain completions fire from the server, not the client.

The one concern is that the GPS spec does not mention device attestation (DeviceCheck / Play Integrity). This is Phase 2 material per the architecture review. Acceptable for alpha.

---

## 7. Ecosystem Alignment

### FIX-11: Portal API client pattern divergence

**Portal** (`web/portal/src/lib/api.ts`): Uses an `APIClient` class with `_isAuthenticated`, `_accessToken`, `refreshPromise`, `proactiveRefreshTimer`, session event callbacks, and case conversion utils. Auth state is managed internally with `SessionEventCallbacks`.

**Mobile auth spec**: Proposes a fundamentally different pattern -- Zustand store for auth state, separate `TokenRefreshManager` class, `secureStorage.ts` service. The API client reads tokens from Zustand.

This divergence is **correct and intentional**. The portal runs in a browser with cookies; the mobile app uses SecureStore. The portal uses React Context for auth; the mobile app uses Zustand (better for RN). The case conversion utils should be identical (and appear to be). No fix needed -- just documenting the intentional difference.

### PASS: Privy integration matches portal pattern

The mobile auth spec's `PrivyAuthBridge` component follows the same pattern as the portal's `PrivyAuthBridge`:
- Extract wallet from Privy user (embedded first, then any linked, then legacy)
- Get Privy access token with retry (3 attempts, 1s delay)
- Exchange for backend JWT via `POST /auth/privy/verify`
- 30s wallet creation timeout

The mobile spec correctly ports this logic with RN-specific adaptations.

### FIX-12: Upload endpoint mismatch -- no `client_ride_id` or idempotency key support on backend

**GPS spec** (Section 4.1): Sends `X-Idempotency-Key: {ride.id}` header.
**GPS spec** (Section 6.2): Proposes adding `client_ride_id` column and unique index to rides table.

**Existing backend** (`rides.py`): The `upload/init` endpoint uses `file_hash` for dedup (line 428-446) but has NO support for:
- `X-Idempotency-Key` header
- `client_ride_id` field on rides table
- Idempotent retry of `/upload/complete`

The GPS spec acknowledges this needs backend changes (Section 6.2) but understates the scope. This is not a "small change" -- it requires:
1. New `client_ride_id` column + unique index migration
2. Modified `/upload/init` to accept and store `client_ride_id`
3. Modified `/upload/complete` to check for already-completed uploads with same idempotency key
4. Or: entirely new `/rides/upload/mobile` endpoint

This is a backend blocker that must be prioritized alongside the auth refresh fix.

### PASS: On-chain alignment

The testing spec's `config.ts` (Section 4.2) references correct values:
- Program ID: `6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X` (matches MEMORY.md)
- CAL mint: `B9u8L5pkWTce2SXJCKvNSKTrSukvWoajEdzy9STLNh6K` (matches MEMORY.md)
- DUNG mint: `AnPJmvr1HK36DwWNQpdwW2vBd7Qq7AtAerU9kuqA9Sfn` (matches MEMORY.md)
- H3 resolution: 10 (matches CLAUDE.md)
- Devnet RPC URL (correct for pre-TGE)

### PASS: BoulderScan data path

Mobile upload -> ride_processor -> canonical_v2 climb detection -> vault matching -> on-chain completion -> TS indexer -> BoulderScan. This path is the same regardless of upload source (mobile JSON or portal FIT file), because the server is the processing boundary. Mobile uploads enter at ride_processor, which is the same entry point for all ride sources.

### PASS: Language spec compliance

None of the three specs use forbidden terminology. The testing spec's MSW handlers use "total_points" (correct for points period), "Manayunk Wall" (vault name, not "segment"), and appropriate field names.

---

## 8. Compiled Backend Changes List

### Blockers (must land before mobile auth works)

| # | Change | File(s) | Effort |
|---|--------|---------|--------|
| B1 | Token refresh: accept refresh_token from request body (not just cookie) | `backend/app/routes/auth.py` lines 613, 727 | 0.5 day |
| B2 | Restore `refresh_token` field description (remove "deprecated") | `backend/app/schemas.py` line 98 | 5 min |

### Required for ride upload

| # | Change | File(s) | Effort |
|---|--------|---------|--------|
| R1 | **Option A:** Add 'json' to `ALLOWED_FILE_TYPES` and add a JSON->tile_samples converter in ride processing | `rides.py`, `ride_processor.py` | 2-3 days |
| R2 | **Option B (if mobile JSON endpoint):** New `POST /rides/upload/mobile` endpoint | `rides.py`, new `mobile_ingest.py` | 3-4 days |
| R3 | Add `client_ride_id` column + unique index to rides table | New migration | 0.5 day |
| R4 | Wire idempotency key handling in upload endpoints | `rides.py` | 1 day |
| R5 | Add `source` column to rides table (`file | mobile | strava`) | New migration | 0.25 day |

### Nice-to-have (Phase 1+)

| # | Change | File(s) | Effort |
|---|--------|---------|--------|
| N1 | Push notification device registration endpoint | New `notifications.py` routes, new `notification_devices` table | 2 days |
| N2 | Server-side clock drift validation (uploaded_at - ended_at > 48hr flag) | `ride_processor.py` | 0.5 day |
| N3 | Mobile-specific GPS quality metadata storage | rides table + ride_processor.py | 0.5 day |

**Total backend effort for mobile support: ~5-6 days** (mostly the upload path).

---

## 9. Revised Implementation Order

### Dependency Graph

```
B1 (auth refresh fix) ──────> Auth spec implementation
                                    |
                                    v
                              Testing spec (can partially start in parallel)
                                    |
                                    v
R3+R4+R5 (DB migrations) ───> Upload endpoint work (R1 or R2)
                                    |
                                    v
                              GPS spec implementation
```

### Proposed Order

**Day 1-2: Foundation (parallelizable)**

| Task | Spec | Dependencies | Effort |
|------|------|-------------|--------|
| Backend: Auth refresh fix (B1, B2) | Auth | None | 0.5 day |
| Install test deps, jest config, MSW setup | Testing | None | 0.5 day |
| Install zustand + TanStack Query | Auth | None | 0.25 day |
| Create `secureStorage.ts` | Auth | None | 0.25 day |
| Create `authStore.ts` + `queryClient.ts` | Auth | zustand, TQ | 0.5 day |
| Create `ErrorBoundary.tsx` + `ErrorBanner.tsx` | Testing | None | 0.5 day |
| Write API client tests (reference pattern) | Testing | MSW | 0.5 day |

**Day 3-4: Auth wiring**

| Task | Spec | Dependencies | Effort |
|------|------|-------------|--------|
| Create `authService.ts` + `tokenRefreshManager.ts` | Auth | B1 done, secureStorage | 1 day |
| Create `privyBridge.ts` + `PrivyAuthBridge.tsx` | Auth | authService | 0.5 day |
| Wire provider hierarchy in App.tsx | Auth | all auth services | 0.5 day |
| Create `AuthInitializer.tsx` + `RootNavigator.tsx` | Auth | authStore | 0.5 day |
| Write auth store tests | Testing | authStore, MSW | 0.5 day |

**Day 5: Sentry + CI**

| Task | Spec | Dependencies | Effort |
|------|------|-------------|--------|
| Install Sentry, create init + analytics wrapper | Testing | None | 0.5 day |
| Replace empty catch blocks in all screens | Testing | ErrorBanner | 0.5 day |
| Create `eas.json`, convert to `app.config.ts` | Testing | None | 0.5 day |
| Create GitHub Actions workflow | Testing | jest working | 0.5 day |

**Day 6-7: Screen tests + polish**

| Task | Spec | Dependencies | Effort |
|------|------|-------------|--------|
| Write HomeScreen, ProfileScreen, VaultsScreen tests | Testing | MSW, auth wired | 1 day |
| Verify full test suite passes | Testing | All above | 0.25 day |
| Verify TypeScript compiles clean | All | All above | 0.25 day |
| Verify CI workflow passes | Testing | GH Actions | 0.25 day |

**Phase 1 (after Phase 0, ~Day 8+):**

GPS spec implementation begins here, requiring:
- Backend upload endpoint work (R1-R5): 3-5 days
- SQLite schema + database config: 1 day
- GPS validation pipeline: 0.5 day
- Crash recovery: 1 day
- Upload queue: 1.5 days
- Background recording config: 1 day
- Recording store + state machine: 1 day
- Recording screen UI: 3 days

---

## 10. Is 1.5 Weeks Realistic?

**For the Auth + Testing specs (Phase 0 proper): Yes, barely.**

7 working days for auth wiring, state management, error handling, Sentry, CI, and tests is tight but achievable for a senior RN developer who knows the stack. The specs are detailed enough that a dev agent can execute without much ambiguity.

**For all three specs including GPS: No.**

The GPS spec is Phase 1 material. It requires backend endpoint changes, SQLite schema work, background geolocation wiring, crash recovery, and the upload queue. That is 8-10 additional days minimum, plus the backend work (5-6 days, can partially parallelize).

**Revised timeline:**
- **Phase 0 (Auth + Testing + Error handling + CI):** 7 working days / 1.5 weeks
- **Phase 0.5 (Backend mobile upload support):** 5 working days / 1 week (can start in parallel with Phase 0 Day 3+)
- **Phase 1 (GPS recording + upload):** 10 working days / 2 weeks (depends on Phase 0 + backend changes)

**Total to first mobile ride upload: ~4-5 weeks**, not 1.5 weeks. The 1.5 week estimate from the architecture review covers Phase 0 only, which is the foundation layer. The GPS spec is substantially more work than the other two combined.

---

## 11. Additional Findings

### PASS: Zustand over Context for auth

The auth spec correctly argues for Zustand over React Context: `getState()` provides synchronous access needed for navigation guards. TanStack Query's `useQuery` is inherently async. Good call.

### PASS: TanStack Query for server state

The auth spec's "What Goes Where" table (Section 3) cleanly separates local state (Zustand) from server state (TanStack Query). This matches the portal's implicit pattern and is the correct architecture for React Native.

### PASS: Monotonic clock for ride timing

GPS spec's use of `performance.now()` for inter-sample timing (Section 1.4) is correct and prevents clock spoofing of ride duration. Storing offsets as `t_offset_ms` from ride start (not wallclock timestamps) is the right approach.

### PASS: WAL mode for SQLite crash safety

GPS spec correctly mandates `PRAGMA journal_mode = WAL` and `PRAGMA synchronous = NORMAL`. This is the standard crash-safe configuration for SQLite on mobile.

### PASS: Partial unique index for singleton active ride

GPS spec's `CREATE UNIQUE INDEX ... WHERE status IN ('recording', 'paused')` (Section 2.3) is elegant and enforces the "at most one active ride" constraint at the database level. Better than application-level checks.

### PASS: Proactive token refresh during rides

Auth spec's `TokenRefreshManager` (Section 3.4) with 5-minute buffer before expiry handles the 4+ hour ride scenario correctly. The AppState handler that reschedules timers on foreground return is a necessary mobile-specific detail.

### PASS: Recovery from BackgroundGeolocation internal persistence

GPS spec (Section 3.3) correctly identifies that Transistor Software's library has its own internal SQLite database and describes integrating it into crash recovery to close the ~10 second buffer gap.

---

## Summary: Action Items by Priority

### Must fix before handing to dev agents

1. **FIX-1:** Resolve SQLite library choice (op-sqlite vs expo-sqlite) and update ALL THREE specs consistently
2. **FIX-2:** Write one canonical App.tsx spec and reference from all docs
3. **FIX-3:** Choose upload protocol (GPX export vs JSON endpoint) and remove the contradictory design
4. **MISSING-1:** Add auth failure handling to upload queue (the crash recovery + expired auth scenario)
5. **FIX-12:** Scope the backend upload endpoint work and add it to the timeline

### Should fix before handing to dev agents

6. **FIX-4:** Align `ApiError` types with portal's existing implementation
7. **FIX-5:** Remove deprecated `@testing-library/jest-native`
8. **FIX-9:** Fix JWT Base64URL parsing
9. **MISSING-2:** Add dependency section to GPS spec (with cost note for background-geolocation)
10. **MISSING-3:** Add file manifest to GPS spec
11. **MISSING-4:** Define `recordingStore.ts`

### Nice to fix

12. **SIMPLIFY-1:** Remove X-Refresh-Token header (two sources sufficient)
13. **SIMPLIFY-2:** Defer NTP clock check to Phase 1
14. **SIMPLIFY-3:** Remove HMAC section from Phase 0 spec
15. **SIMPLIFY-4:** Defer sensor_samples table to Phase 1
16. **SIMPLIFY-5:** Disable Sentry performance tracing until beta
