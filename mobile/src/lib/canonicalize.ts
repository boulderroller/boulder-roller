/**
 * TypeScript port of `workout-parse/src/canonicalize.rs`.
 *
 * Produces a deterministic, parser-version-stamped canonical form of a
 * ride. SHA256 of the JSON serialization is the preliminary ride hash —
 * the device-side input to the eventual backend compare. This module
 * ships only the device half: the backend compare loop (re-canonicalize
 * the uploaded file, assert hash equality) lands separately on the
 * protocol-agent track.
 *
 * Field order in the JSON output matches Rust's `serde_json::Serialize`
 * struct field order. Symmetry test (canonicalize.test.ts) loads the
 * Rust test vector and asserts the TS hash matches the Rust hash so the
 * two implementations stay byte-equivalent.
 *
 * A semantic parser change must add an immutable PARSER_VERSION_Vn and set
 * CURRENT_PARSER_VERSION to it; existing versions remain replayable forever.
 */

import * as Crypto from 'expo-crypto';

export const PARSER_VERSION_V1 = 1;
export const PARSER_VERSION_V2 = 2;
export const PARSER_VERSION_V3 = 3;
export const PARSER_VERSION_V4 = 4;
export const PARSER_VERSION_V5 = 5;
export const CURRENT_PARSER_VERSION = PARSER_VERSION_V5;

const MAX_ACTIVITY_DURATION_MS = 48 * 60 * 60 * 1000;

// ---------------------------------------------------------------------------
// Output types — field order MUST match the Rust structs for hash parity.
// ---------------------------------------------------------------------------

export interface CanonicalSampleV1 {
  cadence_rpm: number | null;
  dist_dm: number | null;
  elev_dm: number | null;
  hr_bpm: number | null;
  lat_e6: number | null;
  lon_e6: number | null;
  power_w: number | null;
  sec_offset: number;
  speed_cms: number | null;
}

export interface CanonicalRideV1 {
  parser_version: number;
  samples: CanonicalSampleV1[];
  sport: string;
  started_at_ms: number;
}

// ---------------------------------------------------------------------------
// Input shape — mirrors workout-parse `ParsedActivity`. Optional arrays for
// streams that may not be present (e.g., a GPS-only ride has no power/HR).
// Use `null` for per-sample missing values where Rust uses MISSING_* sentinels.
// ---------------------------------------------------------------------------

export interface ParsedActivity {
  time_ms: number[];
  lat_e7?: (number | null)[];
  lon_e7?: (number | null)[];
  elevation_m?: (number | null)[];
  dist_m?: (number | null)[];
  speed_mps?: (number | null)[];
  pwr_w?: (number | null)[];
  hr_bpm?: (number | null)[];
  cadence_rpm?: (number | null)[];
  sport: string;
  started_at_ms: number;
}

// ---------------------------------------------------------------------------
// Algorithm
// ---------------------------------------------------------------------------

interface BucketAccumulator {
  last_lat_e6: number | null;
  last_lon_e6: number | null;
  last_elev_dm: number | null;
  last_dist_dm: number | null;
  speed_sum: number;
  speed_count: number;
  power_sum: number;
  power_count: number;
  hr_sum: number;
  hr_count: number;
  cadence_sum: number;
  cadence_count: number;
}

function emptyBucket(): BucketAccumulator {
  return {
    last_lat_e6: null,
    last_lon_e6: null,
    last_elev_dm: null,
    last_dist_dm: null,
    speed_sum: 0,
    speed_count: 0,
    power_sum: 0,
    power_count: 0,
    hr_sum: 0,
    hr_count: 0,
    cadence_sum: 0,
    cadence_count: 0,
  };
}

/**
 * Round half-away-from-zero, matching Rust f64::round(). JS Math.round
 * rounds half-toward-+Infinity, which differs for negative halves
 * (Math.round(-0.5) === 0, Rust -0.5_f64.round() === -1.0).
 */
function rustRound(x: number): number {
  return x < 0 ? -Math.round(-x) : Math.round(x);
}

function roundScaled(value: number, scale: number): number | null {
  if (!Number.isFinite(value)) return null;
  return rustRound(value * scale);
}

function roundedMeanI64(sum: number, count: number): number | null {
  if (count === 0) return null;
  return rustRound(sum / count);
}

function roundedMeanU16(sum: number, count: number): number | null {
  const v = roundedMeanI64(sum, count);
  if (v === null) return null;
  if (v < 0 || v > 0xffff) return null;
  return v;
}

function roundedMeanU8(sum: number, count: number): number | null {
  const v = roundedMeanI64(sum, count);
  if (v === null) return null;
  if (v < 0 || v > 0xff) return null;
  return v;
}

function sampleSecond(time_ms: number, started_at_ms: number): number {
  return Math.max(0, Math.floor((time_ms - started_at_ms) / 1000));
}

function validateV2Timestamps(activity: ParsedActivity): void {
  const { time_ms: timestamps, started_at_ms } = activity;
  if (timestamps.length === 0) return;

  if (!Number.isSafeInteger(started_at_ms)) {
    throw new Error('started_at_ms must be a finite integer timestamp');
  }
  for (const timestamp of timestamps) {
    if (!Number.isSafeInteger(timestamp)) {
      throw new Error('time_ms must contain finite integer timestamps');
    }
  }

  if (timestamps[0] !== started_at_ms) {
    throw new Error(
      `started_at_ms ${started_at_ms} does not match first sample ${timestamps[0]}`,
    );
  }

  for (let index = 1; index < timestamps.length; index += 1) {
    if (timestamps[index] < timestamps[index - 1]) {
      throw new Error(
        `timestamp at index ${index} is out of order (${timestamps[index]} < ${timestamps[index - 1]})`,
      );
    }
  }

  const durationMs = timestamps[timestamps.length - 1] - timestamps[0];
  if (durationMs > MAX_ACTIVITY_DURATION_MS) {
    throw new Error('Activity duration exceeds maximum 172800s');
  }
}

function normalizeSport(sport: string): string {
  let out = '';
  for (const ch of sport.trim()) {
    if (ch.charCodeAt(0) < 128) out += ch;
  }
  return out.toLowerCase();
}

function bucketToSample(b: BucketAccumulator, sec_offset: number): CanonicalSampleV1 {
  return {
    cadence_rpm: roundedMeanU8(b.cadence_sum, b.cadence_count),
    dist_dm: b.last_dist_dm,
    elev_dm: b.last_elev_dm,
    hr_bpm: roundedMeanU8(b.hr_sum, b.hr_count),
    lat_e6: b.last_lat_e6,
    lon_e6: b.last_lon_e6,
    power_w: roundedMeanU16(b.power_sum, b.power_count),
    sec_offset,
    speed_cms: roundedMeanI64(b.speed_sum, b.speed_count),
  };
}

function canonicalizeWithVersion(
  activity: ParsedActivity,
  parserVersion: number,
): CanonicalRideV1 {
  const sport = normalizeSport(activity.sport);

  if (activity.time_ms.length === 0) {
    return {
      parser_version: parserVersion,
      samples: [],
      sport,
      started_at_ms: activity.started_at_ms,
    };
  }

  if (
    parserVersion === PARSER_VERSION_V2 ||
    parserVersion === PARSER_VERSION_V3 ||
    parserVersion === PARSER_VERSION_V4 ||
    parserVersion === PARSER_VERSION_V5
  ) {
    validateV2Timestamps(activity);
  }

  const lastTime = activity.time_ms[activity.time_ms.length - 1];
  const lastSecOffset = sampleSecond(lastTime, activity.started_at_ms);
  const buckets: BucketAccumulator[] = [];
  for (let i = 0; i <= lastSecOffset; i++) buckets.push(emptyBucket());

  for (let i = 0; i < activity.time_ms.length; i++) {
    const sec = sampleSecond(activity.time_ms[i], activity.started_at_ms);
    const bucket = buckets[sec];

    const lat_e7 = activity.lat_e7?.[i];
    if (lat_e7 != null) {
      bucket.last_lat_e6 = rustRound(lat_e7 / 10);
    }
    const lon_e7 = activity.lon_e7?.[i];
    if (lon_e7 != null) {
      bucket.last_lon_e6 = rustRound(lon_e7 / 10);
    }
    // Rust workout-parse stores elevation, distance, and speed as f32 in
    // ParsedActivity, then casts to f64 before the * scale. JS Number is
    // f64 by default, so we have to round-trip through f32 precision via
    // Math.fround to match Rust's bit-for-bit. Without this, decimal
    // values like 45.05 produce different rounded scales (45.05_f32 cast
    // to f64 yields 45.04999923706055, which * 10 rounds to 450; raw f64
    // yields 450.5 which rounds to 451).
    const elev_m = activity.elevation_m?.[i];
    if (elev_m != null) {
      bucket.last_elev_dm = roundScaled(Math.fround(elev_m), 10);
    }
    const dist_m = activity.dist_m?.[i];
    if (dist_m != null) {
      bucket.last_dist_dm = roundScaled(Math.fround(dist_m), 10);
    }
    const speed_mps = activity.speed_mps?.[i];
    if (speed_mps != null) {
      const scaled = roundScaled(Math.fround(speed_mps), 100);
      if (scaled !== null) {
        bucket.speed_sum += scaled;
        bucket.speed_count += 1;
      }
    }
    const pwr_w = activity.pwr_w?.[i];
    if (pwr_w != null) {
      bucket.power_sum += pwr_w;
      bucket.power_count += 1;
    }
    const hr_bpm = activity.hr_bpm?.[i];
    if (hr_bpm != null) {
      bucket.hr_sum += hr_bpm;
      bucket.hr_count += 1;
    }
    const cad = activity.cadence_rpm?.[i];
    if (cad != null) {
      bucket.cadence_sum += cad;
      bucket.cadence_count += 1;
    }
  }

  const samples = buckets.map((b, sec) => bucketToSample(b, sec));
  return {
    parser_version: parserVersion,
    samples,
    sport,
    started_at_ms: activity.started_at_ms,
  };
}

export function canonicalizeV1(activity: ParsedActivity): CanonicalRideV1 {
  return canonicalizeWithVersion(activity, PARSER_VERSION_V1);
}

export function canonicalizeV2(activity: ParsedActivity): CanonicalRideV1 {
  return canonicalizeWithVersion(activity, PARSER_VERSION_V2);
}

export function canonicalizeV3(activity: ParsedActivity): CanonicalRideV1 {
  return canonicalizeWithVersion(activity, PARSER_VERSION_V3);
}

export function canonicalizeV4(activity: ParsedActivity): CanonicalRideV1 {
  return canonicalizeWithVersion(activity, PARSER_VERSION_V4);
}

export function canonicalizeV5(activity: ParsedActivity): CanonicalRideV1 {
  return canonicalizeWithVersion(activity, PARSER_VERSION_V5);
}

export function canonicalize(
  activity: ParsedActivity,
  parserVersion = CURRENT_PARSER_VERSION,
): CanonicalRideV1 {
  if (parserVersion === PARSER_VERSION_V1) {
    return canonicalizeV1(activity);
  }
  if (parserVersion === PARSER_VERSION_V2) {
    return canonicalizeV2(activity);
  }
  if (parserVersion === PARSER_VERSION_V3) {
    return canonicalizeV3(activity);
  }
  if (parserVersion === PARSER_VERSION_V4) {
    return canonicalizeV4(activity);
  }
  if (parserVersion === PARSER_VERSION_V5) {
    return canonicalizeV5(activity);
  }
  throw new Error(`unsupported canonicalization parser_version: ${parserVersion}`);
}

/**
 * Serialize the canonical ride to a JSON string with field order matching
 * Rust's serde_json::Serialize on the corresponding structs. JSON.stringify
 * preserves insertion order for string-keyed properties, so we hand-build
 * each object literal in the order serde would emit.
 */
export function serializeCanonical(ride: CanonicalRideV1): string {
  const sampleStrs = ride.samples.map((s) =>
    JSON.stringify({
      cadence_rpm: s.cadence_rpm,
      dist_dm: s.dist_dm,
      elev_dm: s.elev_dm,
      hr_bpm: s.hr_bpm,
      lat_e6: s.lat_e6,
      lon_e6: s.lon_e6,
      power_w: s.power_w,
      sec_offset: s.sec_offset,
      speed_cms: s.speed_cms,
    }),
  );
  return (
    `{"parser_version":${ride.parser_version}` +
    `,"samples":[${sampleStrs.join(',')}]` +
    `,"sport":${JSON.stringify(ride.sport)}` +
    `,"started_at_ms":${ride.started_at_ms}}`
  );
}

/**
 * Hash the canonical ride. SHA256 over the serialized JSON, hex-encoded.
 * Matches `hash_canonical_ride_hex(activity, parser_version=<version>)` in
 * workout-parse/src/canonicalize.rs.
 */
export async function hashCanonicalRide(
  activity: ParsedActivity,
  parserVersion = CURRENT_PARSER_VERSION,
): Promise<string> {
  const ride = canonicalize(activity, parserVersion);
  const json = serializeCanonical(ride);
  return Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, json);
}
