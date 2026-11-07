/**
 * GPS Validation Constants Symmetry Test
 *
 * Ensures mobile-side validation constants are consistent with
 * backend validation in workout-parse/src/climb/utils.rs.
 *
 * Mobile is the stricter gatekeeper — samples that pass mobile
 * validation are never rejected by backend. This test verifies
 * that shared checks use identical or tighter thresholds on mobile.
 *
 * If this test fails, one side changed without the other.
 * Check both files and align.
 *
 * Mobile:  mobile/src/lib/gpsValidation.ts
 * Backend: workout-parse/src/climb/utils.rs
 */

import {
  MAX_ACCURACY_M,
  MAX_SPEED_MPS,
  MAX_IMPLIED_SPEED_MPS,
  MAX_ACCEL_MPS2,
  ALT_MIN_M,
  ALT_MAX_M,
} from '../gpsValidation';

import { CURRENT_PARSER_VERSION } from '../preliminaryHash';

describe('GPS validation constants symmetry', () => {
  // workout-parse/src/climb/utils.rs:400-401
  // is_valid_gps checks: lat.abs() <= 90, lon.abs() <= 180, not (0,0)
  // Mobile checks 1+2 are identical. No constant to compare — logic match.

  // workout-parse/src/climb/utils.rs:405
  // MAX_STEP_DISTANCE_M = 500.0 (per-step haversine cap, not a speed gate)
  // Mobile uses MAX_SPEED_MPS = 50 m/s which at 1Hz = 50m/sample.
  // Backend caps at 500m/step — mobile is 10x stricter. Intentional.
  test('mobile speed gate is stricter than backend step-distance cap', () => {
    const backendMaxStepDistanceM = 500;
    const mobileMaxDistancePerSecond = MAX_SPEED_MPS * 1; // 1Hz sampling
    expect(mobileMaxDistancePerSecond).toBeLessThanOrEqual(backendMaxStepDistanceM);
  });

  test('coordinate-derived speed gate matches device speed ceiling', () => {
    expect(MAX_IMPLIED_SPEED_MPS).toBe(MAX_SPEED_MPS);
  });

  // Mobile-only gates (backend does not filter by these — mobile is stricter)
  test('accuracy gate is set to industry-aligned value', () => {
    expect(MAX_ACCURACY_M).toBe(50);
  });

  test('acceleration gate is set to physiological ceiling', () => {
    expect(MAX_ACCEL_MPS2).toBe(6);
  });

  test('altitude bounds cover Dead Sea to Everest', () => {
    expect(ALT_MIN_M).toBe(-500);
    expect(ALT_MAX_M).toBe(9000);
  });

  // workout-parse/src/canonicalize.rs:12
  // CURRENT_PARSER_VERSION = PARSER_VERSION_V5
  test('parser version matches workout-parse CURRENT_PARSER_VERSION', () => {
    const rustParserVersion = 5; // from workout-parse/src/canonicalize.rs
    expect(CURRENT_PARSER_VERSION).toBe(rustParserVersion);
  });
});
