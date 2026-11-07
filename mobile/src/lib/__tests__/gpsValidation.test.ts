/**
 * GPS Validation Tests
 *
 * Tests all 8 fast-rejection checks:
 *   1. Null Island (0, 0)
 *   2. Coordinate range (lat/lon)
 *   3. Accuracy gate (>50m, tightened from 100m per audit)
 *   4. Speed gate (>50 m/s)
 *   5. Altitude range (-500m to 9000m)
 *   6. Time travel (non-increasing timestamp)
 *   7. Coordinate-derived speed gate (>50 m/s)
 *   8. Acceleration gate (>6 m/s², Parkin & Rotheram 2010)
 */

import {
  validateGPSSample,
  RejectionReason,
  createRejectionCounters,
  type GPSSample,
} from '../gpsValidation';

function makeSample(overrides: Partial<GPSSample> = {}): GPSSample {
  return {
    timestamp: 1000,
    latitude: 39.9526,
    longitude: -75.1652,
    altitude: 15.0,
    accuracy: 5.0,
    altitudeAccuracy: 3.0,
    speed: 8.0,
    bearing: 90.0,
    ...overrides,
  };
}

describe('GPS Validation', () => {
  describe('valid samples', () => {
    test('accepts a normal GPS sample (first sample)', () => {
      const result = validateGPSSample(makeSample(), null);
      expect(result.valid).toBe(true);
      expect(result.reason).toBeUndefined();
    });

    test('accepts the first sample with lastAccepted = null', () => {
      const result = validateGPSSample(makeSample({ timestamp: 1 }), null);
      expect(result.valid).toBe(true);
    });

    test('accepts a sample with null speed', () => {
      const result = validateGPSSample(makeSample({ speed: null }), null);
      expect(result.valid).toBe(true);
    });

    test('accepts a sample with null altitude', () => {
      const result = validateGPSSample(makeSample({ altitude: null }), null);
      expect(result.valid).toBe(true);
    });

    test('accepts speed exactly at 50 m/s (boundary)', () => {
      const result = validateGPSSample(makeSample({ speed: 50 }), null);
      expect(result.valid).toBe(true);
    });

    test('accepts accuracy exactly at 50m (boundary)', () => {
      const result = validateGPSSample(makeSample({ accuracy: 50 }), null);
      expect(result.valid).toBe(true);
    });

    test('accepts sequential samples with reasonable acceleration', () => {
      const prev = makeSample({ timestamp: 1000, speed: 8.0 });
      const curr = makeSample({ timestamp: 2000, speed: 12.0 });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(true);
    });

    test('accepts altitude at Dead Sea level (-420m)', () => {
      const result = validateGPSSample(makeSample({ altitude: -420 }), null);
      expect(result.valid).toBe(true);
    });

    test('accepts altitude at extreme high altitude (8848m)', () => {
      const result = validateGPSSample(makeSample({ altitude: 8848 }), null);
      expect(result.valid).toBe(true);
    });
  });

  describe('Null Island rejection', () => {
    test('rejects lat=0, lon=0', () => {
      const result = validateGPSSample(
        makeSample({ latitude: 0, longitude: 0 }),
        null,
      );
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.NULL_ISLAND);
    });

    test('accepts lat=0, lon=1 (not Null Island)', () => {
      const result = validateGPSSample(
        makeSample({ latitude: 0, longitude: 1 }),
        null,
      );
      expect(result.valid).toBe(true);
    });

    test('accepts lat=1, lon=0 (not Null Island)', () => {
      const result = validateGPSSample(
        makeSample({ latitude: 1, longitude: 0 }),
        null,
      );
      expect(result.valid).toBe(true);
    });
  });

  describe('coordinate range rejection', () => {
    test('rejects lat > 90', () => {
      const result = validateGPSSample(makeSample({ latitude: 91 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.OUT_OF_RANGE);
    });

    test('rejects lat < -90', () => {
      const result = validateGPSSample(makeSample({ latitude: -91 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.OUT_OF_RANGE);
    });

    test('rejects lon > 180', () => {
      const result = validateGPSSample(makeSample({ longitude: 181 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.OUT_OF_RANGE);
    });

    test('rejects lon < -180', () => {
      const result = validateGPSSample(makeSample({ longitude: -181 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.OUT_OF_RANGE);
    });

    test('accepts boundary values lat=90, lon=180', () => {
      const result = validateGPSSample(
        makeSample({ latitude: 90, longitude: 180 }),
        null,
      );
      expect(result.valid).toBe(true);
    });

    test('accepts boundary values lat=-90, lon=-180', () => {
      const result = validateGPSSample(
        makeSample({ latitude: -90, longitude: -180 }),
        null,
      );
      expect(result.valid).toBe(true);
    });
  });

  describe('accuracy gate rejection', () => {
    test('rejects accuracy > 50m', () => {
      const result = validateGPSSample(makeSample({ accuracy: 51 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.LOW_ACCURACY);
    });

    test('rejects very poor accuracy (500m)', () => {
      const result = validateGPSSample(makeSample({ accuracy: 500 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.LOW_ACCURACY);
    });
  });

  describe('speed gate rejection', () => {
    test('rejects speed > 50 m/s', () => {
      const result = validateGPSSample(makeSample({ speed: 51 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.IMPOSSIBLE_SPEED);
    });

    test('rejects extreme speed (200 m/s)', () => {
      const result = validateGPSSample(makeSample({ speed: 200 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.IMPOSSIBLE_SPEED);
    });

    test('does not reject when speed is null', () => {
      const result = validateGPSSample(makeSample({ speed: null }), null);
      expect(result.valid).toBe(true);
    });
  });

  describe('altitude range rejection', () => {
    test('rejects altitude below -500m', () => {
      const result = validateGPSSample(makeSample({ altitude: -501 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.ALTITUDE_OUT_OF_RANGE);
    });

    test('rejects altitude above 9000m', () => {
      const result = validateGPSSample(makeSample({ altitude: 9001 }), null);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.ALTITUDE_OUT_OF_RANGE);
    });

    test('accepts boundary altitude -500m', () => {
      const result = validateGPSSample(makeSample({ altitude: -500 }), null);
      expect(result.valid).toBe(true);
    });

    test('accepts boundary altitude 9000m', () => {
      const result = validateGPSSample(makeSample({ altitude: 9000 }), null);
      expect(result.valid).toBe(true);
    });

    test('skips altitude check when altitude is null', () => {
      const result = validateGPSSample(makeSample({ altitude: null }), null);
      expect(result.valid).toBe(true);
    });
  });

  describe('time travel rejection', () => {
    test('rejects timestamp equal to last accepted', () => {
      const prev = makeSample({ timestamp: 1000 });
      const result = validateGPSSample(makeSample({ timestamp: 1000 }), prev);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.TIME_TRAVEL);
    });

    test('rejects timestamp before last accepted', () => {
      const prev = makeSample({ timestamp: 1000 });
      const result = validateGPSSample(makeSample({ timestamp: 999 }), prev);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.TIME_TRAVEL);
    });

    test('accepts timestamp after last accepted', () => {
      const prev = makeSample({ timestamp: 1000 });
      const result = validateGPSSample(makeSample({ timestamp: 1001 }), prev);
      expect(result.valid).toBe(true);
    });

    test('does not check time travel when lastAccepted is null', () => {
      const result = validateGPSSample(makeSample({ timestamp: 1 }), null);
      expect(result.valid).toBe(true);
    });
  });

  describe('coordinate-derived speed rejection', () => {
    test('rejects GPS teleports even when device speed is plausible', () => {
      const prev = makeSample({
        timestamp: 1000,
        latitude: 39.9526,
        longitude: -75.1652,
        speed: 2,
      });
      const curr = makeSample({
        timestamp: 2000,
        latitude: 39.9526,
        longitude: -75.1642,
        speed: 2,
      });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.IMPOSSIBLE_COORDINATE_SPEED);
    });

    test('accepts coordinate movement below the 50 m/s boundary', () => {
      const prev = makeSample({
        timestamp: 1000,
        latitude: 39.9526,
        longitude: -75.1652,
        speed: 5,
      });
      const curr = makeSample({
        timestamp: 2000,
        latitude: 39.95304,
        longitude: -75.1652,
        speed: 5,
      });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(true);
    });
  });

  describe('acceleration gate rejection', () => {
    test('rejects impossible acceleration (0 to 50 m/s in 1 second)', () => {
      const prev = makeSample({ timestamp: 1000, speed: 0 });
      const curr = makeSample({ timestamp: 2000, speed: 50 });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.IMPOSSIBLE_ACCEL);
    });

    test('rejects extreme deceleration (-50 m/s in 1 second)', () => {
      const prev = makeSample({ timestamp: 1000, speed: 50 });
      const curr = makeSample({ timestamp: 2000, speed: 0 });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(false);
      expect(result.reason).toBe(RejectionReason.IMPOSSIBLE_ACCEL);
    });

    test('accepts realistic sprint acceleration (5 m/s² over 1 second)', () => {
      const prev = makeSample({ timestamp: 1000, speed: 5 });
      const curr = makeSample({ timestamp: 2000, speed: 10 });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(true);
    });

    test('accepts exactly 6 m/s² (boundary)', () => {
      const prev = makeSample({ timestamp: 1000, speed: 0 });
      const curr = makeSample({ timestamp: 2000, speed: 6 });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(true);
    });

    test('skips accel check when current speed is null', () => {
      const prev = makeSample({ timestamp: 1000, speed: 10 });
      const curr = makeSample({ timestamp: 2000, speed: null });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(true);
    });

    test('skips accel check when previous speed is null', () => {
      const prev = makeSample({ timestamp: 1000, speed: null });
      const curr = makeSample({ timestamp: 2000, speed: 20 });
      const result = validateGPSSample(curr, prev);
      expect(result.valid).toBe(true);
    });

    test('skips accel check when no previous sample', () => {
      const result = validateGPSSample(makeSample({ speed: 50 }), null);
      expect(result.valid).toBe(true);
    });
  });

  describe('short-circuit behavior', () => {
    test('Null Island check runs before range check', () => {
      const result = validateGPSSample(
        makeSample({ latitude: 0, longitude: 0, accuracy: 200 }),
        null,
      );
      expect(result.reason).toBe(RejectionReason.NULL_ISLAND);
    });

    test('range check runs before accuracy check', () => {
      const result = validateGPSSample(
        makeSample({ latitude: 100, accuracy: 200 }),
        null,
      );
      expect(result.reason).toBe(RejectionReason.OUT_OF_RANGE);
    });

    test('accuracy check runs before altitude check', () => {
      const result = validateGPSSample(
        makeSample({ accuracy: 200, altitude: -600 }),
        null,
      );
      expect(result.reason).toBe(RejectionReason.LOW_ACCURACY);
    });
  });

  describe('createRejectionCounters', () => {
    test('creates counter object with all rejection reasons', () => {
      const counters = createRejectionCounters();
      expect(Object.keys(counters)).toHaveLength(8);
      for (const value of Object.values(counters)) {
        expect(value).toBe(0);
      }
    });
  });
});
