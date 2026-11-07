import assert from 'node:assert/strict';
import test from 'node:test';
import { analysisSamples } from '../v3Model';
import { powerDistribution, rideFileStats } from '../v8Metrics';

const samples = analysisSamples([0, 5, 15, 25, 70, 80].map((t, i) => ({
  t, d: i * 100, lon: 0, lat: 0, elevation: 0,
  power: [0, 100, null, 900, 200, 1500][i], speed: [0, 2, 3, 4, 5, 6][i],
})));
test('V8 power distribution measures covered seconds, including zeros, excluding missing readings and gaps', () => {
  const before = JSON.stringify(samples);
  const distribution = powerDistribution(samples, 25);
  assert.equal(distribution.coveredSeconds, 25);
  assert.equal(distribution.bins.reduce((sum, bin) => sum + bin.seconds, 0), 25);
  assert.deepEqual(distribution.bins.filter(bin => bin.seconds > 0).map(bin => [bin.from, bin.seconds]), [[0, 5], [100, 10], [200, 10]]);
  assert.equal(distribution.bins.at(-1)!.to, 225);
  assert.equal(JSON.stringify(samples), before);
});
test('V8 work integrates only covered power while maxima retain exact recorded readings', () => {
  assert.deepEqual(rideFileStats(samples), { maxPower: 1500, maxSpeed: 6, workKj: 3, powerSeconds: 25 });
  assert.deepEqual(rideFileStats(samples.map(p => ({ ...p, power: null }))), { maxPower: null, maxSpeed: 6, workKj: null, powerSeconds: 0 });
  assert.deepEqual(powerDistribution(samples.map(p => ({ ...p, power: null }))), { bins: [], coveredSeconds: 0 });
});

test('V8 distribution bounds display allocation without clamping recorded outliers', () => {
  const outlier = samples.slice(0, 2).map((p, i) => ({ ...p, t: i, power: i ? 0 : 1e9 }));
  const distribution = powerDistribution(outlier);
  assert.ok(distribution.bins.length <= 160);
  assert.equal(distribution.coveredSeconds, 1);
  assert.equal(distribution.bins.reduce((sum, bin) => sum + bin.seconds, 0), 1);
  assert.equal(outlier[0].power, 1e9);
  const extreme = powerDistribution(outlier.map(p => ({ ...p, power: Number.MAX_VALUE })));
  assert.equal(extreme.bins.length, 0);
  assert.equal(extreme.coveredSeconds, 1);
});
