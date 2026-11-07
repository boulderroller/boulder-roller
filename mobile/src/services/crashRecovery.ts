/**
 * Crash recovery — interrupted-ride detection, save-and-upload, discard.
 *
 * Runs once at app boot from AuthInitializer. When an active ride row is
 * found at startup (meaning a previous session was killed mid-recording),
 * we mark had_crash_recovery=1 immediately so the ride row carries the
 * breadcrumb, then hand the caller the row so it can drive the recovery
 * modal UX.
 *
 * saveInterruptedRide stamps the preliminary ride hash + parser_version
 * on the row BEFORE enqueueing. Without this, recovered rides reach the
 * backend with null preliminary provenance, so when the backend-side
 * compare loop runs it will have nothing to verify against.
 */

import {
  getDatabase,
  getActiveRide,
  updateRide,
  deleteRide,
  type RideRow,
} from './database';
import { enqueueRide } from './uploadQueue';
import { computePreliminaryHash } from '../lib/preliminaryHash';
import {
  recordRideValidationEvent,
  rideHashBytesToHex,
} from '../lib/rideValidation';

/**
 * Detect an interrupted ride from a prior session (if any), mark the row
 * as recovered (had_crash_recovery=1), and return the updated RideRow.
 * Returns null when no active ride is pending recovery.
 */
export function detectInterruptedRide(): RideRow | null {
  const db = getDatabase();
  const active = getActiveRide(db);
  if (!active) return null;
  updateRide(db, active.id, { had_crash_recovery: 1 });
  recordRideValidationEvent(db, active.id, 'crash_recovery_detected', {
    previousStatus: active.status,
    sampleCount: active.sample_count,
    startedAt: active.started_at,
  });
  return { ...active, had_crash_recovery: 1 };
}

/**
 * Stop-equivalent finalize for a recovered ride: compute and stamp the
 * preliminary hash + parser_version, flip status to 'stopped', set
 * ended_at, then enqueue. Mirrors the normal stopRecording finalize
 * flow so recovered rides reach the backend with the same attestation
 * envelope shape as rides stopped cleanly.
 */
export async function saveInterruptedRide(rideId: string): Promise<void> {
  const db = getDatabase();
  const { rideHash, parserVersion } = await computePreliminaryHash(rideId);
  updateRide(db, rideId, {
    status: 'stopped',
    ended_at: Date.now(),
    preliminary_ride_hash: rideHash,
    parser_version: parserVersion,
  });
  recordRideValidationEvent(db, rideId, 'recording_stopped', {
    recovered: true,
    parserVersion,
    parserVersionPresent: parserVersion != null,
    preliminaryRideHashPresent: rideHash != null,
    preliminaryRideHashHex: rideHashBytesToHex(rideHash),
  });
  enqueueRide(rideId);
}

/** Permanently drop a recovered ride — deletes samples via CASCADE. */
export function discardInterruptedRide(rideId: string): void {
  const db = getDatabase();
  deleteRide(db, rideId);
}
