/**
 * Clock-domain discipline tests (MOBILE_TRUTHS §3).
 *
 * The one intentional cross-domain subtraction in gpsRecording lives in
 * sampleOffsetMsFromRideStart. These tests pin the helper's contract so
 * any future change has to declare intent against the truth.
 */

import { sampleOffsetMsFromRideStart } from '../gpsRecording';

describe('sampleOffsetMsFromRideStart', () => {
  test('returns ms since ride start, rounded', () => {
    // Both inputs are Unix ms. Sample arrives 12_345.7 ms after ride start,
    // no pauses. Expect rounded integer ms.
    const rideStart = 1_700_000_000_000;
    const sampleAt = rideStart + 12_346;
    expect(sampleOffsetMsFromRideStart(sampleAt, rideStart, 0)).toBe(12_346);
  });

  test('subtracts accumulated pause duration from the offset', () => {
    // Sample arrives 60s after ride start, rider paused for 15s earlier.
    // Effective ride offset is 45s.
    const rideStart = 1_700_000_000_000;
    const sampleAt = rideStart + 60_000;
    const paused = 15_000;
    expect(sampleOffsetMsFromRideStart(sampleAt, rideStart, paused)).toBe(45_000);
  });

  test('handles sample before ride start (clock skew edge) by returning negative', () => {
    // Wallclock and GPS-sample can drift. A sample arriving before ride
    // start would yield a negative offset; the helper does not silently
    // clamp because that would hide drift from the consumer.
    const rideStart = 1_700_000_000_000;
    const sampleAt = rideStart - 50;
    expect(sampleOffsetMsFromRideStart(sampleAt, rideStart, 0)).toBe(-50);
  });

  test('pause greater than elapsed yields negative (consumer must handle)', () => {
    // Defensive: the helper does not second-guess its inputs. If total
    // pause exceeds elapsed time, it returns negative so the bug is
    // visible at the write site, not laundered into a plausible-looking
    // 0ms offset.
    const rideStart = 1_700_000_000_000;
    const sampleAt = rideStart + 1_000;
    const paused = 5_000;
    expect(sampleOffsetMsFromRideStart(sampleAt, rideStart, paused)).toBe(-4_000);
  });

  test('rounding is half-to-+infinity (JS default Math.round)', () => {
    // Document the rounding mode. Ride-offset precision matters for
    // canonicalization and pause-interval matching downstream — any
    // future switch to a different rounding mode needs a signed change
    // note.
    const rideStart = 0;
    expect(sampleOffsetMsFromRideStart(0.5, rideStart, 0)).toBe(1);
    expect(sampleOffsetMsFromRideStart(1.4, rideStart, 0)).toBe(1);
    expect(sampleOffsetMsFromRideStart(1.5, rideStart, 0)).toBe(2);
  });
});
