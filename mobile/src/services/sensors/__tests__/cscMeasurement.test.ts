import {
  parseCSCMeasurement,
  computeCadenceRpm,
  computeWheelSpeedMps,
  CSC_MEASUREMENT_FLAGS as F,
} from '../ble/parsers/cscMeasurement';

// -------------------------------------------------------------------------
// Fixture helpers — build CSC Measurement packets byte-exact per CSCS 1.0.
// All multi-byte ints are little-endian.
// -------------------------------------------------------------------------

function bytes(...parts: number[]): Uint8Array {
  return new Uint8Array(parts);
}
function u16le(v: number): [number, number] {
  return [v & 0xff, (v >> 8) & 0xff];
}
function u32le(v: number): [number, number, number, number] {
  return [v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >> 24) & 0xff];
}

describe('parseCSCMeasurement', () => {
  describe('field presence', () => {
    test('parses wheel revolution data only (bit 0)', () => {
      const result = parseCSCMeasurement(
        bytes(F.WHEEL_REV_PRESENT, ...u32le(123456), ...u16le(1024)),
      );
      expect(result.wheel_revolution_count).toBe(123456);
      expect(result.last_wheel_event_time_s).toBe(1);
      expect(result.crank_revolution_count).toBeUndefined();
    });

    test('parses crank revolution data only (bit 1)', () => {
      const result = parseCSCMeasurement(
        bytes(F.CRANK_REV_PRESENT, ...u16le(5000), ...u16le(2048)),
      );
      expect(result.crank_revolution_count).toBe(5000);
      expect(result.last_crank_event_time_s).toBe(2);
    });

    test('parses both wheel and crank (bits 0+1)', () => {
      const flags = F.WHEEL_REV_PRESENT | F.CRANK_REV_PRESENT;
      const result = parseCSCMeasurement(
        bytes(
          flags,
          ...u32le(100000), // wheel revs
          ...u16le(512), // 0.5 s wheel event
          ...u16le(5000), // crank revs
          ...u16le(1024), // 1 s crank event
        ),
      );
      expect(result.wheel_revolution_count).toBe(100000);
      expect(result.last_wheel_event_time_s).toBe(0.5);
      expect(result.crank_revolution_count).toBe(5000);
      expect(result.last_crank_event_time_s).toBe(1);
    });

    test('flags=0 yields empty result', () => {
      expect(parseCSCMeasurement(bytes(0x00))).toEqual({});
    });
  });

  describe('error handling', () => {
    test('throws on empty buffer', () => {
      expect(() => parseCSCMeasurement(bytes())).toThrow(/empty/);
    });

    test('throws when wheel flag set but payload truncated', () => {
      expect(() =>
        parseCSCMeasurement(bytes(F.WHEEL_REV_PRESENT, 0x01, 0x02, 0x03)),
      ).toThrow(/too short/);
    });

    test('throws when crank flag set but payload truncated', () => {
      expect(() =>
        parseCSCMeasurement(bytes(F.CRANK_REV_PRESENT, 0x01)),
      ).toThrow(/too short/);
    });

    test('throws when both flags set but crank payload missing', () => {
      // Wheel fields are intact (4+2 bytes) but crank flag is set without
      // the trailing 4-byte payload. Parser must not silently accept
      // partial data.
      const buf = bytes(
        F.WHEEL_REV_PRESENT | F.CRANK_REV_PRESENT,
        ...u32le(100),
        ...u16le(1024),
      );
      expect(() => parseCSCMeasurement(buf)).toThrow(/too short/);
    });
  });

  describe('real-world vendor byte vectors', () => {
    // These vectors match the flag combinations and field widths that
    // manufacturer firmware typically advertises per CSCS 1.0. Captured
    // packets are not shipped; extend here if a live capture diverges.

    test('Wahoo RPM (cadence-only pod) — crank data only', () => {
      // Wahoo's cadence pod (zip-tied to the crank arm) exposes CSC
      // service with only the crank flag. Wheel flag clear.
      const result = parseCSCMeasurement(
        bytes(
          F.CRANK_REV_PRESENT,
          ...u16le(4567), // crank revs
          ...u16le(2048), // 2.0s crank event
        ),
      );
      expect(result.crank_revolution_count).toBe(4567);
      expect(result.last_crank_event_time_s).toBe(2);
      expect(result.wheel_revolution_count).toBeUndefined();
    });

    test('Garmin GSC-10 (combo sensor) — wheel + crank', () => {
      // Classic Garmin combo sensor on chainstay/seatstay with magnets.
      // Exposes both wheel and crank counters.
      const result = parseCSCMeasurement(
        bytes(
          F.WHEEL_REV_PRESENT | F.CRANK_REV_PRESENT,
          ...u32le(8910), // wheel revs
          ...u16le(3072), // 3.0 s wheel event
          ...u16le(2145), // crank revs
          ...u16le(2048), // 2.0 s crank event
        ),
      );
      expect(result.wheel_revolution_count).toBe(8910);
      expect(result.last_wheel_event_time_s).toBe(3);
      expect(result.crank_revolution_count).toBe(2145);
      expect(result.last_crank_event_time_s).toBe(2);
    });

    test('4iiii CSC-only — crank data at typical cadence', () => {
      // 4iiii's standalone cadence-only variant (not their crank-arm
      // meter); uses CSC service, reports only crank data.
      const result = parseCSCMeasurement(
        bytes(
          F.CRANK_REV_PRESENT,
          ...u16le(1234),
          ...u16le(1024), // 1.0 s
        ),
      );
      expect(result.crank_revolution_count).toBe(1234);
      expect(result.last_crank_event_time_s).toBe(1);
    });

    test('wheel-magnet hub sensor — wheel data only, long event time', () => {
      // Older wheel-magnet hubs (Shimano D-Fly, some generic hubs) report
      // wheel-only data. Event time wraps at ~64 s so we test the upper
      // portion of the range.
      const result = parseCSCMeasurement(
        bytes(
          F.WHEEL_REV_PRESENT,
          ...u32le(500000),
          ...u16le(60 * 1024), // 60.0 s last event
        ),
      );
      expect(result.wheel_revolution_count).toBe(500000);
      expect(result.last_wheel_event_time_s).toBeCloseTo(60, 3);
    });

    test('combo sensor at max uint32 wheel revs (pre-wrap)', () => {
      // Long-term odometer trick: some firmware never resets wheel revs, so
      // the counter can reach near-uint32-max over a device's life.
      const result = parseCSCMeasurement(
        bytes(
          F.WHEEL_REV_PRESENT | F.CRANK_REV_PRESENT,
          ...u32le(0xfffffffe), // one short of wrap
          ...u16le(1024),
          ...u16le(99),
          ...u16le(1024),
        ),
      );
      expect(result.wheel_revolution_count).toBe(0xfffffffe);
      expect(result.crank_revolution_count).toBe(99);
    });
  });

  describe('boundary conditions', () => {
    test('parses flags byte only (both flags clear)', () => {
      expect(parseCSCMeasurement(bytes(0x00))).toEqual({});
    });

    test('parses wheel-only minimum legal packet (7 bytes)', () => {
      // flags (1) + uint32 revs (4) + uint16 event (2) = 7 bytes
      const result = parseCSCMeasurement(
        bytes(F.WHEEL_REV_PRESENT, 0, 0, 0, 0, 0, 0),
      );
      expect(result.wheel_revolution_count).toBe(0);
      expect(result.last_wheel_event_time_s).toBe(0);
    });

    test('parses crank-only minimum legal packet (5 bytes)', () => {
      // flags (1) + uint16 revs (2) + uint16 event (2) = 5 bytes
      const result = parseCSCMeasurement(
        bytes(F.CRANK_REV_PRESENT, 0, 0, 0, 0),
      );
      expect(result.crank_revolution_count).toBe(0);
      expect(result.last_crank_event_time_s).toBe(0);
    });

    test('parses maximum legal packet (both flags, 11 bytes)', () => {
      // flags + uint32 + uint16 + uint16 + uint16 = 1+4+2+2+2 = 11
      const result = parseCSCMeasurement(
        bytes(
          F.WHEEL_REV_PRESENT | F.CRANK_REV_PRESENT,
          0xff, 0xff, 0xff, 0xff, // wheel revs max
          0xff, 0xff, // wheel event max
          0xff, 0xff, // crank revs max
          0xff, 0xff, // crank event max
        ),
      );
      expect(result.wheel_revolution_count).toBe(0xffffffff);
      expect(result.last_wheel_event_time_s).toBeCloseTo(65535 / 1024, 4);
      expect(result.crank_revolution_count).toBe(65535);
      expect(result.last_crank_event_time_s).toBeCloseTo(65535 / 1024, 4);
    });

    test('parses single-byte flags=0 (truly empty)', () => {
      // Vendor could technically send just a flags byte with no fields.
      const result = parseCSCMeasurement(bytes(0x00));
      expect(result).toEqual({});
    });

    test('RFU flag bits 2-7 set do not consume field bytes', () => {
      // If a vendor dirties upper flag bits, parser must not walk off the
      // end trying to consume non-existent wheel/crank fields.
      const result = parseCSCMeasurement(bytes(0xfc)); // bits 2-7 set, 0-1 clear
      expect(result).toEqual({});
    });
  });
});

describe('computeCadenceRpm', () => {
  test('computes 90 rpm from 3 revs in 2 seconds', () => {
    // 3 revs / 2 s * 60 = 90 rpm
    const cadence = computeCadenceRpm(
      { crank_revolution_count: 1000, last_crank_event_time_s: 10 },
      { crank_revolution_count: 1003, last_crank_event_time_s: 12 },
    );
    expect(cadence).toBeCloseTo(90, 3);
  });

  test('handles uint16 crank counter wraparound', () => {
    // Prev=65535, curr=2 → delta should be 3 (not -65533)
    const cadence = computeCadenceRpm(
      { crank_revolution_count: 65535, last_crank_event_time_s: 10 },
      { crank_revolution_count: 2, last_crank_event_time_s: 12 },
    );
    expect(cadence).toBeCloseTo(90, 3);
  });

  test('handles event time wraparound (uint16 / 1024)', () => {
    // Event time wraps at 64.0 s
    // Prev 63.5 s, curr 0.5 s → delta should be 1 s
    const cadence = computeCadenceRpm(
      { crank_revolution_count: 1000, last_crank_event_time_s: 63.5 },
      { crank_revolution_count: 1002, last_crank_event_time_s: 0.5 },
    );
    expect(cadence).toBeCloseTo(120, 1); // 2 revs / 1 s * 60 = 120
  });

  test('handles both crank-rev AND event-time wraparound together', () => {
    // Crank revs wrap from 65534 → 1 (delta 3) while event time wraps
    // from 63.0 s → 0.0 s (delta 1 s). Typical at high RPM.
    const cadence = computeCadenceRpm(
      { crank_revolution_count: 65534, last_crank_event_time_s: 63.0 },
      { crank_revolution_count: 1, last_crank_event_time_s: 0.0 },
    );
    // 3 revs / 1 s * 60 = 180 rpm
    expect(cadence).toBeCloseTo(180, 1);
  });

  test('returns null when time delta is zero', () => {
    expect(
      computeCadenceRpm(
        { crank_revolution_count: 1000, last_crank_event_time_s: 10 },
        { crank_revolution_count: 1002, last_crank_event_time_s: 10 },
      ),
    ).toBeNull();
  });

  test('returns 0 when no revs but time moved (rider coasting)', () => {
    // Rider coasting: event time advances, crank rev count static.
    // Valid zero cadence — parser must not null it.
    const cadence = computeCadenceRpm(
      { crank_revolution_count: 1000, last_crank_event_time_s: 10 },
      { crank_revolution_count: 1000, last_crank_event_time_s: 12 },
    );
    expect(cadence).toBe(0);
  });
});

describe('computeWheelSpeedMps', () => {
  test('computes speed from 2 revs × 2.1m circumference over 1 s', () => {
    // 2 revs * 2.1 m / 1 s = 4.2 m/s
    const speed = computeWheelSpeedMps(
      { wheel_revolution_count: 100, last_wheel_event_time_s: 10 },
      { wheel_revolution_count: 102, last_wheel_event_time_s: 11 },
      2.1,
    );
    expect(speed).toBeCloseTo(4.2, 3);
  });

  test('handles uint32 wheel counter wraparound', () => {
    // Prev = 0xFFFFFFFF (max uint32), curr = 0x00000001 → delta should be 2
    const speed = computeWheelSpeedMps(
      { wheel_revolution_count: 0xffffffff, last_wheel_event_time_s: 10 },
      { wheel_revolution_count: 0x00000001, last_wheel_event_time_s: 11 },
      2.0,
    );
    expect(speed).toBeCloseTo(4, 3); // 2 revs * 2.0 m / 1 s
  });

  test('handles event time wraparound at high speed', () => {
    // Event time wraps at 64 s. Prev=63 s, curr=0.5 s → 1.5 s delta.
    // 3 revs * 2.1 m / 1.5 s = 4.2 m/s
    const speed = computeWheelSpeedMps(
      { wheel_revolution_count: 100, last_wheel_event_time_s: 63 },
      { wheel_revolution_count: 103, last_wheel_event_time_s: 0.5 },
      2.1,
    );
    expect(speed).toBeCloseTo(4.2, 2);
  });

  test('returns null when time delta is zero', () => {
    expect(
      computeWheelSpeedMps(
        { wheel_revolution_count: 100, last_wheel_event_time_s: 10 },
        { wheel_revolution_count: 102, last_wheel_event_time_s: 10 },
        2.1,
      ),
    ).toBeNull();
  });

  test('returns 0 when no wheel revs but time moved (coasting then stopped)', () => {
    // Wheel not turning, sensor still notifying. Valid zero speed.
    const speed = computeWheelSpeedMps(
      { wheel_revolution_count: 100, last_wheel_event_time_s: 10 },
      { wheel_revolution_count: 100, last_wheel_event_time_s: 11 },
      2.1,
    );
    expect(speed).toBe(0);
  });

  test('scales linearly with circumference', () => {
    // Same 2 revs / 1 s, different wheel sizes.
    const small = computeWheelSpeedMps(
      { wheel_revolution_count: 100, last_wheel_event_time_s: 10 },
      { wheel_revolution_count: 102, last_wheel_event_time_s: 11 },
      2.0, // 700x25c
    );
    const big = computeWheelSpeedMps(
      { wheel_revolution_count: 100, last_wheel_event_time_s: 10 },
      { wheel_revolution_count: 102, last_wheel_event_time_s: 11 },
      2.3, // 29er MTB
    );
    expect(big! / small!).toBeCloseTo(1.15, 3);
  });
});
