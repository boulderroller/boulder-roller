const test = require('node:test');
const assert = require('node:assert/strict');
const { PublicKey } = require('@solana/web3.js');

const db = require('../dist/db.js');
const { writeDungMintState, writeDungMintSupply } = require('../dist/writers/legend.js');

test('writeDungMintState persists reserved Community liability and policy version', async (t) => {
  const originalQuery = db.query;
  let captured = null;

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [] };
  };

  await writeDungMintState(
    {
      authority: PublicKey.default,
      maxSupply: 1_000n,
      totalMinted: 100n,
      totalBurned: 5n,
      communityMinted: 40n,
      treasuryMinted: 25n,
      teamMinted: 20n,
      investorMinted: 10n,
      polMinted: 5n,
      currentEmissionRateBps: 10_000n,
      lastHalvingEpoch: 120n,
      communityReserved: 77n,
      reservationPolicyVersion: 1,
      bump: 254,
    },
    'dung-state-pda',
    123,
  );

  assert.ok(captured);
  assert.match(captured.sql, /\bcommunity_reserved\b/);
  assert.match(captured.sql, /\breservation_policy_version\b/);
  assert.ok(captured.values.includes('77'));
  assert.ok(captured.values.includes(1));
});

test('writeDungMintSupply preserves exact SPL supply with independent slot provenance', async (t) => {
  const originalQuery = db.query;
  let captured = null;

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [], rowCount: 1 };
  };

  await writeDungMintSupply('18446744073709551615', 456);

  assert.ok(captured);
  assert.match(captured.sql, /spl_mint_supply/);
  assert.match(captured.sql, /spl_mint_supply_slot/);
  assert.match(captured.sql, /\$2::BIGINT > COALESCE\(spl_mint_supply_slot, -1\)/);
  assert.match(captured.sql, /\$2::BIGINT = spl_mint_supply_slot/);
  assert.match(captured.sql, /\$1::NUMERIC = spl_mint_supply/);
  assert.ok(captured.values.includes('18446744073709551615'));
  assert.ok(captured.values.includes(456));
});

test('writeDungMintSupply rejects values outside exact u64 and slot bounds', async () => {
  await assert.rejects(
    writeDungMintSupply('18446744073709551616', 1),
    /canonical u64 decimal string/,
  );
  await assert.rejects(
    writeDungMintSupply('-1', 1),
    /canonical u64 decimal string/,
  );
  await assert.rejects(
    writeDungMintSupply('1.5', 1),
    /canonical u64 decimal string/,
  );
  await assert.rejects(
    writeDungMintSupply('1', Number.MAX_SAFE_INTEGER + 1),
    /valid chain slot/,
  );
});
