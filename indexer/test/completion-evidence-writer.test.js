const test = require('node:test');
const assert = require('node:assert/strict');
const { PublicKey } = require('@solana/web3.js');

const db = require('../dist/db.js');
const { routeAccount } = require('../dist/writers/index.js');

test('V2 completion receipt writer preserves exact monetary evidence', async (t) => {
  const originalQuery = db.query;
  let captured = null;

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [] };
  };

  const evidenceHash = Buffer.alloc(32, 0xa5);
  const routed = await routeAccount(
    {
      type: 'ClimbCompletionReceiptV2',
      fields: {
        rideAttestation: PublicKey.default,
        vault: PublicKey.default,
        evidenceVersion: 2,
        calTributed: 18446744073709551615n,
        completionEvidenceHash: evidenceHash,
        bump: 254,
      },
    },
    'completion-receipt-pda',
    123456
  );

  assert.equal(routed, true);
  assert.ok(captured);
  assert.match(captured.sql, /completion_evidence_version/);
  assert.match(captured.sql, /completion_evidence_hash/);
  assert.match(captured.sql, /cal_tributed/);
  assert.equal(captured.values[3], 2);
  assert.deepEqual(captured.values[4], evidenceHash);
  assert.equal(captured.values[5], '18446744073709551615');
  assert.equal(captured.values[6], 123456);
});

test('V2 completion receipt writer rejects a mislabeled receipt', async () => {
  await assert.rejects(
    routeAccount(
      {
        type: 'ClimbCompletionReceiptV2',
        fields: {
          rideAttestation: PublicKey.default,
          vault: PublicKey.default,
          evidenceVersion: 1,
          calTributed: 1n,
          completionEvidenceHash: Buffer.alloc(32),
          bump: 254,
        },
      },
      'completion-receipt-pda',
      123456
    ),
    /must declare evidence version 2/
  );
});
