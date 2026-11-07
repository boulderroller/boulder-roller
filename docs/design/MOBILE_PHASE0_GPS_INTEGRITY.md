# Mobile Phase 0: GPS Integrity, SQLite Schema, Crash Recovery, Upload Queue

**Date:** 2026-03-28
**Status:** Implementation Spec (ready for dev agents)
**Depends on:** `MOBILE_ARCHITECTURE_REVIEW.md` (findings S5, D1-D4), `MOBILE_UX_DEEP_RESEARCH.md` (Section 3)
**Target:** React Native 0.76.7 / Expo 52 / iOS 16+ / Android 13+

---

## Table of Contents

1. [GPS Data Validation Pipeline](#1-gps-data-validation-pipeline)
2. [SQLite Schema for Ride Recording](#2-sqlite-schema-for-ride-recording)
3. [Crash Recovery](#3-crash-recovery)
4. [Upload Queue with Idempotency](#4-upload-queue-with-idempotency)
5. [Background Recording](#5-background-recording)
6. [Backend Integration Points](#6-backend-integration-points)

---

## 1. GPS Data Validation Pipeline

### 1.1 Validation Split: Device vs Server

**Principle:** Validate early, validate again. The device performs fast rejection of obviously bad samples to avoid polluting the local database. The server performs the full suite of checks because it has more context (historical rides, road network, vault signatures) and is the economic truth boundary.

| Check | Device | Server | Rationale |
|-------|:------:|:------:|-----------|
| Null Island (0,0) | YES | YES | GPS-no-fix sentinel. Reject immediately. |
| FIT sentinel (-214.748) | NO | YES | Only relevant for FIT file parsing. Mobile records raw GPS, not FIT. |
| Lat/lon range (abs(lat)<=90, abs(lon)<=180) | YES | YES | Basic coordinate validity. |
| Horizontal accuracy > 100m | YES | NO | Device has `accuracy` field from CLLocation/FusedLocation. Server does not. |
| Speed > 50 m/s (180 km/h) | YES | YES | Impossible cycling speed. On device: compare `CLLocation.speed`. On server: compute from haversine. |
| Per-step distance > 500m | NO | YES | Requires two consecutive samples and haversine. Server already does this in `utils.rs`. |
| Time travel (t[n] < t[n-1]) | YES | YES | On device: reject sample. On server: reject entire ride or flag for review. |
| VAM > 2500 m/hr | NO | YES | Requires elevation context over time window. Server-side only. |
| Sample frequency outside 0.5-2.0 Hz | NO | YES | Server computes actual frequency from timestamps. |
| Gradient > 45% | NO | YES | Requires elevation smoothing. Already in `persistence.rs`. |
| Device clock drift > 48hr from server | NO | YES | Compare `uploaded_at - ride.ended_at`. Flag for review if > 48hr. |

### 1.2 Device-Side Validation Function

```typescript
// services/gps/validation.ts

interface GPSSample {
  timestamp: number;       // Unix epoch milliseconds
  latitude: number;        // WGS84 decimal degrees
  longitude: number;       // WGS84 decimal degrees
  altitude: number | null; // meters above sea level (barometric preferred)
  accuracy: number;        // horizontal accuracy in meters
  speed: number | null;    // meters per second (from device)
  bearing: number | null;  // degrees from north (0-360)
  source: 'gps' | 'network' | 'fused'; // location provider
}

enum RejectionReason {
  NULL_ISLAND = 'null_island',
  OUT_OF_RANGE = 'out_of_range',
  LOW_ACCURACY = 'low_accuracy',
  IMPOSSIBLE_SPEED = 'impossible_speed',
  TIME_TRAVEL = 'time_travel',
}

interface ValidationResult {
  valid: boolean;
  reason?: RejectionReason;
}
```

**Validation rules (in order, short-circuit on first failure):**

1. **Null Island:** `lat === 0 && lon === 0` -> reject `NULL_ISLAND`
2. **Range check:** `abs(lat) > 90 || abs(lon) > 180` -> reject `OUT_OF_RANGE`
3. **Accuracy gate:** `accuracy > 100` -> reject `LOW_ACCURACY` (100m is unusable for cycling; typical is 3-15m)
4. **Speed gate:** `speed !== null && speed > 50` -> reject `IMPOSSIBLE_SPEED` (180 km/h)
5. **Time travel:** `timestamp <= lastAcceptedTimestamp` -> reject `TIME_TRAVEL`

**Rejection behavior:** Rejected samples are NOT written to SQLite. A counter of rejected samples per reason is kept in-memory and included in the ride metadata at upload time (for server-side analytics on GPS quality).

### 1.3 What `react-native-background-geolocation` Already Filters

Transistor Software's library has its own internal filters. Understanding these avoids redundant work:

| Built-in Filter | Description | Our Action |
|----------------|-------------|------------|
| `distanceFilter` | Min distance (meters) between location events | Set to 5m. Prevents stationary GPS jitter from generating events. |
| `desiredAccuracy` | GPS accuracy level | Set to `DESIRED_ACCURACY_HIGH` (best available). |
| `locationUpdateInterval` | Android: minimum interval (ms) | Set to 1000ms (1Hz). |
| `stationaryRadius` | Radius to trigger stationary detection | Set to 10m. |
| `disableMotionActivityUpdates` | iOS motion activity coprocessor | Leave enabled (helps auto-pause). |
| Internal de-jitter | Removes internally-detected GPS jumps | Active by default. We still apply our own validation above. |

**The library does NOT filter:**
- Null Island
- Impossible speeds (it reports them; we must filter)
- Time travel (it can occur on clock adjustment)
- Altitude accuracy (barometer vs GPS altitude)

### 1.4 Device Clock Spoofing Detection

**Threat model:** A user sets their device clock back to spoof ride timestamps, potentially to claim vault completions at favorable times or overlap with another user's ride window.

**Device-side mitigations (partial -- cannot fully prevent on a rooted device):**

1. **NTP check at ride start:** Before ride begins, compare `Date.now()` against an NTP server (e.g., `time.apple.com` via `react-native-ntp-client` or a simple HTTP HEAD to our API and reading the `Date` response header). If the delta exceeds 60 seconds, store a `clock_drift_ms` field on the ride. Do NOT block the ride -- the user might have a legitimate clock drift.

2. **Monotonic ride clock:** Use `performance.now()` (high-resolution monotonic clock) for inter-sample timing, NOT `Date.now()`. The monotonic clock cannot be spoofed by changing the device clock. Store the initial `Date.now()` as `wallclock_start` and all sample timestamps as `monotonic_offset_ms` from ride start.

3. **Server-side validation (authoritative):**
   - Compare `ride.wallclock_start + ride.duration` against `uploaded_at`. Flag if delta > 48 hours.
   - Compare sample frequency: expect 0.8-1.2 Hz median. Reject < 0.1 Hz or > 5 Hz.
   - Cross-reference GPS trajectory against known road networks (already planned with OSM).
   - If `clock_drift_ms` is present and > 60s, apply the drift correction before processing.

### 1.5 Altitude Handling

**Hierarchy of altitude sources (best to worst):**

1. **Barometric altimeter** (iPhone 6+, most modern Android): `CLLocation.altitude` when `CLLocation.verticalAccuracy > 0`. Resolution ~0.1m, accuracy ~1-3m after calibration.
2. **GPS-derived altitude**: Less accurate (10-30m typical), but always available.
3. **DEM lookup server-side**: Server can enrich samples with SRTM/Copernicus DEM data post-upload.

**Device-side:**
- Record whatever the device provides. Store both `altitude` and `verticalAccuracy`.
- Do NOT attempt to smooth or filter altitude on-device. The server's SMA(5) in `utils.rs` handles this.
- Do NOT trust altitude for the first 100m of distance traveled (barometric calibration drift). The server's `find_startup_end()` in `utils.rs` already handles this.

---

## 2. SQLite Schema for Ride Recording

### 2.1 Library Choice: `@op-engineering/op-sqlite`

**Decision:** Use `op-sqlite` over `expo-sqlite`.

| Factor | `expo-sqlite` | `op-sqlite` |
|--------|:------------:|:-----------:|
| WAL mode | Supported | Supported |
| Performance | Adequate | 2-5x faster (JSI-based, synchronous API) |
| Batch inserts | One at a time | Prepared statements, batch execution |
| TypeScript | Good | Good |
| Maintenance | Expo team | Active community, frequent releases |
| Expo compatibility | Native | Requires `expo prebuild` (already in our scripts) |

**Rationale:** A 4-hour ride at 1Hz = 14,400 samples. With BLE sensor data, each batch write (every 10 seconds) inserts 10 rows. `op-sqlite`'s JSI bridge writes 10 rows in ~0.5ms vs ~3ms for `expo-sqlite`'s async bridge. Over a 4-hour ride, this saves ~1,440ms total battery and JS thread time. Not massive, but the synchronous API also simplifies the crash recovery logic (no async gaps where data could be lost).

### 2.2 Database Configuration

```typescript
// services/database/config.ts

const DB_NAME = 'boulderroller.db';

// Called once at app startup
function initDatabase(db: OPSQLiteDatabase): void {
  db.execute('PRAGMA journal_mode = WAL');        // Write-Ahead Logging for crash safety
  db.execute('PRAGMA synchronous = NORMAL');       // Balance of safety and speed (WAL makes this safe)
  db.execute('PRAGMA foreign_keys = ON');
  db.execute('PRAGMA cache_size = -2000');         // 2MB page cache
  db.execute('PRAGMA busy_timeout = 5000');        // 5s retry on lock contention
}
```

**WAL mode is non-negotiable.** It ensures that a crash mid-write does not corrupt the database. The WAL file acts as a journal: either the entire transaction is committed, or it is rolled back on recovery.

### 2.3 Schema

```sql
-- ============================================================================
-- Table: rides
-- One row per ride. Created at ride start, updated throughout.
-- The "singleton active ride" is the row where status = 'recording' or 'paused'.
-- ============================================================================
CREATE TABLE IF NOT EXISTS rides (
    id                TEXT PRIMARY KEY,           -- UUIDv4, generated at ride start
    status            TEXT NOT NULL DEFAULT 'recording',
                                                  -- recording | paused | stopped | uploading | uploaded | failed
    started_at        INTEGER NOT NULL,           -- Unix epoch ms (wallclock at ride start)
    ended_at          INTEGER,                    -- Unix epoch ms (wallclock at ride stop)
    duration_ms       INTEGER NOT NULL DEFAULT 0, -- Monotonic elapsed time (excludes pauses)
    moving_time_ms    INTEGER NOT NULL DEFAULT 0, -- Time where speed > 1 m/s
    distance_m        REAL NOT NULL DEFAULT 0,    -- Cumulative haversine distance
    elevation_gain_m  REAL NOT NULL DEFAULT 0,    -- Cumulative positive elevation change (raw, unsmoothed)
    max_speed_mps     REAL NOT NULL DEFAULT 0,    -- Peak speed observed
    sport_type        TEXT NOT NULL DEFAULT 'ride', -- ride | virtual_ride | ebike_ride
    clock_drift_ms    INTEGER,                    -- NTP delta measured at ride start (nullable)
    sample_count      INTEGER NOT NULL DEFAULT 0, -- Total accepted GPS samples
    rejected_samples  TEXT,                       -- JSON: {"null_island": 0, "low_accuracy": 3, ...}
    upload_id         TEXT,                       -- Set when upload initiated (for upload queue FK)
    notes             TEXT,                       -- User-entered title/description
    created_at        INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000),
    updated_at        INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
);

-- Only one active ride at a time
CREATE UNIQUE INDEX IF NOT EXISTS idx_rides_active
    ON rides(status) WHERE status IN ('recording', 'paused');

-- ============================================================================
-- Table: gps_samples
-- One row per accepted GPS fix. Written in batches of 10 (every ~10 seconds).
-- ============================================================================
CREATE TABLE IF NOT EXISTS gps_samples (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id         TEXT NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
    t_offset_ms     INTEGER NOT NULL,   -- Monotonic offset from ride start (ms). NOT wallclock.
    latitude        REAL NOT NULL,       -- WGS84 decimal degrees
    longitude       REAL NOT NULL,       -- WGS84 decimal degrees
    altitude_m      REAL,                -- Meters above sea level (barometric preferred)
    accuracy_m      REAL NOT NULL,       -- Horizontal accuracy (meters)
    vert_accuracy_m REAL,                -- Vertical accuracy (meters, null if GPS-only altitude)
    speed_mps       REAL,                -- Device-reported speed (m/s)
    bearing_deg     REAL,                -- Device-reported bearing (0-360)
    source          TEXT NOT NULL DEFAULT 'fused'  -- gps | network | fused
);

-- Query pattern: all samples for a ride, ordered by time
CREATE INDEX IF NOT EXISTS idx_gps_samples_ride_time
    ON gps_samples(ride_id, t_offset_ms);

-- ============================================================================
-- Table: sensor_samples
-- BLE sensor readings (HR, power, cadence). Separate from GPS because
-- sensor frequency may differ (HR: 1Hz, power: variable, cadence: 1Hz).
-- Written in batches alongside GPS samples.
-- ============================================================================
CREATE TABLE IF NOT EXISTS sensor_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id     TEXT NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
    t_offset_ms INTEGER NOT NULL,     -- Monotonic offset from ride start (ms)
    sensor_type TEXT NOT NULL,         -- hr | power | cadence | speed
    value       REAL NOT NULL,         -- BPM, watts, RPM, or m/s depending on type
    device_id   TEXT                   -- BLE device identifier (for multi-sensor disambiguation)
);

CREATE INDEX IF NOT EXISTS idx_sensor_samples_ride_time
    ON sensor_samples(ride_id, t_offset_ms);

CREATE INDEX IF NOT EXISTS idx_sensor_samples_type
    ON sensor_samples(ride_id, sensor_type, t_offset_ms);

-- ============================================================================
-- Table: upload_queue
-- Rides waiting to be uploaded. FIFO order. Retry with exponential backoff.
-- ============================================================================
CREATE TABLE IF NOT EXISTS upload_queue (
    id              TEXT PRIMARY KEY,           -- Same as rides.id (1:1 relationship)
    ride_id         TEXT NOT NULL UNIQUE REFERENCES rides(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',
                                                -- pending | uploading | uploaded | failed_retryable | failed_permanent
    file_hash       TEXT,                       -- SHA256 of serialized payload (computed before first upload attempt)
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 10,
    next_retry_at   INTEGER,                    -- Unix epoch ms. Null = ready now.
    last_error      TEXT,                       -- Last error message
    server_ride_id  TEXT,                       -- UUID returned by server on successful upload
    created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000),
    updated_at      INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
);

-- Query pattern: find next item ready to upload
CREATE INDEX IF NOT EXISTS idx_upload_queue_next
    ON upload_queue(status, next_retry_at)
    WHERE status IN ('pending', 'failed_retryable');

-- ============================================================================
-- Table: pause_events
-- Track pause/resume events for accurate moving time calculation.
-- ============================================================================
CREATE TABLE IF NOT EXISTS pause_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ride_id     TEXT NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,     -- pause | resume
    t_offset_ms INTEGER NOT NULL,  -- Monotonic offset from ride start (ms)
    reason      TEXT               -- manual | auto_pause | app_background
);

CREATE INDEX IF NOT EXISTS idx_pause_events_ride
    ON pause_events(ride_id, t_offset_ms);
```

### 2.4 Why Not a Singleton Active Ride Table

Several architectures use a dedicated `active_ride` singleton table. We use the partial unique index approach instead (`WHERE status IN ('recording', 'paused')`). Reasons:

1. The ride row already tracks all necessary state (`status`, `duration_ms`, `sample_count`).
2. A singleton table requires syncing state between two tables on every sample write.
3. The partial unique index enforces "at most one active ride" at the database level, which is stronger than application logic.
4. Crash recovery simply queries `SELECT * FROM rides WHERE status IN ('recording', 'paused') LIMIT 1`.

### 2.5 Batch Write Strategy

**Frequency:** Every 10 seconds (10 samples at 1Hz).

**Procedure:**
1. GPS callback fires, sample passes validation, appended to in-memory buffer.
2. Every 10 samples (or on pause/stop), flush buffer to SQLite in a single transaction.
3. Transaction includes: INSERT batch of `gps_samples` rows + UPDATE `rides` aggregate fields.

```typescript
// Pseudocode for batch write
function flushSampleBuffer(db: Database, rideId: string, buffer: GPSSample[]): void {
  db.transaction(() => {
    const stmt = db.prepareStatement(
      'INSERT INTO gps_samples (ride_id, t_offset_ms, latitude, longitude, altitude_m, accuracy_m, vert_accuracy_m, speed_mps, bearing_deg, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
    );
    for (const sample of buffer) {
      stmt.execute([rideId, sample.tOffsetMs, sample.latitude, sample.longitude,
        sample.altitude, sample.accuracy, sample.vertAccuracy,
        sample.speed, sample.bearing, sample.source]);
    }
    stmt.finalize();

    // Update ride aggregates
    const lastSample = buffer[buffer.length - 1];
    db.execute(
      `UPDATE rides SET
        sample_count = sample_count + ?,
        duration_ms = ?,
        distance_m = ?,
        elevation_gain_m = ?,
        max_speed_mps = MAX(max_speed_mps, ?),
        updated_at = ?
       WHERE id = ?`,
      [buffer.length, lastSample.elapsedMs, computeNewDistance(buffer),
       computeNewElevGain(buffer), computeMaxSpeed(buffer), Date.now(), rideId]
    );
  });
}
```

**The entire flush is atomic.** If the app crashes between individual INSERTs within the transaction, SQLite's WAL journal rolls back the partial transaction. No orphaned samples, no inconsistent aggregates.

### 2.6 Memory Management

- **In-memory buffer:** Maximum 10 samples (10 seconds at 1Hz). ~400 bytes. Negligible.
- **No full-ride array in JS.** All historical samples live in SQLite. Live display reads the most recent N samples from SQLite (or the in-memory buffer for the current batch).
- **For the live map trace:** Keep the last 60 samples (1 minute) in a circular buffer for smooth map rendering. Older points come from SQLite if the user scrolls the map.

---

## 3. Crash Recovery

### 3.1 Failure Modes

| Scenario | Data State | Recovery |
|----------|-----------|----------|
| App crashes at minute 45 | All samples up to last flush (within 10s of crash) are in SQLite. In-memory buffer (max 10 samples) is lost. | Recover 44:50 of ride. Lose ~10 seconds. |
| iOS kills background process | Same as crash. `react-native-background-geolocation` may have its own persistence (see 3.3). | Same recovery. |
| Phone battery dies | SQLite WAL survives power loss (this is what WAL is designed for). | Full recovery up to last flush. |
| Android force-stop | Same as crash. | Same recovery. |
| OOM kill during upload | Ride data intact in SQLite. Upload queue entry persists. | Retry upload on next launch. |

### 3.2 Detection on App Launch

On every app start (in `App.tsx` initialization, before navigation mounts):

```typescript
// services/recording/crashRecovery.ts

interface InterruptedRide {
  id: string;
  startedAt: number;
  durationMs: number;
  distanceM: number;
  elevationGainM: number;
  sampleCount: number;
  lastSampleTime: number; // t_offset_ms of last recorded sample
  status: 'recording' | 'paused';
}

async function checkForInterruptedRide(db: Database): Promise<InterruptedRide | null> {
  const row = db.execute(
    `SELECT r.id, r.started_at, r.duration_ms, r.distance_m,
            r.elevation_gain_m, r.sample_count, r.status,
            (SELECT MAX(t_offset_ms) FROM gps_samples WHERE ride_id = r.id) as last_sample_t
     FROM rides r
     WHERE r.status IN ('recording', 'paused')
     LIMIT 1`
  ).rows?.[0];

  if (!row) return null;

  return {
    id: row.id,
    startedAt: row.started_at,
    durationMs: row.duration_ms,
    distanceM: row.distance_m,
    elevationGainM: row.elevation_gain_m,
    sampleCount: row.sample_count,
    lastSampleTime: row.last_sample_t ?? 0,
    status: row.status,
  };
}
```

### 3.3 `react-native-background-geolocation` Crash Recovery

Transistor Software's library has its own internal persistence layer:

- **SQLite database** (separate from ours) stores locations when the app is not running.
- On app restart, calling `BackgroundGeolocation.sync()` or `getLocations()` retrieves buffered locations.
- The library's database is at: `{AppSupportDir}/TSLocationManager.db` (iOS) / `{AppFilesDir}/TSLocationManager.db` (Android).

**Integration strategy:**
1. On crash recovery, call `BackgroundGeolocation.getLocations()` to retrieve any samples the library captured after our last SQLite flush.
2. Validate these samples through our validation pipeline.
3. Insert valid samples into our `gps_samples` table, de-duped by `t_offset_ms` (within 500ms tolerance).
4. Call `BackgroundGeolocation.destroyLocations()` to clear the library's buffer after we have ingested them.

This recovers the ~10 second gap between our last flush and the crash.

### 3.4 User-Facing Recovery Flow

```
APP LAUNCH
    |
    v
checkForInterruptedRide()
    |
    +-- null --> normal app startup
    |
    +-- InterruptedRide found
        |
        v
    Recover samples from BackgroundGeolocation buffer
        |
        v
    MODAL (blocks navigation):
    +----------------------------------------------+
    |  Unfinished Ride Found                       |
    |                                              |
    |  You have an unfinished ride from            |
    |  [formatted date/time].                      |
    |                                              |
    |  Duration: 1:45:12                           |
    |  Distance: 42.3 km                           |
    |  Elevation: 687 m                            |
    |                                              |
    |  [Save & Upload]        [Resume Ride]        |
    |                                              |
    |  [Discard]                                   |
    +----------------------------------------------+

    "Save & Upload":
      1. Set ride.status = 'stopped', ride.ended_at = last_sample_wallclock
      2. Create upload_queue entry
      3. Navigate to ride summary screen
      4. Upload proceeds in background

    "Resume Ride":
      1. Keep ride.status = 'recording'
      2. Reset the BackgroundGeolocation listener
      3. Navigate directly to recording screen
      4. New samples append to existing ride
      5. Monotonic clock resumes from last t_offset_ms + time_since_crash
         (estimated from wallclock delta, capped at 30 minutes to prevent
         absurd durations from overnight crashes)

    "Discard":
      1. Confirmation dialog: "This will permanently delete your ride data."
      2. DELETE FROM rides WHERE id = ?  (CASCADE deletes samples)
      3. Normal app startup
```

**Resume timing:** When resuming, the app must handle the time gap. If the crash happened at t=45:00 and the app restarts 5 minutes later, the monotonic offset continues from 45:00 (the gap is treated as a pause). If the gap exceeds 30 minutes, the app defaults to "Save & Upload" and hides the "Resume" option -- the ride context is too stale to meaningfully resume.

### 3.5 Edge Case: Crash During Upload

If the app crashes while uploading:

1. The `upload_queue` row has `status = 'uploading'`.
2. On next launch, the crash recovery check finds the ride has `status = 'stopped'` (it was already stopped before upload began).
3. The upload queue processor sees `status = 'uploading'` with no response -> resets to `status = 'failed_retryable'`, increments `attempt_count`.
4. The upload retries. The server uses `file_hash` dedup to prevent double-processing if the first upload actually succeeded.

---

## 4. Upload Queue with Idempotency

### 4.1 Idempotency Key Design

**Key:** The ride's `id` field (UUIDv4, generated at ride start on the device).

**Why UUID and not a content hash:**
- A content hash (SHA256 of all GPS samples) can only be computed after the ride ends. The UUID is available immediately, which matters for the presigned upload flow (init requires an idempotency key).
- The content hash (`file_hash` = SHA256 of the serialized payload) is a secondary dedup mechanism, computed before the first upload attempt.

**How it flows:**

```
DEVICE                          SERVER
------                          ------
ride.id = UUIDv4()
  |
  v
POST /rides/upload/init
  X-Idempotency-Key: {ride.id}
  Body: { file_hash, file_size, file_type }
  |                              |
  |                              v
  |                      Check rides table:
  |                        1. file_hash match? -> 409 Conflict (existing ride returned)
  |                        2. idempotency_key match with status='uploaded'? -> return existing result
  |                        3. idempotency_key match with status='uploading'? -> return existing signed URL
  |                        4. New -> create ride row, return signed URL
  |                              |
  v                              v
PUT file to signed URL     (Supabase Storage)
  |
  v
POST /rides/upload/complete
  X-Idempotency-Key: {ride.id}
  Body: { ride_metadata }
  |                              |
  |                              v
  |                      Find ride by idempotency_key:
  |                        1. status='uploaded'? -> return existing result (idempotent)
  |                        2. status='uploading'? -> mark 'processing', enqueue
  |                        3. Not found? -> 404
  |                              |
  v                              v
Receive { server_ride_id }   Process ride (canonical_v2, vault matching, on-chain completions)
Mark upload_queue.status = 'uploaded'
```

### 4.2 Upload Payload

The mobile app does NOT upload a FIT/GPX/TCX file. It uploads a JSON payload containing the raw samples and metadata. The server constructs the internal representation.

```typescript
interface RideUploadPayload {
  // Idempotency
  client_ride_id: string;            // UUIDv4 from device
  file_hash: string;                 // SHA256 of this JSON payload (computed before upload)

  // Ride metadata
  started_at: number;                // Unix epoch ms (wallclock)
  ended_at: number;                  // Unix epoch ms (wallclock)
  duration_ms: number;               // Monotonic elapsed time
  moving_time_ms: number;
  sport_type: string;
  clock_drift_ms: number | null;

  // Device info (for server-side analytics and fraud detection)
  device: {
    platform: 'ios' | 'android';
    os_version: string;
    app_version: string;
    model: string;                   // e.g., 'iPhone 15 Pro', 'Pixel 8'
  };

  // GPS quality metadata
  quality: {
    total_samples: number;
    rejected_samples: Record<string, number>;   // { "null_island": 0, "low_accuracy": 3, ... }
    median_accuracy_m: number;
    gps_source_breakdown: Record<string, number>; // { "fused": 14200, "gps": 100, "network": 50 }
  };

  // GPS samples (array, ordered by t_offset_ms)
  gps_samples: Array<{
    t: number;         // t_offset_ms (monotonic, ms from ride start)
    lat: number;       // WGS84 decimal degrees, 7 decimal places
    lon: number;       // WGS84 decimal degrees, 7 decimal places
    alt: number | null; // meters
    acc: number;       // horizontal accuracy meters
    spd: number | null; // speed m/s
    brg: number | null; // bearing degrees
  }>;

  // Sensor samples (array, ordered by t_offset_ms, interleaved types)
  sensor_samples: Array<{
    t: number;         // t_offset_ms
    type: string;      // hr | power | cadence | speed
    val: number;       // BPM, watts, RPM, or m/s
  }>;

  // Pause events
  pauses: Array<{
    t: number;         // t_offset_ms
    event: string;     // pause | resume
    reason: string;    // manual | auto_pause | app_background
  }>;
}
```

**Payload size estimates:**
- 1-hour ride: ~4,200 GPS samples, ~4,200 sensor samples (HR) = ~800 KB JSON, ~200 KB gzipped
- 4-hour ride: ~16,800 GPS + ~16,800 sensor = ~3.2 MB JSON, ~800 KB gzipped
- 8-hour ride (ultra): ~33,600 GPS + ~33,600 sensor = ~6.4 MB JSON, ~1.6 MB gzipped

All rides fit within a single HTTP POST with gzip. No chunking needed. The presigned upload flow handles the storage; the metadata goes in the `/complete` request body.

### 4.3 Upload Queue Processor

```typescript
// services/upload/queueProcessor.ts

// Backoff schedule: 1s, 2s, 4s, 8s, 16s, 32s, 64s, 128s, 256s, 512s (max ~8.5 min)
const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 10 * 60 * 1000; // 10 minutes cap
const MAX_ATTEMPTS = 10;

function computeNextRetry(attemptCount: number): number {
  const delay = Math.min(
    BACKOFF_BASE_MS * Math.pow(2, attemptCount),
    BACKOFF_MAX_MS
  );
  // Add jitter: +/- 20%
  const jitter = delay * 0.2 * (Math.random() * 2 - 1);
  return Date.now() + delay + jitter;
}
```

**State machine:**

```
pending ──────────────> uploading ──────────────> uploaded (TERMINAL)
   ^                      |
   |                      |  (failure)
   |                      v
   +──── failed_retryable (attempt_count < MAX_ATTEMPTS)
                          |
                          |  (attempt_count >= MAX_ATTEMPTS)
                          v
                    failed_permanent (TERMINAL)
                    (surface to user: "Upload failed. Tap to retry or export as file.")
```

**Queue processing trigger points:**
1. Ride ends -> entry created with `status = 'pending'`
2. App comes to foreground -> process queue
3. Network connectivity restored (listen to NetInfo) -> process queue
4. Background fetch (iOS) / WorkManager (Android) -> process queue
5. Manual "retry" button on failed uploads -> reset to `pending`, `attempt_count = 0`

**Processing loop (runs on a single dedicated async worker, NOT re-entrant):**

```
1. SELECT * FROM upload_queue
   WHERE status IN ('pending', 'failed_retryable')
     AND (next_retry_at IS NULL OR next_retry_at <= ?)
   ORDER BY created_at ASC
   LIMIT 1

2. If no row -> sleep 30s, goto 1 (or wait for trigger event)

3. UPDATE upload_queue SET status = 'uploading' WHERE id = ?

4. Build RideUploadPayload from rides + gps_samples + sensor_samples + pause_events

5. Compute file_hash = SHA256(JSON.stringify(payload))
   UPDATE upload_queue SET file_hash = ? WHERE id = ?

6. POST /rides/upload/init
   Headers: { X-Idempotency-Key: ride_id, Content-Type: application/json }
   Body: { file_hash, file_size: payload_size, file_type: 'json' }

   On 409 (duplicate):
     -> UPDATE upload_queue SET status = 'uploaded', server_ride_id = response.existing_ride_id
     -> UPDATE rides SET status = 'uploaded'
     -> Done. Goto 1.

   On 2xx:
     -> signed_url, server_ride_id available

7. PUT payload to signed_url (gzipped)

8. POST /rides/upload/complete
   Headers: { X-Idempotency-Key: ride_id }
   Body: { ride_metadata, device_info, quality_report }

   On 2xx:
     -> UPDATE upload_queue SET status = 'uploaded', server_ride_id = response.ride_id
     -> UPDATE rides SET status = 'uploaded', upload_id = response.ride_id
     -> Done. Goto 1.

   On 4xx (client error, non-retryable):
     -> UPDATE upload_queue SET status = 'failed_permanent', last_error = response.detail
     -> Surface to user.
     -> Goto 1.

   On 5xx / network error / timeout:
     -> attempt_count += 1
     -> If attempt_count >= MAX_ATTEMPTS:
          status = 'failed_permanent'
        Else:
          status = 'failed_retryable'
          next_retry_at = computeNextRetry(attempt_count)
     -> UPDATE upload_queue
     -> Goto 1.
```

### 4.4 Backend Dedup Layers

The server has three layers of dedup protection. The mobile app needs to be aware of all three:

| Layer | Mechanism | When | Mobile Handling |
|-------|-----------|------|-----------------|
| 1. `X-Idempotency-Key` | Backend stores key -> result mapping | During `/init` and `/complete` | Send ride UUID as key. On 409, treat as success. |
| 2. `file_hash` | SHA256 of payload, checked against `rides.file_hash` | During `/init` | Compute before upload. On 409, treat as success. |
| 3. `vault_completions` UNIQUE | `(vault_signature, activity_id)` constraint | During ride processing | Transparent to mobile. Server handles. |

### 4.5 Failed Upload User Experience

After `MAX_ATTEMPTS` (10) failures:

```
RIDE HISTORY SCREEN:
  +----------------------------------------------+
  |  [!] Morning Ride - Mar 28                   |
  |  42.3 km | 1:45:12 | 687 m                  |
  |  Upload failed. Tap to retry.                |
  +----------------------------------------------+

TAP -> OPTIONS:
  [Retry Upload]   -- Reset to pending, attempt_count = 0
  [Export as FIT]   -- Generate FIT file from SQLite data, save to device Files
  [Delete Ride]     -- Confirmation -> delete from SQLite
```

**FIT export** is a v1.1 feature. For v1, "Retry" and "Delete" are sufficient.

---

## 5. Background Recording

### 5.1 Platform-Specific Background Execution

#### iOS

**Required background modes** (already declared in `app.json`):

```json
{
  "ios": {
    "infoPlist": {
      "UIBackgroundModes": ["location", "processing"],
      "NSLocationAlwaysAndWhenInUseUsageDescription": "BoulderRoller records your GPS location to track your ride, detect climbs, and calculate your effort score.",
      "NSLocationWhenInUseUsageDescription": "BoulderRoller needs your location to record your ride."
    }
  }
}
```

**How `react-native-background-geolocation` handles iOS background:**
- Uses `CLLocationManager` with `allowsBackgroundLocationUpdates = true`.
- The OS keeps the app alive as long as location updates are being delivered.
- When the user locks the screen, location updates continue via the background location mode.
- If iOS suspends the app (memory pressure), the library uses **significant location change monitoring** as a fallback, which wakes the app for each ~500m movement. This is coarser but prevents total data loss.
- On iOS 16.1+: **Live Activities** keep the app more reliably in the foreground of the OS task scheduler.

**What we must do:**
1. Configure `BackgroundGeolocation` with `preventSuspend: true` (uses silent audio or BLE tricks to prevent suspension on older iOS versions).
2. Implement Live Activities (via `expo-live-activity` or native module) to display ride stats on the lock screen and Dynamic Island. This also signals to iOS that the app is actively used, reducing suspension risk.

#### Android

**Required permissions:**

```json
{
  "android": {
    "permissions": [
      "ACCESS_FINE_LOCATION",
      "ACCESS_COARSE_LOCATION",
      "ACCESS_BACKGROUND_LOCATION",
      "FOREGROUND_SERVICE",
      "FOREGROUND_SERVICE_LOCATION",
      "POST_NOTIFICATIONS"
    ]
  }
}
```

**How `react-native-background-geolocation` handles Android background:**
- Starts a **foreground service** with a persistent notification (required by Android 8+).
- The notification shows ride status (recording/paused) and basic stats.
- Foreground services are not subject to background execution limits.
- The library handles battery optimization exemptions (prompts the user to disable battery optimization for the app if needed).

**What we must configure:**
1. Foreground service notification: channel name "Ride Recording", icon, and text showing elapsed time + distance.
2. `BackgroundGeolocation` config: `foregroundService: true`, `notification: { title: 'Recording ride', text: '{distance} km | {duration}' }`.

### 5.2 GPS Configuration for Cycling

```typescript
// services/recording/gpsConfig.ts

const CYCLING_GPS_CONFIG = {
  // Accuracy
  desiredAccuracy: BackgroundGeolocation.DESIRED_ACCURACY_HIGH,
  distanceFilter: 5,              // Minimum 5m between events (prevents stationary jitter)

  // Frequency
  locationUpdateInterval: 1000,    // Android: 1Hz target
  fastestLocationUpdateInterval: 500, // Android: accept faster if available

  // Background behavior
  stopOnTerminate: false,          // Continue recording if app is terminated
  startOnBoot: false,              // Do NOT auto-start on device boot
  preventSuspend: true,            // iOS: prevent app suspension during ride

  // Motion detection (for auto-pause)
  isMoving: true,                  // Start in moving state
  stationaryRadius: 10,            // 10m radius for stationary detection
  stopTimeout: 10,                 // 10 seconds stationary before auto-pause triggers

  // Battery optimization
  disableElasticity: true,         // Disable distance-based sample thinning (we want 1Hz)
  heartbeatInterval: 60,           // iOS: heartbeat every 60s when stationary (keeps app alive)

  // Data
  extras: {},                      // We don't use the library's extras field
  persist: true,                   // Library persists locations internally (for crash recovery)
  autoSync: false,                 // We handle upload ourselves
  maxRecordsToPersist: 0,         // -1 = unlimited. 0 = don't persist (we persist ourselves). NOTE: set to -1 if we want library crash recovery.
};
```

**Battery impact target:** < 8% per hour of recording (per MOBILE_UX_DEEP_RESEARCH.md, citing Strava's benchmark).

**Key tradeoff: `maxRecordsToPersist`:**
- Set to `0` = the library does not persist locations internally; we persist them ourselves in our SQLite.
- Set to `-1` = the library persists ALL locations; we can recover them after a crash (see Section 3.3).
- **Recommendation:** Set to `-1`. The redundant storage (~2MB for a 4-hour ride) is negligible. It gives us a crash recovery safety net for samples in our 10-second buffer gap.

**Revised config:** `maxRecordsToPersist: -1` (override the `0` above).

### 5.3 What Happens When iOS Suspends the App

Even with `preventSuspend: true`, iOS can suspend the app under extreme memory pressure or if the user force-quits from the app switcher.

| Event | Library Behavior | Our Data |
|-------|-----------------|----------|
| iOS suspends (memory pressure) | Falls back to significant location change (~500m) | 1Hz GPS lost; ~500m resolution until app resumes. Library persists these coarse locations. |
| User force-quits from app switcher | `stopOnTerminate: false` -> library continues via significant location change | Same coarse locations. On next app launch, we recover what we can. |
| iOS terminates (extended background) | Same as force-quit | Same. |
| Phone locked (screen off) | No change. Background location mode keeps 1Hz. | Full 1Hz GPS continues. |
| Phone enters Low Power Mode | iOS may throttle location to ~1/min | Significant data gaps. We record whatever iOS provides. Ride is still recoverable but lower quality. |

**User education:** During ride start, if Low Power Mode is detected, show a non-blocking banner: "Low Power Mode may reduce GPS accuracy. Consider disabling it for this ride."

### 5.4 Auto-Pause

**Trigger:** GPS reports stationary for 10 consecutive seconds (speed < 0.5 m/s AND distance < 2m).

**Implementation:** Handled by `react-native-background-geolocation`'s motion detection (`stopTimeout: 10`). When the library fires `onMotionChange(isMoving: false)`:

1. Insert `pause_events` row: `{ event_type: 'auto_pause', t_offset_ms: current }`.
2. Update Zustand recording store: `isPaused: true`.
3. UI: dim screen, show "PAUSED" banner, play subtle audio chime (if enabled).
4. Stop accumulating `duration_ms` (but continue writing GPS samples for crash safety).

**Resume:** When `onMotionChange(isMoving: true)`:
1. Insert `pause_events` row: `{ event_type: 'resume', t_offset_ms: current }`.
2. Update store: `isPaused: false`.
3. Resume `duration_ms` accumulation.
4. Play resume chime.

---

## 6. Backend Integration Points

### 6.1 New Backend Endpoint: Mobile Ride Upload

The existing `/rides/upload` endpoint accepts base64-encoded FIT/GPX/TCX files. The mobile app uploads a JSON payload of raw samples instead. A new endpoint is needed.

**Endpoint:** `POST /rides/upload/mobile`

**Request:**
```
Content-Type: application/json
Content-Encoding: gzip
X-Idempotency-Key: {client_ride_id}
Authorization: Bearer {access_token}

Body: RideUploadPayload (see Section 4.2)
```

**Server processing:**
1. Validate idempotency key (check for existing ride with this `client_ride_id`).
2. Validate `file_hash` (check for existing ride with this hash for this user).
3. Convert JSON GPS samples to `activity_tile_samples` format (project to H3 tiles, compute elevation).
4. Store raw JSON payload in Supabase Storage (same path pattern: `rides/{user_id}/{ride_id}.json`).
5. Create `rides` row with `source = 'mobile'`.
6. Enqueue for canonical ride processing (same pipeline as FIT/GPX uploads).

**The server-side validation pipeline applies the full suite** from Section 1.1 (per-step distance cap, VAM cap, gradient cap, frequency check, etc.) before climb detection runs.

### 6.2 Server-Side Idempotency Key Storage

Add to rides table:

```sql
ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS client_ride_id TEXT,
    ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'file';  -- file | mobile | strava

CREATE UNIQUE INDEX IF NOT EXISTS idx_rides_client_ride_id
    ON rides(user_id, client_ride_id)
    WHERE client_ride_id IS NOT NULL;
```

The `(user_id, client_ride_id)` unique index ensures the same device-generated UUID cannot create two rides for the same user, even across retries.

### 6.3 HMAC Payload Signing (v1.1)

**Not in v1 scope.** Documented here for completeness.

The upload payload should be HMAC-signed with a device-specific key to prevent tampering between recording and upload. The key would be derived from the Privy embedded wallet's signing capability:

```
signature = HMAC-SHA256(
  key = privy_wallet.sign(DOMAIN_SEPARATOR),
  message = SHA256(serialized_payload)
)
```

Server verifies by reconstructing the signature using the user's on-chain public key.

This prevents a sophisticated attacker from modifying the JSON payload in transit (beyond what TLS already provides) and provides non-repudiation tied to the user's wallet identity.

---

## Appendix A: Data Flow Diagram

```
DEVICE                                          SERVER
------                                          ------

[GPS Chip / BLE Sensors]
       |
       v
[react-native-background-geolocation]
       |
       v
[Validation Pipeline (Section 1.2)]
  reject bad samples
       |
       v
[In-Memory Buffer (max 10 samples)]
       |  every 10 seconds
       v
[SQLite: gps_samples + sensor_samples] --------> (crash recovery reads from here)
       |
       v (on ride stop)
[Serialize to RideUploadPayload]
[Compute file_hash = SHA256(payload)]
       |
       v
[Upload Queue (SQLite)]
       |
       v (when online)
[POST /rides/upload/mobile]  ---- X-Idempotency-Key ---->  [Dedup Check]
       |                                                        |
       v                                                        v
[Receive server_ride_id]                          [Store raw JSON in Supabase Storage]
[Mark upload complete]                            [Project GPS -> H3 tiles]
                                                  [Server-side validation (Section 1.1)]
                                                  [canonical_v2 climb detection]
                                                  [Vault matching (GPS-gated DCT-II)]
                                                  [On-chain completions]
                                                  [CAL allocation]
                                                  [Push notification -> device]
```

## Appendix B: SQLite Schema ER Diagram

```
rides (1) ──────< (N) gps_samples
  |
  +────────────< (N) sensor_samples
  |
  +────────────< (N) pause_events
  |
  +── (1:1) ──── upload_queue
```

## Appendix C: Validation Constants (Aligned with `workout-parse/src/climb/utils.rs`)

| Constant | Value | Source |
|----------|-------|--------|
| Max cycling speed | 50 m/s (180 km/h) | `MAX_STEP_DISTANCE_M = 500m` at 1Hz ~ 500 m/s, but we use instantaneous speed check at 50 m/s |
| Null Island | (0, 0) | `is_valid_gps()` in utils.rs |
| Lat range | [-90, 90] | `is_valid_gps()` in utils.rs |
| Lon range | [-180, 180] | `is_valid_gps()` in utils.rs |
| Max horizontal accuracy | 100m | Mobile-only (device has accuracy; server does not) |
| Per-step distance cap | 500m | `MAX_STEP_DISTANCE_M` in utils.rs (server-side) |
| Max VAM | 2500 m/hr | Server-side (persistence.rs quality filter) |
| Max gradient | 45% | Server-side (persistence.rs quality filter) |
| Smoothing window | SMA(5) for climb detection | `SMOOTHING_WINDOW = 5` in constants.rs |
| Ride-level elevation smoothing | SMA(21) | Server-side |
| GPS sample rate | 1 Hz target | `locationUpdateInterval: 1000` |
| Sample buffer size | 10 (flush every 10s) | Application constant |
| Auto-pause threshold | 10s stationary | `stopTimeout: 10` |
| Clock drift tolerance | 60s (warn), 48hr (flag) | NTP check (device), upload delta (server) |
| Barometric calibration window | 100m distance / 180s time | `STARTUP_MIN_DISTANCE_M`, `STARTUP_MAX_WINDOW_S` in utils.rs |
