const test = require('node:test');
const assert = require('node:assert/strict');
const { BorshAccountsCoder } = require('@coral-xyz/anchor');
const { PublicKey } = require('@solana/web3.js');
const { ProgramVersionWindow, programVersionWindow, requireCompatibleProgramVersion } = require('../dist/program-version-window.js');
const { config } = require('../dist/config.js');
const { resolveCanonicalDungMint } = require('../dist/supply.js');
const decoder = require('../dist/decoder.js');
const db = require('../dist/db.js');
const { routeAccount } = require('../dist/writers/index.js');
const { writeProgramConfig } = require('../dist/writers/legend.js');
const { handleApiRequest, setApiRuntimeForTests, resetApiRuntimeForTests } = require('../dist/api.js');
const { decodeExplorerEvents } = require('../dist/explorer-events.js');
const { mockProgramVersionStore } = require('./helpers/program-version-store.js');
test.beforeEach(mockProgramVersionStore);

function account(version) {
  const data = Buffer.alloc(334);
  BorshAccountsCoder.accountDiscriminator('ProgramConfig').copy(data);
  data[72] = version; data[73] = 1;
  new PublicKey(config.dungMintAddress).toBuffer().copy(data, 107);
  data.writeBigInt64LE(1704110400n, 325); data[333] = 2;
  return { context: { slot: 700 + version }, value: { data, owner: new PublicKey(config.programId) } };
}

test('cutover window is exactly 0x4C, 0x4D and 0x4E and is monotonic', () => {
  const window = new ProgramVersionWindow();
  for (const version of [0x44, 0x4b, 0x4f, 255, null, true, '77', 77.5]) {
    assert.throws(() => requireCompatibleProgramVersion(version), /ProgramConfig version/);
  }
  window.observe(0x4c);
  assert.equal(window.stage1Available, false);
  assert.throws(() => window.requireStage1(), /not available on this network/);
  window.observe(0x4d); window.requireStage1();
  assert.throws(() => window.observe(0x4c), /version downgrade/);
  assert.equal(window.programVersion, 0x4d);
  assert.equal(window.stage1Available, false);
  assert.throws(() => window.requireStage1(), /version downgrade/);
});

test('Stage 1 stays available across the 0x4D to 0x4E advance and refuses the downgrade', () => {
  const window = new ProgramVersionWindow();
  assert.equal(requireCompatibleProgramVersion(0x4e), 0x4e);
  window.observe(0x4d); window.requireStage1();
  window.observe(0x4e); window.requireStage1();
  assert.equal(window.programVersion, 0x4e);
  assert.deepEqual(window.status(), { program_version: 0x4e, stage1: 'available' });
  assert.throws(() => window.observe(0x4d), /version downgrade/);
  assert.equal(window.stage1Available, false);
});

test('missing config fences the previous Stage 1 capability', async () => {
  const window = new ProgramVersionWindow();
  window.observe(0x4d);
  await assert.rejects(resolveCanonicalDungMint({
    getAccountInfoAndContext: async () => ({ context: { slot: 900 }, value: null }),
  }, window), /ProgramConfig is missing/);
  assert.equal(window.stage1Available, false);
  assert.throws(() => window.status(), /ProgramConfig is missing/);
});

test('every real ProgramConfig version decodes and projects unchanged legacy fields', async t => {
  const writes = t.mock.method(db, 'query', async () => ({ rows: [] }));
  const window = new ProgramVersionWindow();
  for (const version of [0x4c, 0x4d, 0x4e]) {
    const decoded = decoder.decodeAccount(account(version).value.data);
    assert.equal(decoded.type, 'ProgramConfig');
    assert.equal(decoded.fields.programVersion, version);
    assert.equal(decoded.fields.settlementClockV2StartsAt.toString(), '1704110400');
    assert.equal(decoded.fields.settlementClockVersion, 2);
    assert.ok(!Object.keys(decoded.fields).some(name => name.toLowerCase().includes('stage1')));
    await writeProgramConfig(decoded.fields, 'config', version + 700, window);
    assert.equal(writes.mock.calls.at(-1).arguments[1][4], version);
  }
  const count = writes.mock.callCount();
  await assert.rejects(writeProgramConfig(decoder.decodeAccount(account(0x4c).value.data).fields, 'config', 900, window), /version downgrade/);
  assert.equal(writes.mock.callCount(), count);
});

test('live config rereads enable Stage 1 decoding and routes without restart and reject downgrade', async t => {
  let version = 0x4c;
  const connection = { getGenesisHash: async () => 'unit-genesis', getAccountInfoAndContext: async () => account(version) };
  t.after(resetApiRuntimeForTests);
  const rows = [{ event_name: 'Stage1CashReceived', fields: { amount: '5' } }, { event_name: 'CalCredited', fields: { amount: '6' } }];
  let queries = 0;
  setApiRuntimeForTests({ getRpcConnection: () => connection, query: async sql => {
    queries++;
    return { rows: sql.includes('indexed_events') ? rows : [] };
  } });
  const request = async path => {
    const res = { code: 0, body: '', writeHead(code) { this.code = code; }, end(body) { this.body = body; } };
    await handleApiRequest({ url: path, method: 'GET' }, res);
    return { code: res.code, body: JSON.parse(res.body) };
  };
  const data = Buffer.alloc(decoder.getExpectedAccountSize('Stage1Recipient'));
  BorshAccountsCoder.accountDiscriminator('Stage1Recipient').copy(data);
  await resolveCanonicalDungMint(connection);
  assert.equal(programVersionWindow.status().stage1, 'not available on this network');
  assert.equal(decoder.decodeAccount(data), null);
  const dark = await request('/v1/events?name=Stage1CashReceived');
  assert.equal(dark.code, 503);
  assert.match(dark.body.error, /not available on this network/);
  assert.equal(queries, 0, 'a dark Stage1 route must not read its projection');
  assert.deepEqual(decodeExplorerEvents(rows).map(row => row.event_name), ['CalCredited']);
  assert.deepEqual((await request('/v1/events')).body.events, [rows[1]]);
  const accountConnection = connection;
  accountConnection.getParsedTokenAccountsByOwner = async () => ({ value: [] });
  setApiRuntimeForTests({ getRpcConnection: () => accountConnection, query: async sql => {
    if (sql.includes('FROM indexed_accounts')) return { rows: [{ owner_pubkey: PublicKey.default.toBase58() }] };
    if (sql.includes('FROM indexed_events')) return { rows };
    return { rows: [] };
  } });
  const accountResponse = await request(`/v1/accounts/${PublicKey.default.toBase58()}`);
  assert.equal(accountResponse.code, 200);
  assert.deepEqual(accountResponse.body.recent_events.map(row => row.event_name), ['CalCredited']);
  await assert.rejects(routeAccount({ type: 'Stage1Recipient', fields: {} }, 'recipient', 800), /not available on this network/);
  const instruction = decoder.getCoder().instruction.encode('cancelPledge', {});
  assert.equal(decoder.decodeInstruction(instruction), null);
  version = 0x4d;
  await resolveCanonicalDungMint(connection);
  assert.equal(programVersionWindow.status().stage1, 'available');
  assert.equal(decoder.decodeAccount(data).type, 'Stage1Recipient');
  assert.equal(decoder.decodeInstruction(instruction).name, 'cancelPledge');
  assert.equal((await request('/v1/events?name=Stage1CashReceived')).code, 200);
  assert.equal(decodeExplorerEvents(rows).length, 2);
  const privateWrite=t.mock.method(require('../dist/stage1.js'),'writeStage1Account',async()=>{});
  assert.equal(await routeAccount(decoder.decodeAccount(data), 'recipient', 801), true);
  assert.equal(privateWrite.mock.callCount(),1);
  version = 0x4c;
  await assert.rejects(resolveCanonicalDungMint(connection), /version downgrade/);
  assert.equal(programVersionWindow.programVersion, 0x4d);
  assert.equal(programVersionWindow.stage1Available, false);
  await assert.rejects(routeAccount({ type: 'VaultCounter', fields: { count: 0 } }, 'counter', 900), /version downgrade/);
  const replayWrites = t.mock.method(db, 'query', async () => { throw new Error('unexpected replay write'); });
  const cursorWrites = t.mock.method(require('../dist/writers/common.js'), 'updateSyncState', async () => { throw new Error('unexpected cursor write'); });
  const replay = require('../dist/modes/replay.js');
  await assert.rejects(replay.runReplay(), /version downgrade/);
  await assert.rejects(replay.runReplaySweep(), /version downgrade/);
  assert.equal(replayWrites.mock.callCount(), 0);
  assert.equal(cursorWrites.mock.callCount(), 0);
});

test('a fresh service window rejects a durable downgrade and storage failure fences capabilities', async t => {
  const { observeFinalizedProgramVersion } = require('../dist/program-version-state.js');
  const store = require('../dist/program-version-store.js');
  const connection = { getGenesisHash: async () => 'restart-genesis' };
  await observeFinalizedProgramVersion(connection, 0x4d, new ProgramVersionWindow());
  const restarted = new ProgramVersionWindow();
  await assert.rejects(observeFinalizedProgramVersion(connection, 0x4c, restarted), /version downgrade/);
  assert.equal(restarted.stage1Available, false);
  await observeFinalizedProgramVersion(connection, 0x4d, restarted);
  assert.equal(restarted.stage1Available, true);
  t.mock.method(store, 'persistProgramVersion', async () => { throw new Error('observation store unavailable'); });
  await assert.rejects(observeFinalizedProgramVersion(connection, 0x4d, restarted), /store unavailable/);
  assert.equal(restarted.stage1Available, false);
  assert.throws(() => restarted.status(), /store unavailable/);
});

for (const rejected of [0xff, 0x4b, 0x4f]) {
  for (const initial of [null, 0x4c, 0x4d]) {
    test(`rejected byte ${rejected} never reaches the store after ${initial} and 0x4D still advances`, async () => {
      const store = require('../dist/program-version-store.js');
      const window = new ProgramVersionWindow();
      let version = initial;
      const connection = { getGenesisHash: async () => 'rejected-version-genesis', getAccountInfoAndContext: async () => account(version) };
      if (initial !== null) await resolveCanonicalDungMint(connection, window);
      const callsBefore = store.persistProgramVersion.mock.callCount();
      version = rejected;
      await assert.rejects(resolveCanonicalDungMint(connection, window), /version mismatch/);
      assert.equal(store.persistProgramVersion.mock.callCount(), callsBefore, 'reject before the upsert');
      assert.equal(window.programVersion, initial);
      assert.equal(window.stage1Available, false);
      version = 0x4d;
      assert.equal((await resolveCanonicalDungMint(connection, window)).programVersion, 0x4d);
      assert.equal(window.stage1Available, true);
      assert.equal((await resolveCanonicalDungMint(connection, new ProgramVersionWindow())).programVersion, 0x4d);
    });
  }
}
