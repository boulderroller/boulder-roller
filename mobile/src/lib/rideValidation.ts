/**
 * Local ride validation evidence for M1/M2 device gates.
 *
 * This is intentionally local and dev-facing. It records enough facts for a
 * physical ride to prove the recording/upload contract without adding a new
 * backend route or relying on screenshots.
 */

import type { SQLiteDatabase } from 'expo-sqlite';

import * as Database from '../services/database';
import type {
  RideRow,
  RideValidationEventRow,
  UploadQueueRow,
} from '../services/database';

export type RideValidationEventType =
  | 'crash_recovery_detected'
  | 'gps_watchdog_restarted'
  | 'recording_stopped'
  | 'recording_incomplete'
  | 'upload_enqueued'
  | 'upload_interrupted'
  | 'upload_started'
  | 'upload_init_payload'
  | 'upload_accepted'
  | 'upload_failed';

export interface RideValidationSummary {
  rideId: string;
  parserVersionPresent: boolean;
  preliminaryHashPresent: boolean;
  preliminaryHashHex: string | null;
  hadCrashRecovery: boolean;
  rejectedSamples: Record<string, number>;
  uploadStatus: string | null;
  serverRideId: string | null;
  uploadInitObserved: boolean;
  uploadInitHadParserVersion: boolean;
  uploadInitHadPreliminaryHash: boolean;
  stopToQueuedMs: number | null;
  stopToUploadedMs: number | null;
  uploadedWithinOneSecond: boolean | null;
  eventTypes: string[];
}

function metadataFor(event: RideValidationEventRow): Record<string, unknown> {
  if (!event.metadata) return {};
  try {
    const parsed = JSON.parse(event.metadata);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export function rideHashBytesToHex(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === 'string') return value;
  if (value instanceof ArrayBuffer) {
    value = new Uint8Array(value);
  }
  if (ArrayBuffer.isView(value)) {
    const bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    let out = '';
    for (let i = 0; i < bytes.length; i++) {
      out += bytes[i].toString(16).padStart(2, '0');
    }
    return out;
  }
  return null;
}

function parseRejectedSamples(value: string | null): Record<string, number> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: Record<string, number> = {};
    for (const [key, count] of Object.entries(parsed)) {
      out[key] = typeof count === 'number' ? count : Number(count) || 0;
    }
    return out;
  } catch {
    return {};
  }
}

function firstEvent(
  events: RideValidationEventRow[],
  type: RideValidationEventType,
): RideValidationEventRow | null {
  return events.find((event) => event.event_type === type) ?? null;
}

export function recordRideValidationEvent(
  db: SQLiteDatabase,
  rideId: string,
  eventType: RideValidationEventType,
  metadata: Record<string, unknown> = {},
): void {
  if (typeof Database.insertRideValidationEvent !== 'function') return;
  try {
    Database.insertRideValidationEvent(db, rideId, eventType, metadata);
  } catch (err) {
    if (__DEV__) {
      console.warn('[RideValidation] Failed to record event', eventType, err);
    }
  }
}

export function buildRideValidationSummary(args: {
  ride: RideRow;
  uploadEntry: UploadQueueRow | null;
  events: RideValidationEventRow[];
}): RideValidationSummary {
  const { ride, uploadEntry, events } = args;
  const enqueued = firstEvent(events, 'upload_enqueued');
  const accepted = firstEvent(events, 'upload_accepted');
  const initPayload = firstEvent(events, 'upload_init_payload');
  const initMetadata = initPayload ? metadataFor(initPayload) : {};
  const stopAt = ride.ended_at ?? firstEvent(events, 'recording_stopped')?.occurred_at ?? null;
  const stopToQueuedMs = stopAt != null && enqueued
    ? enqueued.occurred_at - stopAt
    : null;
  const stopToUploadedMs = stopAt != null && accepted
    ? accepted.occurred_at - stopAt
    : null;

  return {
    rideId: ride.id,
    parserVersionPresent: ride.parser_version != null,
    preliminaryHashPresent: ride.preliminary_ride_hash != null,
    preliminaryHashHex: rideHashBytesToHex(ride.preliminary_ride_hash),
    hadCrashRecovery: !!ride.had_crash_recovery,
    rejectedSamples: parseRejectedSamples(ride.rejected_samples),
    uploadStatus: uploadEntry?.status ?? null,
    serverRideId: uploadEntry?.server_ride_id ?? null,
    uploadInitObserved: !!initPayload,
    uploadInitHadParserVersion: initMetadata.parserVersionPresent === true,
    uploadInitHadPreliminaryHash: initMetadata.preliminaryRideHashPresent === true,
    stopToQueuedMs,
    stopToUploadedMs,
    uploadedWithinOneSecond: stopToUploadedMs == null ? null : stopToUploadedMs <= 1000,
    eventTypes: events.map((event) => event.event_type),
  };
}

export function getRideValidationSummary(
  db: SQLiteDatabase,
  rideId: string,
): RideValidationSummary | null {
  const ride = Database.getRide(db, rideId);
  if (!ride) return null;
  return buildRideValidationSummary({
    ride,
    uploadEntry: Database.getUploadEntryForRide(db, rideId),
    events: Database.getRideValidationEvents(db, rideId),
  });
}
