const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { BorshAccountsCoder } = require('@coral-xyz/anchor');
const web3 = require('@solana/web3.js');
const db = require('../dist/db.js');
const decoder = require('../dist/decoder.js');
const reconciliation = require('../dist/reconciliation.js');
const writers = require('../dist/writers/index.js');
const { CURRENT_PROGRAM_VERSION } = require('../dist/generated-program-version.js');
const {
  batchUpsert,
  updateSyncState,
  upsert,
} = require('../dist/writers/common.js');

function captureQuery(t) {
  const originalQuery = db.query;
  const captured = [];

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = async (sql, values = []) => {
    captured.push({ sql, values });
    return { rows: [], rowCount: 1 };
  };

  return captured;
}

function assertProjectionGuard(sql, table) {
  assert.match(sql, new RegExp(`${table}\\.chain_slot IS NULL`));
  assert.match(sql, new RegExp(`EXCLUDED\\.chain_slot > ${table}\\.chain_slot`));
  assert.match(sql, new RegExp(`EXCLUDED\\.chain_slot = ${table}\\.chain_slot`));
  assert.match(sql, new RegExp(`EXCLUDED\\.indexed_at >= ${table}\\.indexed_at`));
}

function projectionWouldApply(sql, incoming, current) {
  if (!current || !/EXCLUDED\.chain_slot >/.test(sql)) return true;
  return incoming.chainSlot > current.chainSlot
    || (incoming.chainSlot === current.chainSlot
      && incoming.indexedAt >= current.indexedAt);
}

test('single-row account projections reject stale slots and order equal-slot writes', async (t) => {
  const captured = captureQuery(t);

  await upsert(
    'indexed_vaults',
    ['id', 'pending_rewards', 'chain_slot', 'indexed_at'],
    ['12', '900', 200, new Date('2026-07-15T12:00:00Z')],
    ['id'],
  );

  assert.equal(captured.length, 1);
  assertProjectionGuard(captured[0].sql, 'indexed_vaults');
});

test('batch account projections use the same monotonic conflict guard', async (t) => {
  const captured = captureQuery(t);

  await batchUpsert(
    'indexed_stakes',
    ['user_pubkey', 'vault_id', 'rewards_earned', 'chain_slot', 'indexed_at'],
    [
      ['rider-a', '12', '10', 100, new Date('2026-07-15T12:00:00Z')],
      ['rider-b', '12', '20', 101, new Date('2026-07-15T12:00:01Z')],
    ],
    ['user_pubkey', 'vault_id'],
  );

  assert.equal(captured.length, 1);
  assertProjectionGuard(captured[0].sql, 'indexed_stakes');
});

test('reversed query completion preserves the newest projection version', async (t) => {
  const originalQuery = db.query;
  const pending = [];
  let projected = null;

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = (sql, values) => new Promise((resolve) => {
    const incoming = {
      value: values[1],
      chainSlot: values[2],
      indexedAt: values[3].getTime(),
    };
    pending.push({
      complete() {
        if (projectionWouldApply(sql, incoming, projected)) projected = incoming;
        resolve({ rows: [], rowCount: 1 });
      },
    });
  });

  const observedAt = new Date('2026-07-15T12:00:00Z');
  const older = upsert(
    'indexed_vaults',
    ['id', 'pending_rewards', 'chain_slot', 'indexed_at'],
    ['12', 'old', 100, observedAt],
    ['id'],
  );
  const newer = upsert(
    'indexed_vaults',
    ['id', 'pending_rewards', 'chain_slot', 'indexed_at'],
    ['12', 'new', 200, observedAt],
    ['id'],
  );

  assert.equal(pending.length, 2);
  pending[1].complete();
  pending[0].complete();
  await Promise.all([older, newer]);

  assert.deepEqual(
    { value: projected.value, chainSlot: projected.chainSlot },
    { value: 'new', chainSlot: 200 },
  );
});

test('equal-slot observations receive a strict local ordering tie-breaker', async (t) => {
  const captured = captureQuery(t);
  const observedAt = new Date('2026-07-15T12:00:00Z');

  await upsert(
    'indexed_supply',
    ['id', 'total_minted', 'chain_slot', 'indexed_at'],
    [1, '10', 300, observedAt],
    ['id'],
  );
  await upsert(
    'indexed_supply',
    ['id', 'total_minted', 'chain_slot', 'indexed_at'],
    [1, '20', 300, observedAt],
    ['id'],
  );

  assert.ok(captured[1].values[3].getTime() > captured[0].values[3].getTime());
});

test('account projection helpers reject missing or malformed slot provenance', async () => {
  await assert.rejects(
    upsert(
      'indexed_vaults',
      ['id', 'pending_rewards', 'indexed_at'],
      ['12', '10', new Date()],
      ['id'],
    ),
    /must include chain_slot and indexed_at/,
  );
  await assert.rejects(
    upsert(
      'indexed_vaults',
      ['id', 'pending_rewards', 'chain_slot', 'indexed_at'],
      ['12', '10', null, new Date()],
      ['id'],
    ),
    /invalid chain_slot/,
  );
});

test('sync cursor fields advance only with their nondecreasing slot', async (t) => {
  const captured = captureQuery(t);

  await updateSyncState({
    last_tx_signature: 'newest-signature',
    last_tx_slot: 900,
    last_tx_sync_at: new Date('2026-07-15T12:00:00Z'),
  });

  assert.equal(captured.length, 1);
  const slotParameter = captured[0].values.indexOf(900) + 1;
  assert.ok(slotParameter > 0);
  for (const field of ['last_tx_signature', 'last_tx_slot', 'last_tx_sync_at']) {
    assert.match(
      captured[0].sql,
      new RegExp(`${field} = CASE\\s+WHEN \\$${slotParameter} >= COALESCE\\(last_tx_slot, 0\\)`),
    );
  }
});

test('sync cursor updates reject missing or malformed slot provenance', async (t) => {
  const captured = captureQuery(t);

  await assert.rejects(
    updateSyncState({ last_tx_signature: 'unversioned-signature' }),
    /last_tx_signature requires last_tx_slot/,
  );
  await assert.rejects(
    updateSyncState({ last_account_slot: Number.NaN }),
    /invalid last_account_slot/,
  );

  assert.equal(captured.length, 0);
});

test('snapshot account and snapshot cursors are guarded independently', async (t) => {
  const captured = captureQuery(t);

  await updateSyncState({
    last_account_slot: 901,
    last_account_sync_at: new Date('2026-07-15T12:00:01Z'),
    last_snapshot_at: new Date('2026-07-15T12:00:00Z'),
    last_snapshot_slot: 900,
    snapshot_account_count: 15,
  });

  const values = captured[0].values;
  const accountSlotParameter = values.indexOf(901) + 1;
  const snapshotSlotParameter = values.indexOf(900) + 1;
  assert.match(
    captured[0].sql,
    new RegExp(`last_account_sync_at = CASE\\s+WHEN \\$${accountSlotParameter} >= COALESCE\\(last_account_slot, 0\\)`),
  );
  for (const field of ['last_snapshot_at', 'last_snapshot_slot', 'snapshot_account_count']) {
    assert.match(
      captured[0].sql,
      new RegExp(`${field} = CASE\\s+WHEN \\$${snapshotSlotParameter} >= COALESCE\\(last_snapshot_slot, 0\\)`),
    );
  }
});

test('stream and reconciliation retain monotonic, finalized slot provenance', () => {
  const stream = fs.readFileSync(
    path.join(__dirname, '../src/modes/stream.ts'),
    'utf8',
  );
  const reconciliation = fs.readFileSync(
    path.join(__dirname, '../src/reconciliation.ts'),
    'utf8',
  );

  assert.match(stream, /lastProcessedSlot = Math\.max\(lastProcessedSlot, slot\)/);
  assert.doesNotMatch(stream, /lastProcessedSlot = slot;/);
  assert.match(stream, /onAccountChange\(/);
  assert.match(
    stream,
    /const initialMintSupply = await refreshDungMintSupply\(connection, canonicalDungMint\)/,
  );
  assert.match(stream, /removeAccountChangeListener\(dungMintSubscriptionId\)/);
  assert.doesNotMatch(reconciliation, /['"]confirmed['"]/);
  assert.equal(
    (reconciliation.match(/getAccountInfoAndContext/g) || []).length,
    4,
  );
  assert.equal(
    (reconciliation.match(/routeAccount\([^;]+\.context\.slot\)/g) || []).length,
    3,
  );
  assert.match(
    reconciliation,
    /const wrote = await route\(decoded, pda, response\.context\.slot\)/,
  );
});

test('supply reconciliation routes the decoded finalized response context slot', async (t) => {
  require('./helpers/program-version-store.js').mockProgramVersionStore(t);
  const originalConnection = web3.Connection;
  const originalDecodeAccount = decoder.decodeAccount;
  const originalRouteAccount = writers.routeAccount;
  const originalQuery = db.query;
  const connectionCommitments = [];
  const fetchCommitments = [];
  const routed = [];
  const projectedSupplies = [];

  t.after(() => {
    web3.Connection = originalConnection;
    decoder.decodeAccount = originalDecodeAccount;
    writers.routeAccount = originalRouteAccount;
    db.query = originalQuery;
  });

  web3.Connection = class FakeConnection {
    async getGenesisHash() { return 'unit-genesis'; }
    constructor(_url, commitment) {
      connectionCommitments.push(commitment);
    }

    async getAccountInfoAndContext(pubkey, commitment) {
      fetchCommitments.push(commitment);
      const [programConfigPda] = web3.PublicKey.findProgramAddressSync(
        [Buffer.from('program_config')],
        new web3.PublicKey(require('../dist/config.js').config.programId),
      );
      const isProgramConfig = pubkey.equals(programConfigPda);
      const data = isProgramConfig ? Buffer.alloc(325) : Buffer.from([1]);
      if (isProgramConfig) {
        Buffer.from(BorshAccountsCoder.accountDiscriminator('ProgramConfig')).copy(data, 0);
        data[72] = CURRENT_PROGRAM_VERSION;
        data[73] = 1;
        data[74] = 254;
        new web3.PublicKey(
          require('../dist/config.js').config.dungMintAddress,
        ).toBuffer().copy(data, 107);
      }
      return {
        context: { slot: 4321 },
        value: {
          data,
          owner: new web3.PublicKey(require('../dist/config.js').config.programId),
          testType: isProgramConfig ? 'ProgramConfig' : 'DungMintState',
        },
      };
    }

    async getSlot(commitment) {
      fetchCommitments.push(commitment);
      return 4322;
    }

    async getTokenSupply(_pubkey, commitment) {
      fetchCommitments.push(commitment);
      return {
        context: { slot: 4323 },
        value: { amount: '777', decimals: 9, uiAmount: 0.000000777, uiAmountString: '0.000000777' },
      };
    }
  };
  decoder.decodeAccount = () => ({
    type: 'DungMintState',
    fields: {},
  });
  writers.routeAccount = async (decoded, pda, slot) => {
    routed.push({ decoded, pda, slot });
    return true;
  };
  db.query = async (sql) => {
    if (sql.includes('SELECT * FROM indexed_supply')) {
      return { rows: [], rowCount: 0 };
    }
    if (sql.includes('SET spl_mint_supply')) projectedSupplies.push(sql);
    return { rows: [], rowCount: 1 };
  };

  const result = await reconciliation.reconcileSupply();

  assert.deepEqual(connectionCommitments, ['finalized', 'finalized']);
  assert.deepEqual(fetchCommitments, ['finalized', 'finalized', 'finalized', 'finalized']);
  assert.equal(routed.length, 1);
  assert.equal(routed[0].decoded.type, 'DungMintState');
  assert.equal(routed[0].slot, 4321);
  assert.equal(projectedSupplies.length, 1);
  assert.equal(result.accountsChecked, 2);
  assert.equal(result.discrepanciesFound, 1);
});
