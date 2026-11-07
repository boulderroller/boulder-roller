import assert from 'node:assert/strict';
import { test } from 'node:test';
import { stage1Live, stage1Amount, stage1Backing, stage1StakingAssets, registerStage1TestMint } from '../src/lib/stage1';
import { describePush } from '../src/lib/notificationLedger';
import { stage1Copy } from '../src/lib/stage1Copy';

test('every Stage 1 surface requires an explicit live status', () => {
  for (const status of [null, {}, { stage1: {} }, { stage1: { live: 'true' } }, { stage1: { live: false } }]) {
    assert.equal(stage1Live(status), false);
  }
  assert.equal(stage1Live({ stage1: { live: true } }), true);
});

test('amounts preserve integer precision and omit absent or malformed data', () => {
  assert.equal(stage1Amount({ amount: '9007199254740993', kind: 'dung' }), '9,007,199.254740993 DUNG');
  for (const amount of [undefined, null, '', '-1', 12, '1.5', 'NaN']) {
    assert.equal(stage1Amount({ amount, kind: 'dung' }), null);
  }
  assert.match(stage1Amount({ amount: '123456', mint: 'unknown-mint', kind: 'cash' })!, /123,456/);
  assert.doesNotMatch(stage1Amount({ amount: '123456', mint: 'unknown-mint', kind: 'cash' })!, /DUNG/);
});

test('backing total is absent if any admitted asset has no fresh quote', () => {
  assert.equal(stage1Backing([]), null);
  assert.equal(stage1Backing([{ backingLamports: '10' }, {}]), null);
  assert.equal(stage1Backing([{ backingLamports: '9007199254740993' }, { backingLamports: '7' }]), '9007199254741000');
});

test('Stage 1 notifications retain money row format without assuming DUNG', () => {
  const push = describePush({ notificationType: 'payout_received', title: 'payout_received',
    metadata: { stage1: true, amountBaseUnits: '123456', kind: 'cash', mint: 'unknown-mint', week: 4 },
  } as any, '12:00');
  assert.equal(push.kind, 'money');
  assert.equal(push.noun, stage1Copy.payoutNotification);
  assert.match(push.value!, /123,456/);
  assert.doesNotMatch(push.value!, /DUNG/);
});

test('pinned token amounts use their exact denominations and unknown stays explicit', () => {
  assert.equal(stage1Amount({ amount: '123456789', mint: 'J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn' }), '0.123456789 jitoSOL');
  assert.equal(stage1Amount({ amount: '123456789', mint: 'DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne' }), '123.456789 USDC');
  assert.match(stage1Amount({ amount: '100', mint: 'unknown' })!, new RegExp(stage1Copy.unknownMint));
});

test('the devnet city cash mint is pinned 6-decimal USDC; it cannot be renamed or offered for pledges', () => {
  const cash = '932CwEMTWHDY1BEkV66DKDgngeEypU3JmybWBu4vMh1e';
  assert.equal(stage1Amount({ amount: '123456789', mint: cash, kind: 'cash' }), '123.456789 USDC');
  const push = describePush({ notificationType: 'payout_received', title: 'payout_received',
    metadata: { stage1: true, amountBaseUnits: '123456', kind: 'cash', mint: cash, week: 4 },
  } as any, '12:00');
  assert.equal(push.value, '0.123456 USDC');
  registerStage1TestMint(cash);
  assert.equal(stage1Amount({ amount: '1', mint: cash }), '0.000001 USDC');
  const config = { mint: cash, slot: 0, adapter: 254, enabled: true, admittedEpoch: '1', lastFreshUntil: '0', admittedNumerator: '1', admittedDenominator: '1' };
  assert.deepEqual(stage1StakingAssets({ hill: 'hill', cityState: { seasonAnchor: '0', providerSlots: 1, assetCount: 1, intakePaused: false },
    assets: [{ mint: cash, config }] }), []);
});

test('pre-bond backing lists skip sponsor cash that shares the backed slot', async () => {
  const { pledgePlan } = await import('../src/lib/stage1Actions');
  const jito = 'J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn', cash = '932CwEMTWHDY1BEkV66DKDgngeEypU3JmybWBu4vMh1e';
  const config = (mint: string, adapter: number) => ({ mint, slot: 0, adapter, enabled: true, admittedEpoch: '1', lastFreshUntil: '0', admittedNumerator: '1', admittedDenominator: '1' });
  const bonding = { hill: 'hill', climb: 'climb', bonded: false,
    hillState: { bonded: false, foundingCutoff: '0', foundingFreshSlots: 0, assetLots: ['2'] },
    cityState: { seasonAnchor: '0', providerSlots: 1, assetCount: 2, intakePaused: false },
    assets: [{ mint: cash, config: config(cash, 254) }, { mint: jito, config: config(jito, 2) }] };
  const plan = pledgePlan(bonding, jito, '1000', 26, '7');
  assert.deepEqual(plan.intent.kind === 'stage1_pledge' && plan.intent.backingMints, [jito]);
});
