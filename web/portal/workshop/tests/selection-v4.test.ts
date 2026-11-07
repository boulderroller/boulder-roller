import assert from 'node:assert/strict';
import test from 'node:test';
import { boundSelection, resizeSelection, translateSelection } from '../v4Selection.ts';
import { analysisSamples } from '../v3Model.ts';
const source = analysisSamples([0, 10, 20, 25, 30, 40, 60, 80, 100].map((d, i) => ({ d, t: [0, 5, 10, 20, 25, 30, 40, 50, 60][i], elevation: d, power: 100, lon: -75 + d / 10000, lat: 40 })));

test('a selected stretch cannot escape its ride or climb, including a reversed drag', () => {
  const subject = { startIndex: 2, endIndex: 6 };
  assert.deepEqual(boundSelection(subject, 0, 8), subject);
  assert.deepEqual(boundSelection(subject, 5, 3), { startIndex: 3, endIndex: 5 });
  assert.deepEqual(boundSelection(subject, 6, 6), { startIndex: 5, endIndex: 6 });
});

test('resizing a boundary keeps the other boundary and cannot cross it', () => {
  const subject = { startIndex: 2, endIndex: 8 }, selection = { startIndex: 3, endIndex: 6 };
  assert.deepEqual(resizeSelection(subject, selection, 'start', 8), { startIndex: 5, endIndex: 6 });
  assert.deepEqual(resizeSelection(subject, selection, 'end', 0), { startIndex: 3, endIndex: 4 });
  assert.deepEqual(resizeSelection(subject, selection, 'start', 0), { startIndex: 2, endIndex: 6 });
});

test('moving a stretch follows distance, not irregular sample counts', () => {
  const range = translateSelection(source, { startIndex: 0, endIndex: 8 }, { startIndex: 1, endIndex: 4 }, 10, 'distance');
  assert.deepEqual(range, { startIndex: 2, endIndex: 5 });
  assert.equal(source[range.endIndex].d - source[range.startIndex].d, 20);
  assert.deepEqual(translateSelection(source, { startIndex: 2, endIndex: 6 }, { startIndex: 2, endIndex: 5 }, 999, 'distance'), { startIndex: 5, endIndex: 6 });
});

test('time selection preserves physical duration and allows stationary intervals', () => {
  assert.deepEqual(translateSelection(source, { startIndex: 0, endIndex: 8 }, { startIndex: 1, endIndex: 2 }, 15, 'time'), { startIndex: 3, endIndex: 4 });
  const paused = source.map(p => ({ ...p, d: 0 }));
  assert.deepEqual(translateSelection(paused, { startIndex: 0, endIndex: 8 }, { startIndex: 1, endIndex: 2 }, 15, 'time'), { startIndex: 3, endIndex: 4 });
});

test('distance translation does not collapse a stationary interval or a boundary-clamped pause', () => {
  const paused = analysisSamples([0, 10, 10, 10, 20].map((d, i) => ({ d, t: [0, 1, 61, 121, 122][i], elevation: 20, power: 0, lon: -75, lat: 40 })));
  const subject = { startIndex: 0, endIndex: 4 }, selection = { startIndex: 1, endIndex: 3 };
  assert.deepEqual(translateSelection(paused, subject, selection, 0, 'distance'), selection);
  assert.deepEqual(translateSelection(paused, subject, selection, 5, 'distance'), selection);
  const atEnd = { startIndex: 3, endIndex: 4 };
  assert.deepEqual(translateSelection(paused, subject, atEnd, 50, 'distance'), atEnd);
});
