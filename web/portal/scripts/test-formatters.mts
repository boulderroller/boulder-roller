import assert from 'node:assert/strict';
import test from 'node:test';

import {
  ABSENT_VALUE,
  calculateNetAmountBaseUnits,
  formatBasisPointsPercentage,
  formatCappedInteger,
  formatDate,
  formatDistance,
  formatDurationCompact,
  formatFileSize,
  formatHoursMinutes,
  formatIdentifier,
  formatMonthYear,
  formatRaceTime,
  formatSignificanceScore,
  formatWeightRange,
  isPlausibleWeightKg,
  parseWeight,
} from '../src/lib/formatters.ts';

test('fee previews keep exact base units and floor the fee like the Anchor program', () => {
  assert.deepEqual(calculateNetAmountBaseUnits('1234567891', '500'), {
    feeBaseUnits: '61728394',
    netBaseUnits: '1172839497',
  });
  assert.deepEqual(calculateNetAmountBaseUnits('1234567891', '50'), {
    feeBaseUnits: '6172839',
    netBaseUnits: '1228395052',
  });
  assert.equal(formatBasisPointsPercentage('500'), '5%');
  assert.equal(formatBasisPointsPercentage('50'), '0.5%');
});

test('date-only backend values stay on their calendar day west of UTC', () => {
  const previousTimezone = process.env.TZ;
  process.env.TZ = 'America/New_York';
  try {
    assert.equal(formatDate('2026-08-30'), 'Aug 30, 2026');
  } finally {
    if (previousTimezone === undefined) delete process.env.TZ;
    else process.env.TZ = previousTimezone;
  }
});

test('invalid calendar dates use the shared absence marker', () => {
  assert.equal(formatDate('2026-02-30'), ABSENT_VALUE);
});

test('distance and climb time follow the ratified precision ledger', () => {
  assert.equal(formatDistance(500, 'metric'), '0.5 km');
  assert.equal(formatRaceTime(4_328), '1:12:08');
});

test('advertised imperial weight endpoints map into the accepted kg range', () => {
  assert.equal(isPlausibleWeightKg(parseWeight('66', 'imperial')), true);
  assert.equal(isPlausibleWeightKg(parseWeight('441', 'imperial')), true);
  assert.equal(formatWeightRange(30, 200, 'metric'), '30–200 kg');
  assert.equal(formatWeightRange(30, 200, 'imperial'), '66–441 lb');
});

test('semantic formatters reject non-finite values and select the right file-size unit', () => {
  assert.equal(formatDistance(Number.POSITIVE_INFINITY, 'metric'), ABSENT_VALUE);
  assert.equal(formatFileSize(50 * 1024 * 1024), '50 MB');
});

test('nonzero short durations never collapse to zero minutes', () => {
  assert.equal(formatDurationCompact(30), '30 s');
  assert.equal(formatDurationCompact(4_328), '1:12');
  assert.equal(formatHoursMinutes(30), '30 s');
});

test('technical identifiers stay exact instead of gaining locale grouping', () => {
  assert.equal(formatIdentifier(1234), '1234');
  assert.equal(formatIdentifier('001234'), '001234');
});

test('significance scores use one diagnostic precision', () => {
  assert.equal(formatSignificanceScore(0.12345), '0.123');
});

test('capped counts use the shared integer formatter', () => {
  assert.equal(formatCappedInteger(99), '99');
  assert.equal(formatCappedInteger(100), '99+');
  assert.equal(formatCappedInteger(Number.NaN), ABSENT_VALUE);
});

test('month-year stamps read as the ledger prints them', () => {
  assert.equal(formatMonthYear('2026-01-15T12:00:00Z'), 'Jan 2026');
  assert.equal(formatMonthYear(null), ABSENT_VALUE);
  assert.equal(formatMonthYear('not-a-date'), ABSENT_VALUE);
});
