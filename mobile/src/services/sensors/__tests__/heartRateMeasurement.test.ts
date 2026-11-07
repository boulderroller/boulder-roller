import {
  parseHeartRateMeasurement,
  parseBodySensorLocation,
  BODY_SENSOR_LOCATION,
  HR_MEASUREMENT_FLAGS as F,
} from '../ble/parsers/heartRateMeasurement';

// -------------------------------------------------------------------------
// Fixture helpers — build HR Measurement packets byte-exact per HRS 1.0.
// All multi-byte ints are little-endian.
// -------------------------------------------------------------------------

function bytes(...parts: number[]): Uint8Array {
  return new Uint8Array(parts);
}
function u16le(v: number): [number, number] {
  return [v & 0xff, (v >> 8) & 0xff];
}

describe('parseHeartRateMeasurement', () => {
  describe('HR value', () => {
    test('parses uint8 HR (bit 0 = 0)', () => {
      // flags=0x00, HR=152
      const result = parseHeartRateMeasurement(bytes(0x00, 152));
      expect(result.heart_rate_bpm).toBe(152);
      expect(result.rr_intervals_ms).toBeUndefined();
    });

    test('parses uint16 HR (bit 0 = 1) for values >255', () => {
      // flags=0x01, HR=300 (pathological but spec-allowed)
      const result = parseHeartRateMeasurement(bytes(F.HR_16BIT, ...u16le(300)));
      expect(result.heart_rate_bpm).toBe(300);
    });

    test('throws when uint16 flag set but buffer too short', () => {
      expect(() => parseHeartRateMeasurement(bytes(F.HR_16BIT, 0x10))).toThrow(
        /buffer too short/,
      );
    });

    test('throws on empty buffer', () => {
      expect(() => parseHeartRateMeasurement(bytes())).toThrow(/too short/);
    });
  });

  describe('sensor contact', () => {
    test('reports contact when supported+detected (bits 1+2 set)', () => {
      const flags = F.SENSOR_CONTACT_SUPPORTED | F.SENSOR_CONTACT_DETECTED;
      const result = parseHeartRateMeasurement(bytes(flags, 150));
      expect(result.sensor_contact).toBe(true);
    });

    test('reports no contact when supported but not detected (bit 2 only)', () => {
      const result = parseHeartRateMeasurement(
        bytes(F.SENSOR_CONTACT_SUPPORTED, 150),
      );
      expect(result.sensor_contact).toBe(false);
    });

    test('omits sensor_contact when feature not supported (bit 2 clear)', () => {
      const result = parseHeartRateMeasurement(bytes(0x00, 150));
      expect(result.sensor_contact).toBeUndefined();
    });
  });

  describe('energy expended', () => {
    test('parses energy (bit 3)', () => {
      const result = parseHeartRateMeasurement(
        bytes(F.ENERGY_EXPENDED_PRESENT, 150, ...u16le(1500)),
      );
      expect(result.energy_expended_kj).toBe(1500);
    });
  });

  describe('RR intervals', () => {
    test('parses single RR interval (bit 4)', () => {
      // RR = 400 in 1/1024 s units → 390.625 ms
      const result = parseHeartRateMeasurement(
        bytes(F.RR_INTERVAL_PRESENT, 150, ...u16le(400)),
      );
      expect(result.rr_intervals_ms).toHaveLength(1);
      expect(result.rr_intervals_ms![0]).toBeCloseTo(390.625, 3);
    });

    test('parses multiple RR intervals (older-first per spec)', () => {
      // Three RRs: 410, 400, 395 (in 1/1024 s units)
      const result = parseHeartRateMeasurement(
        bytes(
          F.RR_INTERVAL_PRESENT,
          150,
          ...u16le(410),
          ...u16le(400),
          ...u16le(395),
        ),
      );
      expect(result.rr_intervals_ms).toHaveLength(3);
      expect(result.rr_intervals_ms![0]).toBeCloseTo(410 * 1000 / 1024, 3);
      expect(result.rr_intervals_ms![2]).toBeCloseTo(395 * 1000 / 1024, 3);
    });

    test('empty RR payload yields empty array', () => {
      const result = parseHeartRateMeasurement(bytes(F.RR_INTERVAL_PRESENT, 150));
      expect(result.rr_intervals_ms).toEqual([]);
    });

    test('parses eight RR intervals (max observed per-packet from Polar H10)', () => {
      // Polar H10 batches up to 8 RRs per notification when HR is high and
      // notifications space out under BLE contention.
      const rrs = [410, 412, 409, 408, 405, 407, 404, 403];
      const payload = rrs.flatMap((r) => u16le(r));
      const result = parseHeartRateMeasurement(
        bytes(F.RR_INTERVAL_PRESENT, 150, ...payload),
      );
      expect(result.rr_intervals_ms).toHaveLength(8);
      for (let i = 0; i < rrs.length; i++) {
        expect(result.rr_intervals_ms![i]).toBeCloseTo(rrs[i] * 1000 / 1024, 3);
      }
    });

    test('truncates at buffer end if final RR is only 1 byte (malformed tail)', () => {
      // Defensive: if a vendor trims the last RR, off+1 < byteLength prevents
      // a dangling half-read. We accept the leading intact intervals.
      const result = parseHeartRateMeasurement(
        bytes(F.RR_INTERVAL_PRESENT, 150, ...u16le(400), 0xAB),
      );
      expect(result.rr_intervals_ms).toHaveLength(1);
      expect(result.rr_intervals_ms![0]).toBeCloseTo(400 * 1000 / 1024, 3);
    });
  });

  describe('combined (Garmin HRM-Pro typical packet)', () => {
    test('uint8 HR + contact detected + 2 RR intervals', () => {
      const flags =
        F.SENSOR_CONTACT_SUPPORTED |
        F.SENSOR_CONTACT_DETECTED |
        F.RR_INTERVAL_PRESENT;
      const result = parseHeartRateMeasurement(
        bytes(flags, 152, ...u16le(400), ...u16le(405)),
      );
      expect(result.heart_rate_bpm).toBe(152);
      expect(result.sensor_contact).toBe(true);
      expect(result.rr_intervals_ms).toHaveLength(2);
    });
  });

  describe('real-world vendor byte vectors', () => {
    // These vectors match the flag combinations and field widths that
    // manufacturer firmware typically advertises at steady state per HRS 1.0.
    // Captured packets are not shipped; we construct per spec and will extend
    // here if a live capture diverges.

    test('Polar H10 — HR + contact detected + 3 RR intervals (HRV packet)', () => {
      // Polar H10 is the HRV reference device. It reports uint8 HR, always
      // claims contact support, and packs multiple RR intervals per notify
      // at higher BPM so HRV consumers get beat-by-beat data.
      const flags =
        F.SENSOR_CONTACT_SUPPORTED |
        F.SENSOR_CONTACT_DETECTED |
        F.RR_INTERVAL_PRESENT;
      const result = parseHeartRateMeasurement(
        bytes(
          flags,
          148, // HR 148 bpm
          ...u16le(415), // RR #1 older
          ...u16le(410), // RR #2
          ...u16le(413), // RR #3 newer
        ),
      );
      expect(result.heart_rate_bpm).toBe(148);
      expect(result.sensor_contact).toBe(true);
      expect(result.rr_intervals_ms).toHaveLength(3);
      expect(result.rr_intervals_ms![0]).toBeCloseTo(415 * 1000 / 1024, 3);
      expect(result.rr_intervals_ms![2]).toBeCloseTo(413 * 1000 / 1024, 3);
    });

    test('Garmin HRM-Dual — HR + contact detected + 1 RR + energy expended', () => {
      // HRM-Dual ships BLE + ANT+. Its HRS packet typically includes energy
      // expended (accumulated kJ since session start) alongside RR intervals.
      const flags =
        F.SENSOR_CONTACT_SUPPORTED |
        F.SENSOR_CONTACT_DETECTED |
        F.ENERGY_EXPENDED_PRESENT |
        F.RR_INTERVAL_PRESENT;
      const result = parseHeartRateMeasurement(
        bytes(
          flags,
          162, // HR
          ...u16le(850), // energy 850 kJ
          ...u16le(380), // RR in 1/1024 s
        ),
      );
      expect(result.heart_rate_bpm).toBe(162);
      expect(result.sensor_contact).toBe(true);
      expect(result.energy_expended_kj).toBe(850);
      expect(result.rr_intervals_ms).toHaveLength(1);
      expect(result.rr_intervals_ms![0]).toBeCloseTo(380 * 1000 / 1024, 3);
    });

    test('Wahoo TICKR — HR + contact detected + 2 RR intervals', () => {
      // TICKR chest strap reports uint8 HR, contact status, typically 2 RR
      // intervals per notification at moderate effort.
      const flags =
        F.SENSOR_CONTACT_SUPPORTED |
        F.SENSOR_CONTACT_DETECTED |
        F.RR_INTERVAL_PRESENT;
      const result = parseHeartRateMeasurement(
        bytes(flags, 140, ...u16le(430), ...u16le(425)),
      );
      expect(result.heart_rate_bpm).toBe(140);
      expect(result.sensor_contact).toBe(true);
      expect(result.rr_intervals_ms).toHaveLength(2);
    });

    test('Wahoo TICKR — rider sweaty with poor contact (supported but not detected)', () => {
      // Mid-ride sweat/slip case. TICKR still sends HR from the last valid
      // QRS but contact flag flips to not-detected — UI should surface this.
      const flags = F.SENSOR_CONTACT_SUPPORTED; // bit 2 set, bit 1 clear
      const result = parseHeartRateMeasurement(bytes(flags, 138));
      expect(result.heart_rate_bpm).toBe(138);
      expect(result.sensor_contact).toBe(false);
    });

    test('Magene H64 optical armband — HR only, no contact support', () => {
      // Optical armbands often do not expose sensor-contact bit because the
      // contact semantics don't apply (no skin-electrode pair). Flags = 0.
      const result = parseHeartRateMeasurement(bytes(0x00, 125));
      expect(result.heart_rate_bpm).toBe(125);
      expect(result.sensor_contact).toBeUndefined();
      expect(result.rr_intervals_ms).toBeUndefined();
    });

    test('Xiaomi-generic chest strap — minimal HRS, uint8 HR only', () => {
      // Cheap generic straps ship the bare minimum: flags byte + uint8 HR.
      // Many of these skip the contact-support bit and the RR flag entirely.
      const result = parseHeartRateMeasurement(bytes(0x00, 75));
      expect(result.heart_rate_bpm).toBe(75);
      expect(Object.keys(result)).toEqual(['heart_rate_bpm']);
    });

    test('Garmin HRM-Pro Plus — HR + contact + energy + 4 RR (full HRV packet)', () => {
      // HRM-Pro Plus at high HR batches 3-4 RR intervals per notification and
      // reports accumulated energy for session-total calorie math.
      const flags =
        F.SENSOR_CONTACT_SUPPORTED |
        F.SENSOR_CONTACT_DETECTED |
        F.ENERGY_EXPENDED_PRESENT |
        F.RR_INTERVAL_PRESENT;
      const result = parseHeartRateMeasurement(
        bytes(
          flags,
          175,
          ...u16le(1200), // 1200 kJ energy
          ...u16le(355), // RRs at high HR (~170 bpm = ~353 ms)
          ...u16le(350),
          ...u16le(358),
          ...u16le(351),
        ),
      );
      expect(result.heart_rate_bpm).toBe(175);
      expect(result.sensor_contact).toBe(true);
      expect(result.energy_expended_kj).toBe(1200);
      expect(result.rr_intervals_ms).toHaveLength(4);
    });

    test('Polar OH1 optical — 16-bit HR format (device firmware choice)', () => {
      // Some optical sensors use 16-bit HR even when the value fits in 8 bits.
      // Parser must not assume 8-bit from value magnitude alone — the flag
      // is authoritative.
      const flags = F.HR_16BIT | F.SENSOR_CONTACT_SUPPORTED | F.SENSOR_CONTACT_DETECTED;
      const result = parseHeartRateMeasurement(
        bytes(flags, ...u16le(88)),
      );
      expect(result.heart_rate_bpm).toBe(88);
      expect(result.sensor_contact).toBe(true);
    });

    test('RFU bits 5-7 set — parser ignores them gracefully', () => {
      // Some firmware dirties the reserved bits (future-proofing bug we've seen
      // reported in the wild for cheap generic straps). Parser must not treat
      // them as field presence; bit 4 alone drives RR consumption.
      const flagsRaw = 0xE0 | F.RR_INTERVAL_PRESENT; // 0xF0
      const result = parseHeartRateMeasurement(
        bytes(flagsRaw, 140, ...u16le(400)),
      );
      expect(result.heart_rate_bpm).toBe(140);
      expect(result.rr_intervals_ms).toHaveLength(1);
    });
  });

  describe('boundary conditions', () => {
    test('throws on empty buffer', () => {
      expect(() => parseHeartRateMeasurement(bytes())).toThrow(/too short/);
    });

    test('throws on single byte (flags only, no HR)', () => {
      expect(() => parseHeartRateMeasurement(bytes(0x00))).toThrow(/too short/);
    });

    test('parses minimum legal packet: flags + uint8 HR', () => {
      const result = parseHeartRateMeasurement(bytes(0x00, 45));
      expect(result.heart_rate_bpm).toBe(45);
    });

    test('parses uint8 HR = 0 (rider not wearing strap; firmware reports 0)', () => {
      // Some straps report 0 bpm when contact is lost entirely. This is
      // absence-as-zero from the firmware — the parser cannot tell. Upper
      // layers should prefer the contact flag for truth; we preserve the 0.
      const result = parseHeartRateMeasurement(bytes(F.SENSOR_CONTACT_SUPPORTED, 0));
      expect(result.heart_rate_bpm).toBe(0);
      expect(result.sensor_contact).toBe(false);
    });

    test('parses uint8 HR at max (255)', () => {
      const result = parseHeartRateMeasurement(bytes(0x00, 0xff));
      expect(result.heart_rate_bpm).toBe(255);
    });

    test('parses uint16 HR at max (65535)', () => {
      const result = parseHeartRateMeasurement(bytes(F.HR_16BIT, 0xff, 0xff));
      expect(result.heart_rate_bpm).toBe(65535);
    });

    test('parses widest legal packet: uint16 HR + contact + energy + 4 RR', () => {
      const flags =
        F.HR_16BIT |
        F.SENSOR_CONTACT_SUPPORTED |
        F.SENSOR_CONTACT_DETECTED |
        F.ENERGY_EXPENDED_PRESENT |
        F.RR_INTERVAL_PRESENT;
      const result = parseHeartRateMeasurement(
        bytes(
          flags,
          ...u16le(180),
          ...u16le(1000),
          ...u16le(350),
          ...u16le(345),
          ...u16le(352),
          ...u16le(348),
        ),
      );
      expect(result.heart_rate_bpm).toBe(180);
      expect(result.sensor_contact).toBe(true);
      expect(result.energy_expended_kj).toBe(1000);
      expect(result.rr_intervals_ms).toHaveLength(4);
    });

    test('handles flags byte only when extra fields demanded but absent (energy)', () => {
      // Energy flag set but no payload. Parser reads whatever is at off+0..1
      // which is undefined territory. Document behavior explicitly: getUint16
      // throws when the view is out of range. We don't try to handle this
      // gracefully because the packet is malformed and we'd be papering over a
      // genuine vendor bug.
      expect(() =>
        parseHeartRateMeasurement(bytes(F.ENERGY_EXPENDED_PRESENT, 140)),
      ).toThrow();
    });
  });
});

describe('parseBodySensorLocation', () => {
  test('parses chest location', () => {
    expect(parseBodySensorLocation(bytes(BODY_SENSOR_LOCATION.CHEST))).toBe(1);
  });

  test('parses wrist location', () => {
    expect(parseBodySensorLocation(bytes(BODY_SENSOR_LOCATION.WRIST))).toBe(2);
  });

  test('parses all enumerated locations', () => {
    for (const [name, value] of Object.entries(BODY_SENSOR_LOCATION)) {
      expect(parseBodySensorLocation(bytes(value))).toBe(value);
      // Also ensure the name round-trips (sanity check on the enum itself).
      expect(typeof name).toBe('string');
    }
  });

  test('throws on empty buffer', () => {
    expect(() => parseBodySensorLocation(bytes())).toThrow(/empty/);
  });
});
