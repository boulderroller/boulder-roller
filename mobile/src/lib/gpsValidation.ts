/**
 * GPS Sample Validation — Device-Side
 *
 * Fast-rejection checks run on every GPS sample before SQLite write.
 * Thresholds are benchmarked against industry baselines (Avenza 32m
 * accuracy default, Parkin & Rotheram 2010 cycling acceleration
 * ceiling) and must stay symmetric with backend validation in
 * workout-parse/src/climb/utils.rs. See constants symmetry test.
 */

export interface GPSSample {
  timestamp: number;        // Unix epoch milliseconds
  latitude: number;         // WGS84 decimal degrees
  longitude: number;        // WGS84 decimal degrees
  altitude: number | null;  // meters above sea level (barometric preferred)
  accuracy: number;         // horizontal accuracy in meters
  altitudeAccuracy: number | null; // vertical accuracy in meters
  speed: number | null;     // meters per second (from device)
  bearing: number | null;   // degrees from north (0-360)
}

export enum RejectionReason {
  NULL_ISLAND = 'null_island',
  OUT_OF_RANGE = 'out_of_range',
  LOW_ACCURACY = 'low_accuracy',
  IMPOSSIBLE_SPEED = 'impossible_speed',
  IMPOSSIBLE_COORDINATE_SPEED = 'impossible_coordinate_speed',
  IMPOSSIBLE_ACCEL = 'impossible_accel',
  ALTITUDE_OUT_OF_RANGE = 'altitude_out_of_range',
  TIME_TRAVEL = 'time_travel',
}

export interface ValidationResult {
  valid: boolean;
  reason?: RejectionReason;
}

/**
 * Horizontal accuracy gate (meters). 50m is conservative middle-ground
 * vs Avenza's 32m default. Covers partial-obstruction cycling (forests,
 * urban canyons) without accepting genuinely unusable samples.
 */
const MAX_ACCURACY_M = 50;

/** Max cycling speed (m/s). 50 m/s = 180 km/h — physics ceiling. */
const MAX_SPEED_MPS = 50;

/**
 * Max coordinate-derived speed (m/s). Device-reported speed can lag or
 * stay plausible through GPS teleports, so consecutive accepted points
 * must also pass the same physics ceiling.
 */
const MAX_IMPLIED_SPEED_MPS = 50;

/**
 * Max cycling acceleration (m/s²). ~6 m/s² is the physiological
 * ceiling for a sprint start. Parkin & Rotheram, Transport Policy 2010.
 */
const MAX_ACCEL_MPS2 = 6;

/** Altitude sanity bounds (meters). Dead Sea floor / Everest summit. */
const ALT_MIN_M = -500;
const ALT_MAX_M = 9000;

function haversineM(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const earthRadiusM = 6_371_000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const rLat1 = lat1 * Math.PI / 180;
  const rLat2 = lat2 * Math.PI / 180;
  const aRaw =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rLat1) * Math.cos(rLat2) * Math.sin(dLon / 2) ** 2;
  const a = Math.min(1, Math.max(0, aRaw));
  return earthRadiusM * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/**
 * Validate a GPS sample with fast-rejection checks.
 * Short-circuits on first failure for efficiency.
 *
 * @param sample - The GPS sample to validate
 * @param lastAccepted - The previous accepted sample, or null for the first sample.
 * @returns ValidationResult with valid=true or valid=false and a reason.
 */
export function validateGPSSample(
  sample: GPSSample,
  lastAccepted: GPSSample | null,
): ValidationResult {
  // 1. Null Island: GPS-no-fix sentinel (0, 0)
  if (sample.latitude === 0 && sample.longitude === 0) {
    return { valid: false, reason: RejectionReason.NULL_ISLAND };
  }

  // 2. Coordinate range: lat in [-90, 90], lon in [-180, 180]
  if (
    Math.abs(sample.latitude) > 90 ||
    Math.abs(sample.longitude) > 180
  ) {
    return { valid: false, reason: RejectionReason.OUT_OF_RANGE };
  }

  // 3. Accuracy gate
  if (sample.accuracy > MAX_ACCURACY_M) {
    return { valid: false, reason: RejectionReason.LOW_ACCURACY };
  }

  // 4. Speed gate: reject if device-reported speed > 50 m/s (180 km/h)
  if (sample.speed !== null && sample.speed > MAX_SPEED_MPS) {
    return { valid: false, reason: RejectionReason.IMPOSSIBLE_SPEED };
  }

  // 5. Altitude sanity
  if (
    sample.altitude !== null &&
    (sample.altitude < ALT_MIN_M || sample.altitude > ALT_MAX_M)
  ) {
    return { valid: false, reason: RejectionReason.ALTITUDE_OUT_OF_RANGE };
  }

  // 6. Time travel: reject if timestamp is not strictly increasing
  if (lastAccepted && sample.timestamp <= lastAccepted.timestamp) {
    return { valid: false, reason: RejectionReason.TIME_TRAVEL };
  }

  // 7. Coordinate-derived speed sanity (guards device-speed lag/dropouts)
  if (lastAccepted) {
    const dtSec = (sample.timestamp - lastAccepted.timestamp) / 1000;
    if (dtSec > 0) {
      const distM = haversineM(
        lastAccepted.latitude,
        lastAccepted.longitude,
        sample.latitude,
        sample.longitude,
      );
      if (distM / dtSec > MAX_IMPLIED_SPEED_MPS) {
        return {
          valid: false,
          reason: RejectionReason.IMPOSSIBLE_COORDINATE_SPEED,
        };
      }
    }
  }

  // 8. Acceleration sanity (requires previous sample with speed)
  if (
    lastAccepted &&
    sample.speed !== null &&
    lastAccepted.speed !== null
  ) {
    const dtSec = (sample.timestamp - lastAccepted.timestamp) / 1000;
    if (dtSec > 0) {
      const accel = Math.abs(sample.speed - lastAccepted.speed) / dtSec;
      if (accel > MAX_ACCEL_MPS2) {
        return { valid: false, reason: RejectionReason.IMPOSSIBLE_ACCEL };
      }
    }
  }

  return { valid: true };
}

/** Initial rejection counters — one per reason. */
export function createRejectionCounters(): Record<string, number> {
  return {
    [RejectionReason.NULL_ISLAND]: 0,
    [RejectionReason.OUT_OF_RANGE]: 0,
    [RejectionReason.LOW_ACCURACY]: 0,
    [RejectionReason.IMPOSSIBLE_SPEED]: 0,
    [RejectionReason.IMPOSSIBLE_COORDINATE_SPEED]: 0,
    [RejectionReason.IMPOSSIBLE_ACCEL]: 0,
    [RejectionReason.ALTITUDE_OUT_OF_RANGE]: 0,
    [RejectionReason.TIME_TRAVEL]: 0,
  };
}

// Exported for constants-symmetry test against workout-parse
export {
  MAX_ACCURACY_M,
  MAX_SPEED_MPS,
  MAX_IMPLIED_SPEED_MPS,
  MAX_ACCEL_MPS2,
  ALT_MIN_M,
  ALT_MAX_M,
};
