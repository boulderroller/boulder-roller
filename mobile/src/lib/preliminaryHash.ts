/**
 * Preliminary Ride Hash — TS-canonicalize implementation
 *
 * Produces a deterministic, parser-version-stamped hash of a ride at
 * ride-stop time and persists it on the rides row. The hash +
 * parser_version pair is the device-side input to the backend compare
 * (TRUTHS §2.3). The backend re-canonicalizes the uploaded file and
 * asserts hash equality; mismatch flags tampering, MITM, network
 * corruption, or parser drift between implementations.
 *
 * Algorithm: pulls samples + ride row from SQLite, normalizes into the
 * same upload-wire shape the backend will parse, then runs the TS port
 * of canonicalize_v1 + SHA256. Native recordings upload as FIT by
 * default, even when no sensors are paired, so the preliminary hash keeps
 * the wider sample row. Symmetry test in canonicalize.test.ts verifies
 * the TS hash matches the Rust reference vector.
 */

import {
  getDatabase,
  getRide,
  getRideSamples,
} from '../services/database';
import {
  hashCanonicalRide,
  CURRENT_PARSER_VERSION,
  type ParsedActivity,
} from './canonicalize';

export { CURRENT_PARSER_VERSION };

export interface PreliminaryHashResult {
  rideHash: Uint8Array | null;
  parserVersion: number;
}

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  return out;
}

/**
 * Lowercase hex serialization of a byte array. Used on the upload path
 * to put the preliminary_ride_hash on the wire for the eventual backend
 * compare.
 */
export function bytesToHex(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i].toString(16).padStart(2, '0');
  }
  return out;
}

/**
 * Build the canonicalize input shape from this ride's SQLite rows.
 * The shape mirrors the file format the upload queue will use so the
 * device hash and backend re-canonicalization hash the same bytes'
 * semantic content.
 */
function buildParsedActivity(rideId: string): ParsedActivity | null {
  const db = getDatabase();
  const ride = getRide(db, rideId);
  if (!ride) return null;
  const samples = getRideSamples(db, rideId);

  const timeMs = samples.map((s) => ride.started_at + s.t_offset_ms);
  const startedAtMs = timeMs[0] ?? ride.started_at;
  const latE7 = samples.map((s) => Math.round(s.latitude * 10_000_000));
  const lonE7 = samples.map((s) => Math.round(s.longitude * 10_000_000));
  const elevationM = samples.map((s) => s.altitude_m);

  return {
    time_ms: timeMs,
    lat_e7: latE7,
    lon_e7: lonE7,
    elevation_m: elevationM,
    speed_mps: samples.map((s) => s.speed_mps),
    pwr_w: samples.map((s) => s.power_w ?? null),
    hr_bpm: samples.map((s) => s.heart_rate_bpm ?? null),
    cadence_rpm: samples.map((s) => s.cadence_rpm ?? null),
    sport: 'cycling',
    started_at_ms: startedAtMs,
  };
}

/**
 * Compute the preliminary canonical ride hash for a ride.
 * Returns parserVersion + 32-byte SHA256, or null hash if the ride row
 * is missing (caller should not normally hit this — ride row is always
 * created before stop).
 */
export async function computePreliminaryHash(
  rideId: string,
): Promise<PreliminaryHashResult> {
  const activity = buildParsedActivity(rideId);
  if (!activity) {
    return { rideHash: null, parserVersion: CURRENT_PARSER_VERSION };
  }
  const hex = await hashCanonicalRide(activity);
  return { rideHash: hexToBytes(hex), parserVersion: CURRENT_PARSER_VERSION };
}
