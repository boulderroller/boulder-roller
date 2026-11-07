import test from 'node:test';
import assert from 'node:assert/strict';
import { buildEstimatedPowerStream, estimateClimbPower } from '../src/lib/estimatedPower.ts';
import type { GpsPoint, StreamResponse } from '../src/lib/api.ts';

const points: GpsPoint[] = Array.from({ length: 6 }, (_, index) => ({
  sequenceNum: index,
  timestamp: new Date(Date.UTC(2026, 9, 20, 12, 0, index)).toISOString(),
  latitude: 40,
  longitude: -75 + index * 0.0001,
  distanceM: index * 10,
  elevationM: 100,
}));
const speedStream: StreamResponse = {
  id: null,
  rideId: 'same-effort',
  streamType: 'speed',
  timestamps: points.map(point => String(point.timestamp)),
  values: points.map(() => 10),
  sampleCount: points.length,
  minValue: 10,
  maxValue: 10,
  avgValue: 10,
};
const effort = { rideId: 'same-effort', points, speedStream, rideDurationS: 5 };

test('steady flat effort uses the 75 kg rider plus 8 kg bike reference', () => {
  const estimate = buildEstimatedPowerStream(effort);
  assert.ok(estimate);
  // At 10 m/s on level ground, the standard-mass model rounds to 243 W.
  assert.deepEqual(estimate.values, [243, 243, 243, 243, 243, 243]);
  assert.equal(estimate.avgValue, 243);
  assert.equal(estimate.streamType, 'estimated_power');
});

test('stored rider weights cannot change any sample or summary of an effort', () => {
  const standard = buildEstimatedPowerStream(effort);
  assert.ok(standard);
  for (const riderWeightKg of [55, 75, 100, null, undefined]) {
    // Exercise stale runtime callers too, even after weight leaves the input type.
    const input = { ...effort, riderWeightKg };
    assert.deepEqual(buildEstimatedPowerStream(input), standard, `stored weight: ${riderWeightKg}`);
  }
});


test('canonical estimate and range match the backend exact-slope model', () => {
  for (const [distance, gain, time] of [[100, 10, 20], [1000, 300, 100], [1000, 0, 100], [1000, -100, 100]]) {
    const speed = distance / time;
    const angle = Math.atan2(gain, distance);
    const power = (cda: number, crr: number) => Math.max(0,
      (83 * 9.80665 * (Math.sin(angle) + crr * Math.cos(angle)) * speed
        + .5 * 1.225 * cda * speed ** 3) / .975);
    const result = estimateClimbPower(distance, gain, time);
    assert.ok(Math.abs(result.watts - power(.32, .005)) < 1e-9);
    assert.ok(Math.abs(result.rangeW[0] - power(.28, .004)) < 1e-9);
    assert.ok(Math.abs(result.rangeW[1] - power(.36, .006)) < 1e-9);
  }
});

test('gravity offsets acceleration before the descent trace is clamped', () => {
  let distance = 0;
  const descent: GpsPoint[] = Array.from({ length: 120 }, (_, i) => {
    const point = { sequenceNum: i, latitude: 39.95 + distance / 111195, longitude: -75.2,
      elevationM: 300 - .06 * distance, distanceM: distance,
      timestamp: new Date(Date.UTC(2026, 9, 1, 12, 0, i)).toISOString() };
    distance += Math.min(18, 6 + i * .4);
    return point;
  });
  const estimate = buildEstimatedPowerStream({ points: descent });
  assert.ok(estimate);
  // The reviewed signed-force model is about 91 W. Clamping away downhill
  // gravity before acceleration raised this same trace to about 133 W.
  assert.ok(estimate.avgValue > 90 && estimate.avgValue < 92, `${estimate.avgValue} W`);
});
