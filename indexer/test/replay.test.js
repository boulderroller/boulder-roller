const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { BorshAccountsCoder } = require('@coral-xyz/anchor');
const { PublicKey } = require('@solana/web3.js');

const { decodeAccount, decodeEvents } = require('../dist/decoder.js');
const {
  decodeClimbCompletionFlow,
  decodeStakerAllocationEpochs,
  serializeEventFields,
  shouldProjectCanonicalEvent,
  summarizeReplayResults,
} = require('../dist/modes/replay.js');

const PROGRAM_ID = 'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH';

test('decodeEvents parses live Anchor Program data logs for epoch distribution', () => {
  const logs = [
    `Program ${PROGRAM_ID} invoke [1]`,
    'Program log: Instruction: DistributeEpochRewards',
    'Program data: 6F/JDF6NSTsFAAAAAAAAAHcAAAAAAAAAR8VUuuGfZiyMG8jrFqmc0VYVGF8gcqkTAneqGdsj4UB1SQIAAAAAAABAehDzWgAAdwAAAAAAAABFzOdpAAAAAA==',
    'Program data: G3kvFZ7uf4wFAAAAAAAAAHcAAAAAAAAAsptsAgAAAADF29EBAAAAAHVJAgAAAAAAFGkZAAAAAADMWSoAAAAAAJizVAAAAAAAAQAAAAE/aOIAAAAAAEXM52kAAAAA',
    `Program ${PROGRAM_ID} success`,
  ];

  const events = decodeEvents(logs);
  assert.deepEqual(
    events.map((event) => event.name),
    ['StakerAllocation', 'EpochRewardsDistributed']
  );

  const distribution = events.find((event) => event.name === 'EpochRewardsDistributed');
  assert.ok(distribution);
  assert.equal(distribution.data.vaultId.toString(), '5');
  assert.equal(distribution.data.epoch.toString(), '119');
  assert.equal(distribution.data.totalDistributed.toString(), '40672178');
});

test('summarizeReplayResults refuses an all-processed cursor when any tx was unavailable', () => {
  assert.deepEqual(
    summarizeReplayResults([
      { events: 2, processed: true },
      { events: 0, processed: false },
    ]),
    { processed: 1, events: 2, allProcessed: false }
  );
});

test('failed transactions never enter canonical event projections', () => {
  assert.equal(shouldProjectCanonicalEvent(null), true);
  assert.equal(shouldProjectCanonicalEvent(undefined), true);
  assert.equal(shouldProjectCanonicalEvent({ InstructionError: [0, 'Custom'] }), false);
});

test('staker allocation replay preserves eligibility and derives snapshot week from epoch', () => {
  assert.deepEqual(
    decodeStakerAllocationEpochs({
      epoch: 119n,
      eligibleFromEpoch: 117n,
    }),
    {
      epoch: 119,
      eligibleFromEpoch: 117,
      snapshotEpoch: 119,
    }
  );
});

test('completion-flow replay preserves exact hash bytes and credited settlement week', () => {
  const evidenceHash = Buffer.alloc(32, 0xab);
  const serialized = serializeEventFields({
    vaultId: 42n,
    rideAttestation: new PublicKey('2'.repeat(44)),
    completionEvidenceHash: [...evidenceHash],
    creditedSettlementWeek: 119n,
    calTributed: 1000n,
  });

  assert.equal(serialized.completionEvidenceHash, evidenceHash.toString('hex'));
  const flow = decodeClimbCompletionFlow(serialized);
  assert.equal(flow.evidenceVersion, 1);
  assert.equal(flow.vaultId, '42');
  assert.equal(flow.rideAttestation, new PublicKey('2'.repeat(44)).toBase58());
  assert.deepEqual(flow.completionEvidenceHash, evidenceHash);
  assert.equal(flow.creditedSettlementWeek, '119');
  assert.equal(flow.calTributed, '1000');
});

test('completion-flow replay preserves explicit V2 evidence and full-width tribute', () => {
  const evidenceHash = Buffer.alloc(32, 0xef);
  const maxU64 = '18446744073709551615';
  const flow = decodeClimbCompletionFlow({
    evidenceVersion: 2,
    vaultId: maxU64,
    rideAttestation: new PublicKey('2'.repeat(44)).toBase58(),
    completionEvidenceHash: evidenceHash.toString('hex'),
    creditedSettlementWeek: maxU64,
    calTributed: maxU64,
  });

  assert.equal(flow.evidenceVersion, 2);
  assert.equal(flow.vaultId, maxU64);
  assert.deepEqual(flow.completionEvidenceHash, evidenceHash);
  assert.equal(flow.creditedSettlementWeek, maxU64);
  assert.equal(flow.calTributed, maxU64);
});

test('decodeEvents parses the completion-flow Anchor wire event', () => {
  const evidenceHash = Buffer.alloc(32, 0xcd);
  const rideAttestation = new PublicKey('2'.repeat(44));
  const u64 = (value) => {
    const encoded = Buffer.alloc(8);
    encoded.writeBigUInt64LE(BigInt(value));
    return encoded;
  };
  const i64 = (value) => {
    const encoded = Buffer.alloc(8);
    encoded.writeBigInt64LE(BigInt(value));
    return encoded;
  };
  const eventData = Buffer.concat([
    crypto.createHash('sha256').update('event:ClimbCompletionFlowAssigned').digest().subarray(0, 8),
    u64(42),
    rideAttestation.toBuffer(),
    evidenceHash,
    u64(119),
    u64(1000),
    i64(1_700_000_000),
  ]);
  const events = decodeEvents([
    `Program ${PROGRAM_ID} invoke [1]`,
    `Program data: ${eventData.toString('base64')}`,
    `Program ${PROGRAM_ID} success`,
  ]);

  assert.equal(events.length, 1);
  assert.equal(events[0].name, 'ClimbCompletionFlowAssigned');
  const flow = decodeClimbCompletionFlow(serializeEventFields(events[0].data));
  assert.equal(flow.vaultId, '42');
  assert.equal(flow.rideAttestation, rideAttestation.toBase58());
  assert.deepEqual(flow.completionEvidenceHash, evidenceHash);
  assert.equal(flow.creditedSettlementWeek, '119');
  assert.equal(flow.calTributed, '1000');
});

test('decodeEvents parses the V2 completion-flow Anchor wire event', () => {
  const evidenceHash = Buffer.alloc(32, 0xde);
  const rideAttestation = new PublicKey('2'.repeat(44));
  const u64 = (value) => {
    const encoded = Buffer.alloc(8);
    encoded.writeBigUInt64LE(BigInt(value));
    return encoded;
  };
  const i64 = (value) => {
    const encoded = Buffer.alloc(8);
    encoded.writeBigInt64LE(BigInt(value));
    return encoded;
  };
  const eventData = Buffer.concat([
    crypto.createHash('sha256').update('event:ClimbCompletionFlowAssignedV2').digest().subarray(0, 8),
    Buffer.from([2]),
    u64(42),
    rideAttestation.toBuffer(),
    evidenceHash,
    u64(119),
    u64(18446744073709551615n),
    i64(1_700_000_000),
  ]);
  const events = decodeEvents([
    `Program ${PROGRAM_ID} invoke [1]`,
    `Program data: ${eventData.toString('base64')}`,
    `Program ${PROGRAM_ID} success`,
  ]);

  assert.equal(events.length, 1);
  assert.equal(events[0].name, 'ClimbCompletionFlowAssignedV2');
  const flow = decodeClimbCompletionFlow(serializeEventFields(events[0].data));
  assert.equal(flow.evidenceVersion, 2);
  assert.equal(flow.vaultId, '42');
  assert.equal(flow.rideAttestation, rideAttestation.toBase58());
  assert.deepEqual(flow.completionEvidenceHash, evidenceHash);
  assert.equal(flow.creditedSettlementWeek, '119');
  assert.equal(flow.calTributed, '18446744073709551615');
});

test('completion-flow replay rejects malformed monetary evidence', () => {
  const valid = {
    vaultId: '42',
    rideAttestation: new PublicKey('2'.repeat(44)).toBase58(),
    completionEvidenceHash: Buffer.alloc(32, 0xab).toString('hex'),
    creditedSettlementWeek: '119',
    calTributed: '1000',
  };

  assert.throws(
    () => decodeClimbCompletionFlow({ ...valid, completionEvidenceHash: 'ab'.repeat(31) }),
    /exactly 32 bytes/
  );
  assert.throws(
    () => decodeClimbCompletionFlow({ ...valid, creditedSettlementWeek: '-1' }),
    /non-negative integer/
  );
  assert.throws(
    () => decodeClimbCompletionFlow({ ...valid, vaultId: undefined }),
    /non-negative integer/
  );
  const maxU64 = '18446744073709551615';
  const fullWidth = decodeClimbCompletionFlow({
    ...valid,
    vaultId: maxU64,
    creditedSettlementWeek: maxU64,
    calTributed: maxU64,
  });
  assert.equal(fullWidth.vaultId, maxU64);
  assert.equal(fullWidth.creditedSettlementWeek, maxU64);
  assert.equal(fullWidth.calTributed, maxU64);
  assert.throws(
    () => decodeClimbCompletionFlow({ ...valid, vaultId: '18446744073709551616' }),
    /supported integer range/
  );
  assert.throws(
    () => decodeClimbCompletionFlow({ ...valid, calTributed: '1.5' }),
    /non-negative integer/
  );
  assert.throws(
    () => decodeClimbCompletionFlow({ ...valid, evidenceVersion: 4 }),
    /evidenceVersion must be 1, 2, or 3/
  );
});

const LEGACY_LOCAL_LEGEND_BASE64 =
  'GLDX4adSe9UyeQYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACDAAAAAAAAAIsAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABXNWwcAAAAAAf8=';

function legacyLocalLegendFixture() {
  return Buffer.from(LEGACY_LOCAL_LEGEND_BASE64, 'base64');
}

function currentLocalLegendFixture(isBootstrap) {
  const legacy = legacyLocalLegendFixture();
  const current = Buffer.alloc(123);
  legacy.copy(current, 0, 0, 121);
  current[121] = isBootstrap ? 1 : 0;
  current[122] = legacy[121];
  return current;
}

test('decodeAccount infers bootstrap only for the exact 122-byte legacy LocalLegend layout', () => {
  const decoded = decodeAccount(legacyLocalLegendFixture());
  assert.equal(decoded.type, 'LocalLegend');
  assert.equal(decoded.fields.vaultId, 424242n);
  assert.equal(decoded.fields.isActive, true);
  assert.equal(decoded.fields.isBootstrap, true);
  assert.equal(decoded.fields.bump, 255);
});

test('decodeAccount preserves the explicit bootstrap byte in the exact 123-byte LocalLegend layout', () => {
  const decoded = decodeAccount(currentLocalLegendFixture(false));
  assert.equal(decoded.type, 'LocalLegend');
  assert.equal(decoded.fields.vaultId.toString(), '424242');
  assert.equal(decoded.fields.isActive, true);
  assert.equal(decoded.fields.isBootstrap, false);
  assert.equal(decoded.fields.bump, 255);
});

test('decodeAccount fails closed for noncanonical or unexpected LocalLegend layouts', () => {
  const noncanonicalLegacy = legacyLocalLegendFixture();
  noncanonicalLegacy[120] = 2;
  assert.equal(decodeAccount(noncanonicalLegacy), null);

  const oversizedCurrent = Buffer.concat([
    currentLocalLegendFixture(true),
    Buffer.from([0]),
  ]);
  assert.equal(decodeAccount(oversizedCurrent), null);
});
