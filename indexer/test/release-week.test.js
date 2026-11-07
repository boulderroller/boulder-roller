const assert = require('node:assert/strict');
const test = require('node:test');

const {
  ReleaseAuthorityProjectionPending,
  assertFrozenReleaseSettlementWeek,
  requireIndexedReleaseSettlementWeek,
} = require('../dist/releaseWeek.js');

test('released completion week must equal frozen authority week', () => {
  assert.doesNotThrow(() => assertFrozenReleaseSettlementWeek('42', '42'));
  assert.throws(
    () => assertFrozenReleaseSettlementWeek('41', '42'),
    /conflicts with frozen release authority/
  );
  assert.throws(
    () => assertFrozenReleaseSettlementWeek('43', '42'),
    /conflicts with frozen release authority/
  );
});

test('released completion requires the indexed authority before projection', async () => {
  const pending = await requireIndexedReleaseSettlementWeek(
    'release-pda',
    '42',
    async () => ({ rows: [] })
  ).catch((error) => error);
  assert.equal(pending instanceof ReleaseAuthorityProjectionPending, true);
  assert.equal(pending.releaseAuthorityPda, 'release-pda');
  await assert.doesNotReject(
    requireIndexedReleaseSettlementWeek(
      'release-pda',
      '42',
      async () => ({ rows: [{ release_settlement_week: '42' }] })
    )
  );
});

test('release week mismatch remains a permanent conflict', async () => {
  const mismatch = await requireIndexedReleaseSettlementWeek(
    'release-pda',
    '42',
    async () => ({ rows: [{ release_settlement_week: '43' }] })
  ).catch((error) => error);
  assert.equal(mismatch instanceof ReleaseAuthorityProjectionPending, false);
  assert.match(mismatch.message, /conflicts with frozen release authority/);
});
