const test = require('node:test');
const assert = require('node:assert/strict');

const {
  deriveEventTokenFlows,
  handleApiRequest,
  setApiRuntimeForTests,
  resetApiRuntimeForTests,
} = require('../dist/api.js');

const VALID_PUBKEY = '2'.repeat(44);
const VALID_SIGNATURE = '3'.repeat(88);
const CAL_MINT = '4'.repeat(44);
const DUNG_MINT = '5'.repeat(44);
const CANON_CLIMB_ID = '11111111-1111-4111-8111-111111111111';

function createRequest(url, headers = {}) {
  return {
    url,
    method: 'GET',
    headers,
    socket: { remoteAddress: '127.0.0.1' },
  };
}

function createResponse() {
  return {
    statusCode: 200,
    headers: {},
    body: '',
    writeHead(statusCode, headers = {}) {
      this.statusCode = statusCode;
      this.headers = headers;
    },
    end(payload = '') {
      this.body = typeof payload === 'string' ? payload : String(payload);
    },
  };
}

function jsonResult(res) {
  return JSON.parse(res.body || '{}');
}

test.beforeEach(() => {
  resetApiRuntimeForTests();
});

test.after(() => {
  resetApiRuntimeForTests();
});

test('GET /v1/observatory returns the frozen top-level shape', async () => {
  const observatoryQueries = [];
  setApiRuntimeForTests({
    query: async (text) => {
      observatoryQueries.push(text);
      if (text.includes("observatory:ground") || text.includes("observatory:clock")) return { rows: [] };
      if (text.includes('AS climb_references')) return { rows: [] };
      if (
        text.includes('COUNT(*) AS total')
        && text.includes('FROM public.indexed_climbs')
        && !text.includes('ORDER BY COALESCE')
      ) {
        return { rows: [{ total: '12' }] };
      }
      if (text.includes('indexed_rider_souls')) {
        return {
          rows: [
            {
              total_riders: '7',
              total_completions: '55',
              total_cal_staked: '8800000000',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_supply')) {
        return {
          rows: [
            {
              total_minted: '100',
              total_burned: '5',
              spl_mint_supply: '91',
              spl_mint_supply_slot: '321',
              spl_mint_supply_indexed_at: '2026-05-04T01:07:30.000Z',
              max_supply: '1000',
              current_emission_rate_bps: '10000',
              last_halving_epoch: '0',
            },
          ],
        };
      }
      if (
        text.includes('FROM indexed_events')
        && text.includes('successor_handoff_slot')
      ) {
        return {
          rows: [
            {
              tx_signature: VALID_SIGNATURE,
              event_index: 0,
              event_name: 'VaultCreated',
              fields: { vault_id: 12 },
              slot: '123',
              block_time: '1700000000',
            },
          ],
        };
      }
      if (
        text.includes('AS active_climbs')
        && text.includes('ORDER BY COALESCE')
      ) {
        return {
          rows: [
            {
              id: CANON_CLIMB_ID,
              canon_id: '22222222-2222-4222-8222-222222222222',
              version: 1,
              status: 'ratified',
              display_name: 'Manayunk Wall',
              route_name: 'Umbria Street',
              length_m: 800,
              vert_m: 97,
              avg_gradient_pct: 12.4,
              worthiness_score: 0.99,
              canonical_profile: [],
              created_at: '1700000000',
              climb_pda: VALID_PUBKEY,
              vault_id: 12,
              vault_pda: '6'.repeat(44),
              vault_signature: 'ab'.repeat(64),
              vault_minter: VALID_PUBKEY,
              vault_created_at: '1700000001',
              total_completions: '55',
              total_cal_staked: '8800000000',
              staker_count: 4,
              kom_holder: VALID_PUBKEY,
              kom_time_s: 161,
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const req = createRequest('/v1/observatory');
  const res = createResponse();

  const handled = await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(handled, true);
  assert.equal(res.statusCode, 200);
  assert.equal(body.vault_count, 12);
  assert.equal(body.total_riders, 7);
  assert.equal(body.total_completions, 55);
  assert.equal(body.total_cal_staked, '8800000000');
  assert.equal(body.supply.circulating, '91');
  assert.equal(body.supply.circulating_source, 'spl_mint_supply');
  assert.equal(body.supply.spl_mint_supply_slot, '321');
  assert.equal(body.supply.spl_mint_supply_indexed_at, '2026-05-04T01:07:30.000Z');
  assert.equal(body.supply.spl_mint_supply_max_stale_ms, 300_000);
  assert.ok(Array.isArray(body.recent_events));
  assert.ok(Array.isArray(body.top_vaults));
  assert.equal(body.top_vaults[0].id, CANON_CLIMB_ID);
  assert.ok(
    observatoryQueries.some(
      (text) =>
        text.includes('canon_binding_status')
        && text.includes("= 'active'")
        && text.includes('canon_climb_id')
    ),
    'observatory must exclude legacy V4-A vault rows'
  );
  assert.ok(
    observatoryQueries.some(
      (text) =>
        text.includes('indexed_rider_souls')
        && text.includes('successor_handoff_slot')
    ),
    'observatory rider totals must start at the ratified V4-B handoff'
  );
  assert.ok(
    observatoryQueries.some(
      (text) =>
        text.includes('FROM indexed_events')
        && text.includes('successor_handoff_slot')
        && text.includes("'ReleasedClimbCompleted'")
        && text.includes("event_name NOT IN")
    ),
    'observatory events must start at the ratified V4-B handoff and retain the KOM-only completion feed'
  );
  assert.equal(body.freshness.contract_version, 'scan_freshness.v1');
  assert.equal(body.freshness.status, 'unknown');
});

test('GET /v1/transactions/:signature returns metadata, instructions, events, and token flows', async () => {
  setApiRuntimeForTests({
    query: async (text, params) => {
      if (text.includes('indexer_sync_state')) {
        return {
          rows: [
            {
              last_account_slot: '123',
              last_tx_slot: '121',
              last_account_sync_at: new Date().toISOString(),
              last_tx_sync_at: new Date().toISOString(),
              stream_connected: true,
            },
          ],
        };
      }
      if (text.includes('FROM indexed_transactions')) {
        assert.equal(params[0], VALID_SIGNATURE);
        return {
          rows: [
            {
              signature: VALID_SIGNATURE,
              slot: '123',
              block_time: '1700000000',
              status: 'success',
              fee_lamports: '5000',
              compute_units: 142000,
              instruction_index: 0,
              instruction_name: 'create_vault',
              instruction_args: { amount: '1' },
              instruction_accounts: { vault: VALID_PUBKEY },
            },
            {
              signature: VALID_SIGNATURE,
              slot: '123',
              block_time: '1700000000',
              status: 'success',
              fee_lamports: '5000',
              compute_units: 142000,
              instruction_index: 1,
              instruction_name: 'record_vault_completion',
              instruction_args: { completion_time_s: 161 },
              instruction_accounts: { user: VALID_PUBKEY },
            },
          ],
        };
      }
      if (text.includes('FROM indexed_events')) {
        return {
          rows: [
            {
              tx_signature: VALID_SIGNATURE,
              event_index: 0,
              event_name: 'VaultCompleted',
              fields: { vault_id: 12, calTributed: '847000000000' },
              slot: '123',
              block_time: '1700000000',
            },
            {
              tx_signature: VALID_SIGNATURE,
              event_index: 1,
              event_name: 'EpochRewardsDistributed',
              fields: {
                vault_id: 12,
                epoch: 14,
                totalDistributed: '4200000000000',
                leaderboardDistributed: '2310000000000',
                stakerDistributed: '1260000000000',
                localLegendDistributed: '126000000000',
                polDistributed: '210000000000',
                protocolDistributed: '294000000000',
                lockedStakerAmount: '540000000000',
              },
              slot: '123',
              block_time: '1700000000',
            },
            {
              tx_signature: VALID_SIGNATURE,
              event_index: 2,
              event_name: 'StakerRemainderPolicyApplied',
              fields: {
                vaultId: 12,
                settlementWeek: 14,
                policyVersion: 1,
                currentLockedReallocated: '540000000000',
                legacyCarryReallocated: '2673',
              },
              slot: '123',
              block_time: '1700000000',
            },
            {
              tx_signature: VALID_SIGNATURE,
              event_index: 3,
              event_name: 'RewardsHarvested',
              fields: {
                vault_id: 12,
                staker: VALID_PUBKEY,
                dungReceived: '95000000000',
                harvestFee: '5000000000',
              },
              slot: '123',
              block_time: '1700000000',
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const req = createRequest(`/v1/transactions/${VALID_SIGNATURE}`);
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.signature, VALID_SIGNATURE);
  assert.equal(body.status, 'success');
  assert.equal(body.fee_lamports, '5000');
  assert.equal(body.instructions.length, 2);
  assert.equal(body.instructions[1].name, 'record_vault_completion');
  assert.equal(body.events.length, 4);
  assert.ok(Array.isArray(body.token_flows));
  assert.equal(body.token_flows[0].label, 'Climb CAL tribute');
  assert.equal(body.token_flows[0].amount, '847000000000');
  assert.equal(body.token_flows[0].source, 'event');
  const leaderboardFlow = body.token_flows.find((flow) => flow.target === 'Leaderboard');
  assert.equal(leaderboardFlow.label, null);
  assert.equal(leaderboardFlow.amount, '2310000000000');
  const stakerReallocationFlow = body.token_flows.find(
    (flow) => flow.origin === 'Staker allocation' && flow.target === 'Leaderboard pool'
  );
  assert.equal(stakerReallocationFlow.label, null);
  assert.equal(stakerReallocationFlow.amount, '540000000000');
  const legacyCutoverFlow = body.token_flows.find(
    (flow) => flow.origin === 'Prior staker balance' && flow.target === 'Leaderboard pool'
  );
  assert.equal(legacyCutoverFlow.label, 'Balance sweep');
  assert.equal(legacyCutoverFlow.amount, '2673');
  assert.equal(
    body.token_flows.some((flow) => flow.target === 'Climb #12 stakers' && flow.amount === '4200000000000'),
    false
  );
  const harvestFlow = body.token_flows.find((flow) => flow.label === 'Harvest received');
  assert.equal(harvestFlow.owner, VALID_PUBKEY);
  assert.equal(harvestFlow.symbol, 'DUNG');
  assert.equal(body.freshness.contract_version, 'scan_freshness.v1');
  assert.equal(body.freshness.status, 'live');
  assert.equal(body.freshness.read_model, 'transaction_detail');
  assert.equal(body.freshness.max_observed_slot, 123);
});

test('historical settlement events retain their original locked-carry meaning', () => {
  const flows = deriveEventTokenFlows([
    {
      event_name: 'EpochRewardsDistributed',
      fields: {
        vaultId: 12,
        epoch: 13,
        lockedStakerAmount: '540000000000',
      },
    },
  ]);

  const historicalCarry = flows.find(
    (flow) => flow.origin === 'Staker allocation' && flow.target === 'Prior staker balance'
  );
  assert.equal(historicalCarry.amount, '540000000000');
  assert.equal(flows.some((flow) => flow.target === 'Leaderboard pool'), false);
});

test('GET /v1/vaults/:id separates activation audit from live recent activity', async () => {
  setApiRuntimeForTests({
    query: async (text, params) => {
      if (text.includes('FROM indexed_vaults iv')) {
        assert.equal(params[0], 12);
        return {
          rows: [
            {
              id: 12,
              name: 'Activation Ridge',
              signature_hex: 'ab'.repeat(32),
              signature_hash_hex: 'cd'.repeat(32),
              minter: VALID_PUBKEY,
              vert_m: 970,
              distance_m: 800,
              avg_gradient_pct: 1240,
              total_completions: '55',
              total_cal_staked: '8800000000',
              staker_count: 4,
              reward_per_token_stored: '999',
              last_update_time: '1700000001',
              reward_rate: '777',
              staker_remainder_policy_version: 1,
              pending_rewards_next_week: '123000000000',
              carry_record_royalty: '45000000000',
              kom_holder: VALID_PUBKEY,
              kom_time_s: 161,
              created_at: '1700000000',
              on_chain_seeding_status: 'pending',
              on_chain_seed_tx: '6'.repeat(88),
              on_chain_leaderboard_tx: '7'.repeat(88),
              on_chain_activate_tx: '8'.repeat(88),
              on_chain_seeded_at: '2026-03-18T17:45:00Z',
              on_chain_activated_at: '2026-03-18T18:10:00Z',
              activation_pda: '9'.repeat(44),
              activation_is_active: true,
              activation_seed_completions_written: 42,
              activation_leaderboard_seeded: true,
              activation_created_at: '1700000000',
              activation_activated_at: '1700003600',
              activation_last_seed_at: '1700001800',
              activation_chain_slot: '123',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_leaderboards')) {
        return { rows: [{ entries: [{ rank: 1, user: VALID_PUBKEY, time_s: 161, recorded_at: '1700003600' }] }] };
      }
      if (text.includes('FROM indexed_legends')) {
        return {
          rows: [
            {
              vault_id: 12,
              holder: VALID_PUBKEY,
              election_period: '3',
              term_start_epoch: '24',
              term_end_epoch: '32',
              completions_at_election: 147,
              runner_up: null,
              runner_up_completions: 0,
              total_earned: '0',
              is_active: true,
              is_bootstrap: false,
            },
          ],
        };
      }
      if (text.includes("event_name <> 'VaultActivated'")) {
        return {
          rows: [
            {
              tx_signature: VALID_SIGNATURE,
              event_index: 0,
              event_name: 'EpochRewardsDistributed',
              fields: { vault_id: 12, epoch: 14, total_distributed: '4200000000000' },
              slot: '123',
              block_time: '1700007200',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_epoch_distributions')) {
        return {
          rows: [
            {
              tx_signature: '4'.repeat(88),
              event_index: 0,
              vault_id: 12,
              epoch: 14,
              total_distributed: '4200000000000',
              leaderboard_distributed: '2310000000000',
              staker_distributed: '1260000000000',
              local_legend_distributed: '126000000000',
              pol_distributed: '210000000000',
              protocol_distributed: '294000000000',
              staker_count: 4,
              unlock_pct: 70,
              locked_staker_amount: '540000000000',
              slot: '123',
              block_time: '1700007200',
            },
          ],
        };
      }
      if (text.includes("event_name = 'VaultActivated'")) {
        return {
          rows: [
            {
              tx_signature: '5'.repeat(88),
              event_index: 0,
              event_name: 'VaultActivated',
              fields: { vault_id: 12, seed_completions_written: 42, leaderboard_seeded: true },
              slot: '122',
              block_time: '1700003600',
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const req = createRequest('/v1/vaults/12');
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.vault.activation_status, 'active');
  assert.equal(body.vault.activation_is_active, true);
  assert.equal(body.vault.pending_rewards_next_week, '123000000000');
  assert.equal(body.vault.carry_record_royalty, '45000000000');
  assert.equal(body.vault.staker_remainder_policy_version, 1);
  assert.equal(Object.hasOwn(body.vault, 'reward_per_token_stored'), false);
  assert.equal(Object.hasOwn(body.vault, 'last_update_time'), false);
  assert.equal(Object.hasOwn(body.vault, 'reward_rate'), false);
  assert.equal(body.recent_events.length, 1);
  assert.equal(body.recent_events[0].event_name, 'EpochRewardsDistributed');
  assert.equal(body.local_legend.seat_status, 'elected');
  assert.equal(body.local_legend.is_bootstrap, false);
  assert.equal(body.activation_events.length, 1);
  assert.equal(body.activation_events[0].event_name, 'VaultActivated');
});

test('GET /v1/climbs returns UUID-backed registry Climbs with optional Vault economy', async () => {
  setApiRuntimeForTests({
    query: async (text, params) => {
      if (text.includes('COUNT(*) AS total FROM public.canon_climbs')) {
        return { rows: [{ total: '1' }] };
      }
      if (text.includes('FROM public.canon_climbs AS canon')) {
        assert.equal(params[0], 5);
        assert.equal(params[1], 0);
        assert.match(text, /constructor_evidence_verified IS TRUE/);
        assert.match(text, /activation\.seed_generation = 2/);
        assert.match(text, /indexed\.vault_pda = candidate\.pda/);
        return {
          rows: [
            {
              id: CANON_CLIMB_ID,
              canon_id: '22222222-2222-4222-8222-222222222222',
              version: 2,
              status: 'ratified',
              display_name: 'Manayunk Wall',
              length_m: 800,
              vert_m: 97,
              distance_m: 800,
              avg_gradient_pct: 12.4,
              canonical_profile: [{ dist_m: 0, elev_m: 10 }],
              climb_pda: VALID_PUBKEY,
              vault_id: 12,
              vault_signature: 'ab'.repeat(64),
              total_completions: '55',
              total_cal_staked: '8800000000',
              staker_count: 4,
              kom_holder: VALID_PUBKEY,
              kom_time_s: 161,
              created_at: '1700000000',
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const req = createRequest('/v1/climbs?sort=completions&order=asc&limit=5');
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.total, 1);
  assert.equal(body.climbs.length, 1);
  assert.equal(body.climbs[0].id, CANON_CLIMB_ID);
  assert.equal(body.climbs[0].vault_id, 12);
  assert.equal(body.climbs[0].has_vault, true);
  assert.equal(Object.hasOwn(body, 'vaults'), false);
});

test('GET /v1/climbs/:id uses a registry UUID and rejects unbound numeric aliases', async () => {
  setApiRuntimeForTests({
    query: async (text, params) => {
      if (text.includes('AS climb_references')) return { rows: [] };
      if (text.includes('climb-page-data:identity')) return { rows: [] };
      if (text.includes('FROM public.canon_climbs AS canon')) {
        assert.equal(params[0], CANON_CLIMB_ID);
        return {
          rows: [
            {
              id: CANON_CLIMB_ID,
              canon_id: '22222222-2222-4222-8222-222222222222',
              version: 2,
              status: 'ratified',
              display_name: 'Activation Ridge',
              length_m: 800,
              vert_m: 97,
              avg_gradient_pct: 12.4,
              canonical_profile: [],
              vault_id: null,
              created_at: '1700000000',
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const req = createRequest(`/v1/climbs/${CANON_CLIMB_ID}`);
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.contract_version, 'client.v1');
  assert.equal(body.truth_source, 'projected');
  assert.equal(body.climb.id, CANON_CLIMB_ID);
  assert.equal(body.climb.has_vault, false);
  assert.equal(body.vault, null);
  assert.deepEqual(body.leaderboard, []);
  assert.equal(body.local_legend, null);
  assert.deepEqual(body.recent_events, []);
  assert.deepEqual(body.distribution_history, []);
  assert.deepEqual(body.activation_events, []);
  assert.equal(body.freshness.read_model, 'climb_detail');

  const numericRes = createResponse();
  await handleApiRequest(createRequest('/v1/climbs/12'), numericRes);
  assert.equal(numericRes.statusCode, 404);
});

test('GET /v1/climbs/:id attaches only an exact active Vault and Record Board', async () => {
  setApiRuntimeForTests({
    query: async (text, params) => {
      if (text.includes('climb-page-data:identity')) return { rows: [] };
      if (text.includes('FROM public.canon_climbs AS canon')) {
        assert.match(text, /indexed\.vault_pda = candidate\.pda/);
        return {
          rows: [
            {
              id: CANON_CLIMB_ID,
              canon_id: '22222222-2222-4222-8222-222222222222',
              version: 2,
              status: 'ratified',
              display_name: 'Activation Ridge',
              length_m: 800,
              vert_m: 97,
              avg_gradient_pct: 12.4,
              canonical_profile: [],
              climb_pda: VALID_PUBKEY,
              vault_id: 12,
              vault_pda: 'vault-pda',
              vault_signature: 'ab'.repeat(64),
              total_completions: '55',
              total_cal_staked: '8800000000',
              staker_count: 4,
              kom_holder: VALID_PUBKEY,
              kom_time_s: 161,
              created_at: '1700000000',
            },
          ],
        };
      }
      if (text.includes('FROM public.indexed_vaults AS iv')) {
        assert.deepEqual(params, [12, CANON_CLIMB_ID, VALID_PUBKEY]);
        assert.match(text, /constructor_evidence_verified IS TRUE/);
        assert.match(text, /iva\.seed_generation = 2/);
        assert.match(text, /iv\.canon_binding_status = 'active'/);
        assert.match(text, /indexed\.vault_pda = iv\.pda/);
        return {
          rows: [
            {
              id: 12,
              name: 'Activation Ridge',
              pda: 'vault-pda',
              canon_climb_id: CANON_CLIMB_ID,
              climb_pda: VALID_PUBKEY,
              canon_binding_status: 'active',
              total_completions: '55',
              total_cal_staked: '8800000000',
              staker_count: 4,
              activation_pda: 'activation-pda',
              activation_is_active: true,
              activation_seed_completions_written: 0,
              activation_leaderboard_seeded: true,
              activation_created_at: '1700000000',
              activation_activated_at: '1700000000',
              activation_last_seed_at: '1700000000',
              activation_seed_generation: 2,
              activation_seed_cutoff_at: '1700000000',
              activation_matched_users: 0,
              activation_matched_completions: 0,
            },
          ],
        };
      }
      if (text.includes('FROM indexed_leaderboards')) {
        return { rows: [{ entries: [{ rank: 1, user: VALID_PUBKEY, time_s: 161 }] }] };
      }
      if (text.includes('FROM indexed_legends')) {
        return { rows: [] };
      }
      if (text.includes("event_name <> 'VaultActivated'")) {
        return {
          rows: [
            {
              tx_signature: VALID_SIGNATURE,
              event_index: 0,
              event_name: 'CompletionRecorded',
              fields: { vault_id: 12 },
              slot: '123',
              block_time: '1700007200',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_epoch_distributions')) {
        return { rows: [] };
      }
      if (text.includes("event_name = 'VaultActivated'")) {
        return { rows: [] };
      }
      if (text.includes('FROM indexer_sync_state')) {
        return { rows: [] };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const res = createResponse();
  await handleApiRequest(createRequest(`/v1/climbs/${CANON_CLIMB_ID}`), res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.climb.id, CANON_CLIMB_ID);
  assert.equal(body.climb.has_vault, true);
  assert.equal(body.vault.id, 12);
  assert.equal(body.vault.activation_status, 'active');
  assert.equal(body.leaderboard.length, 1);
  assert.equal(body.recent_events[0].event_name, 'CompletionRecorded');
  assert.deepEqual(body.distribution_history, []);
  assert.deepEqual(body.activation_events, []);
});

test('GET /v1/climbs/:id suppresses stale Vault data when exact activation recheck fails', async () => {
  setApiRuntimeForTests({
    query: async (text) => {
      if (text.includes('climb-page-data:identity')) return { rows: [] };
      if (text.includes('FROM public.canon_climbs AS canon')) {
        return {
          rows: [
            {
              id: CANON_CLIMB_ID,
              canon_id: '22222222-2222-4222-8222-222222222222',
              version: 2,
              status: 'ratified',
              display_name: 'Activation Ridge',
              length_m: 800,
              vert_m: 97,
              avg_gradient_pct: 12.4,
              canonical_profile: [],
              climb_pda: VALID_PUBKEY,
              vault_id: 12,
              vault_pda: 'stale-vault-pda',
              vault_signature: 'ab'.repeat(64),
              total_completions: '55',
              created_at: '1700000000',
            },
          ],
        };
      }
      if (text.includes('FROM public.indexed_vaults AS iv')) {
        return { rows: [] };
      }
      if (text.includes('FROM indexed_leaderboards')) {
        return { rows: [{ entries: [{ rank: 1 }] }] };
      }
      if (
        text.includes('FROM indexed_legends')
        || text.includes('FROM indexed_events')
        || text.includes('FROM indexed_epoch_distributions')
        || text.includes('FROM indexer_sync_state')
      ) {
        return { rows: [] };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const res = createResponse();
  await handleApiRequest(createRequest(`/v1/climbs/${CANON_CLIMB_ID}`), res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.climb.has_vault, false);
  assert.equal(body.climb.vault_id, null);
  assert.equal(body.climb.total_completions, 0);
  assert.equal(body.vault, null);
  assert.deepEqual(body.leaderboard, []);
  assert.deepEqual(body.recent_events, []);
});

test('GET /v1/accounts/:pubkey returns recent events and live SPL balances', async () => {
  let stakeQuery = '';
  setApiRuntimeForTests({
    query: async (text) => {
      if (text.includes('FROM indexed_accounts')) {
        return {
          rows: [
            {
              owner_pubkey: VALID_PUBKEY,
              total_rides: '47',
              total_tss: '14200',
              cal_balance: '0',
              cal_earned_today: '0',
              last_cal_mint: '0',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_rider_souls')) {
        return {
          rows: [
            {
              rider_pubkey: VALID_PUBKEY,
              created_at: '1700000000',
              total_rides: '47',
              total_tss: '14200',
              total_distance_m: '321000',
              total_vert_m: '5800',
              total_cal_earned: '9300000000000',
              archetype: 1,
              bio_score: '777',
              climb_card: '6'.repeat(44),
              steady_card: null,
              explorer_card: null,
            },
          ],
        };
      }
      if (text.includes('FROM indexed_beetle_cards')) {
        return {
          rows: [
            {
              owner_pubkey: VALID_PUBKEY,
              card_type: 0,
              scope_id_hex: '0'.repeat(64),
              score: '8500',
              level: 4,
              patterns_scored: 47,
              total_dung_burned: '175000000000',
              created_at: '1700000000',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_stakes')) {
        stakeQuery = text;
        return {
          rows: [
            {
              vault_id: 12,
              cal_staked: '0',
              lp_tokens: '2',
              rewards_earned: '340000000000',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_completions')) {
        return {
          rows: [
            {
              vault_id: 12,
              completions: 12,
              best_time_s: 161,
              last_completed_at: '1700000000',
              total_cal_tributed: '10140000000000',
            },
          ],
        };
      }
      if (text.includes('WHERE user_pubkey = $1')) {
        return {
          rows: [
            {
              tx_signature: VALID_SIGNATURE,
              event_index: 0,
              event_name: 'CalStaked',
              fields: { vault_id: 12, staker: VALID_PUBKEY },
              slot: '123',
              block_time: '1700000000',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_ride_attestations')) {
        return {
          rows: [
            {
              rider_pubkey: VALID_PUBKEY,
              ride_hash_hex: 'ab'.repeat(32),
              attestation_commitment_hex: 'cd'.repeat(32),
              parser_version: 1,
              source_kind: 1,
              completed_at: '1700000300',
              started_at: '1700000000',
              total_tss: 84,
              total_distance_m: 28123,
              total_vert_m: 677,
              cal_earned: '47000000000',
              climbs_crossed: 3,
              attester: '7'.repeat(44),
              settled_at: '1700000400',
              settled_slot: '999',
              economic_epoch: '118',
              finalized: true,
              pda: '8'.repeat(44),
              chain_slot: '1000',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_program_config')) {
        return {
          rows: [
            {
              cal_mint: CAL_MINT,
              dung_mint: DUNG_MINT,
            },
          ],
        };
      }
      if (text.includes('FROM users')) {
        return {
          rows: [
            {
              username: 'coreyb',
              display_name: 'Corey B',
              wallet: VALID_PUBKEY,
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
    getRpcConnection: () => ({
      getParsedTokenAccountsByOwner: async (_owner, { programId }) => {
        if (String(programId) === 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA') {
          return {
            value: [
              {
                account: {
                  data: {
                    parsed: {
                      info: {
                        mint: CAL_MINT,
                        tokenAmount: { amount: '42000000000000' },
                      },
                    },
                  },
                },
              },
              {
                account: {
                  data: {
                    parsed: {
                      info: {
                        mint: DUNG_MINT,
                        tokenAmount: { amount: '1200000000000' },
                      },
                    },
                  },
                },
              },
            ],
          };
        }

        return {
          value: [
            {
              account: {
                data: {
                  parsed: {
                    info: {
                      mint: DUNG_MINT,
                      tokenAmount: { amount: '0' },
                    },
                  },
                },
              },
            },
          ],
        };
      },
    }),
  });

  const req = createRequest(`/v1/accounts/${VALID_PUBKEY}`);
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.pubkey, VALID_PUBKEY);
  assert.equal(body.profile.username, 'coreyb');
  assert.equal(body.profile.display_name, 'Corey B');
  assert.equal(body.profile.wallet, VALID_PUBKEY);
  assert.equal(body.spl_balances.cal, '42000000000000');
  assert.equal(body.spl_balances.dung, '1200000000000');
  assert.equal(body.user_state.legacy_cal_snapshot, '0');
  assert.equal(body.user_state.legacy_cal_earned_today, '0');
  assert.equal(body.user_state.legacy_last_cal_mint, '0');
  assert.equal('cal_balance' in body.user_state, false);
  assert.equal(body.beetle_cards[0].card_type, 'climb');
  assert.equal(body.beetle_cards[0].scope, 'global');
  assert.equal(body.rider_soul.total_rides, '47');
  assert.equal(body.rider_soul.total_cal_earned, '9300000000000');
  assert.equal(body.active_stakes[0].cal_staked, '0');
  assert.equal(body.active_stakes[0].lp_tokens, '2');
  assert.match(stakeQuery, /lp_tokens > 0/);
  assert.doesNotMatch(stakeQuery, /cal_staked > 0/);
  assert.equal(body.recent_ride_attestations.length, 1);
  assert.equal(body.recent_ride_attestations[0].source_kind_label, 'fit');
  assert.equal(body.recent_ride_attestations[0].ride_hash_hex, 'ab'.repeat(32));
  assert.equal(body.recent_events.length, 1);
});

test('GET /v1/accounts/:pubkey filters VaultActivated out of default recent activity', async () => {
  setApiRuntimeForTests({
    query: async (text) => {
      if (text.includes('FROM indexed_accounts')) {
        return {
          rows: [
            {
              owner_pubkey: VALID_PUBKEY,
              total_rides: '47',
              total_tss: '14200',
              cal_balance: '0',
              cal_earned_today: '0',
              last_cal_mint: '0',
            },
          ],
        };
      }
      if (text.includes('FROM indexed_rider_souls')) {
        return { rows: [] };
      }
      if (
        text.includes('FROM indexed_beetle_cards')
        || text.includes('FROM indexed_stakes')
        || text.includes('FROM indexed_completions')
        || text.includes('FROM indexed_ride_attestations')
      ) {
        return { rows: [] };
      }
      if (text.includes("event_name <> 'VaultActivated'")) {
        return { rows: [] };
      }
      if (text.includes('FROM indexed_program_config')) {
        return { rows: [{ cal_mint: CAL_MINT, dung_mint: DUNG_MINT }] };
      }
      if (text.includes('FROM users')) {
        return { rows: [] };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
    getRpcConnection: () => ({
      getParsedTokenAccountsByOwner: async () => ({ value: [] }),
    }),
  });

  const req = createRequest(`/v1/accounts/${VALID_PUBKEY}`);
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.deepEqual(body.recent_events, []);
});

test('GET /v1/accounts/resolve resolves a public username to wallet pubkey', async () => {
  setApiRuntimeForTests({
    query: async (text, params) => {
      if (text.includes('FROM users')) {
        assert.equal(params[0], 'coreyb');
        return {
          rows: [
            {
              username: 'coreyb',
              wallet: VALID_PUBKEY,
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const req = createRequest('/v1/accounts/resolve?username=@coreyb');
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.username, 'coreyb');
  assert.equal(body.pubkey, VALID_PUBKEY);
});

test('GET /v1/accounts/resolve rejects invalid usernames', async () => {
  const req = createRequest('/v1/accounts/resolve?username=Nope!');
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 400);
  assert.equal(body.error, 'Invalid username format');
});

test('GET /v1/accounts/:pubkey returns 404 when the indexed account is missing', async () => {
  setApiRuntimeForTests({
    query: async (text) => {
      if (text.includes('FROM indexed_accounts')) {
        return { rows: [] };
      }
      if (
        text.includes('FROM indexed_rider_souls')
        || text.includes('FROM indexed_ride_attestations')
        || text.includes('FROM indexed_beetle_cards')
        || text.includes('FROM indexed_stakes')
        || text.includes('FROM indexed_completions')
        || text.includes('FROM indexed_events')
        || text.includes('FROM indexed_program_config')
        || text.includes('FROM users')
      ) {
        return { rows: [] };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const req = createRequest(`/v1/accounts/${VALID_PUBKEY}`);
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 404);
  assert.equal(body.error, 'Not found');
});

test('GET /v1/accounts/:pubkey returns rider_soul-only profile when legacy account is absent', async () => {
  setApiRuntimeForTests({
    query: async (text) => {
      if (text.includes('FROM indexed_accounts')) {
        return { rows: [] };
      }
      if (text.includes('FROM indexed_rider_souls')) {
        return {
          rows: [
            {
              rider_pubkey: VALID_PUBKEY,
              created_at: '1700000000',
              total_rides: '9',
              total_tss: '987',
              total_distance_m: '12345',
              total_vert_m: '456',
              total_cal_earned: '1200000000',
              archetype: 2,
              bio_score: '88',
              climb_card: null,
              steady_card: null,
              explorer_card: null,
            },
          ],
        };
      }
      if (
        text.includes('FROM indexed_beetle_cards')
        || text.includes('FROM indexed_stakes')
        || text.includes('FROM indexed_completions')
        || text.includes('FROM indexed_events')
        || text.includes('FROM indexed_ride_attestations')
      ) {
        return { rows: [] };
      }
      if (text.includes('FROM indexed_program_config')) {
        return { rows: [] };
      }
      if (text.includes('FROM users')) {
        return {
          rows: [
            {
              username: 'dungbeetlephoenix',
              display_name: null,
              wallet: VALID_PUBKEY,
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
    getRpcConnection: () => ({
      getParsedTokenAccountsByOwner: async () => ({ value: [] }),
    }),
  });

  const req = createRequest(`/v1/accounts/${VALID_PUBKEY}`);
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.profile.username, 'dungbeetlephoenix');
  assert.equal(body.user_state, null);
  assert.equal(body.rider_soul.total_rides, '9');
  assert.deepEqual(body.recent_ride_attestations, []);
});

test('GET /v1/ride-attestations filters by rider and ride hash', async () => {
  const RIDE_HASH = 'ab'.repeat(32);

  setApiRuntimeForTests({
    query: async (text, params) => {
      if (text.includes('COUNT(*) AS total') && text.includes('FROM indexed_ride_attestations')) {
        assert.equal(params[0], VALID_PUBKEY);
        assert.equal(params[1], RIDE_HASH);
        return { rows: [{ total: '1' }] };
      }
      if (text.includes('FROM indexed_ride_attestations')) {
        assert.equal(params[0], VALID_PUBKEY);
        assert.equal(params[1], RIDE_HASH);
        assert.equal(params[2], 20);
        assert.equal(params[3], 0);
        return {
          rows: [
            {
              rider_pubkey: VALID_PUBKEY,
              ride_hash_hex: RIDE_HASH,
              attestation_commitment_hex: 'cd'.repeat(32),
              parser_version: 1,
              source_kind: 2,
              completed_at: '1700000300',
              started_at: '1700000000',
              total_tss: 84,
              total_distance_m: 28123,
              total_vert_m: 677,
              cal_earned: '47000000000',
              climbs_crossed: 3,
              attester: '7'.repeat(44),
              settled_at: '1700000400',
              settled_slot: '999',
              economic_epoch: '118',
              finalized: false,
              pda: '8'.repeat(44),
              chain_slot: '1000',
            },
          ],
        };
      }
      if (text.includes("transaction-receipt:") || text.includes("account-page-data:") || text.includes("SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")) return {rows: []};
      throw new Error(`Unexpected query: ${text}`);
    },
  });

  const req = createRequest(`/v1/ride-attestations?user=${VALID_PUBKEY}&ride_hash=${RIDE_HASH}`);
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 200);
  assert.equal(body.total, 1);
  assert.equal(body.attestations.length, 1);
  assert.equal(body.attestations[0].source_kind_label, 'gpx');
  assert.equal(body.attestations[0].ride_hash_hex, RIDE_HASH);
});

test('GET /v1/ride-attestations rejects missing filters', async () => {
  const req = createRequest('/v1/ride-attestations');
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 400);
  assert.equal(body.error, 'user or ride_hash is required');
});

test('GET /v1/ride-attestations rejects invalid ride hash', async () => {
  const req = createRequest(`/v1/ride-attestations?ride_hash=xyz&user=${VALID_PUBKEY}`);
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 400);
  assert.equal(body.error, 'ride_hash must be a 32-byte hex digest');
});

test('GET /v1/accounts/:pubkey rate limits public account detail lookups by client IP', async () => {
  let queries = 0;
  setApiRuntimeForTests({
    query: async () => {
      queries += 1;
      return { rows: [] };
    },
  });

  for (let i = 0; i < 60; i += 1) {
    const req = createRequest(`/v1/accounts/${VALID_PUBKEY}`, { 'x-forwarded-for': '203.0.113.9' });
    const res = createResponse();
    await handleApiRequest(req, res);
    assert.equal(res.statusCode, 404);
  }

  const limitedReq = createRequest(`/v1/accounts/${VALID_PUBKEY}`, { 'x-forwarded-for': '203.0.113.9' });
  const limitedRes = createResponse();
  await handleApiRequest(limitedReq, limitedRes);
  const body = jsonResult(limitedRes);

  assert.equal(limitedRes.statusCode, 429);
  assert.equal(body.error, 'Rate limit exceeded');
  assert.ok(queries > 0);
});

test('GET /v1/accounts/:pubkey rejects invalid pubkey input with 400', async () => {
  const req = createRequest('/v1/accounts/not-a-pubkey');
  const res = createResponse();

  await handleApiRequest(req, res);
  const body = jsonResult(res);

  assert.equal(res.statusCode, 400);
  assert.equal(body.error, 'Invalid pubkey format');
});

const liveSupply = require('../../history/boulderscan-census-2026-09-06/build/lnq0e.3/live-supply.json');

async function supplyResponse(row, route = '/v1/supply') {
  setApiRuntimeForTests({ query: async (sql) => {
    if (sql.includes('FROM indexed_supply')) return { rows: row ? [row] : [] };
    return { rows: [] };
  }});
  const res = createResponse();
  await handleApiRequest(createRequest(route), res);
  assert.equal(res.statusCode, 200);
  const body = jsonResult(res);
  return route === '/v1/observatory' ? body.supply : body;
}

function assertSupplyBound(body) {
  if (body.circulating !== undefined && body.total_minted !== undefined && body.total_burned !== undefined) {
    assert.ok(BigInt(body.circulating) <= BigInt(body.total_minted) - BigInt(body.total_burned));
  }
}

test('retained live projection abstains from contradictory counters on both supply routes', async () => {
  for (const route of ['/v1/supply', '/v1/observatory']) {
    const body = await supplyResponse(liveSupply, route);
    assertSupplyBound(body);
    assert.equal(body.circulating, liveSupply.spl_mint_supply);
    assert.equal(Object.hasOwn(body, 'total_minted'), false);
    assert.equal(Object.hasOwn(body, 'total_burned'), false);
  }
});

test('unindexed supply figures are absent, never zero or legacy circulation', async () => {
  for (const row of [
    { circulating: '999' },
    { total_minted: '0', total_burned: '0', spl_mint_supply: '0' },
    { ...liveSupply, total_minted: null, total_burned: null, spl_mint_supply: null },
  ]) {
    const body = await supplyResponse(row);
    for (const key of ['total_minted', 'total_burned', 'circulating', 'spl_mint_supply']) {
      assert.equal(Object.hasOwn(body, key), false, key);
    }
  }
});

test('indexed counters retain exact integers and protocol burns permit holder burns', async () => {
  for (const [minted, burned, circulating] of [
    ['100', '5', '95'], ['100', '5', '91'], ['0', '0', '0'],
    ['18446744073709551615', '5', '18446744073709551610'],
  ]) {
    const body = await supplyResponse({ ...liveSupply, total_minted: minted, total_burned: burned, spl_mint_supply: circulating });
    assertSupplyBound(body);
    assert.equal(body.total_minted, minted);
    assert.equal(body.total_burned, burned);
    assert.equal(body.circulating, circulating);
  }
});

test('invalid counters abstain without changing canonical supply', async () => {
  for (const value of [null, '-1', '1.5', 'invalid', '18446744073709551616']) {
    const body = await supplyResponse({ ...liveSupply, total_minted: value });
    assert.equal(Object.hasOwn(body, 'total_minted'), false);
    assert.equal(body.circulating, liveSupply.spl_mint_supply);
  }
});

test('Observatory counts registry Climbs without requiring active economics and every event link resolves', async () => {
  const indexed = [{ id: CANON_CLIMB_ID, version: 1, status: 'ratified', display_name: 'Registered hill', vault_id: null }];
  setApiRuntimeForTests({ query: async (sql, params) => {
    if (sql.includes('observatory:ground') || sql.includes('observatory:clock')) return { rows: [] };
    if (sql.includes('COUNT(*) AS total')) {
      assert.match(sql, /FROM public\.indexed_climbs/);
      assert.doesNotMatch(sql, /vault\.id IS NOT NULL/);
      return { rows: [{ total: String(indexed.length) }] };
    }
    if (sql.includes('AS total_riders')) return { rows: [] };
    if (sql.includes('FROM indexed_supply')) return { rows: [] };
    if (sql.includes('FROM indexed_events')) return { rows: [
      { event_name: 'VaultCreated', fields: { id: 0 }, slot: '1' },
      { event_name: 'ClimbRegistered', fields: { climb: VALID_PUBKEY }, slot: '2' },
      { event_name: 'VaultCreated', fields: { id: 999 }, slot: '3' },
    ] };
    if (sql.includes('AS climb_references')) return { rows: [{ id: CANON_CLIMB_ID, pda: VALID_PUBKEY, vault_id: '0' }] };
    if (sql.includes('ORDER BY COALESCE')) return { rows: [] };
    if (sql.includes('WHERE canon.id = $1::uuid')) return { rows: indexed.filter(row => row.id === params[0]) };
    throw new Error(`Unexpected query: ${sql}`);
  } });
  const res = createResponse();
  await handleApiRequest(createRequest('/v1/observatory'), res);
  assert.equal(res.statusCode, 200);
  const body = jsonResult(res);
  assert.equal(body.vault_count, indexed.length);
  assert.equal(body.recent_events[0].climb_id, CANON_CLIMB_ID);
  assert.equal(body.recent_events[1].climb_id, CANON_CLIMB_ID);
  assert.equal(Object.hasOwn(body.recent_events[2], 'climb_id'), false);
  for (const event of body.recent_events.filter(e => e.climb_id)) {
    const detail = createResponse();
    await handleApiRequest(createRequest(`/v1/climbs/${event.climb_id}`), detail);
    assert.equal(detail.statusCode, 200);
    assert.equal(jsonResult(detail).climb.id, event.climb_id);
  }
});

test('numeric Vault zero resolves only through an exact registry binding', async () => {
  let bound = true;
  setApiRuntimeForTests({ query: async (sql, params) => {
    if (sql.includes('AS climb_references')) {
      assert.deepEqual(params, [[], ['0']]);
      return { rows: bound ? [{ id: CANON_CLIMB_ID, vault_id: '0' }] : [] };
    }
    if (sql.includes('WHERE canon.id = $1::uuid')) return { rows: [{ id: CANON_CLIMB_ID, version: 1, status: 'ratified', vault_id: null }] };
    throw new Error(`Unexpected query: ${sql}`);
  } });
  const res = createResponse();
  await handleApiRequest(createRequest('/v1/climbs/0'), res);
  assert.equal(res.statusCode, 200);
  assert.equal(jsonResult(res).climb.id, CANON_CLIMB_ID);
  bound = false;
  const missing = createResponse();
  await handleApiRequest(createRequest('/v1/climbs/0'), missing);
  assert.equal(missing.statusCode, 404);
});
