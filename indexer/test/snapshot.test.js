const test = require('node:test');
const assert = require('node:assert/strict');
const { Connection, PublicKey } = require('@solana/web3.js');
const decoder = require('../dist/decoder.js');
const writers = require('../dist/writers/index.js');
const common = require('../dist/writers/common.js');
const supply = require('../dist/supply.js');
const { buildIndexerHealthPayload, indexerHealthStatusCode } = require('../dist/health.js');

const {
  assertSnapshotProjectionComplete,
  runSnapshot,
  getSnapshotRuntimeState,
} = require('../dist/modes/snapshot.js');

const COMPLETE_RESULT = {
  total: 16,
  indexed: 16,
  skipped: 0,
  decodeFailures: 0,
  writeFailures: 0,
  fetchFailures: 0,
};

test('snapshot projection completion accepts an exact failure-free result', () => {
  assert.doesNotThrow(() => assertSnapshotProjectionComplete(COMPLETE_RESULT));
});

function mockSnapshot(t, { types = ['Vault'], fetch, decode, write } = {}) {
  let elapsed = 0;
  const waits = [];
  const healthDuringWait = [];
  t.mock.method(Date, 'now', () => elapsed);
  t.mock.method(global, 'setTimeout', (callback, delay) => {
    waits.push(delay);
    elapsed += delay;
    const payload = buildIndexerHealthPayload({ last_account_slot: 100, last_tx_slot: 100 }, 100);
    healthDuringWait.push({ code: indexerHealthStatusCode(payload), status: payload.snapshot.status });
    queueMicrotask(callback);
  });
  for (const method of ['log', 'warn', 'error']) t.mock.method(console, method, () => {});
  const slot = t.mock.method(Connection.prototype, 'getSlot', async () => 100);
  const reads = t.mock.method(Connection.prototype, 'getProgramAccounts', fetch ?? (async () => ({
    context: { slot: 120 },
    value: [{ pubkey: PublicKey.default, account: { data: Buffer.from([1]) } }],
  })));
  t.mock.method(decoder, 'getAccountTypeNames', () => types);
  t.mock.method(decoder, 'decodeAccount', decode ?? (() => ({ type: 'Vault', fields: {} })));
  const writes = t.mock.method(writers, 'routeAccount', write ?? (async () => true));
  const cursor = t.mock.method(common, 'updateSyncState', async () => {});
  const mint = t.mock.method(supply, 'refreshDungMintSupply', async () => ({ written: true, slot: 130, amount: '1' }));
  return { waits, healthDuringWait, slot, reads, writes, cursor, mint, elapsed: () => elapsed };
}

test('snapshot retries a lagging RPC at the same finalized floor and writes only after success', async (t) => {
  let calls = 0;
  const state = mockSnapshot(t, {
    async fetch(_program, options) {
      assert.equal(options.minContextSlot, 100);
      assert.equal(options.commitment, 'finalized');
      assert.equal(options.withContext, true);
      assert.equal(state.writes.mock.callCount(), 0);
      assert.equal(state.cursor.mock.callCount(), 0);
      if (++calls === 1) throw new Error('Minimum context slot has not been reached');
      return { context: { slot: 120 }, value: [{ pubkey: PublicKey.default, account: { data: Buffer.from([1]) } }] };
    },
  });
  const result = await runSnapshot();
  assert.equal(result.indexed, 1);
  assert.equal(result.fetchFailures, 0);
  assert.equal(state.reads.mock.callCount(), 2);
  assert.equal(state.slot.mock.callCount(), 1);
  assert.equal(state.writes.mock.callCount(), 1);
  assert.equal(state.writes.mock.calls[0].arguments[2], 120);
  assert.equal(state.cursor.mock.callCount(), 1);
  assert.equal(state.cursor.mock.calls[0].arguments[0].last_snapshot_slot, 130);
  assert.deepEqual(state.healthDuringWait, [{ code: 503, status: 'running' }]);
  assert.equal(getSnapshotRuntimeState().status, 'succeeded');
});

test('snapshot fetches share a two-minute retry window and incomplete projection never advances', async (t) => {
  const state = mockSnapshot(t, {
    types: ['Vault', 'UserAccount'],
    async fetch() { throw new Error('503 Service Unavailable'); },
  });
  await assert.rejects(runSnapshot(), /Projection incomplete: 2 fetch failures/);
  assert.ok(state.reads.mock.callCount() > 2);
  assert.equal(state.elapsed(), 120_000, 'account types must not each add two minutes');
  assert.equal(state.writes.mock.callCount(), 0);
  assert.equal(state.mint.mock.callCount(), 0);
  assert.equal(state.cursor.mock.callCount(), 0);
  assert.ok(state.healthDuringWait.every(({ code, status }) => code === 503 && status === 'running'));
  assert.equal(getSnapshotRuntimeState().status, 'failed');
});

test('snapshot does not retry permanent RPC errors', async (t) => {
  const state = mockSnapshot(t, { async fetch() { throw new Error('Invalid param: filters'); } });
  await assert.rejects(runSnapshot(), /Projection incomplete: 1 fetch failure/);
  assert.equal(state.reads.mock.callCount(), 1);
  assert.equal(state.waits.length, 0);
  assert.equal(state.writes.mock.callCount(), 0);
  assert.equal(state.cursor.mock.callCount(), 0);
});

test('snapshot decode failures stay fatal without retrying the fetched accounts', async (t) => {
  const state = mockSnapshot(t, { decode: () => null });
  await assert.rejects(runSnapshot(), /Projection incomplete: 1 decode failure/);
  assert.equal(state.reads.mock.callCount(), 1);
  assert.equal(state.waits.length, 0);
  assert.equal(state.writes.mock.callCount(), 0);
  assert.equal(state.cursor.mock.callCount(), 0);
});

test('snapshot writer timeouts stay fatal without replaying writes or fetches', async (t) => {
  const state = mockSnapshot(t, { async write() { throw new Error('write ETIMEDOUT'); } });
  await assert.rejects(runSnapshot(), /Projection incomplete: 1 write failure/);
  assert.equal(state.reads.mock.callCount(), 1);
  assert.equal(state.writes.mock.callCount(), 1);
  assert.equal(state.waits.length, 0);
  assert.equal(state.cursor.mock.callCount(), 0);
});

test('snapshot projection completion rejects decode, write, and fetch failures', () => {
  assert.throws(
    () => assertSnapshotProjectionComplete({ ...COMPLETE_RESULT, writeFailures: 1 }),
    /1 write failure/
  );
  assert.throws(
    () => assertSnapshotProjectionComplete({ ...COMPLETE_RESULT, decodeFailures: 1 }),
    /1 decode failure/
  );
  assert.throws(
    () => assertSnapshotProjectionComplete({ ...COMPLETE_RESULT, fetchFailures: 1 }),
    /1 fetch failure/
  );
});
