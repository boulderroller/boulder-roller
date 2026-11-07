const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { PublicKey } = require('@solana/web3.js');

const db = require('../dist/db.js');
const { CURRENT_PROGRAM_VERSION, PREVIOUS_PROGRAM_VERSION } = require('../dist/generated-program-version.js');
const {
  SETTLEMENT_STAKER_TRIPWIRE_THRESHOLD,
  STAKER_REMAINDER_POLICY_MARKER,
  decodeVaultMetricScalars,
  decodeStakerRemainderPolicyVersion,
  maybeWarnSettlementStakerTripwire,
  writeVault,
  writeVaultForProgram,
} = require('../dist/writers/vault.js');
const { writeStake } = require('../dist/writers/stake.js');

test('decodeVaultMetricScalars normalizes on-chain fixed point units', () => {
  assert.deepEqual(
    decodeVaultMetricScalars({
      vertM: 9886,
      distanceM: 6136,
      avgGradientPct: 1611,
    }),
    {
      vertM: 988.6,
      distanceM: 6136,
      avgGradientPct: 16.11,
    }
  );
});

function fixedBytes(length, value) {
  return Buffer.alloc(length, value);
}

function makeVaultFields(overrides = {}) {
  const name = Buffer.alloc(64);
  name.write('Test Vault');

  return {
    id: 12n,
    signature: fixedBytes(64, 1),
    signatureHash: fixedBytes(32, 2),
    minter: PublicKey.default,
    mintEpoch: 1n,
    rightsExpiresEpoch: 99n,
    komHolder: PublicKey.default,
    komTimeS: 161,
    komSetEpoch: 2n,
    name,
    avatarIpfs: Buffer.alloc(46),
    slogan: Buffer.alloc(128),
    calTributeAccumulated: 100n,
    calTributeAccumulatedNext: 25n,
    totalCalBurned: 10n,
    totalDungEmitted: 20n,
    totalCompletions: 3n,
    totalCalStaked: 400n,
    stakerCount: 5,
    rewardPerTokenStored: 999n,
    lastUpdateTime: 888n,
    rewardRate: 777n,
    pendingRewards: 600n,
    pendingRewardsNextWeek: 700n,
    openSettlementWeek: 8n,
    carryRecordRoyalty: 9n,
    carryStakers: 10n,
    carryLocalLegend: 11n,
    carryPol: 12n,
    carryTreasury: 13n,
    totalStaked: 400n,
    lastDistributionEpoch: 7n,
    vertM: 9886,
    distanceM: 6136,
    avgGradientPct: 1611,
    createdAt: 1713456789n,
    bump: 255,
    ...overrides,
  };
}

const CANON_COMMITMENT = Buffer.from(
  '01' + '123456781234567890abcdef12345678' + '0002' + '00'.repeat(13) + 'ab'.repeat(32),
  'hex'
);
const CANON_COMMITMENT_HASH = crypto
  .createHash('sha256')
  .update(CANON_COMMITMENT)
  .digest();
const [CANON_CLIMB_PDA] = PublicKey.findProgramAddressSync(
  [Buffer.from('climb'), CANON_COMMITMENT_HASH],
  new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH')
);
const CANON_VAULT_PDA = new PublicKey(Buffer.alloc(32, 8)).toBase58();
const VAULT_ID_BYTES = Buffer.alloc(8);
VAULT_ID_BYTES.writeBigUInt64LE(12n);
const [CANON_VAULT_ACTIVATION_PDA] = PublicKey.findProgramAddressSync(
  [Buffer.from('vault_activation'), VAULT_ID_BYTES],
  new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH')
);
const EXPECTED_CONSTRUCTOR_EVIDENCE = crypto
  .createHash('sha256')
  .update(Buffer.from('BR_VAULT_EMPTY_HISTORY_V2'))
  .update(CANON_CLIMB_PDA.toBuffer())
  .update(new PublicKey(CANON_VAULT_PDA).toBuffer())
  .digest('hex');

function makeChainActivationRow() {
  return {
    vault_id: '12',
    seed_generation: 2,
    seed_cutoff_at: '1713456789',
    economics_start_epoch: '11',
    matched_users: 0,
    matched_completions: 0,
    activated_at: '1713456789',
    evidence_hash: EXPECTED_CONSTRUCTOR_EVIDENCE,
  };
}

test('staker remainder policy projection distinguishes legacy and marked Vaults', () => {
  assert.equal(decodeStakerRemainderPolicyVersion(777n), 0);
  assert.equal(decodeStakerRemainderPolicyVersion(STAKER_REMAINDER_POLICY_MARKER), 1);
});

test('writeVault projects the policy version without exposing deprecated reward slots', async (t) => {
  const originalQuery = db.query;
  let captured = null;

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [] };
  };

  await writeVaultForProgram(makeVaultFields(), 'vault-pda', 123, 0x44, 'V4-A');

  assert.ok(captured);
  assert.doesNotMatch(captured.sql, /\breward_per_token_stored\b/);
  assert.doesNotMatch(captured.sql, /\blast_update_time\b/);
  assert.doesNotMatch(captured.sql, /\breward_rate\b/);
  assert.match(captured.sql, /\bstaker_remainder_policy_version\b/);
  assert.match(captured.sql, /\bpending_rewards_next_week\b/);
  assert.match(captured.sql, /\bcarry_record_royalty\b/);
  assert.equal(captured.values.includes('999'), false);
  assert.equal(captured.values.includes('888'), false);
  assert.equal(captured.values.includes('777'), false);
});

test('V4-B Vault projection and activation finalization are one transaction', async (t) => {
  const originalGetClient = db.getClient;
  const calls = [];
  const client = {
    async query(sql, values) {
      calls.push({ sql, values });
      if (/SELECT indexed\.canon_climb_id/.test(sql)) {
        assert.equal(values.length, 4);
        assert.match(sql, /indexed\.vault_pda = \$4/);
        return { rows: [{ canon_climb_id: 'registry-row' }], rowCount: 1 };
      }
      if (/SELECT activation_status/.test(sql)) {
        return {
          rows: [{
            activation_status: 'confirmed',
            vault_activation_pda: CANON_VAULT_ACTIVATION_PDA.toBase58(),
          }],
          rowCount: 1,
        };
      }
      if (/FROM public\.indexed_vault_activations/.test(sql)) {
        return { rows: [makeChainActivationRow()], rowCount: 1 };
      }
      if (/finalize_canon_vault_activation/.test(sql)) {
        return { rows: [{ activation_status: 'finalized' }], rowCount: 1 };
      }
      return { rows: [], rowCount: 1 };
    },
    release() {},
  };
  t.after(() => {
    db.getClient = originalGetClient;
  });
  db.getClient = async () => client;

  const projected = await writeVaultForProgram(
    makeVaultFields({
      signature: CANON_COMMITMENT,
      signatureHash: CANON_COMMITMENT_HASH,
      climb: CANON_CLIMB_PDA,
    }),
    CANON_VAULT_PDA,
    123,
    CURRENT_PROGRAM_VERSION,
    'V4-B'
  );

  assert.equal(projected, true);
  assert.equal(calls[0].sql, 'BEGIN');
  assert.match(calls[1].sql, /public\.indexed_climbs/);
  assert.match(calls[2].sql, /public\.canon_vault_activations/);
  assert.match(
    calls[2].sql,
    /activation_status IN \('reserved', 'confirmed', 'finalized'\)/
  );
  assert.match(calls[3].sql, /public\.indexed_vault_activations/);
  assert.match(calls[3].sql, /seed_generation = 2/);
  assert.match(calls[3].sql, /seed_completions_written = 0/);
  assert.match(calls[3].sql, /leaderboard_seeded IS TRUE/);
  assert.match(calls[3].sql, /matched_users = 0/);
  assert.match(calls[3].sql, /created_at = seed_cutoff_at/);
  assert.match(calls[3].sql, /evidence_hash::text\)\) = \$3/);
  assert.equal(calls[3].values[2], EXPECTED_CONSTRUCTOR_EVIDENCE);
  assert.match(calls[4].sql, /canon_binding_status/);
  assert.match(calls[4].sql, /backfill_status/);
  assert.match(calls[4].sql, /on_chain_seeding_status/);
  assert.match(calls[4].sql, /activation_seed_generation/);
  assert.match(calls[5].sql, /finalize_canon_vault_activation/);
  assert.equal(calls[5].values[3], EXPECTED_CONSTRUCTOR_EVIDENCE);
  assert.equal(calls.at(-1).sql, 'COMMIT');
});

test('Vault-before-Climb and Vault-before-confirmation stay pending, not quarantined', async (t) => {
  const originalQuery = db.query;
  const originalGetClient = db.getClient;
  const externalCalls = [];
  let dependency = 'climb';
  const client = {
    async query(sql) {
      if (sql === 'BEGIN' || sql === 'ROLLBACK') {
        return { rows: [], rowCount: 1 };
      }
      if (/SELECT indexed\.canon_climb_id/.test(sql)) {
        return dependency === 'climb'
          ? { rows: [], rowCount: 0 }
          : { rows: [{ canon_climb_id: 'registry-row' }], rowCount: 1 };
      }
      if (/SELECT activation_status/.test(sql)) {
        return {
          rows: [{
            activation_status: 'reserved',
            vault_activation_pda: CANON_VAULT_ACTIVATION_PDA.toBase58(),
          }],
          rowCount: 1,
        };
      }
      throw new Error(`unexpected query: ${sql}`);
    },
    release() {},
  };
  t.after(() => {
    db.query = originalQuery;
    db.getClient = originalGetClient;
  });
  db.query = async (sql, values) => {
    externalCalls.push({ sql, values });
    return { rows: [], rowCount: 1 };
  };
  db.getClient = async () => client;
  const fields = makeVaultFields({
    signature: CANON_COMMITMENT,
    signatureHash: CANON_COMMITMENT_HASH,
    climb: CANON_CLIMB_PDA,
  });

  assert.equal(
    await writeVaultForProgram(fields, CANON_VAULT_PDA, 123, CURRENT_PROGRAM_VERSION, 'V4-B'),
    false
  );
  dependency = 'confirmation';
  assert.equal(
    await writeVaultForProgram(fields, CANON_VAULT_PDA, 123, CURRENT_PROGRAM_VERSION, 'V4-B'),
    false
  );

  assert.equal(externalCalls.length, 2);
  assert.equal(
    externalCalls.every((call) => /canon_indexer_pending/.test(call.sql)),
    true
  );
  assert.equal(
    externalCalls.some((call) => /canon_indexer_quarantine/.test(call.sql)),
    false
  );
});

test('Vault-before-Activation stays pending and reconciliation succeeds after Activation arrives', async (t) => {
  const originalQuery = db.query;
  const originalGetClient = db.getClient;
  const externalCalls = [];
  let activationPresent = false;
  let operationalStatus = 'confirmed';
  const client = {
    async query(sql) {
      if (sql === 'BEGIN' || sql === 'ROLLBACK' || sql === 'COMMIT') {
        return { rows: [], rowCount: 1 };
      }
      if (/SELECT indexed\.canon_climb_id/.test(sql)) {
        return { rows: [{ canon_climb_id: 'registry-row' }], rowCount: 1 };
      }
      if (/SELECT activation_status/.test(sql)) {
        return {
          rows: [{
            activation_status: operationalStatus,
            vault_activation_pda: CANON_VAULT_ACTIVATION_PDA.toBase58(),
          }],
          rowCount: 1,
        };
      }
      if (/FROM public\.indexed_vault_activations/.test(sql)) {
        if (/AND pda =/.test(sql)) {
          return activationPresent
            ? { rows: [makeChainActivationRow()], rowCount: 1 }
            : { rows: [], rowCount: 0 };
        }
        return { rows: [], rowCount: 0 };
      }
      if (/INSERT INTO public\.indexed_vaults/.test(sql)) {
        return { rows: [{ id: '12' }], rowCount: 1 };
      }
      if (/finalize_canon_vault_activation/.test(sql)) {
        operationalStatus = 'finalized';
        return { rows: [{ activation_status: 'finalized' }], rowCount: 1 };
      }
      if (/DELETE FROM public\.canon_indexer_pending/.test(sql)) {
        return { rows: [], rowCount: 1 };
      }
      throw new Error(`unexpected query: ${sql}`);
    },
    release() {},
  };
  t.after(() => {
    db.query = originalQuery;
    db.getClient = originalGetClient;
  });
  db.query = async (sql, values) => {
    externalCalls.push({ sql, values });
    return { rows: [], rowCount: 1 };
  };
  db.getClient = async () => client;
  const fields = makeVaultFields({
    signature: CANON_COMMITMENT,
    signatureHash: CANON_COMMITMENT_HASH,
    climb: CANON_CLIMB_PDA,
  });

  assert.equal(
    await writeVaultForProgram(fields, CANON_VAULT_PDA, 123, CURRENT_PROGRAM_VERSION, 'V4-B'),
    false
  );
  assert.match(externalCalls[0].sql, /canon_indexer_pending/);

  activationPresent = true;
  assert.equal(
    await writeVaultForProgram(fields, CANON_VAULT_PDA, 124, CURRENT_PROGRAM_VERSION, 'V4-B'),
    true
  );
  assert.equal(
    await writeVaultForProgram(fields, CANON_VAULT_PDA, 125, CURRENT_PROGRAM_VERSION, 'V4-B'),
    true
  );
});

for (const invalidEvidence of [
  'wrong PDA',
  'inactive',
  'generation below 2',
  'seed completion count is nonzero',
  'leaderboard not seeded',
  'matched history is nonzero',
  'constructor timestamps differ',
  'wrong empty-history evidence hash',
  'zero evidence hash',
]) {
  test(`invalid VaultActivation evidence is fail-closed: ${invalidEvidence}`, async (t) => {
    const originalQuery = db.query;
    const originalGetClient = db.getClient;
    const externalCalls = [];
    const client = {
      async query(sql) {
        if (sql === 'BEGIN' || sql === 'ROLLBACK') {
          return { rows: [], rowCount: 1 };
        }
        if (/SELECT indexed\.canon_climb_id/.test(sql)) {
          return { rows: [{ canon_climb_id: 'registry-row' }], rowCount: 1 };
        }
        if (/SELECT activation_status/.test(sql)) {
          return {
            rows: [{
              activation_status: 'confirmed',
              vault_activation_pda: CANON_VAULT_ACTIVATION_PDA.toBase58(),
            }],
            rowCount: 1,
          };
        }
        if (/FROM public\.indexed_vault_activations/.test(sql)) {
          return /AND pda =/.test(sql)
            ? { rows: [], rowCount: 0 }
            : { rows: [{ vault_id: '12', invalidEvidence }], rowCount: 1 };
        }
        throw new Error(`unexpected query: ${sql}`);
      },
      release() {},
    };
    t.after(() => {
      db.query = originalQuery;
      db.getClient = originalGetClient;
    });
    db.query = async (sql, values) => {
      externalCalls.push({ sql, values });
      return { rows: [], rowCount: 1 };
    };
    db.getClient = async () => client;

    const projected = await writeVaultForProgram(
      makeVaultFields({
        signature: CANON_COMMITMENT,
        signatureHash: CANON_COMMITMENT_HASH,
        climb: CANON_CLIMB_PDA,
      }),
      CANON_VAULT_PDA,
      123,
      CURRENT_PROGRAM_VERSION,
      'V4-B'
    );

    assert.equal(projected, false);
    assert.equal(externalCalls.length, 1);
    assert.match(externalCalls[0].sql, /canon_indexer_quarantine/);
    assert.doesNotMatch(externalCalls[0].sql, /canon_indexer_pending/);
  });
}

test('malformed V4-B Vault is quarantined without a legacy projection', async (t) => {
  const originalQuery = db.query;
  const originalGetClient = db.getClient;
  const calls = [];
  t.after(() => {
    db.query = originalQuery;
    db.getClient = originalGetClient;
  });
  db.query = async (sql, values) => {
    calls.push({ sql, values });
    return { rows: [], rowCount: 1 };
  };
  db.getClient = async () => {
    throw new Error('malformed account must not open a projection transaction');
  };

  const projected = await writeVaultForProgram(
    makeVaultFields({ signature: CANON_COMMITMENT, signatureHash: CANON_COMMITMENT_HASH }),
    'vault-pda',
    123,
    CURRENT_PROGRAM_VERSION,
    'V4-B'
  );

  assert.equal(projected, false);
  assert.equal(calls.length, 1);
  assert.match(calls[0].sql, /canon_indexer_quarantine/);
  assert.match(calls[0].sql, /WITH quarantine_write AS/);
  assert.match(calls[0].sql, /UPDATE public\.indexed_vaults AS vault/);
  assert.match(calls[0].sql, /SET canon_binding_status = 'quarantined'/);
  assert.match(calls[0].sql, /vault\.chain_slot <= quarantine\.chain_slot/);
  assert.doesNotMatch(calls[0].sql, /INSERT INTO indexed_vaults/);
});

test('Vault projection deactivates on a higher invalid slot and only a later valid slot recovers', async (t) => {
  const originalQuery = db.query;
  const originalGetClient = db.getClient;
  const state = {
    vaultSlot: -1,
    bindingStatus: 'quarantined',
    quarantineSlot: -1,
  };
  const client = {
    async query(sql, values) {
      if (sql === 'BEGIN' || sql === 'ROLLBACK' || sql === 'COMMIT') {
        return { rows: [], rowCount: 1 };
      }
      if (/SELECT indexed\.canon_climb_id/.test(sql)) {
        return { rows: [{ canon_climb_id: 'registry-row' }], rowCount: 1 };
      }
      if (/SELECT activation_status/.test(sql)) {
        return {
          rows: [{
            activation_status: 'finalized',
            vault_activation_pda: CANON_VAULT_ACTIVATION_PDA.toBase58(),
          }],
          rowCount: 1,
        };
      }
      if (/FROM public\.indexed_vault_activations/.test(sql)) {
        return { rows: [makeChainActivationRow()], rowCount: 1 };
      }
      if (/INSERT INTO public\.indexed_vaults/.test(sql)) {
        const chainSlotIndex = sql
          .slice(0, sql.indexOf(')\n       VALUES'))
          .split(',')
          .findIndex((column) => /chain_slot/.test(column));
        const observedSlot = values[chainSlotIndex];
        if (observedSlot < state.vaultSlot) {
          return { rows: [], rowCount: 0 };
        }
        state.vaultSlot = observedSlot;
        state.bindingStatus = 'active';
        return { rows: [{ id: '12' }], rowCount: 1 };
      }
      if (/finalize_canon_vault_activation/.test(sql)) {
        return { rows: [{ activation_status: 'finalized' }], rowCount: 1 };
      }
      if (/DELETE FROM public\.canon_indexer_pending/.test(sql)) {
        return { rows: [], rowCount: 1 };
      }
      throw new Error(`unexpected query: ${sql}`);
    },
    release() {},
  };
  t.after(() => {
    db.query = originalQuery;
    db.getClient = originalGetClient;
  });
  db.query = async (sql, values) => {
    if (!/WITH quarantine_write AS/.test(sql)) {
      throw new Error(`unexpected external query: ${sql}`);
    }
    const observedSlot = values[4];
    if (observedSlot >= state.quarantineSlot) {
      state.quarantineSlot = observedSlot;
      if (values[1] === 'Vault' && state.vaultSlot <= observedSlot) {
        state.vaultSlot = observedSlot;
        state.bindingStatus = 'quarantined';
      }
    }
    return { rows: [{}], rowCount: 1 };
  };
  db.getClient = async () => client;
  const validFields = makeVaultFields({
    signature: CANON_COMMITMENT,
    signatureHash: CANON_COMMITMENT_HASH,
    climb: CANON_CLIMB_PDA,
  });

  assert.equal(
    await writeVaultForProgram(validFields, CANON_VAULT_PDA, 100, CURRENT_PROGRAM_VERSION, 'V4-B'),
    true
  );
  assert.deepEqual(
    { vaultSlot: state.vaultSlot, bindingStatus: state.bindingStatus },
    { vaultSlot: 100, bindingStatus: 'active' }
  );

  assert.equal(
    await writeVaultForProgram(
      { ...validFields, signatureHash: Buffer.alloc(32) },
      CANON_VAULT_PDA,
      101,
      CURRENT_PROGRAM_VERSION,
      'V4-B'
    ),
    false
  );
  assert.deepEqual(
    { vaultSlot: state.vaultSlot, bindingStatus: state.bindingStatus },
    { vaultSlot: 101, bindingStatus: 'quarantined' }
  );

  assert.equal(
    await writeVaultForProgram(validFields, CANON_VAULT_PDA, 100, CURRENT_PROGRAM_VERSION, 'V4-B'),
    false
  );
  assert.equal(state.bindingStatus, 'quarantined');

  assert.equal(
    await writeVaultForProgram(validFields, CANON_VAULT_PDA, 102, CURRENT_PROGRAM_VERSION, 'V4-B'),
    true
  );
  assert.deepEqual(
    { vaultSlot: state.vaultSlot, bindingStatus: state.bindingStatus },
    { vaultSlot: 102, bindingStatus: 'active' }
  );
});

test('writeStake projects Settlement Week LP snapshot fields', async (t) => {
  const originalQuery = db.query;
  let captured = null;

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [] };
  };

  await writeStake(
    {
      user: PublicKey.default,
      vaultId: 12n,
      calStaked: 400n,
      lpTokens: 350n,
      stakedAt: 1713456789n,
      pendingEffectiveWeekPlusOne: 10n,
      effectiveLpTokens: 300n,
      rewardsEarned: 25n,
      pendingLpTokens: 350n,
      bump: 254,
    },
    'stake-pda',
    123
  );

  assert.ok(captured);
  assert.match(captured.sql, /\beffective_lp_tokens\b/);
  assert.match(captured.sql, /\bpending_lp_tokens\b/);
  assert.match(captured.sql, /\bpending_effective_week_plus_one\b/);
  assert.match(captured.sql, /\beligible_from_epoch\b/);
  assert.equal(captured.values[5], '0');
  assert.equal(captured.values[8], '10');
  assert.equal(captured.values[9], '300');
  assert.equal(captured.values[11], '350');
});

test('writeStake keeps pre-snapshot eligibility separate from new fields', async (t) => {
  const originalQuery = db.query;
  let captured = null;

  t.after(() => {
    db.query = originalQuery;
  });

  db.query = async (sql, values) => {
    captured = { sql, values };
    return { rows: [] };
  };

  await writeStake(
    {
      user: PublicKey.default,
      vaultId: 12n,
      calStaked: 100n,
      lpTokens: 100n,
      stakedAt: 1713456789n,
      pendingEffectiveWeekPlusOne: 9n,
      effectiveLpTokens: 0n,
      rewardsEarned: 25n,
      pendingLpTokens: 0n,
      bump: 254,
    },
    'legacy-stake-pda',
    123
  );

  assert.ok(captured);
  assert.equal(captured.values[5], '9');
  assert.equal(captured.values[8], '0');
  assert.equal(captured.values[9], '0');
  assert.equal(captured.values[11], '0');
});

test('maybeWarnSettlementStakerTripwire warns at threshold', (t) => {
  assert.equal(SETTLEMENT_STAKER_TRIPWIRE_THRESHOLD, 4);
  const originalWarn = console.warn;
  const warnings = [];

  t.after(() => {
    console.warn = originalWarn;
  });

  console.warn = (...args) => {
    warnings.push(args);
  };

  maybeWarnSettlementStakerTripwire({
    vaultId: '42',
    stakerCount: SETTLEMENT_STAKER_TRIPWIRE_THRESHOLD,
    pda: 'vault-pda',
    slot: 12345,
  });

  assert.equal(warnings.length, 1);
  assert.match(warnings[0][0], /SettlementTripwire/);
  assert.deepEqual(warnings[0][1], {
    vault_id: '42',
    staker_count: 4,
    threshold: 4,
    pda: 'vault-pda',
    slot: 12345,
    action: 'land settlement ALT or chunking before a fifth inventory account',
  });
});

test('maybeWarnSettlementStakerTripwire stays quiet below threshold', (t) => {
  const originalWarn = console.warn;
  let warningCount = 0;

  t.after(() => {
    console.warn = originalWarn;
  });

  console.warn = () => {
    warningCount += 1;
  };

  maybeWarnSettlementStakerTripwire({
    vaultId: '42',
    stakerCount: SETTLEMENT_STAKER_TRIPWIRE_THRESHOLD - 1,
    pda: 'vault-pda',
    slot: 12345,
  });

  assert.equal(warningCount, 0);
});
