const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { BN, BorshAccountsCoder } = require('@coral-xyz/anchor');
const web3 = require('@solana/web3.js');
const db = require('../dist/db.js');
const { loadIdl } = require('../dist/decoder.js');
const common = require('../dist/writers/common.js');
const { runReplay, runReplaySweep } = require('../dist/modes/replay.js');

function signature(signature, slot) {
  return { signature, slot, blockTime: null, err: null, memo: null, confirmationStatus: 'finalized' };
}

function mockedTransaction() {
  return {
    meta: { err: null, fee: 0, computeUnitsConsumed: null, logMessages: [] },
    transaction: {
      message: {
        compiledInstructions: [],
        staticAccountKeys: [],
      },
    },
  };
}

function mockReplayRpc(t, state, pageForOptions) {
  const heads=require('../dist/finalized-head'),oldHeads=heads.finalizedHeads;
  heads.finalizedHeads=new heads.FinalizedHeads();
  t.after(()=>{heads.finalizedHeads=oldHeads;});
  t.mock.method(web3.Connection.prototype,'getSlot',async()=>3000000);
  const originalSignatures = web3.Connection.prototype.getSignaturesForAddress;
  const originalTransaction = web3.Connection.prototype.getTransaction;
  const originalGetSyncState = common.getSyncState;
  const originalUpdateSyncState = common.updateSyncState;
  const calls = [];
  const updates = [];

  t.after(() => {
    web3.Connection.prototype.getSignaturesForAddress = originalSignatures;
    web3.Connection.prototype.getTransaction = originalTransaction;
    common.getSyncState = originalGetSyncState;
    common.updateSyncState = originalUpdateSyncState;
  });

  common.getSyncState = async () => state;
  common.updateSyncState = async (update) => updates.push(update);
  web3.Connection.prototype.getSignaturesForAddress = async (_address, options) => {
    calls.push(options);
    return pageForOptions(options);
  };
  web3.Connection.prototype.getTransaction = async () => mockedTransaction();

  return { calls, updates };
}

test('standalone replay uses the stored cursor as an exclusive lower boundary', async (t) => {
  const storedCursor = 'stored-cursor';
  const newer = [signature('newer-a', 201), signature('newer-b', 200)];
  const { calls } = mockReplayRpc(
    t,
    { last_tx_signature: storedCursor, last_tx_slot: 199 },
    (options) => {
      if (options.limit === 1) return [signature('newest', 201)];
      return [...newer,signature(storedCursor,199)];
      return [];
    },
  );

  const result = await runReplay();

  assert.equal(result.processed, newer.length);
  assert.deepEqual(calls[0], { minContextSlot:3000000, limit:100 });
});

test('standalone replay does not advance the cursor after a later signature page fails', async (t) => {
  const firstPage = Array.from({ length: 100 }, (_, index) => signature(`new-${index}`, 500 - index));
  let pageCount = 0;
  const { updates } = mockReplayRpc(
    t,
    { last_tx_signature: 'stored-cursor', last_tx_slot: 399 },
    (options) => {
      if (options.limit === 1) return [signature('newest', 500)];
      if (pageCount++ === 0) return firstPage;
      throw new Error('later signature page unavailable');
    },
  );

  await runReplay();

  assert.deepEqual(updates, []);
});

test('replay sweep does not advance the cursor after a later signature page fails', async (t) => {
  const firstPage = Array.from({ length: 100 }, (_, index) => signature(`new-${index}`, 500 - index));
  let pageCount = 0;
  const { updates } = mockReplayRpc(
    t,
    { last_tx_signature: 'stored-cursor', last_tx_slot: 399 },
    (options) => {
      if (pageCount++ === 0) return firstPage;
      throw new Error('later signature page unavailable');
    },
  );

  await runReplaySweep();

  assert.deepEqual(updates, []);
});

function u32(value) {
  const encoded = Buffer.alloc(4);
  encoded.writeUInt32LE(value);
  return encoded;
}

function u64(value) {
  const encoded = Buffer.alloc(8);
  encoded.writeBigUInt64LE(BigInt(value));
  return encoded;
}

function i64(value) {
  const encoded = Buffer.alloc(8);
  encoded.writeBigInt64LE(BigInt(value));
  return encoded;
}

function eventDiscriminator(name) {
  return crypto
    .createHash('sha256')
    .update(`event:${name}`)
    .digest()
    .subarray(0, 8);
}

test('release replay retains its cursor after partial projection and converges idempotently', async (t) => {
  const programId = new web3.PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
  const rider = new web3.PublicKey('2'.repeat(44));
  const rideAttestation = new web3.PublicKey('3'.repeat(44));
  const releaseAuthority = new web3.PublicKey('4'.repeat(44));
  const completionReceipt = new web3.PublicKey('5'.repeat(44));
  const evidenceHash = Buffer.alloc(32, 0xa7);
  const coder = new BorshAccountsCoder(loadIdl());
  const authorityData = await coder.encode('HeldRideReleaseAuthority', {
    rideAttestation,
    rider,
    thresholdAuthorityId: Buffer.alloc(16, 0x11),
    thresholdAuthorityCommitment: Buffer.alloc(32, 0x22),
    thresholdEffectiveAt: new BN('1800000000'),
    thresholdW: 250,
    thresholdPolicyVersion: 1,
    economicTss: 64,
    calEarned: new BN('64000000000'),
    calTributeBudget: new BN('6400000000'),
    releasePlanHash: Buffer.alloc(32, 0x33),
    releasedAt: new BN('1800000001'),
    releasedSlot: new BN('123458'),
    releaseSettlementWeek: new BN('119'),
    attester: web3.PublicKey.default,
    bump: 251,
  });
  const receiptData = await coder.encode('ReleasedClimbCompletionReceipt', {
    rideAttestation,
    releaseAuthority,
    vault: web3.PublicKey.default,
    evidenceVersion: 3,
    calTributed: new BN('6400000000'),
    completionEvidenceHash: evidenceHash,
    creditedSettlementWeek: new BN('119'),
    bump: 252,
  });
  const completedEvent = Buffer.concat([
    eventDiscriminator('ReleasedClimbCompleted'),
    Buffer.from([3]),
    completionReceipt.toBuffer(),
    releaseAuthority.toBuffer(),
    u64(42),
    rideAttestation.toBuffer(),
    rider.toBuffer(),
    u32(420),
    u64(6_400_000_000n),
    evidenceHash,
    Buffer.from([0]),
    i64(1_800_000_000),
    i64(1_800_000_001),
  ]);
  const flowEvent = Buffer.concat([
    eventDiscriminator('ReleasedClimbCompletionFlowAssigned'),
    Buffer.from([3]),
    releaseAuthority.toBuffer(),
    u64(42),
    rideAttestation.toBuffer(),
    evidenceHash,
    u64(119),
    u64(6_400_000_000n),
    i64(1_800_000_001),
  ]);
  const tx = {
    meta: {
      err: null,
      fee: 0,
      computeUnitsConsumed: null,
      logMessages: [
        `Program ${programId.toBase58()} invoke [1]`,
        `Program data: ${completedEvent.toString('base64')}`,
        `Program data: ${flowEvent.toString('base64')}`,
        `Program ${programId.toBase58()} success`,
      ],
    },
    transaction: {
      message: { compiledInstructions: [], staticAccountKeys: [] },
    },
  };

  const heads=require('../dist/finalized-head'),oldHeads=heads.finalizedHeads;
  heads.finalizedHeads=new heads.FinalizedHeads();t.after(()=>{heads.finalizedHeads=oldHeads;});
  t.mock.method(web3.Connection.prototype,'getSlot',async()=>3000000);
  const originalSignatures = web3.Connection.prototype.getSignaturesForAddress;
  const originalTransaction = web3.Connection.prototype.getTransaction;
  const originalAccount = web3.Connection.prototype.getAccountInfoAndContext;
  const originalGetSyncState = common.getSyncState;
  const originalUpdateSyncState = common.updateSyncState;
  const originalQuery = db.query;
  const rawEvents = new Set();
  const authorities = new Set();
  const receipts = new Set();
  const flows = new Set();
  const updates = [];
  let failFlowOnce = true;
  t.after(() => {
    web3.Connection.prototype.getSignaturesForAddress = originalSignatures;
    web3.Connection.prototype.getTransaction = originalTransaction;
    web3.Connection.prototype.getAccountInfoAndContext = originalAccount;
    common.getSyncState = originalGetSyncState;
    common.updateSyncState = originalUpdateSyncState;
    db.query = originalQuery;
  });

  common.getSyncState = async () => ({
    last_tx_signature: 'stored-cursor',
    last_tx_slot: 100,
  });
  common.updateSyncState = async (update) => updates.push(update);
  web3.Connection.prototype.getSignaturesForAddress = async (_address, options) => {
    if (options.limit === 1) return [signature('release-tx', 200),signature('stored-cursor',100)];
    return [signature('release-tx', 200),signature('stored-cursor',100)];
  };
  web3.Connection.prototype.getTransaction = async () => tx;
  web3.Connection.prototype.getAccountInfoAndContext = async (pda, options) => {
    const key = pda.toBase58();
    const data = key === releaseAuthority.toBase58()
      ? authorityData
      : key === completionReceipt.toBase58()
        ? receiptData
        : null;
    assert.equal(options.commitment, 'finalized');
    assert.equal(options.minContextSlot, 200);
    return {
      context: { slot: 205 },
      value: data
        ? {
            data,
            executable: false,
            lamports: 1,
            owner: programId,
            rentEpoch: 0,
          }
        : null,
    };
  };
  db.query = async (sql, values) => {
    if (/SELECT release_settlement_week/.test(sql)) {
      return {
        rows: authorities.has(values[0])
          ? [{ release_settlement_week: '119' }]
          : [],
      };
    }
    if (/INSERT INTO indexed_events/.test(sql)) {
      rawEvents.add(`${values[0]}:${values[1]}`);
    } else if (/indexed_held_ride_release_authorities/.test(sql)) {
      authorities.add(values[0]);
    } else if (/indexed_climb_completion_receipts/.test(sql)) {
      receipts.add(values[0]);
    } else if (/INSERT INTO indexed_climb_completion_flows/.test(sql)) {
      if (failFlowOnce) {
        failFlowOnce = false;
        throw new Error('flow projection unavailable once');
      }
      flows.add(`${values[0]}:${values[1]}`);
    }
    return { rows: [] };
  };

  const first = await runReplay();
  assert.deepEqual(first, { processed: 0, events: 0 });
  assert.deepEqual(updates, []);
  assert.deepEqual(rawEvents, new Set(['release-tx:0', 'release-tx:1']));
  assert.deepEqual(authorities, new Set([releaseAuthority.toBase58()]));
  assert.deepEqual(receipts, new Set([completionReceipt.toBase58()]));
  assert.equal(flows.size, 0);

  const second = await runReplay();
  assert.deepEqual(second, { processed: 1, events: 2 });
  assert.equal(updates.length, 1);
  assert.deepEqual(rawEvents, new Set(['release-tx:0', 'release-tx:1']));
  assert.deepEqual(authorities, new Set([releaseAuthority.toBase58()]));
  assert.deepEqual(receipts, new Set([completionReceipt.toBase58()]));
  assert.deepEqual(flows, new Set(['release-tx:1']));
});

test('failed first sweep page must not refresh replay freshness', async (t) => {
  const { updates } = mockReplayRpc(t, { last_tx_signature: 'stored', last_tx_slot: 100 }, () => {
    throw new Error('RPC quota unavailable');
  });
  await runReplaySweep();
  assert.deepEqual(updates, []);
});

test('legacy sweep and lag share one head and the sweep signature page',async(t)=>{
  require('../dist/program-version-window').programVersionWindow.observe(0x4c);
  let heads=0;
  const state={last_tx_signature:'stored-cursor',last_tx_slot:199};
  const {calls}=mockReplayRpc(t,state,()=>[signature('stored-cursor',199)]);
  t.mock.method(web3.Connection.prototype,'getSlot',async()=>{heads++;return 3000000;});
  await runReplaySweep();
  const {measureReplayLag}=require('../dist/lag-monitor');
  const {config}=require('../dist/config');
  const connection=new web3.Connection(config.rpcUrl,'finalized');
  const lag=await measureReplayLag(connection,new web3.PublicKey(config.programId),state);
  assert.equal(heads,1);assert.equal(calls.length,1);assert.equal(lag.status,'current');
  assert.equal(calls[0].minContextSlot,3000000);
});
