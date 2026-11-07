const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { BN, BorshAccountsCoder } = require('@coral-xyz/anchor');
const { PublicKey } = require('@solana/web3.js');

const db = require('../dist/db.js');
const {
  decodeEvents,
  identifyAccountType,
  loadIdl,
} = require('../dist/decoder.js');
const {
  decodeClimbCompletionFlow,
  decodeClimbCompletionFlowEvent,
  serializeEventFields,
} = require('../dist/modes/replay.js');
const { deriveEventTokenFlows } = require('../dist/api.js');
const { routeAccount } = require('../dist/writers/index.js');

const PROGRAM_ID = 'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH';
const RIDER = new PublicKey('2'.repeat(44));
const RIDE_ATTESTATION = new PublicKey('3'.repeat(44));
const RELEASE_AUTHORITY = new PublicKey('4'.repeat(44));

const RELEASE_ACCOUNT_TYPES = [
  'HeldRideReleaseAuthority',
  'ReleasedRideTributeBudget',
  'ReleasedCalMintReceipt',
  'ReleasedClimbCompletionReceipt',
];

const RELEASE_EVENT_TYPES = [
  'HeldRideReleaseAuthorized',
  'ReleasedCalCredited',
  'ReleasedClimbCompleted',
  'ReleasedClimbCompletionFlowAssigned',
  'ReleasedVaultCompleted',
];

function u64(value) {
  const encoded = Buffer.alloc(8);
  encoded.writeBigUInt64LE(BigInt(value));
  return encoded;
}

function i64(value) {
  const encoded = Buffer.alloc(8);
  encoded.writeBigInt64LE(BigInt(value));
  return encoded;
}

function releaseFlowFields(overrides = {}) {
  return {
    evidenceVersion: 3,
    releaseAuthority: RELEASE_AUTHORITY.toBase58(),
    vaultId: '42',
    rideAttestation: RIDE_ATTESTATION.toBase58(),
    completionEvidenceHash: Buffer.alloc(32, 0xa7).toString('hex'),
    creditedSettlementWeek: '119',
    calTributed: '6400000000',
    ...overrides,
  };
}

function ordinaryFlowFields(evidenceVersion) {
  const { releaseAuthority: _releaseAuthority, ...fields } = releaseFlowFields({
    evidenceVersion,
  });
  return fields;
}

function releaseAuthorityFields(overrides = {}) {
  return {
    rideAttestation: RIDE_ATTESTATION,
    rider: RIDER,
    thresholdAuthorityId: Buffer.alloc(16, 0x11),
    thresholdAuthorityCommitment: Buffer.alloc(32, 0x22),
    thresholdEffectiveAt: 1_800_000_000n,
    thresholdW: 250,
    thresholdPolicyVersion: 1,
    economicTss: 64,
    calEarned: 64_000_000_000n,
    calTributeBudget: 6_400_000_000n,
    releasePlanHash: Buffer.alloc(32, 0x33),
    releasedAt: 1_800_000_001n,
    releasedSlot: 123_458n,
    releaseSettlementWeek: 119n,
    attester: PublicKey.default,
    bump: 251,
    ...overrides,
  };
}

test('committed IDL exposes every stable held-release event and account discriminator', () => {
  const idl = loadIdl();
  const eventNames = new Set((idl.events || []).map((event) => event.name));

  for (const eventName of RELEASE_EVENT_TYPES) {
    assert.equal(eventNames.has(eventName), true, `${eventName} missing from IDL`);
  }
  for (const accountName of RELEASE_ACCOUNT_TYPES) {
    const discriminator = Buffer.from(
      BorshAccountsCoder.accountDiscriminator(accountName)
    );
    assert.equal(identifyAccountType(discriminator), accountName);
  }
});

test('replay accepts evidence v3 only for the released completion-flow event', () => {
  const released = decodeClimbCompletionFlowEvent(
    'ReleasedClimbCompletionFlowAssigned',
    releaseFlowFields()
  );
  assert.equal(released.evidenceVersion, 3);
  assert.equal(released.vaultId, '42');
  assert.equal(released.releaseAuthority, RELEASE_AUTHORITY.toBase58());
  assert.equal(released.creditedSettlementWeek, '119');
  assert.equal(released.calTributed, '6400000000');

  assert.throws(
    () => decodeClimbCompletionFlowEvent(
      'ClimbCompletionFlowAssignedV2',
      releaseFlowFields()
    ),
    /expected 2/
  );
  assert.throws(
    () => decodeClimbCompletionFlowEvent(
      'ReleasedClimbCompletionFlowAssigned',
      ordinaryFlowFields(2)
    ),
    /expected 3/
  );

  assert.equal(
    decodeClimbCompletionFlowEvent(
      'ClimbCompletionFlowAssigned',
      ordinaryFlowFields(1)
    ).evidenceVersion,
    1
  );
  assert.equal(
    decodeClimbCompletionFlowEvent(
      'ClimbCompletionFlowAssignedV2',
      ordinaryFlowFields(2)
    ).evidenceVersion,
    2
  );
});

test('decodeEvents parses the released v3 completion-flow wire event exactly', () => {
  const evidenceHash = Buffer.alloc(32, 0xb8);
  const eventData = Buffer.concat([
    crypto
      .createHash('sha256')
      .update('event:ReleasedClimbCompletionFlowAssigned')
      .digest()
      .subarray(0, 8),
    Buffer.from([3]),
    RELEASE_AUTHORITY.toBuffer(),
    u64(42),
    RIDE_ATTESTATION.toBuffer(),
    evidenceHash,
    u64(119),
    u64(6_400_000_000n),
    i64(1_800_000_000),
  ]);
  const events = decodeEvents([
    `Program ${PROGRAM_ID} invoke [1]`,
    `Program data: ${eventData.toString('base64')}`,
    `Program ${PROGRAM_ID} success`,
  ]);

  assert.equal(events.length, 1);
  assert.equal(events[0].name, 'ReleasedClimbCompletionFlowAssigned');
  const flow = decodeClimbCompletionFlow(serializeEventFields(events[0].data));
  assert.equal(flow.evidenceVersion, 3);
  assert.equal(flow.releaseAuthority, RELEASE_AUTHORITY.toBase58());
  assert.equal(flow.rideAttestation, RIDE_ATTESTATION.toBase58());
  assert.deepEqual(flow.completionEvidenceHash, evidenceHash);
  assert.equal(flow.creditedSettlementWeek, '119');
  assert.equal(flow.calTributed, '6400000000');
});

test('released CAL and tribute enter token flows exactly once across companion events', () => {
  const flows = deriveEventTokenFlows([
    {
      event_name: 'HeldRideReleaseAuthorized',
      fields: { rider: RIDER.toBase58(), calEarned: '64000000000' },
    },
    {
      event_name: 'ReleasedCalCredited',
      fields: { rider: RIDER.toBase58(), amount: '64000000000' },
    },
    {
      event_name: 'ReleasedClimbCompleted',
      fields: { vaultId: '42', calTributed: '6400000000' },
    },
    {
      event_name: 'ReleasedVaultCompleted',
      fields: { vaultId: '42', calTributed: '6400000000' },
    },
  ]);

  assert.deepEqual(
    flows.map((flow) => [flow.symbol, flow.amount, flow.label]),
    [
      ['CAL', '64000000000', 'Ride CAL earned'],
      ['CAL', '6400000000', 'Climb CAL tribute'],
    ]
  );
});

test('released receipt accounts reuse existing exact receipt projections', async (t) => {
  const originalQuery = db.query;
  const writes = [];
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    if (/SELECT release_settlement_week/.test(sql)) {
      const authorityProjected = writes.some((write) =>
        /indexed_held_ride_release_authorities/.test(write.sql)
      );
      return {
        rows: authorityProjected ? [{ release_settlement_week: '119' }] : [],
      };
    }
    writes.push({ sql, values });
    return { rows: [] };
  };

  assert.equal(
    await routeAccount(
      {
        type: 'HeldRideReleaseAuthority',
        fields: {
          rideAttestation: RIDE_ATTESTATION,
          rider: RIDER,
          thresholdAuthorityId: Buffer.alloc(16, 0x11),
          thresholdAuthorityCommitment: Buffer.alloc(32, 0x22),
          thresholdEffectiveAt: 1_800_000_000n,
          thresholdW: 250,
          thresholdPolicyVersion: 1,
          economicTss: 64,
          calEarned: 64_000_000_000n,
          calTributeBudget: 6_400_000_000n,
          releasePlanHash: Buffer.alloc(32, 0x33),
          releasedAt: 1_800_000_001n,
          releasedSlot: 123_458n,
          releaseSettlementWeek: 119n,
          attester: PublicKey.default,
          bump: 251,
        },
      },
      RELEASE_AUTHORITY.toBase58(),
      123458
    ),
    true
  );
  assert.equal(
    await routeAccount(
      {
        type: 'ReleasedCalMintReceipt',
        fields: {
          rideAttestation: RIDE_ATTESTATION,
          releaseAuthority: RELEASE_AUTHORITY,
          rider: RIDER,
          amount: 64_000_000_000n,
          releaseSettlementWeek: 119n,
          bump: 253,
        },
      },
      'released-cal-receipt-pda',
      123456
    ),
    true
  );
  assert.equal(
    await routeAccount(
      {
        type: 'ReleasedClimbCompletionReceipt',
        fields: {
          rideAttestation: RIDE_ATTESTATION,
          releaseAuthority: RELEASE_AUTHORITY,
          vault: PublicKey.default,
          evidenceVersion: 3,
          calTributed: 6_400_000_000n,
          completionEvidenceHash: Buffer.alloc(32, 0xc9),
          creditedSettlementWeek: 119n,
          bump: 252,
        },
      },
      'released-completion-receipt-pda',
      123457
    ),
    true
  );

  assert.equal(writes.length, 3);
  assert.match(writes[0].sql, /indexed_held_ride_release_authorities/);
  assert.equal(writes[0].values[1], RIDE_ATTESTATION.toBase58());
  assert.equal(writes[0].values[3], '11'.repeat(16));
  assert.equal(writes[0].values[8], 64);
  assert.equal(writes[0].values[9], '64000000000');
  assert.equal(writes[0].values[14], '119');
  assert.match(writes[1].sql, /indexed_cal_mint_receipts/);
  assert.equal(writes[1].values[2], RELEASE_AUTHORITY.toBase58());
  assert.equal(writes[1].values[4], '64000000000');
  assert.equal(writes[1].values[5], '119');
  assert.match(writes[2].sql, /indexed_climb_completion_receipts/);
  assert.equal(writes[2].values[2], RELEASE_AUTHORITY.toBase58());
  assert.equal(writes[2].values[4], 3);
  assert.deepEqual(writes[2].values[5], Buffer.alloc(32, 0xc9));
  assert.equal(writes[2].values[6], '6400000000');
  assert.equal(writes[2].values[7], '119');

  assert.equal(
    await routeAccount(
      { type: 'ReleasedRideTributeBudget', fields: {} },
      'release-budget-pda',
      123459
    ),
    false
  );
});

test('released completion receipt rejects any evidence version except v3', async () => {
  await assert.rejects(
    routeAccount(
      {
        type: 'ReleasedClimbCompletionReceipt',
        fields: {
          rideAttestation: RIDE_ATTESTATION,
          releaseAuthority: RELEASE_AUTHORITY,
          vault: PublicKey.default,
          evidenceVersion: 2,
          calTributed: 1n,
          completionEvidenceHash: Buffer.alloc(32),
          creditedSettlementWeek: 119n,
          bump: 252,
        },
      },
      'released-completion-receipt-pda',
      123456
    ),
    /must declare evidence version 3/
  );
});

test('child receipt callbacks hydrate their finalized release authority first', async (t) => {
  const originalQuery = db.query;
  const coder = new BorshAccountsCoder(loadIdl());
  const encodedAuthorityFields = releaseAuthorityFields({
    thresholdEffectiveAt: new BN('1800000000'),
    calEarned: new BN('64000000000'),
    calTributeBudget: new BN('6400000000'),
    releasedAt: new BN('1800000001'),
    releasedSlot: new BN('123458'),
    releaseSettlementWeek: new BN('119'),
  });
  const authorityData = await coder.encode(
    'HeldRideReleaseAuthority',
    encodedAuthorityFields
  );
  let authorityProjected = false;
  let fetches = 0;
  const writes = [];
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql, values) => {
    if (/SELECT release_settlement_week/.test(sql)) {
      return {
        rows: authorityProjected ? [{ release_settlement_week: '119' }] : [],
      };
    }
    if (/indexed_held_ride_release_authorities/.test(sql)) {
      authorityProjected = true;
    }
    writes.push({ sql, values });
    return { rows: [] };
  };
  const connection = {
    getAccountInfoAndContext: async (pda, options) => {
      fetches++;
      assert.equal(pda.toBase58(), RELEASE_AUTHORITY.toBase58());
      assert.equal(options.commitment, 'finalized');
      assert.equal(options.minContextSlot, 123456);
      return {
        context: { slot: 123460 },
        value: {
          data: authorityData,
          executable: false,
          lamports: 1,
          owner: new PublicKey(PROGRAM_ID),
          rentEpoch: 0,
        },
      };
    },
  };

  await routeAccount(
    {
      type: 'ReleasedCalMintReceipt',
      fields: {
        rideAttestation: RIDE_ATTESTATION,
        releaseAuthority: RELEASE_AUTHORITY,
        rider: RIDER,
        amount: 64_000_000_000n,
        releaseSettlementWeek: 119n,
        bump: 253,
      },
    },
    RELEASE_AUTHORITY.toBase58(),
    123456,
    { connection }
  );
  assert.equal(fetches, 1);
  assert.match(writes[0].sql, /indexed_held_ride_release_authorities/);
  assert.match(writes[1].sql, /indexed_cal_mint_receipts/);

  authorityProjected = false;
  writes.length = 0;
  fetches = 0;
  await routeAccount(
    {
      type: 'ReleasedClimbCompletionReceipt',
      fields: {
        rideAttestation: RIDE_ATTESTATION,
        releaseAuthority: RELEASE_AUTHORITY,
        vault: PublicKey.default,
        evidenceVersion: 3,
        calTributed: 6_400_000_000n,
        completionEvidenceHash: Buffer.alloc(32, 0xc9),
        creditedSettlementWeek: 119n,
        bump: 252,
      },
    },
    RELEASE_AUTHORITY.toBase58(),
    123456,
    { connection }
  );
  assert.equal(fetches, 1);
  assert.match(writes[0].sql, /indexed_held_ride_release_authorities/);
  assert.match(writes[1].sql, /indexed_climb_completion_receipts/);
});

test('a projected week conflict never hydrates over frozen authority', async (t) => {
  const originalQuery = db.query;
  let fetches = 0;
  t.after(() => {
    db.query = originalQuery;
  });
  db.query = async (sql) => {
    if (/SELECT release_settlement_week/.test(sql)) {
      return { rows: [{ release_settlement_week: '120' }] };
    }
    return { rows: [] };
  };
  const connection = {
    getAccountInfoAndContext: async () => {
      fetches++;
      throw new Error('must not fetch over a permanent conflict');
    },
  };

  await assert.rejects(
    routeAccount(
      {
        type: 'ReleasedCalMintReceipt',
        fields: {
          rideAttestation: RIDE_ATTESTATION,
          releaseAuthority: RELEASE_AUTHORITY,
          rider: RIDER,
          amount: 1n,
          releaseSettlementWeek: 119n,
          bump: 253,
        },
      },
      'released-cal-receipt-pda',
      123456,
      { connection }
    ),
    /conflicts with frozen release authority/
  );
  assert.equal(fetches, 0);
});
