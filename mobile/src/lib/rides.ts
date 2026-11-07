/**
 * Ride archive helpers — local-truth-first.
 *
 * The rider's device-side database is canonical for their own ride
 * history until the backend closes the attestation loop (MOBILE_TRUTHS
 * §9.1). This module reads local rides out of SQLite and, when the
 * network cooperates, merges them with the server's projection of the
 * same rides.
 *
 * Every value surfaced to the UI must survive offline. If a ride lives
 * only in local storage, we still show it. If a ride lives only on the
 * server (e.g., imported from Strava on another device), we show that
 * too. When both sides hold the same ride, local state preserves the
 * local row identifier so tap-through into the detail screen resolves
 * back to the local database — server metadata decorates but never
 * replaces local truth.
 *
 * Naming follows MOBILE_TRUTHS §12: "Ride", not "activity" / "workout".
 */
import type { SQLiteDatabase } from 'expo-sqlite';

import type { RideMedia, RideSummary } from './api';
import { buildRoutePreviewFromGps, type RoutePreview } from './routePreview';
import { getCurrentLocalRideOwnerKey } from '../stores/authStore';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Shape of a locally-recorded ride as joined with upload_queue. The
 * server-side identifier is lifted out of upload_queue so that
 * deduplication against the server projection can happen purely in
 * memory.
 */
export interface LocalRideSummary {
  /** Local primary key — used for RideDetail navigation. */
  id: string;
  /** Device wall-clock timestamp (ms) when recording started. */
  startedAt: number;
  /** Ride status in the local state machine ('stopped', 'uploaded', 'incomplete'). */
  status: string;
  durationMs: number;
  movingTimeMs: number;
  distanceM: number;
  elevationGainM: number;
  maxSpeedMps: number;
  sampleCount: number;
  /** Upload handoff identifier. Null until the backend accepts the file. */
  uploadId: string | null;
  /** Server's ride id once the upload completes. Null while offline. */
  serverRideId: string | null;
  /** True if the server has acknowledged receipt of this ride. */
  uploaded: boolean;
  uploadStatus: string | null;
  uploadLastError: string | null;
  uploadAttemptCount: number | null;
  rejectedSamples: string | null;
  hadCrashRecovery: boolean;
  routePreview: RoutePreview | null;
}

/**
 * Unified ride row used by the HomeScreen archive list. A row can be
 * local-only, server-only, or merged; the source field keeps that
 * provenance visible to both the UI and future attestation-state work.
 */
export interface MergedRide {
  /** Stable key for React lists — prefers local id, falls back to server id. */
  key: string;
  /** Which sources contributed to this row. */
  source: 'local' | 'server' | 'merged';
  /** Local ride id (when present) — required to open the detail screen offline. */
  localRideId: string | null;
  /** Server ride id (when present) — used for CAL / processing lookups. */
  serverRideId: string | null;
  /** Ride start time, normalized to epoch ms for sort stability. */
  startedAtMs: number;
  /** ISO string surface for display, preferring server-supplied value. */
  startedAtIso: string;
  distanceM: number;
  elevationGainM: number;
  durationSec: number;
  /** TSS is server-computed — null when we only have local data. */
  tss: number | null;
  /** Local ride status string, forwarded for UI affordances. */
  localStatus: string | null;
  localSampleCount: number | null;
  localRejectedSamples: string | null;
  hadCrashRecovery: boolean;
  uploadStatus: string | null;
  uploadLastError: string | null;
  uploadAttemptCount: number | null;
  routePreview: RoutePreview | null;
  media?: RideMedia[];
}

// ---------------------------------------------------------------------------
// Local SQLite access
// ---------------------------------------------------------------------------

/** Raw row shape returned by the LEFT JOIN below. */
interface LocalRideJoinRow {
  id: string;
  status: string;
  started_at: number;
  duration_ms: number;
  moving_time_ms: number;
  distance_m: number;
  elevation_gain_m: number;
  max_speed_mps: number;
  sample_count: number;
  rejected_samples: string | null;
  had_crash_recovery: number | null;
  upload_id: string | null;
  server_ride_id: string | null;
  upload_status: string | null;
  upload_last_error: string | null;
  upload_attempt_count: number | null;
}

interface LocalPreviewSampleRow {
  ride_id: string;
  latitude: number | null;
  longitude: number | null;
}

/**
 * Load local rides the rider has finished recording. Rides in the
 * "recording" or "paused" state are still in-flight and excluded — the
 * Record tab owns those.
 *
 * Results are newest-first by start time so the archive reads as a
 * reverse-chronological feed without further sorting.
 */
export function loadLocalRides(db: SQLiteDatabase): LocalRideSummary[] {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) return [];
  const rows = db.getAllSync<LocalRideJoinRow>(
    `SELECT
       r.id,
       r.status,
       r.started_at,
       r.duration_ms,
       r.moving_time_ms,
       r.distance_m,
       r.elevation_gain_m,
       r.max_speed_mps,
       r.sample_count,
       r.rejected_samples,
       r.had_crash_recovery,
       r.upload_id,
       u.server_ride_id AS server_ride_id,
       u.status         AS upload_status,
       u.last_error     AS upload_last_error,
       u.attempt_count  AS upload_attempt_count
     FROM rides r
     LEFT JOIN upload_queue u ON u.ride_id = r.id
     WHERE r.owner_key = ?
       AND r.status IN ('stopped', 'uploaded', 'incomplete')
     ORDER BY r.started_at DESC`,
    [ownerKey],
  );

  const previews = loadLocalRoutePreviews(
    db,
    rows.map((row) => row.id),
    ownerKey,
  );
  return rows.map((row) => toLocalRideSummary(row, previews.get(row.id) ?? null));
}

function loadLocalRoutePreviews(
  db: SQLiteDatabase,
  rideIds: string[],
  ownerKey: string,
): Map<string, RoutePreview> {
  if (!rideIds.length) return new Map();

  const placeholders = rideIds.map(() => '?').join(', ');
  const rows = db.getAllSync<LocalPreviewSampleRow>(
    `SELECT g.ride_id, g.latitude, g.longitude
     FROM gps_samples g
     INNER JOIN rides r ON r.id = g.ride_id
     WHERE r.owner_key = ?
       AND g.ride_id IN (${placeholders})
     ORDER BY g.ride_id, g.t_offset_ms`,
    [ownerKey, ...rideIds],
  );

  const samplesByRideId = new Map<string, LocalPreviewSampleRow[]>();
  for (const row of rows) {
    const samples = samplesByRideId.get(row.ride_id) ?? [];
    samples.push(row);
    samplesByRideId.set(row.ride_id, samples);
  }

  const previews = new Map<string, RoutePreview>();
  for (const [rideId, samples] of samplesByRideId) {
    const preview = buildRoutePreviewFromGps(samples, { source: 'local_gps' });
    if (preview) previews.set(rideId, preview);
  }
  return previews;
}

function toLocalRideSummary(row: LocalRideJoinRow, routePreview: RoutePreview | null): LocalRideSummary {
  return {
    id: row.id,
    startedAt: row.started_at,
    status: row.status,
    durationMs: row.duration_ms,
    movingTimeMs: row.moving_time_ms,
    distanceM: row.distance_m,
    elevationGainM: row.elevation_gain_m,
    maxSpeedMps: row.max_speed_mps,
    sampleCount: row.sample_count,
    uploadId: row.upload_id,
    serverRideId: row.server_ride_id,
    // Either the ride row itself or the upload queue has seen the
    // server accept the file. Either signal counts as "uploaded" for
    // the archive view.
    uploaded: row.status === 'uploaded' || row.upload_status === 'uploaded',
    uploadStatus: row.upload_status,
    uploadLastError: row.upload_last_error,
    uploadAttemptCount: row.upload_attempt_count,
    rejectedSamples: row.rejected_samples,
    hadCrashRecovery: !!row.had_crash_recovery,
    routePreview,
  };
}

// ---------------------------------------------------------------------------
// Merge
// ---------------------------------------------------------------------------

/**
 * Merge local and server ride projections into a single list.
 *
 * Dedup rule: a local ride with a populated serverRideId matches the
 * server row with the same id. When both are present we prefer server
 * metadata for display (TSS is only computable server-side) but keep
 * the localRideId so the rider can still open the ride offline.
 *
 * Server-only rides — e.g., imports from Strava on another device,
 * or rides whose local storage was wiped — remain in the list so the
 * rider never loses visibility of their history.
 *
 * Null / empty server input is a no-op: the rider still sees their
 * local archive. This is MOBILE_TRUTHS §8 "Offline Is Normal" in
 * code form.
 */
export function mergeRideSources(
  locals: LocalRideSummary[],
  servers: RideSummary[] | null,
): MergedRide[] {
  const serverById = new Map<string, RideSummary>();
  if (servers) {
    for (const s of servers) {
      serverById.set(s.id, s);
    }
  }

  const merged: MergedRide[] = [];
  const consumedServerIds = new Set<string>();

  for (const local of locals) {
    const matched = local.serverRideId
      ? serverById.get(local.serverRideId)
      : undefined;

    if (matched) {
      consumedServerIds.add(matched.id);
      merged.push({
        key: local.id,
        source: 'merged',
        localRideId: local.id,
        serverRideId: matched.id,
        startedAtMs: parseStartedAt(matched.startedAt, local.startedAt),
        startedAtIso: matched.startedAt,
        distanceM: matched.distanceM,
        elevationGainM: matched.elevationGainM,
        durationSec: matched.durationSec,
        tss: matched.tss,
        localStatus: local.status,
        localSampleCount: local.sampleCount,
        localRejectedSamples: local.rejectedSamples,
        hadCrashRecovery: local.hadCrashRecovery,
        uploadStatus: local.uploadStatus,
        uploadLastError: local.uploadLastError,
        uploadAttemptCount: local.uploadAttemptCount,
        routePreview: matched.routePreview ?? local.routePreview,
        media: matched.media ?? [],
      });
    } else {
      merged.push({
        key: local.id,
        source: 'local',
        localRideId: local.id,
        serverRideId: local.serverRideId,
        startedAtMs: local.startedAt,
        startedAtIso: new Date(local.startedAt).toISOString(),
        distanceM: local.distanceM,
        elevationGainM: local.elevationGainM,
        durationSec: Math.floor(local.durationMs / 1000),
        tss: null,
        localStatus: local.status,
        localSampleCount: local.sampleCount,
        localRejectedSamples: local.rejectedSamples,
        hadCrashRecovery: local.hadCrashRecovery,
        uploadStatus: local.uploadStatus,
        uploadLastError: local.uploadLastError,
        uploadAttemptCount: local.uploadAttemptCount,
        routePreview: local.routePreview,
        media: [],
      });
    }
  }

  if (servers) {
    for (const server of servers) {
      if (consumedServerIds.has(server.id)) continue;
      merged.push({
        key: `srv:${server.id}`,
        source: 'server',
        localRideId: null,
        serverRideId: server.id,
        startedAtMs: parseStartedAt(server.startedAt, 0),
        startedAtIso: server.startedAt,
        distanceM: server.distanceM,
        elevationGainM: server.elevationGainM,
        durationSec: server.durationSec,
        tss: server.tss,
        localStatus: null,
        localSampleCount: null,
        localRejectedSamples: null,
        hadCrashRecovery: false,
        uploadStatus: null,
        uploadLastError: null,
        uploadAttemptCount: null,
        routePreview: server.routePreview ?? null,
        media: server.media ?? [],
      });
    }
  }

  // Reverse-chronological: newest rides surface first, matching the
  // ordering riders expect from a training log.
  merged.sort((a, b) => b.startedAtMs - a.startedAtMs);
  return merged;
}

/**
 * Parse a server-supplied ISO timestamp to epoch ms with a safe fallback.
 * Server timestamps have been observed to arrive as ISO strings; if one
 * fails to parse we prefer the local wall-clock value rather than
 * anchoring the row to 1970 and wrecking sort order.
 */
function parseStartedAt(iso: string | undefined, fallbackMs: number): number {
  if (!iso) return fallbackMs;
  const parsed = Date.parse(iso);
  return Number.isNaN(parsed) ? fallbackMs : parsed;
}
