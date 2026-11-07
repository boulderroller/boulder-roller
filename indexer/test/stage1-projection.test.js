const test = require('node:test');
const assert = require('node:assert/strict');
const { Connection, PublicKey } = require('@solana/web3.js');
const { BorshAccountsCoder } = require('@coral-xyz/anchor');
const bs58 = require('bs58');
// The devnet release has one extra account; production's canonical ABI omits it.
const path = require('node:path');
require('../dist/config.js').config.idlPath = path.resolve(__dirname, '../../protocol/anchor/idl/boulder_rollers.devnet.json');
const decoder = require('../dist/decoder.js');
require('../dist/program-version-window.js').programVersionWindow.observe(0x4d);
const writers = require('../dist/writers/index.js');
const common = require('../dist/writers/common.js');
const stage1 = require('../dist/stage1.js');
const supply = require('../dist/supply.js');
const { runSnapshot, getSnapshotRuntimeState } = require('../dist/modes/snapshot.js');
const { startStream, stopStream } = require('../dist/modes/stream.js');

function data(type) {
  // Anchor 0.29's size() uses a one-byte placeholder for Vec. Supply the
  // actual bounded allocations, with one Vec entry and unused prepaid padding.
  const result = Buffer.alloc(type === 'Stage1Boost'
    ? 8 + 32 * 4 + 8 * 2 + 1 + 4 + 16 * 32 + 1
    : type === 'Stage1SettlementCursor' ? 641 + 4 + 26 * 217
    : decoder.getExpectedAccountSize(type));
  BorshAccountsCoder.accountDiscriminator(type).copy(result);
  if (type === 'Stage1Boost') result.writeUInt32LE(1, 8 + 32 * 4 + 8 * 2 + 1);
  if (type === 'Stage1SettlementCursor') result.writeUInt32LE(1, 641);
  if (['Stage1ClaimSet','Stage1DungClaimSet'].includes(type)) result[result.length-(type==='Stage1ClaimSet'?2:34)]=2;
  return result;
}

test('DUNG mint decodes the 226-byte release layout and its unminted tail', () => {
  assert.equal(decoder.getExpectedAccountSize('Stage1DungMint'), 226);
  const record = data('Stage1DungMint');
  record.writeBigUInt64LE(175000n, 218);
  const decoded = decoder.decodeAccount(record);
  assert.equal(decoded?.type, 'Stage1DungMint');
  assert.equal(decoded.fields.unminted.toString(), '175000');
  assert.equal(decoder.decodeAccount(record.subarray(0, 218)), null);
  assert.equal(decoder.decodeAccount(record.subarray(0, 225)), null);
});

test('claim-set raw tails are validated before projection', async () => {
  for (const type of ['Stage1ClaimSet','Stage1DungClaimSet']) {
    const fields=decoder.getCoder().accounts.decode(type,data(type));
    fields.leafCount=9;fields.sealed=true;
    const header=await decoder.getCoder().accounts.encode(type,fields);
    const valid=Buffer.concat([header,Buffer.alloc(2)]);
    assert.equal(decoder.decodeAccount(valid)?.type,type);
    assert.equal(decoder.decodeAccount(valid.subarray(0,valid.length-1)),null);
    const unknown=Buffer.from(valid);unknown[header.length-(type==='Stage1ClaimSet'?2:34)]=1;
    assert.equal(decoder.decodeAccount(unknown),null);
    const badBoolean=Buffer.from(valid);badBoolean[header.length-(type==='Stage1ClaimSet'?1:33)]=2;
    assert.equal(decoder.decodeAccount(badBoolean),null);
  }
});
test('carried-hold cursor decodes its full prepaid capacity and refuses a truncated live entry', () => {
  const cursor = data('Stage1SettlementCursor');
  assert.equal(decoder.decodeAccount(cursor)?.fields.carriedHolds.length, 1);
  assert.equal(decoder.decodeAccount(cursor.subarray(0, 641 + 4 + 216)), null);
  cursor.writeUInt32LE(26, 641);
  assert.equal(decoder.decodeAccount(cursor)?.fields.carriedHolds.length, 26);
  assert.equal(decoder.decodeAccount(cursor.subarray(0, cursor.length - 1)), null);
});
function fixture(t, malformed = false) {
  const types = decoder.getAccountTypeNames().filter(x => x.startsWith('Stage1'));
  const rows = new Map(['VaultCounter', ...types].map(type => [type, data(type)]));
  if (malformed) {
    const type = malformed === 'boost' ? 'Stage1Boost' : 'Stage1AssetConfig';
    rows.set(type, rows.get(type).subarray(0, 9));
  }
  t.mock.method(decoder, 'getAccountTypeNames', () => [...rows.keys()]);
  for (const method of ['log', 'error']) t.mock.method(console, method, () => {});
  const warns = t.mock.method(console, 'warn', () => {});
  const writes = t.mock.method(common, 'upsert', async () => {});
  const stage1Writes = t.mock.method(stage1, 'writeStage1Account', async () => {});
  const cursor = t.mock.method(common, 'updateSyncState', async () => {});
  t.mock.method(supply, 'refreshDungMintSupply', async () => ({ written: true, slot: 130 }));
  t.mock.method(supply, 'resolveCanonicalDungMint', async () => ({ address: PublicKey.default }));
  t.mock.method(Connection.prototype, 'getSlot', async () => 100);
  let retried = false;
  t.mock.method(global, 'setTimeout', cb => { queueMicrotask(cb); return 0; });
  t.mock.method(Connection.prototype, 'getProgramAccounts', async (_, options) => {
    assert.equal(options.commitment, 'finalized'); assert.equal(options.minContextSlot, 100);
    const disc = bs58.decode(options.filters[0].memcmp.bytes);
    const row = [...rows].find(([, bytes]) => bytes.subarray(0, 8).equals(disc));
    if (row[0] === 'Stage1AssetConfig' && !retried) { retried = true; throw new Error('503 Service Unavailable'); }
    return { context: { slot: 120 }, value: [{ pubkey: PublicKey.default, account: { data: row[1] } }] };
  });
  return { rows, types, warns, writes, stage1Writes, cursor };
}

test('mixed snapshot projects every final-ABI Stage1 account and preserves bounded retry', async t => {
  const f = fixture(t);
  const result = await runSnapshot();
  assert.equal(result.indexed, 1+f.types.length); assert.equal(result.skipped, 0);
  assert.equal(result.decodeFailures, 0); assert.equal(result.fetchFailures, 0);
  assert.equal(f.writes.mock.callCount(), 1); assert.equal(f.cursor.mock.callCount(), 1);
  assert.equal(f.warns.mock.calls.filter(c => String(c.arguments[0]).includes('Unknown account type')).length, 0);
  assert.equal(f.stage1Writes.mock.callCount(),f.types.length);
  assert.deepEqual(Object.keys(require('../dist/stage1.js').STAGE1_TABLES).sort(), f.types.sort());
});

test('malformed Stage1 snapshot trips Projection incomplete and never advances the cursor', async t => {
  const f = fixture(t, true);
  await assert.rejects(runSnapshot(), /Projection incomplete: 1 decode failure/);
  assert.equal(f.cursor.mock.callCount(), 0); assert.equal(getSnapshotRuntimeState().status, 'failed');
});

test('truncated boost vector fences snapshot completion', async t => {
  const f = fixture(t, 'boost');
  await assert.rejects(runSnapshot(), /Projection incomplete: 1 decode failure/);
  assert.equal(f.cursor.mock.callCount(), 0);
});

test('mixed finalized stream projects legacy and Stage1, and fences malformed Stage1', async t => {
  const f = fixture(t);
  let callback;
  t.mock.method(Connection.prototype, 'onProgramAccountChange', (_, cb, commitment) => {
    assert.equal(commitment, 'finalized'); callback = cb; return 1;
  });
  t.mock.method(Connection.prototype, 'onAccountChange', () => 2);
  t.mock.method(Connection.prototype, 'removeProgramAccountChangeListener', async () => {});
  t.mock.method(Connection.prototype, 'removeAccountChangeListener', async () => {});
  const gaps = [];
  await startStream((a, b) => gaps.push([a, b]));
  try {
    for (const bytes of f.rows.values()) await callback({ accountId: PublicKey.default, accountInfo: { data: bytes } }, { slot: 120 });
    assert.equal(f.writes.mock.callCount(), 1);
    assert.equal(f.warns.mock.calls.filter(c => String(c.arguments[0]).includes('Unknown account type')).length, 0);
    await callback({ accountId: PublicKey.default, accountInfo: { data: data('Stage1AssetConfig').subarray(0, 9) } }, { slot: 121 });
    assert.ok(gaps.length > 0, 'malformed known account requires reconciliation');
    const advances = f.cursor.mock.callCount();
    await callback({ accountId: PublicKey.default, accountInfo: { data: data('VaultCounter') } }, { slot: 122 });
    assert.equal(f.cursor.mock.callCount(), advances, 'incomplete stream must stay fenced until restarted');
  } finally { await stopStream(); }
});

for (const stalledAt of ['writer', 'cursor']) test(`malformed Stage1 fences a legacy ${stalledAt} already in flight`, async t => {
  const f = fixture(t);
  let callback, release, entered;
  const gate = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { entered = resolve; });
  const persisted = {};
  f.writes.mock.mockImplementation(async () => {
    if (stalledAt === 'writer') { entered(); await gate; }
  });
  f.cursor.mock.mockImplementation(async fields => {
    if (stalledAt === 'cursor' && fields.last_account_slot) { entered(); await gate; }
    Object.assign(persisted, fields);
  });
  t.mock.method(Connection.prototype, 'onProgramAccountChange', (_, cb) => { callback = cb; return 1; });
  t.mock.method(Connection.prototype, 'onAccountChange', () => 2);
  t.mock.method(Connection.prototype, 'removeProgramAccountChangeListener', async () => {});
  t.mock.method(Connection.prototype, 'removeAccountChangeListener', async () => {});
  await startStream(() => {});
  try {
    const legacy = callback({ accountId: PublicKey.default, accountInfo: { data: data('VaultCounter') } }, { slot: 122 });
    await started;
    const malformed = callback({ accountId: PublicKey.default, accountInfo: { data: data('Stage1AssetConfig').subarray(0, 9) } }, { slot: 121 });
    release();
    await Promise.all([legacy, malformed]);
    assert.equal(persisted.stream_connected, false, 'in-flight legacy work must not undo the fatal projection fence');
  } finally { release(); await stopStream(); }
});

for (const scheduledStart of [false, true]) for (const stalledAt of ['supply', 'state']) test(`malformed Stage1 prevents reconnect after overlapping ${scheduledStart ? 'scheduled' : 'direct'} startup ${stalledAt} failure`, async t => {
  const f = fixture(t);
  let callback, fail, entered;
  const gate = new Promise((_, reject) => { fail = reject; });
  const started = new Promise(resolve => { entered = resolve; });
  const scheduled = [];
  const persisted = {};
  global.setTimeout.mock.mockImplementation(cb => { scheduled.push(cb); return 0; });
  supply.refreshDungMintSupply.mock.mockImplementation(async () => {
    if (stalledAt === 'supply') { entered(); await gate; }
    return { written: true, slot: 130 };
  });
  f.cursor.mock.mockImplementation(async fields => {
    if (stalledAt === 'state' && fields.stream_connected) { entered(); await gate; }
    Object.assign(persisted, fields);
  });
  t.mock.method(Connection.prototype, 'onProgramAccountChange', (_, cb) => { callback = cb; return 1; });
  t.mock.method(Connection.prototype, 'onAccountChange', () => 2);
  t.mock.method(Connection.prototype, 'removeProgramAccountChangeListener', async () => {});
  t.mock.method(Connection.prototype, 'removeAccountChangeListener', async () => {});
  if (scheduledStart) {
    supply.resolveCanonicalDungMint.mock.mockImplementationOnce(async () => { throw new Error('transient RPC failure'); });
    await startStream(() => {});
    assert.equal(scheduled.length, 1, 'ordinary startup failure still retries');
  }
  const result = (scheduledStart ? scheduled.shift()() : startStream(() => {})).then(() => null, err => err);
  try {
    await started;
    const malformed = callback({ accountId: PublicKey.default, accountInfo: { data: data('Stage1AssetConfig').subarray(0, 9) } }, { slot: 121 });
    fail(new Error('startup failed'));
    await malformed;
    const error = await result;
    if (!scheduledStart) assert.match(error?.message ?? 'startup returned without an error', /Projection incomplete/);
    assert.equal(scheduled.length, 0, 'fatal projection failure requires a healthy snapshot before restart');
    assert.equal(persisted.stream_connected, false);
  } finally { fail(new Error('test cleanup')); await stopStream(); }
});
