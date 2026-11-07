/**
 * CSC Measurement parser — characteristic 0x2A5B (Service 0x1816).
 *
 * Wire format (little-endian):
 *   [flags uint8][...wheel data if bit 0][...crank data if bit 1]
 *
 * Flags byte bit layout (CSCS 1.0):
 *   bit 0    — Wheel Revolution Data Present → uint32 cumulative + uint16 event (1/1024 s)
 *   bit 1    — Crank Revolution Data Present → uint16 cumulative + uint16 event (1/1024 s)
 *   bits 2-7 — RFU
 *
 * Cadence/speed are computed by client from delta(revs) / delta(eventTime).
 * Event time fields wrap at uint16 — callers must handle modulo 2^16.
 */

const FLAG_WHEEL_REV_PRESENT = 1 << 0;
const FLAG_CRANK_REV_PRESENT = 1 << 1;

export interface ParsedCSCMeasurement {
  wheel_revolution_count?: number;
  /** Last wheel event time in seconds (wraps at 64 s per uint16/1024). */
  last_wheel_event_time_s?: number;
  crank_revolution_count?: number;
  /** Last crank event time in seconds (wraps at 64 s per uint16/1024). */
  last_crank_event_time_s?: number;
}

export function parseCSCMeasurement(buf: Uint8Array): ParsedCSCMeasurement {
  if (buf.byteLength < 1) {
    throw new Error(`CSC Measurement empty`);
  }
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const flags = dv.getUint8(0);
  let off = 1;

  const result: ParsedCSCMeasurement = {};

  if (flags & FLAG_WHEEL_REV_PRESENT) {
    if (buf.byteLength < off + 6) {
      throw new Error('CSC Measurement: wheel flag set but payload too short');
    }
    result.wheel_revolution_count = dv.getUint32(off, true);
    off += 4;
    result.last_wheel_event_time_s = dv.getUint16(off, true) / 1024;
    off += 2;
  }

  if (flags & FLAG_CRANK_REV_PRESENT) {
    if (buf.byteLength < off + 4) {
      throw new Error('CSC Measurement: crank flag set but payload too short');
    }
    result.crank_revolution_count = dv.getUint16(off, true);
    off += 2;
    result.last_crank_event_time_s = dv.getUint16(off, true) / 1024;
    off += 2;
  }

  return result;
}

/** Compute cadence RPM from two consecutive crank samples, handling uint16 wraparound. */
export function computeCadenceRpm(
  prev: { crank_revolution_count: number; last_crank_event_time_s: number },
  curr: { crank_revolution_count: number; last_crank_event_time_s: number },
): number | null {
  const revDelta = u16WrapSub(curr.crank_revolution_count, prev.crank_revolution_count);
  // Time field is uint16/1024 so max ~64 s; wrap at 65536/1024 = 64.0
  const timeDeltaS = u16TimeWrapSub(
    curr.last_crank_event_time_s * 1024,
    prev.last_crank_event_time_s * 1024,
  ) / 1024;
  if (timeDeltaS <= 0) return null;
  return (revDelta / timeDeltaS) * 60;
}

/** Compute wheel-based speed in m/s from two consecutive wheel samples. */
export function computeWheelSpeedMps(
  prev: { wheel_revolution_count: number; last_wheel_event_time_s: number },
  curr: { wheel_revolution_count: number; last_wheel_event_time_s: number },
  wheelCircumferenceM: number,
): number | null {
  const revDelta = u32WrapSub(curr.wheel_revolution_count, prev.wheel_revolution_count);
  const timeDeltaS = u16TimeWrapSub(
    curr.last_wheel_event_time_s * 1024,
    prev.last_wheel_event_time_s * 1024,
  ) / 1024;
  if (timeDeltaS <= 0) return null;
  return (revDelta * wheelCircumferenceM) / timeDeltaS;
}

function u16WrapSub(curr: number, prev: number): number {
  return (curr - prev + 0x10000) & 0xffff;
}

function u16TimeWrapSub(curr: number, prev: number): number {
  return (curr - prev + 0x10000) & 0xffff;
}

function u32WrapSub(curr: number, prev: number): number {
  // JS numbers handle 32-bit unsigned in double precision fine
  const diff = curr - prev;
  return diff < 0 ? diff + 0x100000000 : diff;
}

/** Exported for tests. */
export const CSC_MEASUREMENT_FLAGS = {
  WHEEL_REV_PRESENT: FLAG_WHEEL_REV_PRESENT,
  CRANK_REV_PRESENT: FLAG_CRANK_REV_PRESENT,
} as const;
