import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compareBaseUnits,
  decimalToBaseUnits,
  formatBaseUnits,
  formatCompactBaseUnits,
  sumBaseUnits,
} from '../src/lib/tokenAmounts.ts';

test('decimal input remains exact above Number.MAX_SAFE_INTEGER', () => {
  assert.equal(decimalToBaseUnits('9007199.254740993', 9), '9007199254740993');
  assert.equal(compareBaseUnits('9007199254740993', '9007199254740992'), 1);
});

test('base-unit formatting preserves nine-decimal dust without Number', () => {
  assert.equal(formatBaseUnits('340000000000', 9), '340');
  assert.equal(formatBaseUnits('1', 9), '0.000000001');
  assert.equal(formatBaseUnits('9007199254740993', 9), '9,007,199.254740993');
  assert.equal(formatCompactBaseUnits('22154000000000', 9), '22.2K');
});

test('base-unit sums remain exact', () => {
  assert.equal(
    sumBaseUnits(['9007199254740993', '340000000000', '1']),
    '9007539254740994',
  );
});

test('invalid or out-of-range action amounts fail closed', () => {
  assert.equal(decimalToBaseUnits('0', 9), '0');
  assert.equal(decimalToBaseUnits('1.0000000001', 9), null);
  assert.equal(decimalToBaseUnits('18446744073.709551616', 9), null);
  assert.equal(decimalToBaseUnits('9'.repeat(10_000), 9), null);
});
