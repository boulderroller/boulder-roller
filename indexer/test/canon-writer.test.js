const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { PublicKey } = require('@solana/web3.js');

const db = require('../dist/db.js');
const { CURRENT_PROGRAM_VERSION, PREVIOUS_PROGRAM_VERSION } = require('../dist/generated-program-version.js');
const {
  parseCanonCommitment,
  requireCanonIndexerProgramVersion,
  validateClimbAccount,
  validateVaultClimbBinding,
  writeClimb,
} = require('../dist/writers/canon.js');


const CANON_ID_HEX = '123456781234567890abcdef12345678';
const PROFILE_HASH_HEX = 'ab'.repeat(32);
const COMMITMENT_HEX =
  '01' + CANON_ID_HEX + '0002' + '00'.repeat(13) + PROFILE_HASH_HEX;
const COMMITMENT = Buffer.from(COMMITMENT_HEX, 'hex');
const COMMITMENT_HASH = crypto.createHash('sha256').update(COMMITMENT).digest();
const CLIMB_PDA = new PublicKey(Buffer.alloc(32, 7));
const PROGRAM_ID = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
const [EXACT_CLIMB_PDA] = PublicKey.findProgramAddressSync(
  [Buffer.from('climb'), COMMITMENT_HASH],
  PROGRAM_ID
);


function climbFields(overrides = {}) {
  const name = Buffer.alloc(64);
  name.write('Ratified Climb');
  return {
    canonCommitment: COMMITMENT,
    commitmentHash: COMMITMENT_HASH,
    canonId: Buffer.from(CANON_ID_HEX, 'hex'),
    canonVersion: 2,
    canonicalProfileHash: Buffer.from(PROFILE_HASH_HEX, 'hex'),
    predecessorClimb: PublicKey.default,
    successorClimb: PublicKey.default,
    recordContinuityPolicy: { newRecordBoard: {} },
    vault: PublicKey.default,
    name,
    vertM: 100,
    distanceM: 1000,
    avgGradientPct: 1000,
    registeredAt: 1713456789n,
    registeredBy: PublicKey.default,
    bump: 254,
    ...overrides,
  };
}


test('D12 parser accepts only the exact canonical layout', () => {
  assert.deepEqual(parseCanonCommitment(COMMITMENT), {
    commitmentHex: COMMITMENT_HEX,
    commitmentHashHex: COMMITMENT_HASH.toString('hex'),
    canonId: '12345678-1234-5678-90ab-cdef12345678',
    canonVersion: 2,
    canonicalProfileHashHex: PROFILE_HASH_HEX,
  });

  assert.throws(() => parseCanonCommitment(COMMITMENT.subarray(0, 63)), /64 bytes/);
  assert.throws(
    () => parseCanonCommitment(Buffer.concat([Buffer.from([2]), COMMITMENT.subarray(1)])),
    /prefix/
  );
  const reserved = Buffer.from(COMMITMENT);
  reserved[19] = 1;
  assert.throws(() => parseCanonCommitment(reserved), /reserved/);
});


test('canon projection gate rejects V4-A and accepts exact V4-B', () => {
  assert.throws(() => requireCanonIndexerProgramVersion(0x44, 'V4-A'), /V4-B/);
  assert.throws(() => requireCanonIndexerProgramVersion(CURRENT_PROGRAM_VERSION, 'V4-B-next'), /V4-B/);
  assert.throws(() => requireCanonIndexerProgramVersion(PREVIOUS_PROGRAM_VERSION, 'V4-B'), /V4-B/);
  assert.doesNotThrow(() => requireCanonIndexerProgramVersion(CURRENT_PROGRAM_VERSION, 'V4-B'));
});


test('Climb and Vault validation require an exact commitment and PDA link', () => {
  const validated = validateClimbAccount(climbFields());
  assert.equal(validated.canonVersion, 2);
  assert.equal(validated.commitmentHex, COMMITMENT_HEX);

  assert.throws(
    () => validateClimbAccount(climbFields({ recordContinuityPolicy: { carryRecordsForward: {} } })),
    /record migration/
  );

  assert.throws(
    () => validateClimbAccount(climbFields({ canonVersion: 3 })),
    /version/
  );
  assert.throws(
    () => validateClimbAccount(climbFields({ commitmentHash: Buffer.alloc(32) })),
    /commitment hash/
  );

  assert.deepEqual(
    validateVaultClimbBinding(
      {
        signature: COMMITMENT,
        signatureHash: COMMITMENT_HASH,
        climb: CLIMB_PDA,
      },
      CLIMB_PDA.toBase58()
    ),
    {
      climbPda: CLIMB_PDA.toBase58(),
      commitmentHex: COMMITMENT_HEX,
      commitmentHashHex: COMMITMENT_HASH.toString('hex'),
    }
  );
  assert.throws(
    () => validateVaultClimbBinding(
      { signature: COMMITMENT, signatureHash: COMMITMENT_HASH },
      CLIMB_PDA.toBase58()
    ),
    /Climb link/
  );
});


test('malformed Climb is quarantined and never projected', async (t) => {
  const originalQuery = db.query;
  const calls = [];
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    calls.push({ sql, values });
    return { rows: [], rowCount: 1 };
  };

  const projected = await writeClimb(
    climbFields({ canonVersion: 3 }),
    EXACT_CLIMB_PDA.toBase58(),
    123
  );

  assert.equal(projected, false);
  assert.equal(calls.length, 1);
  assert.match(calls[0].sql, /canon_indexer_quarantine/);
  assert.match(calls[0].sql, /WITH quarantine_write AS/);
  assert.match(calls[0].sql, /UPDATE public\.indexed_climbs AS indexed/);
  assert.match(calls[0].sql, /SET quarantined = TRUE/);
  assert.match(calls[0].sql, /indexed\.chain_slot <= quarantine\.chain_slot/);
  assert.match(calls[0].sql, /UPDATE public\.indexed_vaults AS vault/);
  assert.match(calls[0].sql, /vault\.climb_pda = quarantine\.account_pda/);
  assert.match(
    calls[0].sql,
    /chain_slot = GREATEST\(vault\.chain_slot, quarantine\.chain_slot\)/
  );
  assert.doesNotMatch(calls[0].sql, /INSERT INTO public\.indexed_climbs/);
});


test('valid Climb projection resolves the exact private registry row', async (t) => {
  const originalQuery = db.query;
  let captured = null;
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [{ canon_climb_id: 'registry-row' }], rowCount: 1 };
  };

  const projected = await writeClimb(climbFields(), EXACT_CLIMB_PDA.toBase58(), 123);

  assert.equal(projected, true);
  assert.match(captured.sql, /INSERT INTO public\.indexed_climbs/);
  assert.match(captured.sql, /JOIN public\.canon_climbs/);
  assert.match(captured.sql, /canon\.display_name = \$11/);
  assert.match(captured.sql, /round\(canon\.vert_m \* 10\) = \$19::numeric/);
  assert.match(captured.sql, /round\(canon\.length_m\) = \$13::numeric/);
  assert.match(
    captured.sql,
    /round\(canon\.avg_gradient_pct \* 100\) = \$20::numeric/
  );
  assert.match(captured.sql, /canon\.vert_m > 0/);
  assert.match(captured.sql, /canon\.length_m > 0/);
  assert.match(captured.sql, /canon\.avg_gradient_pct >= 0/);
  assert.match(captured.sql, /canon\.avg_gradient_pct <> 'NaN'::numeric/);
  assert.match(captured.sql, /quarantined = FALSE/);
  assert.equal(captured.values.includes(COMMITMENT_HEX), true);
  assert.equal(captured.values[18], 100);
  assert.equal(captured.values[19], 1000);
});

test('Climb projection deactivates on a higher invalid slot and only a later valid slot recovers', async (t) => {
  const originalQuery = db.query;
  const state = {
    climbSlot: -1,
    climbQuarantined: false,
    vaultSlot: 100,
    vaultBindingStatus: 'active',
    quarantineSlot: -1,
  };
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    if (/INSERT INTO public\.indexed_climbs/.test(sql)) {
      const observedSlot = values[16];
      if (observedSlot < state.climbSlot) {
        return { rows: [], rowCount: 0 };
      }
      state.climbSlot = observedSlot;
      state.climbQuarantined = false;
      return { rows: [{ canon_climb_id: 'registry-row' }], rowCount: 1 };
    }
    if (/WITH quarantine_write AS/.test(sql)) {
      const observedSlot = values[4];
      if (observedSlot >= state.quarantineSlot) {
        state.quarantineSlot = observedSlot;
        if (values[1] === 'Climb' && state.climbSlot <= observedSlot) {
          state.climbSlot = observedSlot;
          state.climbQuarantined = true;
          state.vaultSlot = Math.max(state.vaultSlot, observedSlot);
          state.vaultBindingStatus = 'quarantined';
        }
      }
      return { rows: [{}], rowCount: 1 };
    }
    throw new Error(`unexpected query: ${sql}`);
  };

  assert.equal(
    await writeClimb(climbFields(), EXACT_CLIMB_PDA.toBase58(), 100),
    true
  );
  assert.equal(state.climbQuarantined, false);

  assert.equal(
    await writeClimb(
      climbFields({ commitmentHash: Buffer.alloc(32) }),
      EXACT_CLIMB_PDA.toBase58(),
      101
    ),
    false
  );
  assert.deepEqual(
    {
      climbSlot: state.climbSlot,
      climbQuarantined: state.climbQuarantined,
      vaultSlot: state.vaultSlot,
      vaultBindingStatus: state.vaultBindingStatus,
    },
    {
      climbSlot: 101,
      climbQuarantined: true,
      vaultSlot: 101,
      vaultBindingStatus: 'quarantined',
    }
  );

  assert.equal(
    await writeClimb(climbFields(), EXACT_CLIMB_PDA.toBase58(), 100),
    false
  );
  assert.equal(state.climbQuarantined, true);

  assert.equal(
    await writeClimb(climbFields(), EXACT_CLIMB_PDA.toBase58(), 102),
    true
  );
  assert.equal(state.climbQuarantined, false);
  assert.equal(
    state.vaultBindingStatus,
    'quarantined',
    'dependent Vault requires its own exact revalidation before recovery'
  );

  state.vaultSlot = 200;
  state.vaultBindingStatus = 'active';
  assert.equal(
    await writeClimb(
      climbFields({ commitmentHash: Buffer.alloc(32) }),
      EXACT_CLIMB_PDA.toBase58(),
      150
    ),
    false
  );
  assert.deepEqual(
    {
      climbSlot: state.climbSlot,
      climbQuarantined: state.climbQuarantined,
      vaultSlot: state.vaultSlot,
      vaultBindingStatus: state.vaultBindingStatus,
    },
    {
      climbSlot: 150,
      climbQuarantined: true,
      vaultSlot: 200,
      vaultBindingStatus: 'quarantined',
    }
  );
  assert.equal(
    await writeClimb(climbFields(), EXACT_CLIMB_PDA.toBase58(), 201),
    true
  );
  assert.equal(state.vaultBindingStatus, 'quarantined');
});

test('registry name or encoded metric mismatch is quarantined, never projected', async (t) => {
  const originalQuery = db.query;
  const calls = [];
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    calls.push({ sql, values });
    if (/INSERT INTO public\.indexed_climbs/.test(sql)) {
      return { rows: [], rowCount: 0 };
    }
    return { rows: [], rowCount: 1 };
  };

  const projected = await writeClimb(
    climbFields(),
    EXACT_CLIMB_PDA.toBase58(),
    123
  );

  assert.equal(projected, false);
  assert.equal(calls.length, 2);
  assert.match(calls[0].sql, /canon\.display_name = \$11/);
  assert.match(calls[0].sql, /round\(canon\.vert_m \* 10\) = \$19::numeric/);
  assert.match(calls[1].sql, /canon_indexer_quarantine/);
});

test('retired predecessor notification requires one explicit version successor', async (t) => {
  const originalQuery = db.query;
  let captured = null;
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [{ canon_climb_id: 'predecessor-row' }], rowCount: 1 };
  };

  const projected = await writeClimb(
    climbFields({ successorClimb: new PublicKey(Buffer.alloc(32, 9)) }),
    EXACT_CLIMB_PDA.toBase58(),
    124
  );

  assert.equal(projected, true);
  assert.match(captured.sql, /canon\.status = 'retired'/);
  assert.match(captured.sql, /successor\.version = canon\.version \+ 1/);
  assert.match(captured.sql, /successor\.supersedes_climb_id = canon\.id/);
});
