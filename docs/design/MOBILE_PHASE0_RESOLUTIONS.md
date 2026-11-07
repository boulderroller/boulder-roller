# Mobile Phase 0: Cross-Spec Resolution Document

**Date:** 2026-03-28
**Author:** Senior Architect
**Scope:** Resolves all 12 FIX, 5 SIMPLIFY, and 8 MISSING items from `MOBILE_PHASE0_AUDIT.md`
**Authority:** This document is the final word. Specs must be updated to match.

---

## Table of Contents

1. [FIX Resolutions (1-12)](#fix-resolutions)
2. [SIMPLIFY Resolutions (1-5)](#simplify-resolutions)
3. [MISSING Resolutions (1-8)](#missing-resolutions)
4. [Ecosystem Alignment](#ecosystem-alignment)
5. [Final App.tsx Provider Hierarchy](#final-apptsx-provider-hierarchy)
6. [Final Upload Protocol](#final-upload-protocol)
7. [recordingStore State Machine](#recordingstore-state-machine)
8. [Backend Changes (Prioritized)](#backend-changes-prioritized)
9. [Dependency Graph](#dependency-graph)
10. [Revised Timeline](#revised-timeline)
11. [Revised Cost](#revised-cost)

---

## FIX Resolutions

### FIX-1: SQLite Library Choice

**DECISION: `expo-sqlite`**

**Rationale:**

1. **The architecture review recommends `expo-sqlite`.** The GPS spec's argument for `op-sqlite` (synchronous JSI bridge, 2-5x faster batch inserts) is valid in isolation, but the performance delta is irrelevant for our workload. At 1Hz GPS sampling with 10-sample batch flushes, we write 10 rows every 10 seconds. Even the async bridge handles this in under 5ms. We are not write-bound.

2. **`expo-sqlite` has first-party Expo SDK 52 support.** It is tested and released as part of the SDK. `op-sqlite` is a community library that requires `expo prebuild` and native module compilation. Adding native dependencies increases build times, increases crash surface area from native code, and locks us out of Expo Go for development.

3. **WAL mode is supported in both.** Both libraries support `PRAGMA journal_mode = WAL` and `PRAGMA synchronous = NORMAL`. Crash safety is a WAL property, not a library property.

4. **`expo-sqlite` in SDK 52 has the JSI bridge.** As of Expo SDK 51+, `expo-sqlite` uses a C++ JSI implementation (`expo-sqlite/next`, now the default). The performance gap the GPS spec cited is from the old async bridge, which no longer applies.

5. **Testing alignment.** The testing spec already mocks `expo-sqlite`. Using `op-sqlite` means rewriting all mocks for a library that provides no material benefit.

**Specs to update:**
- GPS spec Section 2.1: Replace `op-sqlite` choice with `expo-sqlite`. Remove the comparison table or update it to show SDK 52's JSI bridge parity.
- GPS spec Section 2.2: Change `OPSQLiteDatabase` types to `expo-sqlite` equivalents. The synchronous call surface is available via `db.execSync()` or `db.runSync()`.
- Testing spec Section 1.6: No change needed (already mocks `expo-sqlite`).
- All import paths: `@op-engineering/op-sqlite` becomes `expo-sqlite`.

**Cost impact:** $0 (expo-sqlite is free, already in SDK).

---

### FIX-2: App.tsx Provider Hierarchy

**DECISION: The auth spec's hierarchy is canonical, with two additions: ErrorBoundary (from testing spec) and crash recovery check (from GPS spec).**

See [Final App.tsx Provider Hierarchy](#final-apptsx-provider-hierarchy) below for the definitive nesting order.

**Specs to update:**
- Testing spec Section 2.3: Replace the `PrivyWrapper > ErrorBoundary > NavigationContainer > TabNavigator` example with a reference to this document's canonical hierarchy.
- GPS spec Section 3.2: Specify that crash recovery runs inside `AuthInitializer`, after SecureStore hydration but before navigation mounts.
- Auth spec Section 8: Add `ErrorBoundary` as a wrapper around `NavigationContainer`.

---

### FIX-3: Upload Protocol

**DECISION: GPX export on device, upload via existing presigned flow. Zero new backend endpoints for Phase 0/1.**

**Rationale:**

1. **The backend already supports GPX.** `ALLOWED_FILE_TYPES = {"fit", "gpx", "tcx"}` (rides.py line 399). The Rust parser handles GPX files natively via `quick-xml`. The entire ride processing pipeline (metrics, tiles, climb detection, vault matching, on-chain completions) runs identically regardless of whether the input is FIT or GPX.

2. **The presigned upload flow already exists and works.** `upload/init` then PUT to signed URL then `upload/complete` is production-ready. The mobile app calls the same three endpoints the portal would call. No new backend code.

3. **JSON endpoint (GPS spec Section 6.1) is premature.** A new `POST /rides/upload/mobile` endpoint requires: a new ingest path in ride_processor.py to convert JSON samples to the internal `ParsedRide` format, new server-side GPS validation equivalent to `utils.rs`, new tests, and deployment. This is 3-5 days of backend work that provides no user-facing benefit over GPX export.

4. **GPX preserves all data we need.** The mobile GPS sample format (lat, lon, altitude, time, accuracy) maps directly to GPX `<trkpt>` elements. We lose `accuracy_m`, `vert_accuracy_m`, `bearing_deg`, and `source` fields -- these are device-side quality metadata that the server does not currently use for any processing decision. The GPS spec's `quality` metadata (rejected sample counts, median accuracy) can be sent as a query parameter or header on the `/upload/complete` call if needed later.

5. **Sensor data (HR, power, cadence) is Phase 2.** The GPS spec's `sensor_samples` array is BLE data that does not exist in Phase 0. GPX `<extensions>` can carry HR/power/cadence when BLE is added.

6. **The upload queue still works.** The queue serializes the GPX file (SQLite data converted to GPX), hashes it, and uploads via the presigned flow. The idempotency key is the `file_hash` (SHA-256 of the GPX bytes), which the backend already uses for dedup (`find_ride_by_hash`).

**What changes on the mobile side:**
- After ride stop, convert SQLite GPS samples to a GPX file in the app's document directory.
- Compute SHA-256 of the GPX file bytes.
- Upload via `POST /rides/upload/init` (file_type: "gpx", file_hash, file_size) then PUT then `POST /rides/upload/complete`.
- The upload queue manages retry with the same GPX file.

**What the GPX file contains:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="BoulderRoller Mobile 0.1.0">
  <metadata>
    <time>2026-03-28T14:30:00Z</time>
  </metadata>
  <trk>
    <name>Morning Ride</name>
    <type>Ride</type>
    <trkseg>
      <trkpt lat="39.9526" lon="-75.1652">
        <ele>15.3</ele>
        <time>2026-03-28T14:30:00Z</time>
      </trkpt>
      <!-- one per accepted GPS sample -->
    </trkseg>
  </trk>
</gpx>
```

**Backend changes needed: ZERO for the upload path.** The only backend blocker is the auth refresh fix (token from body, not just cookie).

**Specs to update:**
- GPS spec Section 4.2: Remove the `RideUploadPayload` JSON schema. Replace with GPX generation specification.
- GPS spec Section 6.1: Remove `POST /rides/upload/mobile` endpoint spec. Replace with a note that the app uses the existing presigned flow with GPX files.
- GPS spec Section 4.1: Simplify the upload queue to: serialize GPX, hash, init, PUT, complete.
- Data Contracts Part 5 Option A: Mark as CHOSEN. Remove Option B.

**Phase 2 reconsideration:** When BLE sensors ship and we need to upload HR/power/cadence alongside GPS, we can revisit a JSON endpoint. By then the recording infrastructure will be stable and the cost is justified.

---

### FIX-4: Crash Recovery + Expired Auth (CRITICAL)

**DECISION: Add `failed_auth` status to upload queue. Auth failure is never permanent.**

**The exact flow:**

```
1. Ride recorded. App crashes at minute 90.
2. User reopens app 3 days later.
3. Crash recovery detects interrupted ride (SQLite query: status IN ('recording', 'paused')).
4. User taps "Save & Upload."
5. Ride is finalized: status -> 'stopped', ended_at set, upload_queue entry created.
6. Upload queue processor picks up the entry.
7. Processor calls POST /rides/upload/init with Authorization header.
8. Server returns 401 (access token expired).

9. Queue processor intercepts the 401 BEFORE classifying the error:
   a. Call tokenRefreshManager.refresh().
   b. If refresh succeeds (refresh token still valid within 14-day window):
      - Update SecureStore + Zustand with new tokens.
      - Retry the upload request immediately. Do NOT increment attempt_count.
      - Continue normal upload flow.
   c. If refresh FAILS (refresh token expired or revoked):
      - Set upload_queue.status = 'failed_auth' (NEW STATUS).
      - Do NOT increment attempt_count.
      - Do NOT mark as failed_permanent.
      - Store last_error = 'Session expired. Please log in to upload your ride.'

10. On app foreground, if any upload_queue entries have status = 'failed_auth':
    - Show persistent banner: "1 ride waiting to upload. Log in to continue."
    - Banner tap opens login screen.

11. After successful re-login:
    - AuthInitializer queries: SELECT * FROM upload_queue WHERE status = 'failed_auth'
    - Reset each to status = 'pending', attempt_count unchanged.
    - Queue processor resumes normally.

12. The ride data is NEVER deleted due to auth failure.
    It sits in SQLite indefinitely until either:
    - User logs in and upload succeeds.
    - User manually deletes the ride.
    - User exports as GPX file to share/import elsewhere (Phase 2 feature).
```

**Upload queue status additions:**

```
EXISTING:  pending | uploading | uploaded | failed_retryable | failed_permanent
NEW:       failed_auth
```

`failed_auth` is NOT a terminal state. It can only transition to `pending` (after re-login).

**Error classification in queue processor:**

```typescript
// In the upload attempt error handler:
if (response.status === 401) {
  const refreshed = await tokenRefreshManager.refresh();
  if (refreshed) {
    // Retry immediately, don't count as attempt
    return await retryUpload(entry);
  }
  // Refresh failed - auth is broken, wait for re-login
  await updateQueueEntry(entry.id, {
    status: 'failed_auth',
    last_error: 'Session expired. Log in to upload.',
  });
  return; // Don't process more queue items
}

if (response.status === 409) {
  // Duplicate - treat as success
  await markUploaded(entry, response.existing_ride_id);
  return;
}

if (response.status >= 400 && response.status < 500) {
  // Client error (bad data, validation failure) - permanent
  await markFailedPermanent(entry, response.detail);
  return;
}

// 5xx or network error - retryable
await markFailedRetryable(entry);
```

**Specs to update:**
- GPS spec Section 4.3: Add `failed_auth` status to the state machine diagram. Add the 401-specific handling described above.
- Auth spec Section 3.4: Add a paragraph about upload queue interaction: "When the upload queue encounters a 401, it attempts a token refresh before classifying the error."
- GPS spec Section 3.4 (recovery modal): Add note that if the user is not logged in when they tap "Save & Upload," the upload will queue as `failed_auth` and surface a login prompt.

---

### FIX-5: Backend Idempotency + Deprecated jest-native

The audit document has two items labeled FIX-5. Resolving both.

#### FIX-5a: `@testing-library/jest-native` is deprecated

**DECISION: Remove it. Use built-in matchers from `@testing-library/react-native` v12.4+.**

The testing spec uses `@testing-library/react-native@^12.9.0`, which includes all matchers (`toBeVisible`, `toHaveTextContent`, etc.) natively via:

```typescript
import '@testing-library/react-native/extend-expect';
```

**Specs to update:**
- Testing spec Section 1.1: Remove `@testing-library/jest-native@^5.4.3` from devDependencies.
- Testing spec Section 1.2 and 1.3: Change `setupFilesAfterSetup` entries from `@testing-library/jest-native/extend-expect` to `@testing-library/react-native/extend-expect`.
- Testing spec Section 6: Remove from dependency summary.

#### FIX-5b: Backend idempotency for mobile uploads

**DECISION: No new `client_ride_id` column needed. The existing `file_hash` dedup is sufficient.**

**Rationale:**

1. The backend already deduplicates via `find_ride_by_hash(user_id, file_hash)` on the `upload/init` endpoint (rides.py line 428-446). If the same user uploads the same file twice, the second call returns 409 with the existing ride ID.

2. With the GPX upload protocol (FIX-3 decision), the mobile app computes `SHA-256(gpx_bytes)` before uploading. The same ride will always produce the same GPX (deterministic serialization from SQLite data). Therefore, `file_hash` is a perfect idempotency key.

3. A `client_ride_id` would be needed if we used the JSON upload protocol (where the payload might vary due to timing differences). Since we chose GPX, the file content IS the identity.

4. The upload queue on the device uses `file_hash` as its dedup key. If the queue retries an upload and gets 409, it marks the entry as `uploaded` with the existing server ride ID.

5. The `upload/complete` endpoint already handles the "already processing" case (returns 409 if status is not 'uploading').

**Backend changes needed: NONE for idempotency.** The existing `file_hash` dedup covers all mobile retry scenarios.

**Specs to update:**
- GPS spec Section 4.1: Remove `X-Idempotency-Key` header from the upload flow. The `file_hash` in the init request body is the idempotency mechanism.
- GPS spec Section 6.2: Remove the `client_ride_id` column migration. Remove the `source` column migration (useful but not needed for Phase 0; defer to Phase 1).
- Audit document Section 8 (Backend Changes): Remove R3 (client_ride_id) and R4 (idempotency key wiring).

---

### FIX-6: Background Geolocation License ($300/yr)

**DECISION: Use `expo-location` for Phase 0/1. Do NOT pay $300/yr yet.**

**Rationale:**

1. **Cost-consciousness is a core project value.** The staging droplet is $6/mo, Supabase is free tier, Vercel is free tier. A $300/yr library license for a pre-alpha app with fewer than 10 users is not justified until we validate that people actually use the recording feature.

2. **`expo-location` covers the core requirement.** It supports:
   - Foreground location with `watchPositionAsync` (1Hz, high accuracy).
   - Background location with `startLocationUpdatesAsync` + `TaskManager`.
   - iOS `UIBackgroundModes: ["location"]` support.
   - Android foreground service via `TaskManager`.

3. **What we lose vs `react-native-background-geolocation`:**
   - No internal SQLite persistence (Transistor's library persists in its own DB). We already persist to our own SQLite, so this is redundant.
   - No motion detection auto-pause (Transistor uses accelerometer + GPS fusion). We implement our own: if speed < 0.5 m/s for 10 consecutive samples, pause. This is 20 lines of code.
   - No `preventSuspend` iOS trick (silent audio). iOS 16+ with `UIBackgroundModes: ["location"]` plus `TaskManager` keeps the app alive during active location tracking. For extreme background cases, we accept the degradation.
   - No crash recovery from library's internal buffer. Our own SQLite batch writes every 10 seconds cover this; the 10-second gap is acceptable.

4. **Migration path.** If alpha testing reveals that `expo-location` drops too many samples in background on iOS, we purchase the Transistor license and swap. The GPS validation pipeline, SQLite schema, upload queue, and crash recovery are all library-agnostic. The swap affects only `gpsConfig.ts` and the location callback wiring -- roughly 200 lines of code.

5. **The $300/yr license becomes justified at 100+ active recording users.** At that point, the battery optimization, motion detection, and crash recovery features pay for themselves in reduced support burden.

**Specs to update:**
- GPS spec: Replace all `react-native-background-geolocation` references with `expo-location` equivalents. Specifically:
  - Section 1.3: Remove Transistor library filter table. Replace with `expo-location` accuracy/interval config.
  - Section 3.3: Remove Transistor internal persistence recovery. Our SQLite is the sole persistence layer.
  - Section 5.1-5.4: Rewrite background recording section using `expo-location` TaskManager + foreground service patterns.
  - Section 5.2: Replace `CYCLING_GPS_CONFIG` with `expo-location` equivalents (`LocationAccuracy.BestForNavigation`, `timeInterval: 1000`, `distanceInterval: 5`).
- GPS spec: Add a "Phase 2: Commercial GPS Library" section noting that Transistor Software license should be evaluated if background recording quality is insufficient.

**Cost impact:** -$300/yr.

---

### FIX-7: MSW v2 + React Native Compatibility

**DECISION: Keep MSW v2. Add a documentation note.**

MSW v2's `setupServer` from `msw/node` works in Jest (which runs in Node.js) regardless of the test target being React Native. This is correct for unit/integration tests.

**Spec to update:**
- Testing spec Section 1.4: Add a note after the MSW server setup:

> **Note:** MSW handlers intercept requests in the Node.js Jest environment, not in the React Native runtime. These handlers work for unit and integration tests run via `npm test`. For on-device API mocking (E2E tests), use Maestro with a staging backend or a local mock server. Do not attempt to use MSW's `setupWorker` in the RN app.

---

### FIX-8: Device ID Not Bound to Hardware

**DECISION: Acceptable for Phase 0. No change.**

The audit correctly identifies that `device_id` is `crypto.randomUUID()` with no hardware attestation. The mitigation (TLS prevents token interception) is sufficient. Device attestation (iOS DeviceCheck / Android Play Integrity) is a Phase 2 hardening measure.

**Specs to update:** None.

---

### FIX-9: JWT Base64URL Parsing

**DECISION: Fix the `parseJwtExpiry` function to use proper Base64URL decoding.**

The auth spec's `jwtUtils.ts` uses `atob()` which does not handle Base64URL encoding (no padding, `-`/`_` chars). While JWT payloads rarely contain these characters in practice, the fix is trivial and eliminates a class of silent failures.

**Corrected implementation:**

```typescript
// mobile/src/lib/jwtUtils.ts

function base64UrlDecode(str: string): string {
  const padded = str + '=='.slice(0, (4 - (str.length % 4)) % 4);
  return atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
}

export function parseJwtExpiry(token: string): number {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) throw new Error('Invalid JWT format');
    const payload = JSON.parse(base64UrlDecode(parts[1]));
    if (typeof payload.exp === 'number') {
      return payload.exp * 1000; // Convert seconds to milliseconds
    }
  } catch {
    // Invalid JWT format
  }
  // Fallback: assume 15 minutes from now (matches server default)
  return Date.now() + 15 * 60 * 1000;
}
```

**Specs to update:**
- Auth spec Appendix (jwtUtils.ts): Replace the `atob` implementation with the `base64UrlDecode` version above.

---

### FIX-10: Server-Side Validation for Mobile Uploads

**DECISION: Not applicable. GPX goes through the existing parser.**

Since we chose GPX export (FIX-3), the server processes the GPX file through the same `workout-parse` Rust parser that handles FIT/GPX/TCX files. All validation in `utils.rs` (`is_valid_gps`, `MAX_STEP_DISTANCE_M`, VAM cap, gradient cap) applies automatically. No additional server-side validation code is needed.

**Specs to update:**
- GPS spec Section 6.1: Remove the note about server needing to validate mobile JSON payloads. Replace with: "Mobile rides are uploaded as GPX files and processed through the same `workout-parse` parser as all other ride types. All server-side validation applies automatically."

---

### FIX-11: Portal API Client Pattern Divergence

**DECISION: Divergence is correct and intentional. No change needed.**

The audit already confirms this. The portal uses browser cookies and React Context. The mobile app uses SecureStore and Zustand. The case conversion utilities (`toSnakeCase`, `toCamelCase`) should be copied from the portal's `api.ts` to ensure identical behavior.

**Specs to update:** None (just copy the portal's case conversion utils).

---

### FIX-12: Upload Endpoint Idempotency

**DECISION: Already resolved by FIX-3 (GPX upload) and FIX-5b (file_hash dedup).**

The `file_hash` dedup in `upload/init` handles all retry scenarios. No `client_ride_id` column, no `X-Idempotency-Key` header needed.

**Specs to update:** See FIX-3 and FIX-5b updates above.

---

## SIMPLIFY Resolutions

### SIMPLIFY-1: Three-Source Token Refresh Fallback

**DECISION: CUT the `X-Refresh-Token` header. Keep two sources: cookie (web) and body (mobile).**

The auth spec proposes three sources for the refresh token. The third source (custom `X-Refresh-Token` header with `_extract_bearer` helper) is unnecessary. No client needs it when the body field already exists.

**Backend change:** In `auth.py` line 613, replace the cookie-only read with:

```python
refresh_token = (
    request.cookies.get("refresh_token")  # 1. Cookie (web browsers)
    or payload.refresh_token               # 2. Request body (mobile apps)
)
```

Do NOT add the `_extract_bearer` helper or the `X-Refresh-Token` header support.

Apply the same two-source fallback to the `logout` endpoint (line 726).

**Specs to update:**
- Auth spec Section 1: Remove source 3 (`X-Refresh-Token` header). Remove the `_extract_bearer` helper function. Keep only cookie and body sources.

---

### SIMPLIFY-2: NTP Clock Check

**DECISION: CUT from Phase 0. Defer to Phase 1.**

The server already validates `uploaded_at - ended_at > 48hr`. The device-side NTP check adds complexity (network request before ride start, offline handling, storing `clock_drift_ms`) with minimal Phase 0 value.

**What stays:** The `clock_drift_ms` column in the SQLite `rides` table stays in the schema (it is nullable). When the NTP check is implemented in Phase 1, it populates this field.

**What goes:** Remove the NTP HTTP HEAD request from the ride start flow. Remove `react-native-ntp-client` from the dependency list.

**Specs to update:**
- GPS spec Section 1.4: Move the NTP check section to a "Phase 1 Improvements" appendix. Keep the monotonic clock (`performance.now()`) section as-is -- that stays in Phase 0.

---

### SIMPLIFY-3: HMAC Payload Signing

**DECISION: CUT from the Phase 0 spec entirely.**

The GPS spec Section 6.3 is already marked "v1.1" but takes up spec real estate that could confuse implementing agents. Move to a future security roadmap.

**Specs to update:**
- GPS spec Section 6.3: Delete this section entirely. If needed, create a separate `MOBILE_SECURITY_ROADMAP.md` document later.

---

### SIMPLIFY-4: Sensor Samples Table

**DECISION: CUT from Phase 0 schema. Defer to Phase 2 (BLE).**

The `sensor_samples` table is for BLE HR/power/cadence data. BLE is explicitly Phase 2 in all specs. Creating the table now adds schema surface that serves no purpose.

**Specs to update:**
- GPS spec Section 2.3: Remove the `sensor_samples` CREATE TABLE statement and its two indexes. Keep `rides`, `gps_samples`, `pause_events`, and `upload_queue`.
- GPS spec Section 4.2 (upload payload): Remove the `sensor_samples` array (moot since we chose GPX, but for completeness).

---

### SIMPLIFY-5: Sentry Performance Profiling

**DECISION: CUT performance tracing. Keep crash reporting at full rate.**

Set `tracesSampleRate: 0` and `profilesSampleRate: 0` for production. These consume free-tier quota without value at fewer than 100 users. Enable at beta when there are real traffic patterns to profile.

Keep `enabled: !__DEV__` for crash reporting (error events at full rate).

**Specs to update:**
- Testing spec Section 3.2: Change production `tracesSampleRate` to `0` and `profilesSampleRate` to `0`.
- Testing spec Section 3.5: Add a note: "Performance monitoring is disabled in production until beta (>100 active users). Enable by setting `tracesSampleRate: 0.2` and `profilesSampleRate: 0.1` in `sentry.ts`."

---

## MISSING Resolutions

### MISSING-1: Crash Recovery + Auth Expiry

**DECISION: Fully resolved in FIX-4 above.**

The `failed_auth` upload queue status, the 401 interception in the queue processor, and the post-login retry mechanism cover this gap completely.

---

### MISSING-2: GPS Spec Dependency List

**DECISION: Here is the complete dependency list for the GPS/recording spec.**

#### Production Dependencies (Phase 1 - Recording)

| Package | Version | Cost | Purpose |
|---------|---------|------|---------|
| `expo-location` | `~18.0.0` | $0 | Foreground + background GPS recording |
| `expo-task-manager` | `~12.0.0` | $0 | Background task registration for location updates |
| `expo-sqlite` | `~14.0.0` | $0 | Local ride/sample persistence (already in package.json) |
| `expo-file-system` | `~18.0.0` | $0 | GPX file writing before upload |
| `expo-crypto` | `~13.0.0` | $0 | SHA-256 hashing for file_hash dedup |

All are Expo first-party packages, installed via `npx expo install`. Zero paid licenses.

#### NOT included (deferred)

| Package | Cost | Deferred To | Reason |
|---------|------|-------------|--------|
| `react-native-background-geolocation` | $300/yr | Phase 2 (if needed) | Evaluate after alpha testing |
| `react-native-ntp-client` | $0 | Phase 1 | NTP clock drift check |
| BLE sensor libraries | $0 | Phase 2 | HR, power, cadence |

**Specs to update:**
- GPS spec: Add a "Dependencies" section listing the packages above.

---

### MISSING-3: File Manifest for GPS Spec

**DECISION: Here is the complete file manifest.**

#### New Files (Phase 1 - Recording)

| File | Purpose |
|------|---------|
| `mobile/src/services/database/schema.ts` | SQLite table creation, migration runner |
| `mobile/src/services/database/migrations.ts` | Versioned schema migrations |
| `mobile/src/services/gps/validation.ts` | GPS sample validation (Null Island, range, accuracy, speed, time travel) |
| `mobile/src/services/gps/gpxExporter.ts` | Convert SQLite GPS samples to GPX file |
| `mobile/src/services/recording/recordingService.ts` | GPS callback handler, buffer management, SQLite batch writes |
| `mobile/src/services/recording/crashRecovery.ts` | Detect interrupted rides on app launch |
| `mobile/src/services/recording/autoPause.ts` | Speed-based auto-pause logic |
| `mobile/src/services/upload/queueProcessor.ts` | Upload queue state machine, retry, backoff |
| `mobile/src/stores/recordingStore.ts` | Zustand recording state machine |
| `mobile/src/components/CrashRecoveryModal.tsx` | "Unfinished ride found" modal |
| `mobile/src/screens/RecordScreen.tsx` | Recording UI (map + controls + live stats) |
| `mobile/src/hooks/useLocationTracking.ts` | expo-location wrapper hook |

#### Modified Files (Phase 1 - Recording)

| File | Change |
|------|--------|
| `mobile/App.tsx` | Add crash recovery check in AuthInitializer |
| `mobile/src/components/AuthInitializer.tsx` | Query for interrupted rides after auth hydration |
| `mobile/package.json` | Add expo-location, expo-task-manager, expo-file-system, expo-crypto |
| `mobile/app.config.ts` | Add location permission strings, UIBackgroundModes |

**Specs to update:**
- GPS spec: Add this file manifest as a new section.

---

### MISSING-4: recordingStore State Machine

**DECISION: Fully specified below.**

See [recordingStore State Machine](#recordingstore-state-machine) section for the complete definition.

---

### MISSING-5: Push Notification Wiring

**DECISION: Explicitly deferred to Phase 2. No action in Phase 0 or Phase 1.**

Push notifications require:
1. New backend endpoint (`POST /notifications/devices`).
2. New `notification_devices` table.
3. Firebase Cloud Messaging integration (FCM for both iOS and Android).
4. `expo-notifications` library integration.

This is 3-4 days of work across backend and mobile. It provides no value until there are 50+ active users generating notifications worth pushing.

**Specs to update:**
- Testing spec Section 3.4: Add a note under breadcrumbs: "Push notification registration is Phase 2 scope. Notifications are poll-based (GET /notifications every 60s on foreground) until then."

---

### MISSING-6: SQLite Migration Strategy

**DECISION: Use `PRAGMA user_version` with a migration runner on app startup.**

```typescript
// mobile/src/services/database/migrations.ts

interface Migration {
  version: number;
  up: string[]; // SQL statements to run
}

const MIGRATIONS: Migration[] = [
  {
    version: 1,
    up: [
      // rides, gps_samples, pause_events, upload_queue tables
      // (Phase 0 schema from GPS spec Section 2.3, minus sensor_samples)
    ],
  },
  // Future:
  // { version: 2, up: ['CREATE TABLE IF NOT EXISTS sensor_samples (...)'] },
];

export async function runMigrations(db: SQLiteDatabase): Promise<void> {
  const result = db.getFirstSync<{ user_version: number }>(
    'PRAGMA user_version'
  );
  const currentVersion = result?.user_version ?? 0;

  for (const migration of MIGRATIONS) {
    if (migration.version > currentVersion) {
      db.execSync('BEGIN TRANSACTION');
      try {
        for (const sql of migration.up) {
          db.execSync(sql);
        }
        db.execSync(`PRAGMA user_version = ${migration.version}`);
        db.execSync('COMMIT');
      } catch (error) {
        db.execSync('ROLLBACK');
        throw error;
      }
    }
  }
}
```

**Key properties:**
- `PRAGMA user_version` is an atomic integer stored in the SQLite file header. It survives crashes.
- Migrations run in transactions. If a migration fails partway, it rolls back.
- Migrations are append-only. Never modify an existing migration; add a new version.
- The migration runner runs on every app startup, before any data access. It is idempotent (skips versions already applied).

**Specs to update:**
- GPS spec: Add a "Migration Strategy" section with the above pattern.

---

### MISSING-7: Offline Recording + Upload Coordination

**DECISION: Local rides are visible in a "Pending Uploads" section above the server ride list. After upload, invalidate the TanStack Query cache.**

**Exact behavior:**

1. **During recording:** The ride list screen does NOT show the in-progress ride. The recording screen is the UI for the active ride.

2. **After ride stop, before upload:** The ride appears in a "Pending" section at the top of the ride history screen. Data comes from the local `rides` SQLite table (distance, duration, elevation, sample count). It shows a status badge: "Uploading..." or "Waiting for connection" or "Failed - tap to retry".

3. **After upload succeeds:** The upload queue marks `status = 'uploaded'` and stores `server_ride_id`. The app invalidates the TanStack Query `['rides']` key, which triggers a refetch from the server. The server ride list now includes the uploaded ride with full processing data (TSS, climbs, points). The local "Pending" section filters out `uploaded` entries.

4. **Cleanup:** Local SQLite data for uploaded rides is retained for 7 days (for offline viewing), then pruned. This is a background task, not user-facing.

**Implementation:**

```typescript
// In the ride history screen:
const pendingRides = usePendingUploads(); // reads from local SQLite
const serverRides = useQuery({
  queryKey: ['rides'],
  queryFn: () => api.getRides(),
});

// Render:
// {pendingRides.length > 0 && <PendingUploadSection rides={pendingRides} />}
// <ServerRideList rides={serverRides.data} />
```

```typescript
// After successful upload in queueProcessor.ts:
import { queryClient } from '../lib/queryClient';
queryClient.invalidateQueries({ queryKey: ['rides'] });
queryClient.invalidateQueries({ queryKey: ['points'] });
```

**Specs to update:**
- GPS spec: Add a "Local-to-Server Ride Handoff" section with the above.

---

### MISSING-8: End-to-End Data Flow

**DECISION: Here is the definitive data flow, from GPS callback to upload queue.**

```
GPS CALLBACK FIRES (expo-location, ~1Hz)
    |
    v
[1] VALIDATION (validation.ts)
    - Null Island check
    - Range check (lat/lon)
    - Accuracy gate (>100m -> reject)
    - Speed gate (>50 m/s -> reject)
    - Time travel check (t <= last_t -> reject)
    |
    | rejected -> increment rejection counter (in-memory)
    | accepted
    v
[2] IN-MEMORY BUFFER (recordingService.ts)
    - Append sample to array (max 10)
    - Update live stats (distance, elevation, speed) in recordingStore
    |
    | buffer.length === 10 OR user tapped pause/stop
    v
[3] SQLITE BATCH WRITE (recordingService.ts, inside transaction)
    - BEGIN TRANSACTION
    - INSERT 10 rows into gps_samples
    - UPDATE rides SET sample_count += 10, duration_ms = ?, distance_m = ?, ...
    - COMMIT
    |
    | (transaction is atomic: crash here = rollback, no partial writes)
    v
[4] BUFFER CLEARED
    - In-memory buffer reset to empty
    - Continue collecting samples
    |
    | ... ride continues for hours ...
    |
    | USER TAPS STOP
    v
[5] RIDE FINALIZATION (recordingService.ts)
    - Flush remaining buffer (<10 samples) via step [3]
    - Set rides.status = 'stopped', rides.ended_at = wallclock
    - Stop location tracking (expo-location)
    |
    v
[6] GPX EXPORT (gpxExporter.ts)
    - SELECT * FROM gps_samples WHERE ride_id = ? ORDER BY t_offset_ms
    - Convert wallclock_start + t_offset_ms to ISO 8601 timestamps
    - Write GPX XML to documentDirectory/rides/{ride_id}.gpx
    - Compute SHA-256 hash of file bytes
    |
    v
[7] UPLOAD QUEUE ENTRY (queueProcessor.ts)
    - INSERT INTO upload_queue (id, ride_id, status, file_hash, ...)
    - status = 'pending'
    |
    v
[8] QUEUE PROCESSOR (runs on trigger: ride end, foreground, network restored)
    - SELECT next pending/retryable entry
    - POST /rides/upload/init { file_type: 'gpx', file_hash, file_size }
      - 409 Conflict? -> already uploaded, mark 'uploaded', done.
      - 401? -> attempt refresh -> retry or mark 'failed_auth'
    - PUT gpx_bytes to signed_url
    - POST /rides/upload/complete { upload_id }
      - Success: mark 'uploaded', invalidate TanStack Query cache
      - 5xx / network error: mark 'failed_retryable', backoff
      - 4xx (non-401, non-409): mark 'failed_permanent'
```

**Specs to update:**
- GPS spec: Replace the existing "Appendix A: Data Flow Diagram" with this flow.

---

## Ecosystem Alignment

### Does the mobile GPS sample format match what workout-parse expects?

**YES.** By exporting to GPX (FIX-3 decision), the mobile ride goes through the same `quick-xml` GPX parser in workout-parse that handles all other GPX files. The parser extracts lat, lon, elevation, and timestamp from `<trkpt>` elements. The mobile app produces standard GPX 1.1 format. No conversion layer needed.

### Will mobile rides hit the same ride_processor pipeline?

**YES.** The upload flow is: `upload/init` (file_type="gpx") then PUT GPX bytes to Supabase Storage then `upload/complete`. This is identical to a portal FIT/GPX upload. The `enqueue_ride_ingest` function creates a `RideIngestJob` with `file_type="gpx"` and `source="manual_upload_direct"`. The same `RideProcessor.process_ride()` method handles it.

**One distinction:** We should set `source="mobile"` instead of `"manual_upload_direct"` for analytics. This requires a small change to the `upload/complete` endpoint to accept a `source` parameter. Defer this to Phase 1 (nice-to-have, not a blocker).

### Same on-chain completions?

**YES.** The ride processor handles receipt-backed on-chain climb completions identically regardless of ride source. The climb detection, vault matching, and `send_record_climb_completion` call are all server-side.

### Same indexer? Same BoulderScan display?

**YES.** On-chain operations are triggered by the server. The TS indexer watches on-chain events. BoulderScan displays indexed data. The ride source (mobile GPX vs portal FIT) is invisible to the chain and indexer.

---

## Final App.tsx Provider Hierarchy

This is the single canonical provider tree. All three specs reference this.

```typescript
// mobile/App.tsx

import { initSentry } from './src/lib/sentry';
initSentry(); // Must run before any React rendering

function App() {
  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <PrivyProvider appId={PRIVY_APP_ID} config={privyConfig}>
            <PrivyAuthBridge>
              <AuthInitializer>
                <NavigationContainer theme={navigationTheme}>
                  <StatusBar style="light" />
                  <RootNavigator />
                </NavigationContainer>
              </AuthInitializer>
            </PrivyAuthBridge>
          </PrivyProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}

export default Sentry.wrap(App);
```

**Provider responsibilities (outer to inner):**

| # | Provider | Responsibility | Fails Gracefully? |
|---|----------|---------------|-------------------|
| 0 | `Sentry.wrap(App)` | Wraps entire app for performance monitoring + crash capture | Yes (noop if no DSN) |
| 1 | `SafeAreaProvider` | Device inset measurements | Always succeeds |
| 2 | `ErrorBoundary` | Catches any React render error below it | Renders restart screen on error |
| 3 | `QueryClientProvider` | TanStack Query cache + client | Always succeeds |
| 4 | `PrivyProvider` | Privy SDK initialization | Shows loading state if SDK slow |
| 5 | `PrivyAuthBridge` | Syncs Privy auth to backend JWT to Zustand | Renders children regardless |
| 6 | `AuthInitializer` | Hydrates Zustand from SecureStore, checks for interrupted rides, starts refresh timer | Shows splash until complete |
| 7 | `NavigationContainer` | React Navigation root | Always succeeds |
| 8 | `RootNavigator` | Reads `useAuthStore` to render AuthStack or TabNavigator | Always succeeds |

**Key changes from original specs:**
- `ErrorBoundary` moved ABOVE `QueryClientProvider` (was below in testing spec). This ensures that crashes in TanStack Query internals or Privy SDK are caught.
- Crash recovery check happens inside `AuthInitializer`, not as a separate component. After hydrating auth from SecureStore, AuthInitializer queries SQLite for interrupted rides and shows the recovery modal if found.
- `Sentry.wrap(App)` at the export level, not inside the tree.

---

## Final Upload Protocol

```
MOBILE DEVICE                              SERVER
--------------                             ------

[Ride ends. GPS samples in SQLite.]

1. Convert SQLite samples -> GPX file
   SELECT * FROM gps_samples
     WHERE ride_id = ? ORDER BY t_offset_ms
   Write GPX XML to documentDir/rides/id.gpx

2. Compute file_hash = SHA256(gpx_bytes)

3. POST /rides/upload/init
   Authorization: Bearer {accessToken}
   Body: {
     file_type: "gpx",
     file_hash: "abc123...",              Check find_ride_by_hash()
     file_size: 245000                    hash match -> 409 (already uploaded)
   }                                      no match -> create ride row
   <--- { uploadId, signedUrl, expiresIn }    return signed URL

4. PUT gpx_bytes to signedUrl             Upload to Supabase Storage
   Content-Type: application/octet-stream

5. POST /rides/upload/complete
   Body: { upload_id: uploadId }          Verify file exists
   <--- { ride_id, status: "processing" } Enqueue ride processing

6. Poll GET /rides/{ride_id}/status       Process ride:
   every 3s                                Phase 1: parse, metrics, GPS
                                           Phase 2: tiles, climbs, vaults
                                           Phase 3: points, achievements

7. When status = "completed":
   GET /rides/{ride_id}/patterns          Climb cards, vault matches
   GET /rides/{ride_id}/gps               Map trace
   GET /points/balance                    Updated points

   Invalidate TanStack Query caches.
   Show post-ride summary.
```

---

## recordingStore State Machine

```typescript
// mobile/src/stores/recordingStore.ts

import { create } from 'zustand';

type RecordingStatus = 'idle' | 'recording' | 'paused' | 'stopping' | 'saving';

interface RecordingState {
  // Status
  status: RecordingStatus;

  // Current ride metadata
  rideId: string | null;
  startedAt: number | null;       // wallclock epoch ms
  elapsedMs: number;              // monotonic elapsed (excludes pauses)
  distanceM: number;              // cumulative haversine distance
  elevationGainM: number;         // cumulative positive elevation
  currentSpeedMps: number;        // latest GPS speed
  maxSpeedMps: number;            // peak speed
  sampleCount: number;            // accepted GPS samples
  rejectedSamples: Record<string, number>;

  // GPS buffer state
  bufferSize: number;             // samples in current buffer (0-10)

  // Actions
  startRide: (rideId: string) => void;
  pauseRide: () => void;
  resumeRide: () => void;
  stopRide: () => void;
  discardRide: () => void;
  updateLiveStats: (stats: Partial<LiveStats>) => void;
  incrementBuffer: () => void;
  resetBuffer: () => void;
  reset: () => void;
}

interface LiveStats {
  elapsedMs: number;
  distanceM: number;
  elevationGainM: number;
  currentSpeedMps: number;
  maxSpeedMps: number;
  sampleCount: number;
}
```

**State machine transitions:**

```
         startRide()
idle ----------------------> recording
  ^                           |   ^
  |                           |   |
  |                 pauseRide()   resumeRide()
  |                           |   |
  |                           v   |
  |                         paused
  |                           |
  |                 stopRide() (from recording OR paused)
  |                           |
  |                           v
  |                        stopping  (flushing buffer, finalizing ride row)
  |                           |
  |                           v
  |                         saving   (generating GPX, creating upload queue entry)
  |                           |
  |                           v
  +------ reset() ---------- idle    (upload queue handles the rest independently)

  discardRide() (from any state except idle):
    -> DELETE ride from SQLite
    -> reset() -> idle
```

**Invariants:**
- Only one ride can be active at a time (enforced by SQLite partial unique index AND by Zustand state).
- `stopRide()` can be called from `recording` or `paused`. Both paths flush the buffer and finalize.
- The `stopping` state exists because buffer flush + ride finalization + GPX export is async. The UI shows "Saving..." during this state and disables all buttons.
- `saving` is distinct from `stopping` because GPX export and upload queue insertion could fail (disk full, etc.). If saving fails, the ride stays in `stopping` state and the user can retry.
- `discardRide()` requires confirmation in the UI. It permanently deletes the ride and all its GPS samples from SQLite.
- After `reset()`, the upload queue runs independently. The recording store does not track upload status. Upload status is a separate concern with its own UI (pending uploads section in ride history).

---

## Backend Changes (Prioritized)

### BLOCKER (must land before mobile auth works)

| # | Change | File(s) | Effort | Details |
|---|--------|---------|--------|---------|
| B1 | Token refresh: accept from body, not just cookie | `backend/app/routes/auth.py` line 613 | 2 hours | Replace cookie-only read with cookie-or-body fallback. See SIMPLIFY-1. |
| B2 | Restore `refresh_token` field description | `backend/app/schemas.py` line 95-99 | 5 min | Change "Deprecated" to "Required for mobile clients." |
| B3 | Logout: accept refresh_token from body | `backend/app/routes/auth.py` line 726 | 30 min | Same cookie-or-body fallback for logout endpoint. |

**Total blocker effort: 3 hours.**

### NICE TO HAVE (Phase 1)

| # | Change | File(s) | Effort | Details |
|---|--------|---------|--------|---------|
| N1 | Add `source` column to rides table | New migration | 1 hour | `ALTER TABLE rides ADD COLUMN source TEXT DEFAULT 'file'`. Set to `'mobile'` for mobile uploads. Analytics only. |
| N2 | Server-side clock drift validation | `ride_processor.py` | 2 hours | Flag rides where `uploaded_at - ended_at > 48hr`. |
| N3 | Push notification device registration | New routes + table | 2-3 days | Phase 2 scope. |

---

## Dependency Graph

```
PHASE 0 (Auth + Testing + Error Handling)
=========================================

B1 (backend auth fix) ---+
                          +--> Mobile auth works
B2 (schema description) -+
                              |
                              v
secureStorage.ts --> authStore.ts --> authService.ts --> tokenRefreshManager.ts
                                            |
                                            v
queryClient.ts --> PrivyAuthBridge.tsx --> AuthInitializer.tsx --> RootNavigator.tsx
                                            |
                                            v
ErrorBoundary.tsx --> App.tsx (full provider hierarchy)
                              |
sentry.ts --------------------+
                              |
jest.setup.ts --> MSW handlers --> api.test.ts --> auth-store.test.ts
                                                          |
eas.json --> app.config.ts --> mobile-ci.yml --------------+


PHASE 1 (GPS Recording + Upload) -- DEPENDS ON PHASE 0
=======================================================

expo-location --> useLocationTracking.ts --> recordingService.ts
                                                    |
expo-sqlite schema --> migrations.ts ---------------+
                              |
validation.ts ----------------+
                              |
autoPause.ts -----------------+
                              v
recordingStore.ts --> RecordScreen.tsx
                              |
                              v (on ride stop)
gpxExporter.ts --> queueProcessor.ts --> (existing /rides/upload/init flow)
                              |
crashRecovery.ts --> CrashRecoveryModal.tsx --> AuthInitializer.tsx (wired in)
```

**Key insight:** Phase 0 has ZERO dependency on any backend upload changes. The only backend blocker is the auth refresh fix (B1-B3), which is 3 hours of work. Phase 1 (GPS recording) also has zero backend changes -- it uses the existing presigned upload flow with GPX files.

---

## Revised Timeline

### Phase 0: Auth + Testing + Error Handling + CI

**Duration: 7 working days (1.5 weeks)**

| Day | Tasks | Dependencies |
|-----|-------|-------------|
| 1 | Backend auth fix (B1-B3). Install test deps. Jest config. MSW setup. | None |
| 2 | secureStorage.ts, authStore.ts, queryClient.ts. API client tests. | B1 done |
| 3 | authService.ts, tokenRefreshManager.ts, PrivyAuthBridge.tsx. | Auth store |
| 4 | AuthInitializer.tsx, RootNavigator.tsx. Wire App.tsx provider hierarchy. | Auth services |
| 5 | ErrorBoundary.tsx, ErrorBanner.tsx. Replace empty catch blocks. Sentry init. | App.tsx wired |
| 6 | eas.json, app.config.ts, GitHub Actions CI. Auth store tests. | Jest working |
| 7 | Screen tests (Home, Profile, Vaults). Full test suite pass. CI green. | All above |

### Phase 1: GPS Recording + Upload

**Duration: 10 working days (2 weeks)**

| Day | Tasks | Dependencies |
|-----|-------|-------------|
| 8 | SQLite schema + migrations. validation.ts. expo-location setup. | Phase 0 done |
| 9 | recordingStore.ts. recordingService.ts (GPS callback, buffer, batch write). | SQLite + validation |
| 10 | useLocationTracking.ts. autoPause.ts. Background location config. | recordingService |
| 11 | gpxExporter.ts. Upload queue processor. | recordingService |
| 12 | crashRecovery.ts. CrashRecoveryModal.tsx. Wire into AuthInitializer. | SQLite + queue |
| 13 | RecordScreen.tsx (map + start/stop/pause + live stats). | recordingStore |
| 14 | RecordScreen.tsx continued. Post-ride summary screen. | RecordScreen |
| 15 | Upload queue integration testing. Offline/retry testing. | Queue + screen |
| 16 | Recording service tests. Upload queue tests. GPS validation tests. | All recording code |
| 17 | Integration testing. Bug fixes. Polish. | All above |

### Total to first mobile ride upload: 17 working days (~3.5 weeks)

This is faster than the audit's 4-5 week estimate because:
1. We eliminated the backend upload endpoint work (GPX goes through existing flow).
2. We eliminated the $300/yr library (using free `expo-location`).
3. We eliminated `client_ride_id` migration + idempotency wiring.
4. The only backend change is 3 hours of auth fix.

---

## Revised Cost

### Phase 0 Cost

| Item | Cost | Notes |
|------|------|-------|
| Sentry free tier | $0 | 5K errors/mo, 10K transactions/mo |
| EAS Build free tier | $0 | 30 builds/mo |
| EAS Update free tier | $0 | 1K monthly updating users |
| Apple Developer Program | $99/yr | Required for TestFlight (may already exist) |
| Google Play Developer | $25 one-time | Required for Play Store (may already exist) |
| GitHub Actions | $0 | 2K min/mo free for private repos |
| **Total Phase 0** | **$0-$124** | Depending on whether Apple/Google accounts exist |

### Phase 1 Cost

| Item | Cost | Notes |
|------|------|-------|
| expo-location | $0 | First-party Expo package |
| expo-task-manager | $0 | First-party Expo package |
| expo-file-system | $0 | First-party Expo package |
| expo-crypto | $0 | First-party Expo package |
| **Total Phase 1** | **$0** | All free |

### Deferred Costs

| Item | Cost | When | Trigger |
|------|------|------|---------|
| Transistor BG Geolocation license | $300/yr | Phase 2 | If expo-location background recording is insufficient |
| Sentry Team plan | $26/mo | Beta | If >5K errors/mo or >10K transactions/mo |
| Firebase Cloud Messaging | $0 | Phase 2 | Push notifications (free tier covers our scale) |

### Eliminated Costs (vs original specs)

| Item | Original Cost | Decision |
|------|---------------|----------|
| `react-native-background-geolocation` | $300/yr | Use `expo-location` instead ($0) |
| Backend endpoint development (3-5 days) | Engineering time | GPX upload uses existing flow (0 days) |
| `client_ride_id` migration + wiring | Engineering time | file_hash dedup is sufficient (0 days) |

---

## Summary of Spec Updates Required

After this resolution document is accepted, the following specs must be updated:

### `MOBILE_PHASE0_AUTH_STATE.md`
1. Section 1: Remove X-Refresh-Token header (SIMPLIFY-1). Keep cookie + body only.
2. Section 8: Add ErrorBoundary to provider hierarchy. Reference this document's canonical tree.
3. Appendix (jwtUtils.ts): Fix Base64URL decoding (FIX-9).

### `MOBILE_PHASE0_GPS_INTEGRITY.md`
1. Section 1.3: Replace Transistor library with expo-location (FIX-6).
2. Section 1.4: Move NTP check to Phase 1 appendix (SIMPLIFY-2).
3. Section 2.1: Change op-sqlite to expo-sqlite (FIX-1).
4. Section 2.3: Remove sensor_samples table (SIMPLIFY-4).
5. Section 3.3: Remove Transistor internal persistence recovery (FIX-6).
6. Section 4.1: Remove X-Idempotency-Key. Simplify to GPX upload flow (FIX-3).
7. Section 4.2: Replace RideUploadPayload JSON with GPX generation spec (FIX-3).
8. Section 4.3: Add `failed_auth` status (FIX-4). Add 401 handling logic.
9. Section 5.1-5.4: Rewrite for expo-location (FIX-6).
10. Section 6.1: Remove /rides/upload/mobile endpoint (FIX-3).
11. Section 6.2: Remove client_ride_id migration (FIX-5b).
12. Section 6.3: Delete HMAC section entirely (SIMPLIFY-3).
13. Add new sections: Dependencies (MISSING-2), File Manifest (MISSING-3), Migration Strategy (MISSING-6), Data Flow (MISSING-8), Local-to-Server Handoff (MISSING-7).

### `MOBILE_PHASE0_TESTING_CI.md`
1. Section 1.1: Remove @testing-library/jest-native (FIX-5a).
2. Section 1.2-1.3: Change extend-expect import path (FIX-5a).
3. Section 1.4: Add MSW React Native compatibility note (FIX-7).
4. Section 2.3: Update provider hierarchy to reference this document (FIX-2).
5. Section 3.2: Disable performance tracing in production (SIMPLIFY-5).
6. Section 6: Update dependency summary to remove jest-native.

### `MOBILE_DATA_CONTRACTS.md`
1. Part 5 Option A: Mark as CHOSEN.
2. Part 5 Option B: Mark as DEFERRED to Phase 2.
