/**
 * Heart Rate Measurement parser — characteristic 0x2A37 (Service 0x180D).
 *
 * Wire format (little-endian):
 *   [flags uint8][hr uint8 or uint16][...optional fields]
 *
 * Flags byte bit layout (HRS 1.0):
 *   bit 0    — HR Value Format (0 = uint8, 1 = uint16)
 *   bits 1-2 — Sensor Contact Status:
 *                00/01 = feature not supported
 *                10    = supported but not detected
 *                11    = supported and detected
 *   bit 3    — Energy Expended Present → adds uint16 (kJ)
 *   bit 4    — RR-Interval Present → adds uint16[] (1/1024 s units, older-first)
 *   bits 5-7 — RFU
 *
 * Garmin HRM-Pro/Dual, Polar H10, Wahoo TICKR all set bit 4 with 1-8 RR
 * intervals per notification (for HRV analysis).
 */

const FLAG_HR_16BIT = 1 << 0;
const FLAG_SENSOR_CONTACT_SUPPORTED = 1 << 2;
const FLAG_SENSOR_CONTACT_DETECTED = 1 << 1;
const FLAG_ENERGY_EXPENDED_PRESENT = 1 << 3;
const FLAG_RR_INTERVAL_PRESENT = 1 << 4;

export interface ParsedHeartRateMeasurement {
  heart_rate_bpm: number;
  /** True if sensor detects body contact (only meaningful when supported). */
  sensor_contact?: boolean;
  /** Energy expended in kilojoules since last reset. */
  energy_expended_kj?: number;
  /** RR intervals in milliseconds, older-first. */
  rr_intervals_ms?: number[];
}

export function parseHeartRateMeasurement(buf: Uint8Array): ParsedHeartRateMeasurement {
  if (buf.byteLength < 2) {
    throw new Error(`HR Measurement too short: ${buf.byteLength} bytes (need ≥2)`);
  }
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const flags = dv.getUint8(0);
  let off = 1;

  let heart_rate_bpm: number;
  if (flags & FLAG_HR_16BIT) {
    if (buf.byteLength < off + 2) {
      throw new Error('HR Measurement: flag indicates uint16 HR but buffer too short');
    }
    heart_rate_bpm = dv.getUint16(off, true);
    off += 2;
  } else {
    heart_rate_bpm = dv.getUint8(off);
    off += 1;
  }

  const result: ParsedHeartRateMeasurement = { heart_rate_bpm };

  // Sensor contact is only meaningful when the "supported" bit is set.
  if (flags & FLAG_SENSOR_CONTACT_SUPPORTED) {
    result.sensor_contact = (flags & FLAG_SENSOR_CONTACT_DETECTED) !== 0;
  }

  if (flags & FLAG_ENERGY_EXPENDED_PRESENT) {
    result.energy_expended_kj = dv.getUint16(off, true);
    off += 2;
  }

  if (flags & FLAG_RR_INTERVAL_PRESENT) {
    const rrs: number[] = [];
    while (off + 1 < buf.byteLength) {
      // 1/1024 s units → convert to ms (×1000/1024 = ÷1.024)
      rrs.push(dv.getUint16(off, true) * 1000 / 1024);
      off += 2;
    }
    result.rr_intervals_ms = rrs;
  }

  return result;
}

/** Body Sensor Location enum (char 0x2A38). */
export const BODY_SENSOR_LOCATION = {
  OTHER: 0,
  CHEST: 1,
  WRIST: 2,
  FINGER: 3,
  HAND: 4,
  EAR_LOBE: 5,
  FOOT: 6,
} as const;

export function parseBodySensorLocation(buf: Uint8Array): number {
  if (buf.byteLength < 1) {
    throw new Error('Body Sensor Location empty');
  }
  return buf[0];
}

/** Exported for tests that construct fixtures. */
export const HR_MEASUREMENT_FLAGS = {
  HR_16BIT: FLAG_HR_16BIT,
  SENSOR_CONTACT_DETECTED: FLAG_SENSOR_CONTACT_DETECTED,
  SENSOR_CONTACT_SUPPORTED: FLAG_SENSOR_CONTACT_SUPPORTED,
  ENERGY_EXPENDED_PRESENT: FLAG_ENERGY_EXPENDED_PRESENT,
  RR_INTERVAL_PRESENT: FLAG_RR_INTERVAL_PRESENT,
} as const;
