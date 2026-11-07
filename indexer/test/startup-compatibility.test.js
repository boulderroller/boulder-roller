const test = require('node:test');
const assert = require('node:assert/strict');
const { mockProgramVersionStore } = require('./helpers/program-version-store.js');
test.beforeEach(mockProgramVersionStore);
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { BorshAccountsCoder } = require('@coral-xyz/anchor');
const { PublicKey } = require('@solana/web3.js');
const { config } = require('../dist/config.js');
const { CURRENT_PROGRAM_VERSION } = require('../dist/generated-program-version.js');
const { requireIndexerProgramCompatibility } = require('../dist/program-compatibility.js');

function programConfig() {
  const data = Buffer.alloc(325);
  Buffer.from(BorshAccountsCoder.accountDiscriminator('ProgramConfig')).copy(data);
  data[72] = CURRENT_PROGRAM_VERSION;
  data[73] = 1;
  new PublicKey(config.dungMintAddress).toBuffer().copy(data, 107);
  return { context: { slot: 700 }, value: { data, owner: new PublicKey(config.programId) } };
}

test('indexer checks finalized ProgramConfig and its durable window before projecting accounts', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '../src/index.ts'),
    'utf8',
  );
  const compatibilityCheck = source.indexOf(
    'await requireIndexerProgramCompatibility(',
  );
  const databaseBoundary = source.indexOf('if (!config.databaseUrl)');

  assert.notEqual(compatibilityCheck, -1, 'startup compatibility check is missing');
  assert.notEqual(databaseBoundary, -1, 'database startup boundary is missing');
  assert.ok(
    compatibilityCheck < databaseBoundary,
    'ProgramConfig compatibility must be established before projection setup',
  );
});

test('compatibility retries a provider usage cap before accepting finalized ProgramConfig', async (t) => {
  let elapsed = 0;
  const waits = [];
  const warnings = [];
  t.mock.method(Date, 'now', () => elapsed);
  t.mock.method(global, 'setTimeout', (callback, delay) => {
    waits.push(delay);
    elapsed += delay;
    queueMicrotask(callback);
  });
  t.mock.method(console, 'warn', (message) => warnings.push(message));
  let calls = 0;
  const result = await requireIndexerProgramCompatibility({
    async getGenesisHash() { return 'unit-genesis'; },
    async getAccountInfoAndContext(_pda, commitment) {
      assert.equal(commitment, 'finalized');
      if (++calls === 1) throw new Error('429 Too Many Requests: max usage reached');
      return programConfig();
    },
  });
  assert.equal(result.programVersion, CURRENT_PROGRAM_VERSION);
  assert.equal(result.canonicalDungMint.programConfigSlot, 700);
  assert.equal(calls, 2);
  assert.equal(waits.length, 1);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /rate_limit/);
});

test('compatibility owner, decode and ABI failures do not wait or retry', async (t) => {
  const timer = t.mock.method(global, 'setTimeout', () => assert.fail('fatal validation must not wait'));
  for (const [mutate, error] of [
    [(account) => { account.value.owner = PublicKey.default; }, /not owned/],
    [(account) => { account.value.data = Buffer.alloc(1); }, /could not be decoded/],
    [(account) => { account.value.data[72] = 0; }, /version (mismatch|downgrade)/],
  ]) {
    let calls = 0;
    const account = programConfig();
    mutate(account);
    await assert.rejects(requireIndexerProgramCompatibility({
      async getGenesisHash() { return 'unit-genesis'; },
      async getAccountInfoAndContext() { calls++; return account; },
    }), error);
    assert.equal(calls, 1);
  }
  assert.equal(timer.mock.callCount(), 0);
});

for (const phase of ['compatibility', 'snapshot']) {
  test(`startup exits non-zero after ${phase} retries exhaust without cursor writes`, () => {
    // Exercise the real entrypoint and exit handler with no provider or database.
    const probe = spawnSync(process.execPath, ['-e', `
      const { Connection } = require('@solana/web3.js');
      const compatibility = require('./dist/program-compatibility.js');
      const decoder = require('./dist/decoder.js');
      const db = require('./dist/db.js');
      const common = require('./dist/writers/common.js');
      const writers = require('./dist/writers/index.js');
      const health = require('./dist/health.js');
      const { config } = require('./dist/config.js');
      config.mode = 'snapshot';
      config.databaseUrl = 'mocked';
      config.rpcUrl = 'http://127.0.0.1:8899';
      let elapsed = 0, calls = 0, writes = 0, healthStarts = 0, dbCalls = 0;
      Date.now = () => elapsed;
      global.setTimeout = (callback, delay) => { elapsed += delay; queueMicrotask(callback); };
      decoder.loadIdl = () => {};
      decoder.getAccountTypeNames = () => ['Vault'];
      db.getPool = () => ({ query: async () => { dbCalls++; return { rows: [] }; } });
      common.ensureSyncState = async () => {};
      common.updateSyncState = async () => { writes++; };
      writers.routeAccount = async () => { writes++; return true; };
      health.startHealthServer = () => { healthStarts++; };
      Connection.prototype.getSlot = async () => 100;
      const failure = async () => { calls++; throw new Error('429 Too Many Requests: max usage reached'); };
      if (${JSON.stringify(phase)} === 'compatibility') {
        Connection.prototype.getAccountInfoAndContext = failure;
      } else {
        compatibility.requireIndexerProgramCompatibility = async () => ({
          programVersion: 76, canonicalDungMint: { programConfigSlot: 100 },
        });
        Connection.prototype.getProgramAccounts = failure;
      }
      process.on('exit', () => console.log('PROBE ' + JSON.stringify({ elapsed, calls, writes, healthStarts, dbCalls })));
      require('./dist/index.js');
    `], { cwd: path.join(__dirname, '..'), encoding: 'utf8', timeout: 10_000 });
    assert.equal(probe.error, undefined);
    assert.equal(probe.status, 1, probe.stderr);
    const outcome = JSON.parse(probe.stdout.match(/PROBE (.+)/)[1]);
    assert.ok(outcome.calls > 1, 'transient startup error must be retried');
    assert.equal(outcome.elapsed, phase === 'compatibility' ? 600_000 : 120_000);
    assert.equal(outcome.writes, 0);
    assert.equal(outcome.healthStarts, phase === 'compatibility' ? 0 : 1);
    assert.equal(outcome.dbCalls, phase === 'compatibility' ? 0 : 1);
    assert.match(probe.stderr, phase === 'compatibility' ? /Program compatibility check failed/ : /Projection incomplete: 1 fetch failure/);
  });
}
