/**
 * SQLite Database Service
 *
 * Uses expo-sqlite with WAL journal mode for crash-safe ride recording.
 * Schema is versioned via PRAGMA user_version with a migration runner.
 *
 * Tables: rides, gps_samples, pause_events, upload_queue
 * Batch writes every 10 seconds (10 samples at 1Hz).
 *
 * Per MOBILE_PHASE0_RESOLUTIONS.md FIX-1: expo-sqlite, not op-sqlite.
 */

import { openDatabaseSync, type SQLiteDatabase } from 'expo-sqlite';

import {
  getCurrentLocalRideOwnerKey,
  requireCurrentLocalRideOwnerKey,
} from '../stores/authStore';
import { getOrCreateDbEncryptionKey } from './secureStorage';

const DB_NAME = 'boulderroller.db';

let _db: SQLiteDatabase | null = null;

// ---------------------------------------------------------------------------
// Migration definitions
// ---------------------------------------------------------------------------

interface Migration {
  version: number;
  up: string[];
}

const MIGRATIONS: Migration[] = [
  {
    version: 1,
    up: [
      // rides table (v1 schema)
      `CREATE TABLE IF NOT EXISTS rides (
        id                TEXT PRIMARY KEY,
        status            TEXT NOT NULL DEFAULT 'recording',
        started_at        INTEGER NOT NULL,
        ended_at          INTEGER,
        duration_ms       INTEGER NOT NULL DEFAULT 0,
        moving_time_ms    INTEGER NOT NULL DEFAULT 0,
        distance_m        REAL NOT NULL DEFAULT 0,
        elevation_gain_m  REAL NOT NULL DEFAULT 0,
        max_speed_mps     REAL NOT NULL DEFAULT 0,
        sport_type        TEXT NOT NULL DEFAULT 'ride',
        clock_drift_ms    INTEGER,
        sample_count      INTEGER NOT NULL DEFAULT 0,
        rejected_samples  TEXT,
        upload_id         TEXT,
        notes             TEXT,
        created_at        INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000),
        updated_at        INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
      )`,

      // Only one active ride at a time
      `CREATE UNIQUE INDEX IF NOT EXISTS idx_rides_active
        ON rides(status) WHERE status IN ('recording', 'paused')`,

      // gps_samples table
      `CREATE TABLE IF NOT EXISTS gps_samples (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ride_id         TEXT NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
        t_offset_ms     INTEGER NOT NULL,
        latitude        REAL NOT NULL,
        longitude       REAL NOT NULL,
        altitude_m      REAL,
        accuracy_m      REAL NOT NULL,
        vert_accuracy_m REAL,
        speed_mps       REAL,
        bearing_deg     REAL,
        source          TEXT NOT NULL DEFAULT 'fused'
      )`,

      `CREATE INDEX IF NOT EXISTS idx_gps_samples_ride_time
        ON gps_samples(ride_id, t_offset_ms)`,

      // pause_events table
      `CREATE TABLE IF NOT EXISTS pause_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ride_id     TEXT NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
        event_type  TEXT NOT NULL,
        t_offset_ms INTEGER NOT NULL,
        reason      TEXT
      )`,

      `CREATE INDEX IF NOT EXISTS idx_pause_events_ride
        ON pause_events(ride_id, t_offset_ms)`,

      // upload_queue table
      `CREATE TABLE IF NOT EXISTS upload_queue (
        id              TEXT PRIMARY KEY,
        ride_id         TEXT NOT NULL UNIQUE REFERENCES rides(id) ON DELETE CASCADE,
        status          TEXT NOT NULL DEFAULT 'pending',
        file_hash       TEXT,
        attempt_count   INTEGER NOT NULL DEFAULT 0,
        max_attempts    INTEGER NOT NULL DEFAULT 10,
        next_retry_at   INTEGER,
        last_error      TEXT,
        server_ride_id  TEXT,
        created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000),
        updated_at      INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
      )`,

      `CREATE INDEX IF NOT EXISTS idx_upload_queue_next
        ON upload_queue(status, next_retry_at)
        WHERE status IN ('pending', 'failed_retryable')`,
    ],
  },
  {
    version: 2,
    up: [
      // TRUTHS §6.9 Obligation 2: preliminary canonical hash stored for
      // the device-side half of the attestation loop. Backend compare /
      // re-canonicalization lands separately; on the mobile side we only
      // persist the input to that compare.
      `ALTER TABLE rides ADD COLUMN preliminary_ride_hash BLOB`,
      // Parser version stamped at ride stop (§6.9 Obligation 3)
      `ALTER TABLE rides ADD COLUMN parser_version INTEGER`,
      // Crash recovery breadcrumb (§6.9 Obligation 5)
      `ALTER TABLE rides ADD COLUMN had_crash_recovery INTEGER NOT NULL DEFAULT 0`,
    ],
  },
  {
    version: 3,
    up: [
      // BLE sensor snapshot columns. Each row is merged on the 1 Hz GPS tick
      // from SensorRegistry.getLatest*(). Null when no connected source.
      `ALTER TABLE gps_samples ADD COLUMN power_w INTEGER`,
      `ALTER TABLE gps_samples ADD COLUMN heart_rate_bpm INTEGER`,
      `ALTER TABLE gps_samples ADD COLUMN cadence_rpm INTEGER`,
    ],
  },
  {
    version: 4,
    up: [
      // M1/M2 validation evidence. This is local QA telemetry, not product
      // state: it lets a physical device run prove stop timing, upload
      // handshake provenance, and crash/GPS honesty without screenshots
      // or guesswork.
      `CREATE TABLE IF NOT EXISTS ride_validation_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ride_id     TEXT NOT NULL REFERENCES rides(id) ON DELETE CASCADE,
        event_type  TEXT NOT NULL,
        occurred_at INTEGER NOT NULL,
        metadata    TEXT
      )`,
      `CREATE INDEX IF NOT EXISTS idx_ride_validation_events_ride_time
        ON ride_validation_events(ride_id, occurred_at)`,
    ],
  },
  {
    version: 5,
    up: [
      // Local rides are account-scoped, not device-global. Existing rows stay
      // NULL and therefore remain quarantined until an explicit, trustworthy
      // ownership recovery exists; never infer their owner from who logs in.
      `ALTER TABLE rides ADD COLUMN owner_key TEXT
        CHECK (owner_key IS NULL OR length(trim(owner_key)) > 0)`,
      // A stale active ride belonging to account A must not block account B
      // from recording after a switch. Legacy-null rows are not claimable.
      `DROP INDEX IF EXISTS idx_rides_active`,
      `CREATE UNIQUE INDEX idx_rides_active
        ON rides(owner_key)
        WHERE owner_key IS NOT NULL
          AND status IN ('recording', 'paused')`,
      `CREATE INDEX idx_rides_owner_started
        ON rides(owner_key, started_at DESC)
        WHERE owner_key IS NOT NULL`,
    ],
  },
];

// ---------------------------------------------------------------------------
// Database initialization
// ---------------------------------------------------------------------------

/**
 * Initialize the singleton database connection. Async because the SQLCipher
 * passphrase has to be fetched from the keychain (expo-secure-store is
 * async-only). Call once at app boot — AuthInitializer awaits this before
 * any other init step. Idempotent.
 *
 * After init, getDatabase() returns the singleton synchronously.
 */
export async function initDatabase(): Promise<SQLiteDatabase> {
  if (_db) return _db;

  const key = await getOrCreateDbEncryptionKey();
  const db = openDatabaseSync(DB_NAME);

  // PRAGMA key MUST run as the very first statement against an encrypted
  // database, before any other ops including journal_mode setup. SQLCipher
  // derives the encryption key via PBKDF2 here — expensive (intentional)
  // but only on this open. We keep the singleton open for the app lifetime
  // to avoid paying the derivation cost again. Single-quote-escape defends
  // against future key formats; current base64 is safe but the guard is cheap.
  const escapedKey = key.replace(/'/g, "''");
  db.execSync(`PRAGMA key = '${escapedKey}'`);

  // Standard pragmas for crash safety and performance
  db.execSync('PRAGMA journal_mode = WAL');
  db.execSync('PRAGMA synchronous = NORMAL');
  db.execSync('PRAGMA foreign_keys = ON');
  db.execSync('PRAGMA cache_size = -2000');
  db.execSync('PRAGMA busy_timeout = 5000');

  runMigrations(db);

  _db = db;
  return db;
}

/**
 * Synchronous accessor for the initialized DB. Throws if initDatabase has
 * not been awaited yet — callers in production code rely on AuthInitializer
 * having completed its init flow before any other surface runs.
 */
export function getDatabase(): SQLiteDatabase {
  if (!_db) {
    throw new Error(
      'Database not initialized. Call initDatabase() before any DB access.',
    );
  }
  return _db;
}

/** Test-only: reset the cached singleton so a test can re-init from scratch. */
export function _resetDatabaseForTests(): void {
  _db = null;
}

/**
 * Run pending schema migrations.
 * Uses PRAGMA user_version as the version tracker.
 */
function runMigrations(db: SQLiteDatabase): void {
  const result = db.getFirstSync<{ user_version: number }>(
    'PRAGMA user_version',
  );
  const currentVersion = result?.user_version ?? 0;

  for (const migration of MIGRATIONS) {
    if (migration.version > currentVersion) {
      db.withTransactionSync(() => {
        for (const sql of migration.up) {
          db.execSync(sql);
        }
        db.execSync(`PRAGMA user_version = ${migration.version}`);
      });
    }
  }
}

// ---------------------------------------------------------------------------
// Ride CRUD operations
// ---------------------------------------------------------------------------

export interface RideRow {
  id: string;
  /** Present on schema-v5 rows; legacy/test fixtures may omit it. */
  owner_key?: string | null;
  status: string;
  started_at: number;
  ended_at: number | null;
  duration_ms: number;
  moving_time_ms: number;
  distance_m: number;
  elevation_gain_m: number;
  max_speed_mps: number;
  sport_type: string;
  clock_drift_ms: number | null;
  sample_count: number;
  rejected_samples: string | null;
  upload_id: string | null;
  notes: string | null;
  preliminary_ride_hash: Uint8Array | null;
  parser_version: number | null;
  had_crash_recovery: number;
}

export interface GPSSampleRow {
  id?: number;
  ride_id: string;
  t_offset_ms: number;
  latitude: number;
  longitude: number;
  altitude_m: number | null;
  accuracy_m: number;
  vert_accuracy_m: number | null;
  speed_mps: number | null;
  bearing_deg: number | null;
  source: string;
  /** Instantaneous power from a connected power meter, null if none. */
  power_w?: number | null;
  /** Heart rate from a connected HR strap, null if none. */
  heart_rate_bpm?: number | null;
  /** Cadence (power source preferred, CSC fallback), null if none. */
  cadence_rpm?: number | null;
}

export interface PauseEventRow {
  ride_id: string;
  event_type: string;
  t_offset_ms: number;
  reason: string | null;
}

export interface UploadQueueRow {
  id: string;
  ride_id: string;
  status: string;
  file_hash: string | null;
  attempt_count: number;
  max_attempts: number;
  next_retry_at: number | null;
  last_error: string | null;
  server_ride_id: string | null;
  created_at: number;
  updated_at: number;
}

export interface RideValidationEventRow {
  id?: number;
  ride_id: string;
  event_type: string;
  occurred_at: number;
  metadata: string | null;
}

/** Create a new ride row. */
export function createRide(db: SQLiteDatabase, id: string, startedAt: number): void {
  const ownerKey = requireCurrentLocalRideOwnerKey();
  db.runSync(
    `INSERT INTO rides (id, owner_key, status, started_at)
     VALUES (?, ?, 'recording', ?)`,
    [id, ownerKey, startedAt],
  );
}

/** Get a ride by ID. */
export function getRide(db: SQLiteDatabase, id: string): RideRow | null {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return null;
  return db.getFirstSync<RideRow>(
    'SELECT * FROM rides WHERE id = ? AND owner_key = ?',
    [id, ownerKey],
  );
}

/** Find any active (recording or paused) ride. */
export function getActiveRide(db: SQLiteDatabase): RideRow | null {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return null;
  return db.getFirstSync<RideRow>(
    `SELECT * FROM rides
     WHERE owner_key = ?
       AND status IN ('recording', 'paused')
     LIMIT 1`,
    [ownerKey],
  );
}

/** Update ride status and metadata. */
export function updateRide(
  db: SQLiteDatabase,
  id: string,
  updates: Partial<Pick<
    RideRow,
    'status' | 'ended_at' | 'duration_ms' | 'moving_time_ms' |
    'distance_m' | 'elevation_gain_m' | 'max_speed_mps' | 'sample_count' |
    'rejected_samples' | 'upload_id' | 'notes' |
    'preliminary_ride_hash' | 'parser_version' | 'had_crash_recovery'
  >>,
): void {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return;
  const setClauses: string[] = [];
  const values: unknown[] = [];

  for (const [key, value] of Object.entries(updates)) {
    if (value !== undefined) {
      setClauses.push(`${key} = ?`);
      values.push(value);
    }
  }

  if (setClauses.length === 0) return;

  setClauses.push('updated_at = ?');
  values.push(Date.now());
  values.push(id);
  values.push(ownerKey);

  db.runSync(
    `UPDATE rides SET ${setClauses.join(', ')}
     WHERE id = ? AND owner_key = ?`,
    values as (string | number | null)[],
  );
}

/** Delete a ride and all associated data (CASCADE). */
export function deleteRide(db: SQLiteDatabase, id: string): void {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return;
  db.runSync('DELETE FROM rides WHERE id = ? AND owner_key = ?', [id, ownerKey]);
}

/** Batch insert GPS samples and update ride aggregates in a single transaction. */
export function flushSampleBatch(
  db: SQLiteDatabase,
  rideId: string,
  samples: GPSSampleRow[],
  aggregates: {
    durationMs: number;
    distanceM: number;
    elevationGainM: number;
    maxSpeedMps: number;
    movingTimeMs: number;
  },
): void {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return;
  db.withTransactionSync(() => {
    for (const s of samples) {
      db.runSync(
        `INSERT INTO gps_samples
          (ride_id, t_offset_ms, latitude, longitude, altitude_m,
           accuracy_m, vert_accuracy_m, speed_mps, bearing_deg, source,
           power_w, heart_rate_bpm, cadence_rpm)
         SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
         WHERE EXISTS (
           SELECT 1 FROM rides WHERE id = ? AND owner_key = ?
         )`,
        [
          rideId, s.t_offset_ms, s.latitude, s.longitude, s.altitude_m,
          s.accuracy_m, s.vert_accuracy_m, s.speed_mps, s.bearing_deg, s.source,
          s.power_w ?? null, s.heart_rate_bpm ?? null, s.cadence_rpm ?? null,
          rideId, ownerKey,
        ],
      );
    }

    db.runSync(
      `UPDATE rides SET
        sample_count = sample_count + ?,
        duration_ms = ?,
        moving_time_ms = ?,
        distance_m = ?,
        elevation_gain_m = ?,
        max_speed_mps = MAX(max_speed_mps, ?),
        updated_at = ?
       WHERE id = ? AND owner_key = ?`,
      [
        samples.length,
        aggregates.durationMs,
        aggregates.movingTimeMs,
        aggregates.distanceM,
        aggregates.elevationGainM,
        aggregates.maxSpeedMps,
        Date.now(),
        rideId,
        ownerKey,
      ],
    );
  });
}

/** Get all GPS samples for a ride, ordered by time offset. */
export function getRideSamples(
  db: SQLiteDatabase,
  rideId: string,
): GPSSampleRow[] {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return [];
  return db.getAllSync<GPSSampleRow>(
    `SELECT g.*
     FROM gps_samples g
     INNER JOIN rides r ON r.id = g.ride_id
     WHERE g.ride_id = ? AND r.owner_key = ?
     ORDER BY g.t_offset_ms`,
    [rideId, ownerKey],
  );
}

/** Insert a pause event. */
export function insertPauseEvent(
  db: SQLiteDatabase,
  event: PauseEventRow,
): void {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return;
  db.runSync(
    `INSERT INTO pause_events (ride_id, event_type, t_offset_ms, reason)
     SELECT ?, ?, ?, ?
     WHERE EXISTS (
       SELECT 1 FROM rides WHERE id = ? AND owner_key = ?
     )`,
    [
      event.ride_id,
      event.event_type,
      event.t_offset_ms,
      event.reason,
      event.ride_id,
      ownerKey,
    ],
  );
}

/** Get pause events for a ride. */
export function getPauseEvents(
  db: SQLiteDatabase,
  rideId: string,
): PauseEventRow[] {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return [];
  return db.getAllSync<PauseEventRow>(
    `SELECT p.*
     FROM pause_events p
     INNER JOIN rides r ON r.id = p.ride_id
     WHERE p.ride_id = ? AND r.owner_key = ?
     ORDER BY p.t_offset_ms`,
    [rideId, ownerKey],
  );
}

// ---------------------------------------------------------------------------
// Upload queue operations
// ---------------------------------------------------------------------------

/**
 * Create an upload queue entry. Idempotent — re-enqueueing the same ride
 * (e.g., after crash recovery save-and-upload following a normal stop)
 * silently no-ops instead of throwing on the PK conflict. Existing entry's
 * status / attempt_count / file_hash are preserved; use retryFailedUpload
 * for explicit retry semantics.
 */
export function createUploadEntry(
  db: SQLiteDatabase,
  rideId: string,
): void {
  const ownerKey = requireCurrentLocalRideOwnerKey();
  db.runSync(
    `INSERT OR IGNORE INTO upload_queue (id, ride_id, status)
     SELECT ?, ?, 'pending'
     WHERE EXISTS (
       SELECT 1 FROM rides WHERE id = ? AND owner_key = ?
     )`,
    [rideId, rideId, rideId, ownerKey],
  );
}

/** Get the next upload queue entry that is ready to process. */
export function getNextUploadEntry(db: SQLiteDatabase): UploadQueueRow | null {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return null;
  return db.getFirstSync<UploadQueueRow>(
    `SELECT u.*
     FROM upload_queue u
     INNER JOIN rides r ON r.id = u.ride_id
     WHERE r.owner_key = ?
       AND u.status IN ('pending', 'failed_retryable')
       AND (u.next_retry_at IS NULL OR u.next_retry_at <= ?)
     ORDER BY u.created_at ASC
     LIMIT 1`,
    [ownerKey, Date.now()],
  );
}

/** Get all upload queue entries with a specific status. */
export function getUploadEntriesByStatus(
  db: SQLiteDatabase,
  status: string,
): UploadQueueRow[] {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return [];
  return db.getAllSync<UploadQueueRow>(
    `SELECT u.*
     FROM upload_queue u
     INNER JOIN rides r ON r.id = u.ride_id
     WHERE u.status = ? AND r.owner_key = ?`,
    [status, ownerKey],
  );
}

/** Get the upload queue entry for a local ride, if present. */
export function getUploadEntryForRide(
  db: SQLiteDatabase,
  rideId: string,
): UploadQueueRow | null {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return null;
  return db.getFirstSync<UploadQueueRow>(
    `SELECT u.*
     FROM upload_queue u
     INNER JOIN rides r ON r.id = u.ride_id
     WHERE u.ride_id = ? AND r.owner_key = ?`,
    [rideId, ownerKey],
  );
}

/** Update an upload queue entry. */
export function updateUploadEntry(
  db: SQLiteDatabase,
  id: string,
  updates: Partial<Pick<
    UploadQueueRow,
    'status' | 'file_hash' | 'attempt_count' | 'next_retry_at' |
    'last_error' | 'server_ride_id'
  >>,
): void {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return;
  const setClauses: string[] = [];
  const values: unknown[] = [];

  for (const [key, value] of Object.entries(updates)) {
    if (value !== undefined) {
      setClauses.push(`${key} = ?`);
      values.push(value);
    }
  }

  if (setClauses.length === 0) return;

  setClauses.push('updated_at = ?');
  values.push(Date.now());
  values.push(id);
  values.push(ownerKey);

  db.runSync(
    `UPDATE upload_queue SET ${setClauses.join(', ')}
     WHERE id = ?
       AND EXISTS (
         SELECT 1
         FROM rides r
         WHERE r.id = upload_queue.ride_id AND r.owner_key = ?
       )`,
    values as (string | number | null)[],
  );
}

// ---------------------------------------------------------------------------
// M1/M2 ride validation evidence
// ---------------------------------------------------------------------------

export function insertRideValidationEvent(
  db: SQLiteDatabase,
  rideId: string,
  eventType: string,
  metadata: Record<string, unknown> = {},
  occurredAt: number = Date.now(),
): void {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return;
  db.runSync(
    `INSERT INTO ride_validation_events
      (ride_id, event_type, occurred_at, metadata)
     SELECT ?, ?, ?, ?
     WHERE EXISTS (
       SELECT 1 FROM rides WHERE id = ? AND owner_key = ?
     )`,
    [
      rideId,
      eventType,
      occurredAt,
      JSON.stringify(metadata),
      rideId,
      ownerKey,
    ],
  );
}

export function getRideValidationEvents(
  db: SQLiteDatabase,
  rideId: string,
): RideValidationEventRow[] {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return [];
  return db.getAllSync<RideValidationEventRow>(
    `SELECT v.*
     FROM ride_validation_events v
     INNER JOIN rides r ON r.id = v.ride_id
     WHERE v.ride_id = ? AND r.owner_key = ?
     ORDER BY v.occurred_at ASC, v.id ASC`,
    [rideId, ownerKey],
  );
}

/** Get count of rides pending upload (for badge/indicator). */
export function getPendingUploadCount(db: SQLiteDatabase): number {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return 0;
  const row = db.getFirstSync<{ count: number }>(
    `SELECT COUNT(*) as count
     FROM upload_queue u
     INNER JOIN rides r ON r.id = u.ride_id
     WHERE r.owner_key = ?
       AND u.status IN ('pending', 'failed_retryable', 'failed_auth', 'uploading')`,
    [ownerKey],
  );
  return row?.count ?? 0;
}

// ---------------------------------------------------------------------------
// Cleanup / reset (for testing)
// ---------------------------------------------------------------------------

/** Close the database connection. For testing only. */
export function closeDatabase(): void {
  if (_db) {
    _db.closeSync();
    _db = null;
  }
}
