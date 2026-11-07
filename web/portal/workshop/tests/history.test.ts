import assert from 'node:assert/strict';
import test from 'node:test';
import { historyComparison } from '../v2Model.ts';

test('history compares every duration on one uncapped, zero-based scale', () => {
  const rows = historyComparison('2026-09-10', 82, [
    { date: '2026-08-21', duration: 78 },
    { date: '2026-08-07', duration: 90 },
    { date: '2026-07-17', duration: 80 },
    { date: '2026-06-26', duration: 98 },
  ]);
  assert.equal(rows.length, 5);
  assert.equal(rows[0].current, true);
  assert.equal(rows[1].duration, 78);
  assert.equal(rows.at(-1)!.percent, 100);
  assert.ok(Math.abs(rows[1].percent / rows.at(-1)!.percent - 78 / 98) < 1e-12);
  assert.ok(rows[1].percent < rows[0].percent);
  assert.ok(rows[0].percent < rows[2].percent);
});

test('history needs a prior effort, and equal times keep equal lengths', () => {
  assert.deepEqual(historyComparison('2026-09-10', 235, []), []);
  const rows = historyComparison('2026-09-10', 235, [
    { date: '2026-07-01', duration: 235 },
    { date: '2026-08-01', duration: 263 },
  ]);
  assert.equal(rows[1].date, '2026-08-01');
  assert.equal(rows[0].percent, rows[2].percent);
  assert.equal(rows[1].percent, 100);
});
