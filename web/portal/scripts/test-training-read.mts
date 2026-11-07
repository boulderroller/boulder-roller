import assert from 'node:assert/strict';
import test from 'node:test';
import { trainingRead } from '../src/components/ride/trainingRead.ts';
test('reads engine values, including genuine zero, without recalculating', () => {
  const read = trainingRead({movingS: 0, elapsedS: 900, powerCurveS: [60], powerCurveW: [213.25],
    powerZoneS: [5, 0, 1, 0, 0, 0, 0], powerZoneTotalS: 6,
    powerZoneRangesW: [[0,137],[138,187]], powerZonePct: [83.3,0,16.7,0,0,0,0]});
  assert.equal(read.moving, 0);
  assert.equal(read.curve[0], 213.25);
  assert.deepEqual(read.zones?.ranges, [[0,137],[138,187]]);
});
test('unavailable backend data stays absent', () => {
  assert.equal(trainingRead(undefined).moving, null);
  assert.equal(trainingRead(undefined).zones, null);
});
