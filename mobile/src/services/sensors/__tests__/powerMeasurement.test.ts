import {
  parsePowerMeasurement,
  POWER_MEASUREMENT_FLAGS as F,
} from '../ble/parsers/powerMeasurement';

// -------------------------------------------------------------------------
// Fixture helpers — build CPM packets byte-exact per CPS 1.1 spec.
// All multi-byte ints are little-endian.
// -------------------------------------------------------------------------

function u16le(v: number): [number, number] {
  return [v & 0xff, (v >> 8) & 0xff];
}
function u32le(v: number): [number, number, number, number] {
  return [v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >> 24) & 0xff];
}
function s16le(v: number): [number, number] {
  const u = v < 0 ? v + 0x10000 : v;
  return u16le(u);
}
function bytes(...parts: number[]): Uint8Array {
  return new Uint8Array(parts);
}

describe('parsePowerMeasurement', () => {
  describe('mandatory fields', () => {
    test('parses minimal packet (flags=0, power only)', () => {
      // flags=0, power=250
      const buf = bytes(...u16le(0x0000), ...s16le(250));
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(250);
      expect(Object.keys(result)).toEqual(['power_w']);
    });

    test('parses negative power (coasting with some meters)', () => {
      const buf = bytes(...u16le(0x0000), ...s16le(-5));
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(-5);
    });

    test('parses int16 max power', () => {
      const buf = bytes(...u16le(0x0000), ...s16le(32767));
      expect(parsePowerMeasurement(buf).power_w).toBe(32767);
    });

    test('throws on too-short input', () => {
      expect(() => parsePowerMeasurement(bytes(0x00, 0x00, 0x10))).toThrow(/too short/);
    });
  });

  describe('optional fields', () => {
    test('parses pedal power balance (bit 0)', () => {
      // flags=0x0001 (balance present, no reference)
      // power=250, balance=52% → 104 (in 0.5% units)
      const buf = bytes(...u16le(F.PEDAL_BALANCE_PRESENT), ...s16le(250), 104);
      const result = parsePowerMeasurement(buf);
      expect(result.pedal_balance_pct).toBe(52);
      expect(result.pedal_balance_left_ref).toBe(false);
    });

    test('parses pedal balance with left reference (bits 0+1)', () => {
      const flags = F.PEDAL_BALANCE_PRESENT | F.PEDAL_BALANCE_LEFT_REF;
      const buf = bytes(...u16le(flags), ...s16le(250), 100);
      const result = parsePowerMeasurement(buf);
      expect(result.pedal_balance_pct).toBe(50);
      expect(result.pedal_balance_left_ref).toBe(true);
    });

    test('parses accumulated torque (bit 2, wheel-source)', () => {
      // Accum torque = 15 Nm → 480 in 1/32 units
      const buf = bytes(
        ...u16le(F.ACCUMULATED_TORQUE_PRESENT),
        ...s16le(250),
        ...u16le(480),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.accumulated_torque_nm).toBe(15);
      expect(result.torque_source_crank).toBe(false);
    });

    test('parses accumulated torque with crank source (bits 2+3)', () => {
      const flags = F.ACCUMULATED_TORQUE_PRESENT | F.TORQUE_SOURCE_CRANK;
      const buf = bytes(...u16le(flags), ...s16le(250), ...u16le(480));
      const result = parsePowerMeasurement(buf);
      expect(result.torque_source_crank).toBe(true);
    });

    test('parses wheel revolution data (bit 4)', () => {
      // Revs=123456789, last event at 2 s (4096 in 1/2048 s units)
      const buf = bytes(
        ...u16le(F.WHEEL_REV_PRESENT),
        ...s16le(250),
        ...u32le(123456789),
        ...u16le(4096),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.wheel_revolution_count).toBe(123456789);
      expect(result.last_wheel_event_time_s).toBe(2);
    });

    test('parses crank revolution data (bit 5)', () => {
      // Revs=1234, last event at 1 s (1024 in 1/1024 s units)
      const buf = bytes(
        ...u16le(F.CRANK_REV_PRESENT),
        ...s16le(250),
        ...u16le(1234),
        ...u16le(1024),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.crank_revolution_count).toBe(1234);
      expect(result.last_crank_event_time_s).toBe(1);
    });

    test('parses extreme force magnitudes (bit 6)', () => {
      const buf = bytes(
        ...u16le(F.EXTREME_FORCE_PRESENT),
        ...s16le(250),
        ...s16le(800),
        ...s16le(-100),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.extreme_force_max_n).toBe(800);
      expect(result.extreme_force_min_n).toBe(-100);
      expect(result.extreme_torque_max_nm).toBeUndefined();
    });

    test('parses extreme torque magnitudes (bit 7)', () => {
      // Max 25 Nm → 800, Min -3.125 Nm → -100
      const buf = bytes(
        ...u16le(F.EXTREME_TORQUE_PRESENT),
        ...s16le(250),
        ...s16le(800),
        ...s16le(-100),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.extreme_torque_max_nm).toBe(25);
      expect(result.extreme_torque_min_nm).toBe(-3.125);
      expect(result.extreme_force_max_n).toBeUndefined();
    });

    test('bit 6 takes precedence over bit 7 (spec is mutex, but defensive)', () => {
      const flags = F.EXTREME_FORCE_PRESENT | F.EXTREME_TORQUE_PRESENT;
      const buf = bytes(
        ...u16le(flags),
        ...s16le(250),
        ...s16le(800),
        ...s16le(-100),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.extreme_force_max_n).toBe(800);
      expect(result.extreme_torque_max_nm).toBeUndefined();
    });

    test('parses packed 12-bit extreme angles (bit 8)', () => {
      // max = 180 (0x0B4), min = 240 (0x0F0)
      // byte0 = 0xB4
      // byte1 low nibble = 0x0 (max high 4 bits), high nibble = 0x0 (min low 4 bits)
      // byte2 = 0x0F (min high 8 bits)
      // Actually let me use max=0x1B4=436, min=0x0F0=240 for clarity:
      // byte0 = 0xB4 (max bits 0-7)
      // byte1 = 0x01 (max bits 8-11 in low nib) | (min bits 0-3 = 0x0 in high nib) = 0x01
      // byte2 = 0x0F (min bits 4-11 = 0x0F)
      const buf = bytes(
        ...u16le(F.EXTREME_ANGLES_PRESENT),
        ...s16le(250),
        0xb4,
        0x01,
        0x0f,
      );
      const result = parsePowerMeasurement(buf);
      expect(result.extreme_angle_max_deg).toBe(0x1b4);
      expect(result.extreme_angle_min_deg).toBe(0x0f0);
    });

    test('parses top dead spot angle (bit 9)', () => {
      const buf = bytes(
        ...u16le(F.TOP_DEAD_SPOT_PRESENT),
        ...s16le(250),
        ...u16le(180),
      );
      expect(parsePowerMeasurement(buf).top_dead_spot_angle_deg).toBe(180);
    });

    test('parses bottom dead spot angle (bit 10)', () => {
      const buf = bytes(
        ...u16le(F.BOTTOM_DEAD_SPOT_PRESENT),
        ...s16le(250),
        ...u16le(45),
      );
      expect(parsePowerMeasurement(buf).bottom_dead_spot_angle_deg).toBe(45);
    });

    test('parses accumulated energy (bit 11)', () => {
      const buf = bytes(
        ...u16le(F.ACCUMULATED_ENERGY_PRESENT),
        ...s16le(250),
        ...u16le(1500),
      );
      expect(parsePowerMeasurement(buf).accumulated_energy_kj).toBe(1500);
    });

    test('parses offset compensation indicator (bit 12, flag-only)', () => {
      const buf = bytes(...u16le(F.OFFSET_COMPENSATION_INDICATOR), ...s16le(250));
      expect(parsePowerMeasurement(buf).offset_compensation_indicator).toBe(true);
    });
  });

  describe('combined fields (real-world packets)', () => {
    test('Stages-typical: power + accum torque + crank data', () => {
      // bits 2 + 5
      const flags = F.ACCUMULATED_TORQUE_PRESENT | F.CRANK_REV_PRESENT;
      const buf = bytes(
        ...u16le(flags),
        ...s16le(240),       // power
        ...u16le(400),       // 12.5 Nm
        ...u16le(5000),      // crank revs
        ...u16le(2048),      // 2 s last crank event
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(240);
      expect(result.accumulated_torque_nm).toBe(12.5);
      expect(result.crank_revolution_count).toBe(5000);
      expect(result.last_crank_event_time_s).toBe(2);
    });

    test('Favero dual-sided: balance + accum torque + crank data', () => {
      const flags =
        F.PEDAL_BALANCE_PRESENT |
        F.PEDAL_BALANCE_LEFT_REF |
        F.ACCUMULATED_TORQUE_PRESENT |
        F.CRANK_REV_PRESENT;
      const buf = bytes(
        ...u16le(flags),
        ...s16le(300),
        104, // 52% balance
        ...u16le(480), // 15 Nm
        ...u16le(5000),
        ...u16le(2048),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(300);
      expect(result.pedal_balance_pct).toBe(52);
      expect(result.pedal_balance_left_ref).toBe(true);
      expect(result.accumulated_torque_nm).toBe(15);
      expect(result.crank_revolution_count).toBe(5000);
    });
  });

  describe('RFU-bit tolerance (early Stages firmware)', () => {
    test('ignores reserved bits 13-15 (masked with 0x1FFF)', () => {
      // 0xE025 = RFU 13-15 set + bits 0+2+5 we care about
      const flagsRaw = 0xe025;
      const buf = bytes(
        ...u16le(flagsRaw),
        ...s16le(250),
        104,           // balance
        ...u16le(480), // accum torque
        ...u16le(5000), // crank revs
        ...u16le(2048), // crank event
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(250);
      expect(result.pedal_balance_pct).toBe(52);
      expect(result.accumulated_torque_nm).toBe(15);
      expect(result.crank_revolution_count).toBe(5000);
    });
  });

  describe('real-world vendor byte vectors', () => {
    // These vectors approximate packets we expect to see in the wild. Each
    // vector is constructed from the CPS 1.1 spec — we do not ship captured
    // packets, but the flag combinations and field widths match what
    // manufacturer firmware typically advertises at steady state. If a real
    // capture later diverges, extend here and keep both.

    test('4iiii Precision (balance + crank data, no torque)', () => {
      // 4iiii crank-arm meters typically ship pedal balance + crank revs.
      // flags = bit0 | bit5 = 0x21
      const flags = F.PEDAL_BALANCE_PRESENT | F.CRANK_REV_PRESENT;
      const buf = bytes(
        ...u16le(flags),
        ...s16le(220), // power
        100,           // 50% balance
        ...u16le(12345), // crank revs
        ...u16le(1024), // 1.0s crank event
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(220);
      expect(result.pedal_balance_pct).toBe(50);
      expect(result.pedal_balance_left_ref).toBe(false);
      expect(result.crank_revolution_count).toBe(12345);
      expect(result.last_crank_event_time_s).toBe(1);
    });

    test('Quarq DZero spider (torque + crank data, no balance)', () => {
      // Quarq spider meters ship accumulated torque + crank revs.
      // flags = bit2 | bit3 (crank source) | bit5 = 0x2C
      const flags =
        F.ACCUMULATED_TORQUE_PRESENT |
        F.TORQUE_SOURCE_CRANK |
        F.CRANK_REV_PRESENT;
      const buf = bytes(
        ...u16le(flags),
        ...s16le(285),
        ...u16le(960), // 30 Nm accumulated torque
        ...u16le(7777), // crank revs
        ...u16le(2048), // 2.0s crank event
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(285);
      expect(result.accumulated_torque_nm).toBe(30);
      expect(result.torque_source_crank).toBe(true);
      expect(result.crank_revolution_count).toBe(7777);
    });

    test('Garmin Vector 3 pedals (balance left-ref + crank + dead spots)', () => {
      // Vector 3 dual-sided pedals report balance + crank rev data +
      // top/bottom dead spot angles. flags = bit0|bit1|bit5|bit9|bit10
      const flags =
        F.PEDAL_BALANCE_PRESENT |
        F.PEDAL_BALANCE_LEFT_REF |
        F.CRANK_REV_PRESENT |
        F.TOP_DEAD_SPOT_PRESENT |
        F.BOTTOM_DEAD_SPOT_PRESENT;
      const buf = bytes(
        ...u16le(flags),
        ...s16le(310),
        98, // 49% left
        ...u16le(3141), // crank revs
        ...u16le(1024), // 1.0s event
        ...u16le(15), // top dead spot 15 deg
        ...u16le(195), // bottom dead spot 195 deg
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(310);
      expect(result.pedal_balance_pct).toBe(49);
      expect(result.pedal_balance_left_ref).toBe(true);
      expect(result.crank_revolution_count).toBe(3141);
      expect(result.top_dead_spot_angle_deg).toBe(15);
      expect(result.bottom_dead_spot_angle_deg).toBe(195);
    });

    test('Wahoo Kickr smart trainer (wheel rev + crank rev + accum energy)', () => {
      // Smart trainers simulate both wheel and crank rev; Kickr firmware
      // additionally reports accumulated energy for session kJ.
      // flags = bit4 | bit5 | bit11 = 0x830
      const flags =
        F.WHEEL_REV_PRESENT | F.CRANK_REV_PRESENT | F.ACCUMULATED_ENERGY_PRESENT;
      const buf = bytes(
        ...u16le(flags),
        ...s16le(275),
        ...u32le(2500), // wheel revs
        ...u16le(4096), // 2.0s wheel event (1/2048 units)
        ...u16le(8000), // crank revs
        ...u16le(1024), // 1.0s crank event
        ...u16le(425), // 425 kJ
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(275);
      expect(result.wheel_revolution_count).toBe(2500);
      expect(result.last_wheel_event_time_s).toBe(2);
      expect(result.crank_revolution_count).toBe(8000);
      expect(result.last_crank_event_time_s).toBe(1);
      expect(result.accumulated_energy_kj).toBe(425);
    });

    test('Favero Assioma duo with offset compensation indicator', () => {
      // Assioma duo reports balance (left ref) + torque (crank) + crank revs.
      // The offset-compensation indicator bit (12) flips for one packet
      // after a calibration completes — code must tolerate the flag
      // without requiring a field to follow.
      const flags =
        F.PEDAL_BALANCE_PRESENT |
        F.PEDAL_BALANCE_LEFT_REF |
        F.ACCUMULATED_TORQUE_PRESENT |
        F.TORQUE_SOURCE_CRANK |
        F.CRANK_REV_PRESENT |
        F.OFFSET_COMPENSATION_INDICATOR;
      const buf = bytes(
        ...u16le(flags),
        ...s16le(245),
        102, // 51% left
        ...u16le(320), // 10 Nm torque
        ...u16le(6100), // crank revs
        ...u16le(1024),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(245);
      expect(result.pedal_balance_pct).toBe(51);
      expect(result.pedal_balance_left_ref).toBe(true);
      expect(result.accumulated_torque_nm).toBe(10);
      expect(result.torque_source_crank).toBe(true);
      expect(result.crank_revolution_count).toBe(6100);
      expect(result.offset_compensation_indicator).toBe(true);
    });
  });

  describe('boundary conditions', () => {
    test('parses exactly the 4-byte minimum packet', () => {
      const buf = bytes(0x00, 0x00, 0x00, 0x00);
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(0);
    });

    test('parses int16 min power (extreme negative, regen trainer)', () => {
      const buf = bytes(...u16le(0x0000), ...s16le(-32768));
      expect(parsePowerMeasurement(buf).power_w).toBe(-32768);
    });

    test('throws on empty buffer', () => {
      expect(() => parsePowerMeasurement(new Uint8Array(0))).toThrow(/too short/);
    });

    test('throws on single byte', () => {
      expect(() => parsePowerMeasurement(bytes(0x00))).toThrow(/too short/);
    });

    test('parses all non-mutex optional fields together in spec order', () => {
      // Every optional field present except bit 6 (mutex with 7; use 7).
      // This is the widest legal packet we expect to parse. The point is
      // to verify cursor position is right after every field width —
      // miscounting one field drifts the whole trailing payload.
      const flags =
        F.PEDAL_BALANCE_PRESENT |
        F.PEDAL_BALANCE_LEFT_REF |
        F.ACCUMULATED_TORQUE_PRESENT |
        F.TORQUE_SOURCE_CRANK |
        F.WHEEL_REV_PRESENT |
        F.CRANK_REV_PRESENT |
        F.EXTREME_TORQUE_PRESENT |
        F.EXTREME_ANGLES_PRESENT |
        F.TOP_DEAD_SPOT_PRESENT |
        F.BOTTOM_DEAD_SPOT_PRESENT |
        F.ACCUMULATED_ENERGY_PRESENT |
        F.OFFSET_COMPENSATION_INDICATOR;

      const buf = bytes(
        ...u16le(flags),
        ...s16le(300),       // power
        110,                 // balance 55%
        ...u16le(640),       // 20 Nm torque
        ...u32le(1_000_000), // wheel revs
        ...u16le(10240),     // 5.0s wheel event (1/2048 units)
        ...u16le(50000),     // crank revs
        ...u16le(1024),      // 1.0s crank event
        ...s16le(1600),      // extreme torque max 50 Nm
        ...s16le(-800),      // extreme torque min -25 Nm
        0x64, 0x03, 0x06,    // extreme angles packed 12-bit (max=0x364, min=0x060)
        ...u16le(12),        // top dead spot
        ...u16le(190),       // bottom dead spot
        ...u16le(750),       // 750 kJ
      );
      const result = parsePowerMeasurement(buf);

      expect(result.power_w).toBe(300);
      expect(result.pedal_balance_pct).toBe(55);
      expect(result.pedal_balance_left_ref).toBe(true);
      expect(result.accumulated_torque_nm).toBe(20);
      expect(result.torque_source_crank).toBe(true);
      expect(result.wheel_revolution_count).toBe(1_000_000);
      expect(result.last_wheel_event_time_s).toBe(5);
      expect(result.crank_revolution_count).toBe(50000);
      expect(result.last_crank_event_time_s).toBe(1);
      expect(result.extreme_torque_max_nm).toBe(50);
      expect(result.extreme_torque_min_nm).toBe(-25);
      expect(result.extreme_angle_max_deg).toBe(0x364);
      expect(result.extreme_angle_min_deg).toBe(0x060);
      expect(result.top_dead_spot_angle_deg).toBe(12);
      expect(result.bottom_dead_spot_angle_deg).toBe(190);
      expect(result.accumulated_energy_kj).toBe(750);
      expect(result.offset_compensation_indicator).toBe(true);
    });

    test('parses all-force-path widest packet (bit 6 instead of bit 7)', () => {
      // Same as above but exercise the extreme-force branch (mutex sibling)
      const flags =
        F.PEDAL_BALANCE_PRESENT |
        F.ACCUMULATED_TORQUE_PRESENT |
        F.WHEEL_REV_PRESENT |
        F.CRANK_REV_PRESENT |
        F.EXTREME_FORCE_PRESENT |
        F.EXTREME_ANGLES_PRESENT |
        F.TOP_DEAD_SPOT_PRESENT |
        F.BOTTOM_DEAD_SPOT_PRESENT |
        F.ACCUMULATED_ENERGY_PRESENT;

      const buf = bytes(
        ...u16le(flags),
        ...s16le(260),
        120, // balance 60%
        ...u16le(500), // torque
        ...u32le(123), // wheel revs
        ...u16le(2048), // 1.0s wheel
        ...u16le(456), // crank revs
        ...u16le(1024), // 1.0s crank
        ...s16le(950), // max force
        ...s16le(-200), // min force
        0x00, 0x00, 0x00, // angles packed (all zero)
        ...u16le(20), // top dead
        ...u16le(180), // bottom dead
        ...u16le(100),
      );
      const result = parsePowerMeasurement(buf);
      expect(result.power_w).toBe(260);
      expect(result.extreme_force_max_n).toBe(950);
      expect(result.extreme_force_min_n).toBe(-200);
      expect(result.extreme_torque_max_nm).toBeUndefined();
      expect(result.accumulated_energy_kj).toBe(100);
    });
  });
});
