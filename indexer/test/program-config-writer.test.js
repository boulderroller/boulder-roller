const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PublicKey } = require('@solana/web3.js');

const db = require('../dist/db.js');
const { mockProgramVersionStore } = require('./helpers/program-version-store.js');
test.beforeEach(mockProgramVersionStore);
const { writeProgramConfig } = require('../dist/writers/legend.js');
const {
  CURRENT_PROGRAM_VERSION,
} = require('../dist/generated-program-version.js');

const V4_A_PREDECESSOR_PROGRAM_VERSION = 0x44;

function programConfigFields(programVersion = CURRENT_PROGRAM_VERSION) {
  return {
    adminAuthority: PublicKey.default,
    backendAuthority: PublicKey.default,
    initialized: true,
    programVersion,
    calMint: PublicKey.default,
    dungMint: PublicKey.default,
    calMintAuthBump: 250,
    dungMintAuthBump: 251,
    polTokenAccount: PublicKey.default,
    treasuryTokenAccount: PublicKey.default,
    vaultCreationDung: 100n,
    vaultCreationCal: 200n,
    harvestFeeBps: 300n,
    minterRightsEpochs: 4n,
    localLegendTermEpochs: 5n,
    epochsPerHalving: 104n,
    settlementClockV2StartsAt: 1765195200n,
    settlementClockVersion: 2,
    bump: 252,
  };
}

test('writeProgramConfig projects the authoritative settlement clock contract', async (t) => {
  const originalQuery = db.query;
  let captured = null;

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [] };
  };

  await writeProgramConfig(
    programConfigFields(),
    'program-config-pda',
    987654,
  );

  assert.ok(captured);
  assert.match(captured.sql, /\bsettlement_clock_v2_starts_at\b/);
  assert.match(captured.sql, /\bsettlement_clock_version\b/);
  assert.match(captured.sql, /\bsettlement_clock_source_commitment\b/);
  assert.equal(captured.values[17], '1765195200');
  assert.equal(captured.values[18], 2);
  assert.equal(captured.values[19], 'finalized');
  assert.equal(captured.values[20], 'program-config-pda');
  assert.equal(captured.values[21], 987654);
});

test('writeProgramConfig rejects an unsupported ABI before projection', async (t) => {
  const originalQuery = db.query;
  let queryCount = 0;

  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async () => {
    queryCount += 1;
    return { rows: [] };
  };

  await assert.rejects(
    writeProgramConfig(
      programConfigFields(V4_A_PREDECESSOR_PROGRAM_VERSION),
      'program-config-pda',
      987655,
    ),
    /ProgramConfig version (mismatch|downgrade)/,
  );
  assert.equal(queryCount, 0);
});

test('ProgramConfig account snapshots and streams use finalized commitment', () => {
  for (const relativePath of ['../src/modes/snapshot.ts', '../src/modes/stream.ts']) {
    const source = fs.readFileSync(path.join(__dirname, relativePath), 'utf8');
    assert.match(source, /['"]finalized['"]/);
    assert.doesNotMatch(source, /['"]confirmed['"]/);
  }
  const snapshot = fs.readFileSync(
    path.join(__dirname, '../src/modes/snapshot.ts'),
    'utf8',
  );
  assert.match(snapshot, /withContext:\s*true/);
  assert.match(
    snapshot,
    /routeAccount\(decoded, pubkey, responseSlot, \{ connection \}\)/,
  );
});
