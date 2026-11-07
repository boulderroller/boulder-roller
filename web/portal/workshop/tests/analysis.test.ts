import assert from 'node:assert/strict';
import test from 'node:test';
import { analysisSamples, channelSummary, nearestIndex, normalizeRange, scopedSamples, traceRuns, thinRun } from '../v3Model.ts';
import type { Sample } from '../scenario.ts';

const points = (count = 12): Sample[] => Array.from({ length: count }, (_, i) => ({ lon: -75 + i / 10000, lat: 40, t: i * 2, d: i * 20, elevation: i * 2, power: i * 10, cadence: 80, speed: 10, heartRate: null }));

test('analysis preserves zeros, weights irregular intervals, and leaves missing channels absent', () => {
  const source = points(4);
  [0, 2, 12, 62].forEach((t, i) => { source[i].t = t; });
  [0, 100, 200, 300].forEach((power, i) => { source[i].power = power; });
  source[0].cadence = 0;
  const data = analysisSamples(source);
  assert.deepEqual(channelSummary(data, 'power'), { average: 1000 / 12, min: 0, max: 300, coverage: 12 });
  assert.equal(channelSummary(data, 'cadence').average, 800 / 12);
  assert.deepEqual(channelSummary(data, 'heartRate'), { average: null, min: null, max: null, coverage: 0 });
  assert.deepEqual(traceRuns(data, 'power').map(run => run.length), [3, 1]);
});

test('selection keeps global indexes and exact boundaries across distance and time axes', () => {
  const data = analysisSamples(points());
  const range = normalizeRange(data.length, 8, 3);
  assert.deepEqual(range, { startIndex: 3, endIndex: 8 });
  assert.equal(nearestIndex(data, data[3].d, 'distance'), 3);
  assert.equal(nearestIndex(data, data[3].t, 'time'), 3);
  const selected = scopedSamples(data, range);
  assert.equal(selected[0].index, 3);
  assert.equal(selected.at(-1)!.index, 8);
  assert.equal(selected.at(-1)!.t - selected[0].t, 10);
  assert.deepEqual(normalizeRange(data.length, 11, 11), { startIndex: 10, endIndex: 11 });
});

test('grade follows the recorded slope and abstains across gaps, missing elevation, and stationary windows', () => {
  const source = points();
  assert.equal(analysisSamples(source)[5].grade, 10);
  source[6].elevation = null;
  assert.equal(analysisSamples(source)[5].grade, null);
  const gap = points(); gap.slice(6).forEach(p => { p.t += 60; });
  assert.equal(analysisSamples(gap)[5].grade, null);
  assert.equal(analysisSamples(points().map(p => ({ ...p, d: 0 })))[5].grade, null);
  assert.equal(scopedSamples(analysisSamples(points()), { startIndex: 4, endIndex: 5 })[0].grade, null);
});

test('speed fallback respects recording gaps and chart thinning retains a short power spike', () => {
  const source = points(2000);
  source[0].speed = null;
  source[1].speed = null;
  source[2].speed = null; source[2].t = 50;
  const data = analysisSamples(source.slice(0, 3));
  assert.equal(data[0].speed, 10);
  assert.equal(data[0].speedDerived, true);
  assert.equal(data[1].speed, null);
  assert.equal(data[2].speed, null);
  source[941].power = 1700;
  source.forEach((p, i) => { if (i !== 941) p.power = 100; });
  source.forEach((p, i) => { p.t = i * 2; });
  const thin = thinRun(analysisSamples(source), 'power', 200);
  assert.ok(thin.some(p => p.index === 941 && p.power === 1700));
  assert.equal(thin[0].index, 0);
  assert.equal(thin.at(-1)!.index, 1999);
});

test('derived speed is weighted over the exact interval that produced it', () => {
  const source = points(3);
  [0, 10, 30].forEach((t, i) => { source[i].t = t; source[i].speed = null; });
  [0, 100, 500].forEach((d, i) => { source[i].d = d; });
  assert.equal(channelSummary(analysisSamples(source), 'speed').average, 500 / 30);
  assert.equal(channelSummary(analysisSamples(source), 'speed').coverage, 30);
});

test('selected speed excludes a derived interval outside its final endpoint but retains a recorded reading', () => {
  const source = points(3);
  [0, 10, 20].forEach((t, i) => { source[i].t = t; source[i].speed = null; });
  [0, 100, 1100].forEach((d, i) => { source[i].d = d; });
  const selected = scopedSamples(analysisSamples(source), { startIndex: 0, endIndex: 1 });
  assert.equal(selected.at(-1)!.speed, null);
  assert.equal(channelSummary(selected, 'speed').max, 10);
  source[1].speed = 11;
  assert.equal(scopedSamples(analysisSamples(source), { startIndex: 0, endIndex: 1 }).at(-1)!.speed, 11);
});
