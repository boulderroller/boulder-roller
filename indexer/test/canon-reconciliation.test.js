const test = require('node:test');
const assert = require('node:assert/strict');
const { PublicKey } = require('@solana/web3.js');

const db = require('../dist/db.js');
const { reconcilePendingCanonAccounts } = require('../dist/reconciliation.js');

const VAULT_PDA = new PublicKey(Buffer.alloc(32, 13)).toBase58();

test('pending canon reconciliation refetches finalized Vault and clears only after projection', async (t) => {
  const originalQuery = db.query;
  const calls = [];
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    calls.push({ sql, values });
    if (/SELECT account_pda/.test(sql)) {
      return {
        rows: [{ account_pda: VAULT_PDA, chain_slot: 100 }],
        rowCount: 1,
      };
    }
    return { rows: [], rowCount: 1 };
  };
  const connection = {
    async getAccountInfoAndContext() {
      return {
        context: { slot: 123 },
        value: { data: Buffer.from([1, 2, 3]) },
      };
    },
  };
  const routed = [];
  const result = await reconcilePendingCanonAccounts({
    connection,
    decode: () => ({ type: 'Vault', fields: { exact: true } }),
    route: async (decoded, pda, slot) => {
      routed.push({ decoded, pda, slot });
      return true;
    },
  });

  assert.deepEqual(result, { checked: 1, finalized: 1 });
  assert.deepEqual(routed, [
    { decoded: { type: 'Vault', fields: { exact: true } }, pda: VAULT_PDA, slot: 123 },
  ]);
  assert.equal(calls.some((call) => /DELETE FROM public\.canon_indexer_pending/.test(call.sql)), true);
});

test('pending canon reconciliation retains a Vault that is not finalized-visible yet', async (t) => {
  const originalQuery = db.query;
  const calls = [];
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    calls.push({ sql, values });
    if (/SELECT account_pda/.test(sql)) {
      return {
        rows: [{ account_pda: VAULT_PDA, chain_slot: 100 }],
        rowCount: 1,
      };
    }
    return { rows: [], rowCount: 1 };
  };

  const result = await reconcilePendingCanonAccounts({
    connection: {
      async getAccountInfoAndContext() {
        return { context: { slot: 123 }, value: null };
      },
    },
    route: async () => {
      throw new Error('missing account must not route');
    },
  });

  assert.deepEqual(result, { checked: 1, finalized: 0 });
  assert.equal(calls.some((call) => /UPDATE public\.canon_indexer_pending/.test(call.sql)), true);
  assert.equal(calls.some((call) => /DELETE FROM public\.canon_indexer_pending/.test(call.sql)), false);
});
