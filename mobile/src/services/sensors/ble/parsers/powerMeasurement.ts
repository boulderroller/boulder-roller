/**
 * Cycling Power Measurement parser — characteristic 0x2A63 (Service 0x1818).
 *
 * Wire format (little-endian):
 *   [flags uint16][power int16][...optional fields keyed by flag bits]
 *
 * Flags byte bit layout (CPS 1.1):
 *   bit 0  — Pedal Power Balance Present  → adds uint8 (% × 2, so 0.5% units)
 *   bit 1  — Pedal Power Balance Reference (0=unknown, 1=left)
 *   bit 2  — Accumulated Torque Present   → adds uint16 (1/32 Nm)
 *   bit 3  — Accumulated Torque Source    (0=wheel, 1=crank)
 *   bit 4  — Wheel Revolution Data Present → adds uint32 + uint16 (1/2048 s)
 *   bit 5  — Crank Revolution Data Present → adds uint16 + uint16 (1/1024 s)
 *   bit 6  — Extreme Force Magnitudes      → adds 2× int16 (N), mutex with 7
 *   bit 7  — Extreme Torque Magnitudes     → adds 2× int16 (1/32 Nm), mutex with 6
 *   bit 8  — Extreme Angles Present        → adds 3 bytes packed (12b max, 12b min)
 *   bit 9  — Top Dead Spot Angle Present   → adds uint16 (deg)
 *   bit 10 — Bottom Dead Spot Angle Present → adds uint16 (deg)
 *   bit 11 — Accumulated Energy Present    → adds uint16 (kJ)
 *   bit 12 — Offset Compensation Indicator — flag only, no field
 *   bits 13-15 — RFU
 *
 * RFU bits must be ignored on read — some early Stages/Quarq firmware sets
 * them. Mask flagsRaw with 0x1FFF before bit checks.
 */

const FLAG_PEDAL_BALANCE_PRESENT = 1 << 0;
const FLAG_PEDAL_BALANCE_LEFT_REF = 1 << 1;
const FLAG_ACCUMULATED_TORQUE_PRESENT = 1 << 2;
const FLAG_TORQUE_SOURCE_CRANK = 1 << 3;
const FLAG_WHEEL_REV_PRESENT = 1 << 4;
const FLAG_CRANK_REV_PRESENT = 1 << 5;
const FLAG_EXTREME_FORCE_PRESENT = 1 << 6;
const FLAG_EXTREME_TORQUE_PRESENT = 1 << 7;
const FLAG_EXTREME_ANGLES_PRESENT = 1 << 8;
const FLAG_TOP_DEAD_SPOT_PRESENT = 1 << 9;
const FLAG_BOTTOM_DEAD_SPOT_PRESENT = 1 << 10;
const FLAG_ACCUMULATED_ENERGY_PRESENT = 1 << 11;
const FLAG_OFFSET_COMPENSATION_INDICATOR = 1 << 12;
const FLAG_VALID_MASK = 0x1fff;

export interface ParsedPowerMeasurement {
  /** Instantaneous power in watts (signed). */
  power_w: number;
  /** Pedal power balance as percentage 0-100. */
  pedal_balance_pct?: number;
  /** True if balance is left-referenced, false if unknown reference. */
  pedal_balance_left_ref?: boolean;
  /** Accumulated torque in Nm. */
  accumulated_torque_nm?: number;
  /** True if torque is crank-based, false if wheel-based. */
  torque_source_crank?: boolean;
  /** Cumulative wheel revolutions (uint32 wraps at ~4.3B). */
  wheel_revolution_count?: number;
  /** Last wheel event time in seconds (uint16 wraps at 32 s). */
  last_wheel_event_time_s?: number;
  /** Cumulative crank revolutions (uint16 wraps at 65535). */
  crank_revolution_count?: number;
  /** Last crank event time in seconds (uint16 wraps at 64 s). */
  last_crank_event_time_s?: number;
  extreme_force_max_n?: number;
  extreme_force_min_n?: number;
  extreme_torque_max_nm?: number;
  extreme_torque_min_nm?: number;
  extreme_angle_max_deg?: number;
  extreme_angle_min_deg?: number;
  top_dead_spot_angle_deg?: number;
  bottom_dead_spot_angle_deg?: number;
  accumulated_energy_kj?: number;
  offset_compensation_indicator?: boolean;
}

export function parsePowerMeasurement(buf: Uint8Array): ParsedPowerMeasurement {
  if (buf.byteLength < 4) {
    throw new Error(`Power Measurement too short: ${buf.byteLength} bytes (need ≥4)`);
  }
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const flagsRaw = dv.getUint16(0, true);
  const flags = flagsRaw & FLAG_VALID_MASK;
  const power_w = dv.getInt16(2, true);

  const result: ParsedPowerMeasurement = { power_w };
  let off = 4;

  if (flags & FLAG_PEDAL_BALANCE_PRESENT) {
    result.pedal_balance_pct = dv.getUint8(off) / 2;
    result.pedal_balance_left_ref = (flags & FLAG_PEDAL_BALANCE_LEFT_REF) !== 0;
    off += 1;
  }

  if (flags & FLAG_ACCUMULATED_TORQUE_PRESENT) {
    result.accumulated_torque_nm = dv.getUint16(off, true) / 32;
    result.torque_source_crank = (flags & FLAG_TORQUE_SOURCE_CRANK) !== 0;
    off += 2;
  }

  if (flags & FLAG_WHEEL_REV_PRESENT) {
    result.wheel_revolution_count = dv.getUint32(off, true);
    off += 4;
    result.last_wheel_event_time_s = dv.getUint16(off, true) / 2048;
    off += 2;
  }

  if (flags & FLAG_CRANK_REV_PRESENT) {
    result.crank_revolution_count = dv.getUint16(off, true);
    off += 2;
    result.last_crank_event_time_s = dv.getUint16(off, true) / 1024;
    off += 2;
  }

  // Bits 6 and 7 are mutually exclusive per spec.
  if (flags & FLAG_EXTREME_FORCE_PRESENT) {
    result.extreme_force_max_n = dv.getInt16(off, true);
    result.extreme_force_min_n = dv.getInt16(off + 2, true);
    off += 4;
  } else if (flags & FLAG_EXTREME_TORQUE_PRESENT) {
    result.extreme_torque_max_nm = dv.getInt16(off, true) / 32;
    result.extreme_torque_min_nm = dv.getInt16(off + 2, true) / 32;
    off += 4;
  }

  if (flags & FLAG_EXTREME_ANGLES_PRESENT) {
    // 3 bytes packed as two 12-bit fields (LE):
    //   byte0           = maxAngle bits 0-7
    //   byte1 low nib   = maxAngle bits 8-11
    //   byte1 high nib  = minAngle bits 0-3
    //   byte2           = minAngle bits 4-11
    const b0 = dv.getUint8(off);
    const b1 = dv.getUint8(off + 1);
    const b2 = dv.getUint8(off + 2);
    result.extreme_angle_max_deg = b0 | ((b1 & 0x0f) << 8);
    result.extreme_angle_min_deg = (b1 >> 4) | (b2 << 4);
    off += 3;
  }

  if (flags & FLAG_TOP_DEAD_SPOT_PRESENT) {
    result.top_dead_spot_angle_deg = dv.getUint16(off, true);
    off += 2;
  }

  if (flags & FLAG_BOTTOM_DEAD_SPOT_PRESENT) {
    result.bottom_dead_spot_angle_deg = dv.getUint16(off, true);
    off += 2;
  }

  if (flags & FLAG_ACCUMULATED_ENERGY_PRESENT) {
    result.accumulated_energy_kj = dv.getUint16(off, true);
    off += 2;
  }

  if (flags & FLAG_OFFSET_COMPENSATION_INDICATOR) {
    result.offset_compensation_indicator = true;
  }

  return result;
}

/** Exported for tests that want to construct fixtures programmatically. */
export const POWER_MEASUREMENT_FLAGS = {
  PEDAL_BALANCE_PRESENT: FLAG_PEDAL_BALANCE_PRESENT,
  PEDAL_BALANCE_LEFT_REF: FLAG_PEDAL_BALANCE_LEFT_REF,
  ACCUMULATED_TORQUE_PRESENT: FLAG_ACCUMULATED_TORQUE_PRESENT,
  TORQUE_SOURCE_CRANK: FLAG_TORQUE_SOURCE_CRANK,
  WHEEL_REV_PRESENT: FLAG_WHEEL_REV_PRESENT,
  CRANK_REV_PRESENT: FLAG_CRANK_REV_PRESENT,
  EXTREME_FORCE_PRESENT: FLAG_EXTREME_FORCE_PRESENT,
  EXTREME_TORQUE_PRESENT: FLAG_EXTREME_TORQUE_PRESENT,
  EXTREME_ANGLES_PRESENT: FLAG_EXTREME_ANGLES_PRESENT,
  TOP_DEAD_SPOT_PRESENT: FLAG_TOP_DEAD_SPOT_PRESENT,
  BOTTOM_DEAD_SPOT_PRESENT: FLAG_BOTTOM_DEAD_SPOT_PRESENT,
  ACCUMULATED_ENERGY_PRESENT: FLAG_ACCUMULATED_ENERGY_PRESENT,
  OFFSET_COMPENSATION_INDICATOR: FLAG_OFFSET_COMPENSATION_INDICATOR,
} as const;
