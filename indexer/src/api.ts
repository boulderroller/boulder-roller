import { buildTransactionReceipt } from './transaction-receipt';
import { buildAccountPageData } from './account-page-data';
import { buildClimbPageData } from './climb-page-data';
import http from 'http';
import url from 'url';
import { Connection, PublicKey } from '@solana/web3.js';
import { config } from './config';
import { MAX_DUNG_SUPPLY_STALE_MS } from './supply-refresh';
import { requireIndexerProgramCompatibility } from './program-compatibility';
import { isStage1Instruction, programVersionWindow, STAGE1_UNAVAILABLE } from './program-version-window';
import { PRIVATE_STAGE1_INSTRUCTIONS, privatePayPredicate } from './program-visibility';
import { visibleEvents, legacyTransactionPredicate, eventVisibilitySql } from './program-visibility';
import { query } from './db';
import { decodeExplorerEvents } from './explorer-events';
import { attestedNumber, attestedAtomic, projectGround, projectIndexed, projectWeekClock, projectDisplayEvent } from './observatory';

/**
 * BoulderScan public read API.
 *
 * All endpoints are read-only, public (no auth), and return JSON.
 * Wired into the health server for paths starting with /v1/.
 */

// CAL and DUNG are both classic SPL Token; Token-2022 is never returned
// and querying it doubled the RPC cost per profile view for zero benefit.
const TOKEN_PROGRAM_IDS = [
  new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'),
];

type SplBalances = { cal: string | null; dung: string | null; token_accounts?: Array<{account: string; symbol: string; amount: string}> };
type ApiFreshnessStatus = 'live' | 'catching_up' | 'stale' | 'unknown';
type ApiFreshness = {
  contract_version: 'scan_freshness.v1';
  source: 'indexer';
  status: ApiFreshnessStatus;
  read_model: string;
  tables: string[];
  account_slot: number;
  tx_slot: number;
  max_observed_slot: number;
  last_account_sync_at: unknown;
  last_tx_sync_at: unknown;
  stream_connected: boolean;
  loaded_at: string;
};
const SPL_BALANCE_CACHE_TTL_MS = 30_000;
const SPL_BALANCE_CACHE_MAX = 1000;
const API_SYNC_STALE_MS = Math.max(config.pollIntervalMs * 3, 15 * 60 * 1000);
const splBalanceCache = new Map<string, { expiresAt: number; value: SplBalances }>();
const ACCOUNT_DETAIL_RATE_LIMIT_WINDOW_MS = 60_000;
const ACCOUNT_DETAIL_RATE_LIMIT_MAX = 60;
const accountDetailRateBuckets = new Map<string, { resetAt: number; count: number }>();

function getCachedSplBalances(key: string): SplBalances | null {
  const entry = splBalanceCache.get(key);
  if (!entry) return null;
  if (entry.expiresAt <= Date.now()) {
    splBalanceCache.delete(key);
    return null;
  }
  // Refresh LRU position: Map iteration is insertion order.
  splBalanceCache.delete(key);
  splBalanceCache.set(key, entry);
  return entry.value;
}

function setCachedSplBalances(key: string, value: SplBalances): void {
  if (splBalanceCache.size >= SPL_BALANCE_CACHE_MAX) {
    const oldest = splBalanceCache.keys().next().value;
    if (oldest !== undefined) splBalanceCache.delete(oldest);
  }
  splBalanceCache.set(key, { expiresAt: Date.now() + SPL_BALANCE_CACHE_TTL_MS, value });
}

function firstHeaderValue(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

function getClientRateLimitKey(req: http.IncomingMessage): string {
  const headers = req.headers || {};
  const forwardedFor = firstHeaderValue(headers['x-forwarded-for']);
  const realIp = firstHeaderValue(headers['x-real-ip']);
  const clientIp = (forwardedFor?.split(',')[0] || realIp || req.socket?.remoteAddress || 'unknown').trim();
  return clientIp || 'unknown';
}

function accountDetailRateLimitAllows(req: http.IncomingMessage): { allowed: boolean; retryAfter: number } {
  const key = getClientRateLimitKey(req);
  const now = Date.now();
  const current = accountDetailRateBuckets.get(key);
  if (!current || current.resetAt <= now) {
    accountDetailRateBuckets.set(key, {
      resetAt: now + ACCOUNT_DETAIL_RATE_LIMIT_WINDOW_MS,
      count: 1,
    });
    return { allowed: true, retryAfter: 0 };
  }

  current.count += 1;
  if (current.count <= ACCOUNT_DETAIL_RATE_LIMIT_MAX) {
    return { allowed: true, retryAfter: 0 };
  }
  return {
    allowed: false,
    retryAfter: Math.max(1, Math.ceil((current.resetAt - now) / 1000)),
  };
}

let rpcConnection: Connection | null = null;
type QueryFn = typeof query;
type ApiRuntime = {
  query: QueryFn;
  getRpcConnection: () => Connection;
};

const LEGACY_SYNTHETIX_VAULT_FIELDS = [
  'reward_per_token_stored',
  'last_update_time',
  'reward_rate',
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Clamp limit to [1, 100], default 20. */
function parseLimit(raw: string | undefined | null): number {
  const n = parseInt(raw || '20', 10);
  if (isNaN(n) || n < 1) return 20;
  return Math.min(n, 100);
}

/** Clamp offset to >= 0, default 0. */
function parseOffset(raw: string | undefined | null): number {
  const n = parseInt(raw || '0', 10);
  if (isNaN(n) || n < 0) return 0;
  return n;
}

/** Validate that a string looks like a base58 Solana pubkey (32-44 chars, alphanumeric). */
function isValidPubkey(s: string): boolean {
  return /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(s);
}

/** Validate that a string looks like a base58 transaction signature (80-90 chars). */
function isValidSignature(s: string): boolean {
  return /^[1-9A-HJ-NP-Za-km-z]{43,90}$/.test(s);
}

/** Validate that a string is a 32-byte hex digest. */
function isValidHex32(s: string): boolean {
  return /^[0-9a-f]{64}$/i.test(s);
}

function isValidUuid(s: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(s);
}

/** Validate that a string looks like a public Boulder Rollers username. */
function isValidUsername(s: string): boolean {
  return /^[a-z0-9_]{3,20}$/i.test(s);
}

/** Send a JSON response. */
function json(res: http.ServerResponse, statusCode: number, body: unknown): void {
  res.writeHead(statusCode, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

function getRpcConnection(): Connection {
  if (!rpcConnection) {
    rpcConnection = new Connection(config.rpcUrl, 'confirmed');
  }
  return rpcConnection;
}

const defaultRuntime: ApiRuntime = {
  query,
  getRpcConnection,
};

let runtime: ApiRuntime = defaultRuntime;

export function setApiRuntimeForTests(overrides: Partial<ApiRuntime>): void {
  runtime = {
    ...runtime,
    ...overrides,
  };
}

export function resetApiRuntimeForTests(): void {
  runtime = defaultRuntime;
  accountDetailRateBuckets.clear();
}

function parseCount(value: unknown): number {
  const parsed = parseInt(String(value ?? '0'), 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

function parseSlot(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function timestampIsRecent(value: unknown, now: Date, maxAgeMs: number): boolean {
  if (!value) return false;
  const timestamp = new Date(value as any).getTime();
  return Number.isFinite(timestamp) && now.getTime() - timestamp <= maxAgeMs;
}

async function buildApiFreshness(
  readModel: string,
  tables: string[]
): Promise<ApiFreshness> {
  const now = new Date();

  try {
    const result = await runtime.query('SELECT * FROM indexer_sync_state WHERE id = 1');
    const state = result.rows[0] ?? null;
    const accountSlot = parseSlot(state?.last_account_slot);
    const txSlot = parseSlot(state?.last_tx_slot);
    const streamConnected = state?.stream_connected === true;
    const accountRecent =
      streamConnected || timestampIsRecent(state?.last_account_sync_at, now, API_SYNC_STALE_MS);
    const txRecent = timestampIsRecent(state?.last_tx_sync_at, now, API_SYNC_STALE_MS);
    const status: ApiFreshnessStatus = !state
      ? 'unknown'
      : accountRecent && txRecent
        ? 'live'
        : accountRecent || txRecent || streamConnected
          ? 'catching_up'
          : 'stale';

    return {
      contract_version: 'scan_freshness.v1',
      source: 'indexer',
      status,
      read_model: readModel,
      tables,
      account_slot: accountSlot,
      tx_slot: txSlot,
      max_observed_slot: Math.max(accountSlot, txSlot),
      last_account_sync_at: state?.last_account_sync_at ?? null,
      last_tx_sync_at: state?.last_tx_sync_at ?? null,
      stream_connected: streamConnected,
      loaded_at: now.toISOString(),
    };
  } catch {
    return {
      contract_version: 'scan_freshness.v1',
      source: 'indexer',
      status: 'unknown',
      read_model: readModel,
      tables,
      account_slot: 0,
      tx_slot: 0,
      max_observed_slot: 0,
      last_account_sync_at: null,
      last_tx_sync_at: null,
      stream_connected: false,
      loaded_at: now.toISOString(),
    };
  }
}

function parseBoolean(value: unknown): boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value !== 0;
  const normalized = String(value).trim().toLowerCase();
  if (!normalized) return null;
  if (['true', 't', '1', 'yes'].includes(normalized)) return true;
  if (['false', 'f', '0', 'no'].includes(normalized)) return false;
  return null;
}

function mapCardType(cardType: number): string {
  switch (cardType) {
    case 0:
      return 'climb';
    case 1:
      return 'steady';
    case 2:
      return 'explorer';
    default:
      return String(cardType);
  }
}

function isZeroHex(hex: string | null | undefined): boolean {
  return !!hex && /^0+$/.test(hex);
}

function parseBigInt(value: unknown): bigint {
  try {
    return BigInt(String(value ?? '0'));
  } catch {
    return 0n;
  }
}

function serializeSupplyRow(row: Record<string, any> | null): Record<string, any> | null {
  if (!row) return null;

  const u64 = (value: unknown): string | undefined => {
    if (typeof value !== 'string' || !/^\d+$/.test(value)) return undefined;
    return BigInt(value) <= (1n << 64n) - 1n ? value : undefined;
  };
  const observed = (slot: unknown, timestamp: unknown): boolean => (
    slot != null && /^\d+$/.test(String(slot))
    && Number.isSafeInteger(Number(slot))
    && timestamp != null && Number.isFinite(new Date(String(timestamp)).getTime())
  );
  const projected = { ...row };
  // Never leak default counters or the legacy derived circulation through the
  // row spread. These figures require their own indexed account provenance.
  for (const key of ['total_minted', 'total_burned', 'circulating', 'spl_mint_supply']) {
    delete projected[key];
  }
  const circulating = observed(row.spl_mint_supply_slot, row.spl_mint_supply_indexed_at)
    ? u64(row.spl_mint_supply) : undefined;
  const countersIndexed = Boolean(row.pda) && observed(row.chain_slot, row.indexed_at);
  const minted = countersIndexed ? u64(row.total_minted) : undefined;
  const burned = countersIndexed ? u64(row.total_burned) : undefined;
  // DungMintState counts program activity, not necessarily the mint's complete
  // history. Contradictory counters cannot attest lifetime minted/burned totals.
  // Protocol burns exclude holder SPL burns, so equality is not required.
  if (minted !== undefined && burned !== undefined
      && BigInt(minted) >= BigInt(burned)
      && (circulating === undefined || BigInt(circulating) <= BigInt(minted) - BigInt(burned))) {
    projected.total_minted = minted;
    projected.total_burned = burned;
  }
  if (circulating !== undefined) {
    projected.circulating = circulating;
    projected.spl_mint_supply = circulating;
  }

  return {
    ...projected,
    community_reserved: String(row.community_reserved ?? '0'),
    reservation_policy_version: Number(row.reservation_policy_version ?? 0),
    circulating_source: circulating === undefined ? 'unavailable' : 'spl_mint_supply',
    spl_mint_supply_max_stale_ms: MAX_DUNG_SUPPLY_STALE_MS,
    spl_mint_supply_refresh_interval_ms: config.dungSupplyRefreshIntervalMs,
  };
}

function serializeBeetleCard(row: Record<string, any>): Record<string, any> {
  return {
    card_type: mapCardType(Number(row.card_type)),
    scope: isZeroHex(row.scope_id_hex) ? 'global' : 'scoped',
    scope_id_hex: row.scope_id_hex,
    score: row.score,
    level: row.level,
    rides_counted: row.patterns_scored,
    total_dung_burned: row.total_dung_burned,
    created_at: row.created_at,
  };
}

function serializeInstructionRow(row: Record<string, any>): Record<string, any> {
  return {
    instruction_index: row.instruction_index,
    name: row.instruction_name,
    args: row.instruction_args,
    accounts: row.instruction_accounts,
  };
}

function serializeEventRow(row: Record<string, any>): Record<string, any> {
  return {
    tx_signature: row.tx_signature,
    event_index: row.event_index,
    event_name: row.event_name,
    fields: row.fields,
    slot: row.slot,
    block_time: row.block_time,
  };
}

type TokenFlowDirection = 'positive' | 'negative' | 'neutral';

type TokenFlow = {
  amount: string;
  raw_amount: string;
  symbol: string;
  direction: TokenFlowDirection;
  target: string;
  source: 'event';
  label: string | null;
  owner?: string | null;
  origin?: string | null;
};

function readEventField(
  fields: Record<string, any>,
  ...keys: string[]
): unknown {
  for (const key of keys) {
    const value = fields[key];
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return null;
}

function positiveAtomicAmount(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  const raw = String(value);
  return parseBigInt(raw) > 0n ? raw : null;
}

function targetFromAccount(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function vaultTarget(fields: Record<string, any>): string {
  const vaultId = readEventField(fields, 'vaultId', 'vault_id', 'id');
  return vaultId !== null ? `Climb #${vaultId}` : 'climb';
}

function pushEventTokenFlow(
  flows: TokenFlow[],
  rawAmount: unknown,
  symbol: string,
  direction: TokenFlowDirection,
  target: string,
  label: string | null,
  owner?: unknown,
  origin?: string | null
): void {
  const amount = positiveAtomicAmount(rawAmount);
  if (!amount) return;

  flows.push({
    amount,
    raw_amount: amount,
    symbol,
    direction,
    target,
    source: 'event',
    label,
    owner: typeof owner === 'string' ? owner : null,
    origin: origin ?? null,
  });
}

function settlementPolicyKey(fields: Record<string, any>): string | null {
  const vaultId = readEventField(fields, 'vaultId', 'vault_id');
  const settlementWeek = readEventField(
    fields,
    'settlementWeek',
    'settlement_week',
    'epoch'
  );
  if (vaultId === undefined || vaultId === null || settlementWeek === undefined || settlementWeek === null) {
    return null;
  }
  return `${String(vaultId)}:${String(settlementWeek)}`;
}

export function deriveEventTokenFlows(events: Record<string, any>[]): TokenFlow[] {
  const flows: TokenFlow[] = [];
  const sameWeekPolicySettlements = new Set(
    events
      .filter((event) => event.event_name === 'StakerRemainderPolicyApplied')
      .map((event) => settlementPolicyKey(
        event.fields && typeof event.fields === 'object' ? event.fields : {}
      ))
      .filter((key): key is string => key !== null)
  );

  for (const event of events) {
    const fields = event.fields && typeof event.fields === 'object' ? event.fields : {};

    switch (event.event_name) {
      case 'CalCredited':
      case 'ReleasedCalCredited':
      case 'RideAttestationRecorded': {
        const rider = readEventField(fields, 'rider', 'user');
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'amount', 'calEarned', 'cal_earned'),
          'CAL',
          'positive',
          targetFromAccount(rider, 'rider'),
          'Ride CAL earned',
          rider
        );
        break;
      }

      case 'CalTributed':
      case 'VaultCompleted':
      case 'VaultCompletedV2':
      case 'ReleasedVaultCompleted': {
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'calTributed', 'cal_tributed', 'cal_tribute', 'amount'),
          'CAL',
          'positive',
          vaultTarget(fields),
          'Climb CAL tribute'
        );
        break;
      }

      case 'CalStaked': {
        const staker = readEventField(fields, 'staker');
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'amount'),
          'CAL',
          'positive',
          vaultTarget(fields),
          'CAL staked'
        );
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'lpMinted', 'lp_minted'),
          'LP',
          'positive',
          targetFromAccount(staker, 'staker'),
          'LP minted',
          staker
        );
        break;
      }

      case 'CalUnstaked': {
        const staker = readEventField(fields, 'staker');
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'calReturned', 'cal_returned'),
          'CAL',
          'positive',
          targetFromAccount(staker, 'staker'),
          'CAL returned',
          staker
        );
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'lpBurned', 'lp_burned'),
          'LP',
          'negative',
          targetFromAccount(staker, 'staker'),
          'LP burned',
          staker
        );
        break;
      }

      case 'StakerRemainderPolicyApplied': {
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'legacyCarryReallocated', 'legacy_carry_reallocated'),
          'DUNG',
          'neutral',
          'Leaderboard pool',
          'Balance sweep',
          undefined,
          'Prior staker balance'
        );
        break;
      }

      case 'EpochRewardsDistributed': {
        const bucketFlows: Array<[string, string[], string | null]> = [
          ['Leaderboard', ['leaderboardDistributed', 'leaderboard_distributed'], null],
          ['Stakers', ['stakerDistributed', 'staker_distributed'], null],
          ['Local Legend', ['localLegendDistributed', 'local_legend_distributed'], null],
          ['POL', ['polDistributed', 'pol_distributed'], null],
          ['Protocol Treasury', ['protocolDistributed', 'protocol_distributed'], null],
        ];

        for (const [target, fieldNames, label] of bucketFlows) {
          pushEventTokenFlow(
            flows,
            readEventField(fields, ...fieldNames),
            'DUNG',
            'positive',
            target,
            label
          );
        }

        const usesSameWeekPolicy = sameWeekPolicySettlements.has(
          settlementPolicyKey(fields) ?? ''
        );
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'lockedStakerAmount', 'locked_staker_amount'),
          'DUNG',
          'neutral',
          usesSameWeekPolicy ? 'Leaderboard pool' : 'Prior staker balance',
          null,
          undefined,
          'Staker allocation'
        );
        break;
      }

      case 'RewardsHarvested': {
        const staker = readEventField(fields, 'staker');
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'dungReceived', 'dung_received'),
          'DUNG',
          'positive',
          targetFromAccount(staker, 'staker'),
          'Harvest received',
          staker
        );
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'harvestFee', 'harvest_fee'),
          'DUNG',
          'positive',
          'Protocol Treasury',
          'Harvest fee'
        );
        break;
      }

      case 'StakerAllocation': {
        const staker = readEventField(fields, 'staker');
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'amount'),
          'DUNG',
          'positive',
          targetFromAccount(staker, 'staker'),
          'Staker allocation',
          staker
        );
        break;
      }

      case 'DungMinted': {
        const recipient = readEventField(fields, 'recipient');
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'amount'),
          'DUNG',
          'positive',
          targetFromAccount(recipient, 'recipient'),
          'DUNG minted',
          recipient
        );
        break;
      }

      case 'DungBurned': {
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'amount'),
          'DUNG',
          'negative',
          'burned',
          'DUNG burned'
        );
        break;
      }

      case 'VaultAllocClaimed': {
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'calAmount', 'cal_amount'),
          'CAL',
          'positive',
          vaultTarget(fields),
          'Tribute allocation claimed'
        );
        pushEventTokenFlow(
          flows,
          readEventField(fields, 'dungConverted', 'dung_converted'),
          'DUNG',
          'positive',
          'climb rewards',
          'Tribute converted to DUNG'
        );
        break;
      }
    }
  }

  return flows;
}

function serializeEpochDistributionRow(row: Record<string, any>): Record<string, any> {
  return {
    tx_signature: row.tx_signature,
    event_index: row.event_index,
    event_name: 'EpochRewardsDistributed',
    fields: {
      vault_id: row.vault_id,
      epoch: row.epoch,
      total_distributed: row.total_distributed,
      leaderboard_distributed: row.leaderboard_distributed,
      staker_distributed: row.staker_distributed,
      local_legend_distributed: row.local_legend_distributed,
      pol_distributed: row.pol_distributed,
      protocol_distributed: row.protocol_distributed,
      staker_count: row.staker_count,
      unlock_pct: row.unlock_pct,
      locked_staker_amount: row.locked_staker_amount,
    },
    slot: row.slot,
    block_time: row.block_time,
  };
}

function serializeUserStateRow(row: Record<string, any>): Record<string, any> {
  return {
    owner_pubkey: row.owner_pubkey,
    legacy_cal_snapshot: row.cal_balance,
    legacy_cal_earned_today: row.cal_earned_today,
    legacy_last_cal_mint: row.last_cal_mint,
    total_rides: row.total_rides,
    total_tss: row.total_tss,
    bio_score: row.bio_score,
  };
}

function sourceKindLabel(sourceKind: number): string {
  switch (sourceKind) {
    case 1:
      return 'fit';
    case 2:
      return 'gpx';
    case 3:
      return 'tcx';
    default:
      return 'unknown';
  }
}

function serializeRiderSoulRow(row: Record<string, any>): Record<string, any> {
  return {
    rider_pubkey: row.rider_pubkey,
    created_at: row.created_at,
    total_rides: row.total_rides,
    total_tss: row.total_tss,
    total_distance_m: row.total_distance_m,
    total_vert_m: row.total_vert_m,
    total_cal_earned: row.total_cal_earned,
    archetype: row.archetype,
    bio_score: row.bio_score,
    climb_card: row.climb_card,
    steady_card: row.steady_card,
    explorer_card: row.explorer_card,
  };
}

function serializeRideAttestationRow(row: Record<string, any>): Record<string, any> {
  const sourceKind = Number(row.source_kind ?? 0);
  return {
    rider_pubkey: row.rider_pubkey,
    ride_hash_hex: row.ride_hash_hex,
    attestation_commitment_hex: row.attestation_commitment_hex,
    parser_version: row.parser_version,
    source_kind: sourceKind,
    source_kind_label: sourceKindLabel(sourceKind),
    completed_at: row.completed_at,
    started_at: row.started_at,
    total_tss: row.total_tss,
    total_distance_m: row.total_distance_m,
    total_vert_m: row.total_vert_m,
    cal_earned: row.cal_earned,
    climbs_crossed: row.climbs_crossed,
    attester: row.attester,
    settled_at: row.settled_at,
    settled_slot: row.settled_slot,
    economic_epoch: row.economic_epoch,
    finalized: parseBoolean(row.finalized) ?? false,
    pda: row.pda,
  };
}

function hasActivationProjection(row: Record<string, any>): boolean {
  return [
    row.activation_pda,
    row.activation_is_active,
    row.activation_seed_completions_written,
    row.activation_leaderboard_seeded,
    row.activation_created_at,
    row.activation_activated_at,
    row.activation_last_seed_at,
    row.activation_seed_generation,
    row.activation_seed_cutoff_at,
    row.activation_economics_start_epoch,
    row.activation_matched_users,
    row.activation_matched_completions,
    row.activation_evidence_hash,
  ].some((value) => value !== null && value !== undefined);
}

function deriveActivationStatus(row: Record<string, any>): string | null {
  if (hasActivationProjection(row)) {
    if (parseBoolean(row.activation_is_active)) {
      return 'active';
    }

    if (
      parseCount(row.activation_seed_completions_written) > 0
      || parseBoolean(row.activation_leaderboard_seeded)
      || parseBigInt(row.activation_last_seed_at) > 0n
    ) {
      return 'seeded';
    }

    return 'pending';
  }

  const mirrored = typeof row.on_chain_seeding_status === 'string'
    ? row.on_chain_seeding_status.trim()
    : '';
  return mirrored || null;
}

function serializeVaultRow(row: Record<string, any>): Record<string, any> {
  const publicRow = { ...row };
  for (const field of LEGACY_SYNTHETIX_VAULT_FIELDS) {
    delete publicRow[field];
  }

  return {
    ...publicRow,
    activation_status: deriveActivationStatus(row),
    activation_is_active: parseBoolean(row.activation_is_active),
    activation_leaderboard_seeded: parseBoolean(row.activation_leaderboard_seeded),
  };
}

function serializeLegendRow(row: Record<string, any> | null | undefined): Record<string, any> | null {
  if (!row) return null;

  const isActive = parseBoolean(row.is_active) === true;
  const explicitBootstrap = parseBoolean(row.is_bootstrap);
  const isBootstrap =
    explicitBootstrap === null
      ? parseCount(row.election_period) === 0 && parseCount(row.completions_at_election) === 0
      : explicitBootstrap;

  return {
    ...row,
    is_active: isActive,
    is_bootstrap: isBootstrap,
    seat_status: isActive ? (isBootstrap ? 'bootstrap' : 'elected') : 'inactive',
  };
}

async function fetchSplBalances(
  ownerPubkey: string,
  calMint: string | null,
  dungMint: string | null
): Promise<SplBalances> {
  if (!calMint && !dungMint) {
    return { cal: null, dung: null };
  }

  const cacheKey = `${ownerPubkey}|${calMint ?? ''}|${dungMint ?? ''}`;
  const cached = getCachedSplBalances(cacheKey);
  if (cached) return cached;

  try {
    const owner = new PublicKey(ownerPubkey);
    const connection = runtime.getRpcConnection();
    const responses = await Promise.all(
      TOKEN_PROGRAM_IDS.map((programId) =>
        connection.getParsedTokenAccountsByOwner(owner, { programId }, 'confirmed')
      )
    );

    const totals = new Map<string, bigint>();
    const token_accounts: NonNullable<SplBalances["token_accounts"]> = [];

    for (const response of responses) {
      for (const tokenAccount of response.value) {
        const parsedInfo = (tokenAccount.account.data as any)?.parsed?.info;
        const mint = parsedInfo?.mint as string | undefined;
        const amount = parsedInfo?.tokenAmount?.amount as string | undefined;
        if (!mint || !amount) continue;
        totals.set(mint, (totals.get(mint) || 0n) + BigInt(amount));
        if ((mint === calMint || mint === dungMint) && tokenAccount.pubkey && BigInt(amount) > 0n) token_accounts.push({account: tokenAccount.pubkey.toString(), symbol: mint === calMint ? "CAL" : "DUNG", amount});
      }
    }

    const result: SplBalances = {
      token_accounts,
      cal: calMint ? (totals.get(calMint)?.toString() ?? '0') : null,
      dung: dungMint ? (totals.get(dungMint)?.toString() ?? '0') : null,
    };
    setCachedSplBalances(cacheKey, result);
    return result;
  } catch (err) {
    console.warn(`[API] Failed to fetch SPL balances for ${ownerPubkey}:`, err);
    return { cal: null, dung: null };
  }
}

// ---------------------------------------------------------------------------
// Vault sort column allowlist
// ---------------------------------------------------------------------------

const VAULT_SORT_COLUMNS: Record<string, string> = {
  staked: 'total_cal_staked',
  completions: 'total_completions',
  created: 'created_at',
};

type ClimbSurface = 'vault' | 'climb';

const CANON_CLIMB_SORT_COLUMNS: Record<string, string> = {
  staked: 'COALESCE(vault.total_cal_staked, 0)',
  completions: 'COALESCE(vault.total_completions, 0)',
  created: 'canon.created_at',
};

const CANON_CLIMB_SELECT = `
  SELECT canon.id::text AS id, canon.canon_id::text AS canon_id,
         canon.version, canon.status, canon.display_name, canon.route_name,
         canon.length_m, canon.vert_m, canon.avg_gradient_pct,
         canon.worthiness_score, canon.canonical_profile, canon.created_at,
         indexed.pda AS climb_pda,
         vault.id AS vault_id, vault.pda AS vault_pda,
         vault.signature_hex AS vault_signature,
         vault.minter AS vault_minter,
         vault.created_at AS vault_created_at,
         vault.total_completions, vault.total_cal_staked,
         vault.staker_count, vault.kom_holder, vault.kom_time_s
  FROM public.canon_climbs AS canon
  LEFT JOIN public.indexed_climbs AS indexed
    ON indexed.canon_climb_id = canon.id
   AND indexed.quarantined IS FALSE
   AND indexed.successor_climb_pda IS NULL
  LEFT JOIN LATERAL (
    SELECT candidate.*
    FROM public.indexed_vaults AS candidate
    JOIN public.canon_vault_activations AS operational
      ON operational.canon_climb_id = canon.id
     AND operational.climb_pda = indexed.pda
     AND operational.vault_id = candidate.id
     AND operational.vault_pda = candidate.pda
     AND operational.activation_status = 'finalized'
     AND operational.constructor_evidence_verified IS TRUE
    JOIN public.indexed_vault_activations AS activation
      ON activation.vault_id = candidate.id
     AND activation.pda = operational.vault_activation_pda
     AND activation.is_active IS TRUE
     AND activation.seed_generation = 2
     AND activation.seed_completions_written = 0
     AND activation.leaderboard_seeded IS TRUE
     AND activation.matched_users = 0
     AND activation.matched_completions = 0
     AND activation.created_at > 0
     AND activation.created_at = activation.activated_at
     AND activation.created_at = activation.last_seed_at
     AND activation.created_at = activation.seed_cutoff_at
     AND lower(btrim(activation.evidence_hash::text))
           = operational.constructor_evidence_hash
    WHERE candidate.canon_climb_id = canon.id
      AND candidate.climb_pda = indexed.pda
      AND indexed.vault_pda = candidate.pda
      AND candidate.canon_commitment_hex = indexed.canon_commitment_hex
      AND candidate.canon_binding_status = 'active'
    LIMIT 1
  ) AS vault ON TRUE`;

function serializeCanonClimbRow(row: Record<string, any>): Record<string, any> {
  const vaultId = row.vault_id == null ? null : Number(row.vault_id);
  return {
    contract_version: 'client.v1',
    truth_source: 'projected',
    id: String(row.id),
    canon_id: row.canon_id == null ? null : String(row.canon_id),
    version: Number(row.version),
    revision_state: row.status === 'retired' ? 'retired' : 'current',
    name: row.display_name,
    route_name: row.route_name ?? null,
    length_m: row.length_m == null ? null : Number(row.length_m),
    elev_gain_m: row.vert_m == null ? null : Number(row.vert_m),
    avg_gradient_pct:
      row.avg_gradient_pct == null ? null : Number(row.avg_gradient_pct),
    worthiness_score:
      row.worthiness_score == null ? null : Number(row.worthiness_score),
    canonical_profile: row.canonical_profile ?? [],
    climb_pda: row.climb_pda ?? null,
    has_vault: vaultId !== null,
    vault_id: vaultId,
    vault_pda: row.vault_pda ?? null,
    vault_signature: row.vault_signature ?? null,
    total_completions: parseCount(row.total_completions),
    total_cal_staked: String(row.total_cal_staked ?? '0'),
    staker_count: parseCount(row.staker_count),
    kom_holder: row.kom_holder ?? null,
    kom_time_s: row.kom_time_s == null ? null : Number(row.kom_time_s),
    created_at: row.created_at ?? null,
  };
}

const ACTIVE_CANON_CLIMB_SELECT = `${CANON_CLIMB_SELECT}
  WHERE canon.status = 'ratified'
    AND vault.id IS NOT NULL`;

function serializeObservatoryClimbRow(
  row: Record<string, any>
): Record<string, any> {
  const climb = serializeCanonClimbRow(row);
  return {
    contract_version: climb.contract_version,
    truth_source: climb.truth_source,
    id: climb.id,
    canon_id: climb.canon_id,
    version: climb.version,
    name: climb.name,
    signature_hex: row.vault_signature ?? null,
    minter: row.vault_minter ?? null,
    vert_m: row.vert_m == null ? null : Math.round(Number(row.vert_m) * 10),
    distance_m:
      row.length_m == null ? null : Math.round(Number(row.length_m)),
    avg_gradient_pct:
      row.avg_gradient_pct == null
        ? null
        : Math.round(Number(row.avg_gradient_pct) * 100),
    total_completions: climb.total_completions,
    total_cal_staked: climb.total_cal_staked,
    staker_count: climb.staker_count,
    kom_holder: climb.kom_holder,
    kom_time_s: climb.kom_time_s,
    created_at: row.vault_created_at ?? row.created_at ?? null,
    activation_status: 'active',
    activation_is_active: true,
    vault_id: climb.vault_id,
    vault_pda: climb.vault_pda,
    climb_pda: climb.climb_pda,
  };
}

function withoutCanonVaultEconomy(climb: Record<string, any>): Record<string, any> {
  return {
    ...climb,
    has_vault: false,
    vault_id: null,
    vault_pda: null,
    vault_signature: null,
    total_completions: 0,
    total_cal_staked: '0',
    staker_count: 0,
    kom_holder: null,
    kom_time_s: null,
  };
}

// ---------------------------------------------------------------------------
// Route handlers
// ---------------------------------------------------------------------------

// Registry identity is independent of Vault economic activation. Retired versions
// remain addressable; quarantined accounts cannot attest a public Climb.
const INDEXED_CLIMB_REGISTRY = `
  FROM public.indexed_climbs AS registry
  JOIN public.canon_climbs AS canon ON canon.id = registry.canon_climb_id
  WHERE registry.quarantined IS FALSE
    AND canon.status IN ('ratified', 'retired')`;

async function resolveClimbReferences(pdas: string[], vaultIds: string[]) {
  if (!pdas.length && !vaultIds.length) return [];
  const result = await runtime.query(
    `SELECT * FROM (
       SELECT canon.id::text AS id, canon.display_name AS name, canon.length_m, registry.pda, bound.id::text AS vault_id
       FROM public.indexed_climbs AS registry
       JOIN public.canon_climbs AS canon ON canon.id = registry.canon_climb_id
       LEFT JOIN public.indexed_vaults AS bound
         ON bound.climb_pda = registry.pda
        AND bound.pda = registry.vault_pda
        AND bound.canon_climb_id = canon.id
        AND bound.canon_commitment_hex = registry.canon_commitment_hex
        AND bound.canon_binding_status = 'active'
       WHERE registry.quarantined IS FALSE
         AND canon.status IN ('ratified', 'retired')
     ) AS climb_references
     WHERE pda = ANY($1::text[]) OR vault_id = ANY($2::text[])`,
    [pdas, vaultIds]
  );
  return result.rows;
}

async function serializeLinkedEvents(rows: Record<string, any>[]) {
  rows = visibleEvents(rows);
  const vaultId = (row: Record<string, any>): string | null => {
    const fields = row.fields ?? {};
    const id = fields.vault_id ?? fields.vaultId
      ?? (row.event_name === 'VaultCreated' ? fields.id : undefined);
    return id != null && /^\d+$/.test(String(id)) ? String(id) : null;
  };
  const references = await resolveClimbReferences(
    rows.flatMap(row => typeof row.fields?.climb === 'string' ? [row.fields.climb] : []),
    rows.flatMap(row => vaultId(row) === null ? [] : [vaultId(row)!])
  );
  return rows.map(row => {
    const matches = references.filter(ref => row.fields?.climb
      ? ref.pda === row.fields.climb
      : vaultId(row) !== null && ref.vault_id === vaultId(row));
    const ids = new Set(matches.map(ref => ref.id));
    return { ...serializeEventRow(row), ...(ids.size === 1 ? { climb_id: matches[0].id, climb_name: matches[0].name, climb_length_m: matches[0].length_m } : {}) };
  });
}

/** GET /v1/observatory -- Home page stats. */
async function handleObservatory(res: http.ServerResponse, params: url.URLSearchParams): Promise<void> {
  const [vaultCountResult, aggregatesResult, supplyResult, eventsResult, topVaultsResult, freshness] = await Promise.all([
    runtime.query(
      `SELECT COUNT(*) AS total ${INDEXED_CLIMB_REGISTRY}`
    ),
    runtime.query(
      `SELECT
         (
           SELECT COUNT(*)
           FROM indexed_rider_souls AS rider
           WHERE rider.chain_slot >= COALESCE(
             (
               SELECT successor_handoff_slot::BIGINT
               FROM public.settlement_clock_program_lineage
               WHERE id = 1
             ),
             9223372036854775807
           )
         ) AS total_riders,
         COALESCE(SUM(active_vaults.total_completions), 0)
           AS total_completions,
         COALESCE(SUM(active_vaults.total_cal_staked), 0)
           AS total_cal_staked
       FROM (${ACTIVE_CANON_CLIMB_SELECT}) AS active_vaults`
    ),
    runtime.query(
      'SELECT pda, chain_slot, indexed_at, total_minted, total_burned, spl_mint_supply, spl_mint_supply_slot, spl_mint_supply_indexed_at, max_supply, current_emission_rate_bps, last_halving_epoch, community_reserved, reservation_policy_version FROM indexed_supply WHERE id = 1'
    ),
    runtime.query(
      `SELECT tx_signature, event_index, event_name, fields, slot, block_time
       FROM indexed_events
       WHERE slot >= COALESCE(
           (
             SELECT successor_handoff_slot::BIGINT
             FROM public.settlement_clock_program_lineage
             WHERE id = 1
           ),
           9223372036854775807
         )
         AND event_name IN (
           'ClimbRegistered',
           'CalStaked',
           'VaultCreated',
           'ClimbCompleted',
           'ClimbCompletedV2',
           'ReleasedClimbCompleted',
           'RideAttestationRecorded',
           'CalCredited',
           'HeldRideReleaseAuthorized',
           'ReleasedCalCredited',
           'LocalLegendElected',
           'LocalLegendDormant',
           'EpochRewardsDistributed'
         )
         AND (
           event_name NOT IN (
             'ClimbCompleted',
             'ClimbCompletedV2',
             'ReleasedClimbCompleted'
           )
           OR COALESCE(fields->>'is_new_kom', 'false') = 'true'
         )
       ORDER BY block_time DESC NULLS LAST, slot DESC, event_index DESC
       LIMIT 20 OFFSET $1`, [parseOffset(params.get('events_offset'))]
    ),
    runtime.query(
      `SELECT *
       FROM (${ACTIVE_CANON_CLIMB_SELECT}) AS active_climbs
       ORDER BY COALESCE(active_climbs.total_cal_staked, 0) DESC,
                active_climbs.id ASC
       LIMIT 10`
    ),
    buildApiFreshness('observatory', [
      'indexed_vaults',
      'indexed_climbs',
      'canon_climbs',
      'indexed_vault_activations',
      'canon_vault_activations',
      'indexed_rider_souls',
      'indexed_supply',
      'indexed_events',
    ]),
  ]);

  const count = vaultCountResult.rows[0]?.total;
  const vaultCount = count != null && Number.isSafeInteger(Number(count)) && Number(count) >= 0
    ? Number(count) : undefined;
  const aggregates = aggregatesResult.rows[0] || {};
  const supply = serializeSupplyRow(supplyResult.rows[0] ?? null);

  const indexed = projectIndexed(freshness);
  const [groundResult, clockResult] = await Promise.all([
    runtime.query(`/* observatory:ground */ SELECT ground.*, ST_AsGeoJSON(canon.centerline_geom)::json AS geometry
      FROM (${CANON_CLIMB_SELECT} WHERE canon.status = 'ratified') AS ground
      JOIN public.canon_climbs AS canon ON canon.id::text = ground.id ORDER BY ground.id`),
    runtime.query(`/* observatory:clock */ SELECT settlement_clock_version, settlement_clock_v2_starts_at, chain_slot
      FROM indexed_program_config WHERE id = 1`),
  ]);
  const climbs = groundResult.rows.map(row => projectGround(row, Boolean(indexed)));
  const clock = projectWeekClock(clockResult.rows[0], indexed?.at);
  let week: Record<string, any> = {};
  if (indexed) {
    week = {
      climbs_registered: attestedNumber(vaultCount),
      cal_deposited: attestedAtomic(aggregates.total_cal_staked),
      riders: attestedNumber(aggregates.total_riders),
    };
    if ('epoch' in clock) {
      const figures = await runtime.query(`/* observatory:week */ SELECT
        (SELECT NULLIF(COUNT(*), 0) FROM indexed_ride_attestations
          WHERE settled_slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id = 1)
            AND economic_epoch = $1 AND finalized IS TRUE) AS rides_attested,
        (SELECT SUM(total_distributed) FROM indexed_epoch_distributions
          WHERE slot >= (SELECT successor_handoff_slot::BIGINT FROM public.settlement_clock_program_lineage WHERE id = 1)
            AND epoch = $2) AS dung_distributed`, [clock.epoch, clock.epoch! - 1]);
      week = {...week, epoch: clock.epoch, settles_at: new Date(clock.finalizes_at! * 1000).toISOString(),
        rides_attested: attestedNumber(figures.rows[0]?.rides_attested),
        dung_distributed: attestedAtomic(figures.rows[0]?.dung_distributed)};
    }
  }
  const recentEvents = (await serializeLinkedEvents(eventsResult.rows)).map(event => projectDisplayEvent(event, climbs));
  json(res, 200, {
    week, climbs, indexed,
    events_next_offset: eventsResult.rows.length === 20 ? parseOffset(params.get('events_offset')) + 20 : null,
    program_id: config.programId,
    vault_count: vaultCount,
    total_riders: parseCount(aggregates.total_riders),
    total_completions: parseCount(aggregates.total_completions),
    total_cal_staked: String(aggregates.total_cal_staked ?? '0'),
    supply,
    recent_events: recentEvents,
    top_vaults: topVaultsResult.rows.map(serializeObservatoryClimbRow),
    freshness,
  });
}

async function handleClimbList(
  res: http.ServerResponse,
  params: url.URLSearchParams
): Promise<void> {
  const sortParam = params.get('sort') || 'staked';
  const sortColumn = CANON_CLIMB_SORT_COLUMNS[sortParam];
  if (!sortColumn) {
    json(res, 400, {
      error: `Invalid sort. Must be one of: ${Object.keys(CANON_CLIMB_SORT_COLUMNS).join(', ')}`,
    });
    return;
  }
  const order = (params.get('order') || 'desc').toLowerCase() === 'asc'
    ? 'ASC'
    : 'DESC';
  const limit = parseLimit(params.get('limit'));
  const offset = parseOffset(params.get('offset'));
  const [climbsResult, countResult, freshness] = await Promise.all([
    runtime.query(
      `${CANON_CLIMB_SELECT}
       WHERE canon.status = 'ratified'
       ORDER BY ${sortColumn} ${order}, canon.id ASC
       LIMIT $1 OFFSET $2`,
      [limit, offset]
    ),
    runtime.query(
      "SELECT COUNT(*) AS total FROM public.canon_climbs WHERE status = 'ratified'"
    ),
    buildApiFreshness('climb_list', [
      'canon_climbs',
      'indexed_climbs',
      'indexed_vaults',
      'indexed_vault_activations',
    ]),
  ]);
  json(res, 200, {
    climbs: climbsResult.rows.map(serializeCanonClimbRow),
    total: parseCount(countResult.rows[0]?.total),
    freshness,
  });
}

async function handleClimbDetail(
  res: http.ServerResponse,
  climbId: string
): Promise<void> {
  const climbResult = await runtime.query(
    `${CANON_CLIMB_SELECT}
     WHERE canon.id = $1::uuid
       AND canon.status IN ('ratified', 'retired')`,
    [climbId]
  );
  if (climbResult.rows.length !== 1) {
    json(res, 404, { error: 'Not found' });
    return;
  }

  const projectedClimb = serializeCanonClimbRow(climbResult.rows[0]);
  const vaultId = projectedClimb.vault_id as number | null;
  const climbPda = projectedClimb.climb_pda as string | null;
  const freshnessTables = [
    'canon_climbs',
    'indexed_climbs',
    'canon_vault_activations',
    'indexed_vaults',
    'indexed_vault_activations',
    'indexed_leaderboards',
    'indexed_legends',
    'indexed_events',
    'indexed_epoch_distributions',
  ];

  if (vaultId === null || climbPda === null) {
    const freshness = await buildApiFreshness('climb_detail', freshnessTables);
    json(res, 200, {
      contract_version: 'client.v1',
      truth_source: 'projected',
      climb: withoutCanonVaultEconomy(projectedClimb),
      vault: null,
      leaderboard: [],
      local_legend: null,
      recent_events: [],
      distribution_history: [],
      activation_events: [],
      freshness,
      ...await buildClimbPageData(runtime.query, projectedClimb, null, freshness),
    });
    return;
  }

  const [
    vaultResult,
    leaderboardResult,
    legendResult,
    eventsResult,
    distributionHistoryResult,
    activationEventsResult,
    freshness,
  ] = await Promise.all([
    runtime.query(
      `SELECT iv.*,
              iva.pda AS activation_pda,
              iva.is_active AS activation_is_active,
              iva.seed_completions_written AS activation_seed_completions_written,
              iva.leaderboard_seeded AS activation_leaderboard_seeded,
              iva.created_at AS activation_created_at,
              iva.activated_at AS activation_activated_at,
              iva.last_seed_at AS activation_last_seed_at,
              iva.seed_generation AS activation_seed_generation,
              iva.seed_cutoff_at AS activation_seed_cutoff_at,
              iva.economics_start_epoch AS activation_economics_start_epoch,
              iva.matched_users AS activation_matched_users,
              iva.matched_completions AS activation_matched_completions,
              iva.evidence_hash AS activation_evidence_hash,
              iva.chain_slot AS activation_chain_slot,
              iva.indexed_at AS activation_indexed_at,
              iva.bump AS activation_bump
       FROM public.indexed_vaults AS iv
       JOIN public.indexed_climbs AS indexed
         ON indexed.canon_climb_id = $2::uuid
        AND indexed.pda = $3
        AND indexed.quarantined IS FALSE
        AND indexed.successor_climb_pda IS NULL
        AND indexed.vault_pda = iv.pda
        AND indexed.canon_commitment_hex = iv.canon_commitment_hex
       JOIN public.canon_vault_activations AS operational
         ON operational.canon_climb_id = $2::uuid
        AND operational.climb_pda = indexed.pda
        AND operational.vault_id = iv.id
        AND operational.vault_pda = iv.pda
        AND operational.activation_status = 'finalized'
        AND operational.constructor_evidence_verified IS TRUE
       JOIN public.indexed_vault_activations AS iva
         ON iva.vault_id = iv.id
        AND iva.pda = operational.vault_activation_pda
        AND iva.is_active IS TRUE
        AND iva.seed_generation = 2
        AND iva.seed_completions_written = 0
        AND iva.leaderboard_seeded IS TRUE
        AND iva.matched_users = 0
        AND iva.matched_completions = 0
        AND iva.created_at > 0
        AND iva.created_at = iva.activated_at
        AND iva.created_at = iva.last_seed_at
        AND iva.created_at = iva.seed_cutoff_at
        AND lower(btrim(iva.evidence_hash::text))
              = operational.constructor_evidence_hash
       WHERE iv.id = $1
         AND iv.canon_climb_id = $2::uuid
         AND iv.climb_pda = $3
         AND iv.canon_binding_status = 'active'`,
      [vaultId, climbId, climbPda]
    ),
    runtime.query('SELECT * FROM indexed_leaderboards WHERE vault_id = $1', [vaultId]),
    runtime.query('SELECT * FROM indexed_legends WHERE vault_id = $1', [vaultId]),
    runtime.query(
      `SELECT tx_signature, event_index, event_name, fields, slot, block_time
       FROM indexed_events
       WHERE vault_id = $1
         AND event_name <> 'VaultActivated'
         ${eventVisibilitySql()}
       ORDER BY block_time DESC NULLS LAST, slot DESC
       LIMIT 20`,
      [vaultId]
    ),
    runtime.query(
      `SELECT tx_signature, event_index, vault_id, epoch,
              total_distributed, leaderboard_distributed, staker_distributed,
              local_legend_distributed, pol_distributed, protocol_distributed,
              staker_count, unlock_pct, locked_staker_amount,
              slot, block_time
       FROM indexed_epoch_distributions
       WHERE vault_id = $1
       ORDER BY epoch DESC, block_time DESC NULLS LAST, slot DESC`,
      [vaultId]
    ),
    runtime.query(
      `SELECT tx_signature, event_index, event_name, fields, slot, block_time
       FROM indexed_events
       WHERE vault_id = $1 AND event_name = 'VaultActivated'
       ORDER BY block_time DESC NULLS LAST, slot DESC
       LIMIT 10`,
      [vaultId]
    ),
    buildApiFreshness('climb_detail', freshnessTables),
  ]);

  if (vaultResult.rows.length !== 1) {
    json(res, 200, {
      contract_version: 'client.v1',
      truth_source: 'projected',
      climb: withoutCanonVaultEconomy(projectedClimb),
      vault: null,
      leaderboard: [],
      local_legend: null,
      recent_events: [],
      distribution_history: [],
      activation_events: [],
      freshness,
      ...await buildClimbPageData(runtime.query, projectedClimb, null, freshness),
    });
    return;
  }

  json(res, 200, {
    contract_version: 'client.v1',
    truth_source: 'projected',
    climb: projectedClimb,
    vault: serializeVaultRow(vaultResult.rows[0]),
    leaderboard: leaderboardResult.rows[0]?.entries ?? [],
    local_legend: serializeLegendRow(legendResult.rows[0]),
    recent_events: visibleEvents(eventsResult.rows).map(serializeEventRow),
    distribution_history: distributionHistoryResult.rows.map(
      serializeEpochDistributionRow
    ),
    activation_events: visibleEvents(activationEventsResult.rows).map(serializeEventRow),
    freshness,
    ...await buildClimbPageData(runtime.query, projectedClimb, {...vaultResult.rows[0], legend: legendResult.rows[0], leaderboard: leaderboardResult.rows[0]?.entries}, freshness),
  });
}

/**
 * GET /v1/climbs?sort=staked|completions|created&order=desc|asc&limit=20&offset=0
 * GET /v1/vaults?sort=staked|completions|created&order=desc|asc&limit=20&offset=0
 */
async function handleVaultList(
  res: http.ServerResponse,
  params: url.URLSearchParams,
  surface: ClimbSurface = 'vault'
): Promise<void> {
  const sortParam = params.get('sort') || 'staked';
  const orderParam = (params.get('order') || 'desc').toLowerCase();
  const limit = parseLimit(params.get('limit'));
  const offset = parseOffset(params.get('offset'));

  const sortColumn = VAULT_SORT_COLUMNS[sortParam];
  if (!sortColumn) {
    json(res, 400, { error: `Invalid sort. Must be one of: ${Object.keys(VAULT_SORT_COLUMNS).join(', ')}` });
    return;
  }

  const order = orderParam === 'asc' ? 'ASC' : 'DESC';

  const [vaultsResult, countResult, freshness] = await Promise.all([
    runtime.query(
      `SELECT iv.id, iv.name, iv.signature_hex, iv.minter, iv.vert_m, iv.distance_m,
              iv.avg_gradient_pct, iv.total_completions, iv.total_cal_staked,
              iv.staker_count, iv.kom_holder, iv.kom_time_s, iv.created_at,
              iv.on_chain_seeding_status,
              iva.is_active AS activation_is_active,
              iva.seed_completions_written AS activation_seed_completions_written,
              iva.leaderboard_seeded AS activation_leaderboard_seeded,
              iva.activated_at AS activation_activated_at,
              iva.last_seed_at AS activation_last_seed_at,
              iva.seed_generation AS activation_seed_generation,
              iva.seed_cutoff_at AS activation_seed_cutoff_at,
              iva.economics_start_epoch AS activation_economics_start_epoch,
              iva.matched_users AS activation_matched_users,
              iva.matched_completions AS activation_matched_completions,
              iva.evidence_hash AS activation_evidence_hash
       FROM indexed_vaults iv
       LEFT JOIN indexed_vault_activations iva ON iva.vault_id = iv.id
       ORDER BY iv.${sortColumn} ${order}
       LIMIT $1 OFFSET $2`,
      [limit, offset]
    ),
    runtime.query('SELECT COUNT(*) AS total FROM indexed_vaults'),
    buildApiFreshness(surface === 'climb' ? 'climb_list' : 'vault_list', [
      'indexed_vaults',
      'indexed_vault_activations',
    ]),
  ]);

  const rows = vaultsResult.rows.map(serializeVaultRow);
  const total = parseCount(countResult.rows[0]?.total);

  json(
    res,
    200,
    surface === 'climb'
      ? { climbs: rows, vaults: rows, total, freshness }
      : { vaults: rows, total, freshness }
  );
}

/**
 * GET /v1/climbs/:id -- Climb detail, backed by the indexed vault projection
 * GET /v1/vaults/:id -- Vault detail compatibility lane
 */
async function handleVaultDetail(
  res: http.ServerResponse,
  vaultId: number,
  surface: ClimbSurface = 'vault'
): Promise<void> {
  const [vaultResult, leaderboardResult, legendResult, eventsResult, distributionHistoryResult, activationEventsResult, freshness] = await Promise.all([
    runtime.query(
      `SELECT iv.*,
              iva.pda AS activation_pda,
              iva.is_active AS activation_is_active,
              iva.seed_completions_written AS activation_seed_completions_written,
              iva.leaderboard_seeded AS activation_leaderboard_seeded,
              iva.created_at AS activation_created_at,
              iva.activated_at AS activation_activated_at,
              iva.last_seed_at AS activation_last_seed_at,
              iva.seed_generation AS activation_seed_generation,
              iva.seed_cutoff_at AS activation_seed_cutoff_at,
              iva.economics_start_epoch AS activation_economics_start_epoch,
              iva.matched_users AS activation_matched_users,
              iva.matched_completions AS activation_matched_completions,
              iva.evidence_hash AS activation_evidence_hash,
              iva.chain_slot AS activation_chain_slot,
              iva.indexed_at AS activation_indexed_at,
              iva.bump AS activation_bump
       FROM indexed_vaults iv
       LEFT JOIN indexed_vault_activations iva ON iva.vault_id = iv.id
       WHERE iv.id = $1`,
      [vaultId]
    ),
    runtime.query('SELECT * FROM indexed_leaderboards WHERE vault_id = $1', [vaultId]),
    runtime.query('SELECT * FROM indexed_legends WHERE vault_id = $1', [vaultId]),
    runtime.query(
      `SELECT tx_signature, event_index, event_name, fields, slot, block_time
       FROM indexed_events
       WHERE vault_id = $1
         AND event_name <> 'VaultActivated'
         ${eventVisibilitySql()}
       ORDER BY block_time DESC NULLS LAST, slot DESC
       LIMIT 20`,
      [vaultId]
    ),
    runtime.query(
      `SELECT tx_signature, event_index, vault_id, epoch,
              total_distributed, leaderboard_distributed, staker_distributed,
              local_legend_distributed, pol_distributed, protocol_distributed,
              staker_count, unlock_pct, locked_staker_amount,
              slot, block_time
       FROM indexed_epoch_distributions
       WHERE vault_id = $1
       ORDER BY epoch DESC, block_time DESC NULLS LAST, slot DESC`,
      [vaultId]
    ),
    runtime.query(
      `SELECT tx_signature, event_index, event_name, fields, slot, block_time
       FROM indexed_events
       WHERE vault_id = $1 AND event_name = 'VaultActivated'
       ORDER BY block_time DESC NULLS LAST, slot DESC
       LIMIT 10`,
      [vaultId]
    ),
    buildApiFreshness(surface === 'climb' ? 'climb_detail' : 'vault_detail', [
      'indexed_vaults',
      'indexed_vault_activations',
      'indexed_leaderboards',
      'indexed_legends',
      'indexed_events',
      'indexed_epoch_distributions',
    ]),
  ]);

  if (vaultResult.rows.length === 0) {
    json(res, 404, { error: 'Not found' });
    return;
  }

  const vault = serializeVaultRow(vaultResult.rows[0]);
  const body = {
    vault,
    leaderboard: leaderboardResult.rows[0]?.entries ?? [],
    local_legend: serializeLegendRow(legendResult.rows[0]),
    recent_events: visibleEvents(eventsResult.rows).map(serializeEventRow),
    distribution_history: distributionHistoryResult.rows.map(serializeEpochDistributionRow),
    activation_events: visibleEvents(activationEventsResult.rows).map(serializeEventRow),
    freshness,
  };

  json(res, 200, surface === 'climb' ? { climb: vault, ...body } : body);
}

/**
 * GET /v1/transactions?limit=20&offset=0
 */
async function handleTransactionList(
  res: http.ServerResponse,
  params: url.URLSearchParams
): Promise<void> {
  const limit = parseLimit(params.get('limit'));
  const offset = parseOffset(params.get('offset'));

  const visibleTransactions = `WITH visible_transactions AS (
    SELECT * FROM indexed_transactions candidate
    WHERE ${programVersionWindow.stage1Available ? privatePayPredicate('candidate') : legacyTransactionPredicate('candidate')}
  )`;
  const [txResult, countResult, freshness] = await Promise.all([
    runtime.query(
      `${visibleTransactions}
       SELECT summary.signature, summary.slot, summary.block_time, summary.status,
              summary.fee_lamports, summary.compute_units,
              summary.instruction_name, counts.instruction_count
       FROM (
         SELECT DISTINCT ON (signature)
           signature, slot, block_time, status, fee_lamports, compute_units, instruction_name
         FROM visible_transactions
         ORDER BY signature, instruction_index ASC
       ) summary
       JOIN (
         SELECT signature, COUNT(*) AS instruction_count
         FROM visible_transactions
         GROUP BY signature
       ) counts ON counts.signature = summary.signature
       ORDER BY summary.block_time DESC NULLS LAST, summary.slot DESC
       LIMIT $1 OFFSET $2`,
      [limit, offset]
    ),
    runtime.query(`${visibleTransactions} SELECT COUNT(DISTINCT signature) AS total FROM visible_transactions`),
    buildApiFreshness('transaction_list', ['indexed_transactions']),
  ]);

  json(res, 200, {
    transactions: txResult.rows,
    total: parseInt(countResult.rows[0].total, 10),
    freshness,
  });
}

/**
 * GET /v1/transactions/:signature -- Transaction detail
 */
async function handleTransactionDetail(
  res: http.ServerResponse,
  signature: string
): Promise<void> {
  const [txResult, eventsResult, freshness] = await Promise.all([
    runtime.query(
      `SELECT *
       FROM indexed_transactions
       WHERE signature = $1
       ORDER BY instruction_index ASC`,
      [signature]
    ),
    runtime.query(
      `SELECT tx_signature, event_index, event_name, fields, slot, block_time
       FROM indexed_events
       WHERE tx_signature = $1
       ORDER BY event_index`,
      [signature]
    ),
    buildApiFreshness('transaction_detail', ['indexed_transactions', 'indexed_events']),
  ]);

  if (txResult.rows.length === 0) {
    json(res, 404, { error: 'Not found' });
    return;
  }

  if (txResult.rows.some(row => isStage1Instruction(String(row.instruction_name)))
      || eventsResult.rows.some(row => String(row.event_name).startsWith('Stage1'))) {
    await requireIndexerProgramCompatibility(runtime.getRpcConnection());
    if (!programVersionWindow.stage1Available) {
      json(res, 503, { error: STAGE1_UNAVAILABLE });
      return;
    }
    if (txResult.rows.some(row => PRIVATE_STAGE1_INSTRUCTIONS.has(String(row.instruction_name)))) {
      json(res, 404, { error: 'Not found' });
      return;
    }
  }

  const firstRow = txResult.rows[0];
  const events = decodeExplorerEvents(visibleEvents(eventsResult.rows).map(serializeEventRow));

  const canon = await runtime.query(`/* transaction-receipt:canon */ ${CANON_CLIMB_SELECT} WHERE canon.status = 'ratified'`);
  const receipt = await buildTransactionReceipt(runtime.query, txResult.rows, events, canon.rows);
  json(res, 200, {
    receipt,
    signature: firstRow.signature,
    slot: firstRow.slot,
    block_time: firstRow.block_time,
    status: firstRow.status,
    fee_lamports: firstRow.fee_lamports,
    compute_units: firstRow.compute_units,
    instructions: txResult.rows.map(serializeInstructionRow),
    events,
    token_flows: deriveEventTokenFlows(events),
    freshness,
  });
}

/** Resolve only successful indexed attestation receipts, never legacy mint signatures. */
async function handleProofDetail(res: http.ServerResponse, id: string): Promise<void> {
  let identity: string;
  let params: string[];
  if (isValidUuid(id)) {
    identity = `e.tx_signature IN (
      SELECT r.ride_attestation_tx_signature
      FROM proofs p JOIN rides r ON r.id = p.ride_id
      WHERE p.id = $1::uuid
    )`;
    params = [id];
  } else if (/^[0-9a-fA-F]{64}$/.test(id)) {
    identity = "COALESCE(e.fields->>'rideHash', e.fields->>'ride_hash') = $1";
    params = [id.toLowerCase()];
  } else if (isValidPubkey(id)) {
    identity = `EXISTS (
      SELECT 1 FROM indexed_ride_attestations a
      WHERE a.pda = $1
        AND a.ride_hash_hex = COALESCE(e.fields->>'rideHash', e.fields->>'ride_hash')
        AND a.rider_pubkey = e.fields->>'rider'
    )`;
    params = [id];
  } else {
    json(res, 404, { error: 'Not found' });
    return;
  }
  const result = await runtime.query(
    `SELECT DISTINCT e.tx_signature AS signature
     FROM indexed_events e
     WHERE e.event_name = 'RideAttestationRecorded'
       AND ${identity}
       AND EXISTS (
         SELECT 1 FROM indexed_transactions t
         WHERE t.signature = e.tx_signature AND t.status = 'success'
       )
     ORDER BY signature
     LIMIT 2`,
    params
  );
  // A bare hash shared by multiple riders cannot select an arbitrary receipt.
  if (result.rows.length !== 1 || !isValidSignature(result.rows[0].signature)) {
    json(res, 404, { error: 'Not found' });
    return;
  }
  json(res, 200, { signature: result.rows[0].signature });
}

/**
 * GET /v1/accounts/:pubkey -- Account profile
 */
async function handleAccountDetail(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  pubkey: string
): Promise<void> {
  const rateLimit = accountDetailRateLimitAllows(req);
  if (!rateLimit.allowed) {
    res.writeHead(429, {
      'Content-Type': 'application/json',
      'Retry-After': String(rateLimit.retryAfter),
    });
    res.end(JSON.stringify({ error: 'Rate limit exceeded' }));
    return;
  }

  const [
    accountResult,
    riderSoulResult,
    beetleResult,
    stakesResult,
    completionsResult,
    eventsResult,
    rideAttestationResult,
    programConfigResult,
    profileResult,
    freshness,
  ] = await Promise.all([
    runtime.query('SELECT * FROM indexed_accounts WHERE owner_pubkey = $1', [pubkey]),
    runtime.query('SELECT * FROM indexed_rider_souls WHERE rider_pubkey = $1', [pubkey]),
    runtime.query('SELECT * FROM indexed_beetle_cards WHERE owner_pubkey = $1', [pubkey]),
    runtime.query(
      `SELECT vault_id, cal_staked, lp_tokens, rewards_earned,
              eligible_from_epoch,
              effective_lp_tokens, pending_lp_tokens,
              pending_effective_week_plus_one
       FROM indexed_stakes
       WHERE user_pubkey = $1 AND lp_tokens > 0`,
      [pubkey]
    ),
    runtime.query(
      `SELECT vault_id, completions, best_time_s, last_completed_at, total_cal_tributed
       FROM indexed_completions
       WHERE user_pubkey = $1`,
      [pubkey]
    ),
    runtime.query(
      `SELECT tx_signature, event_index, event_name, fields, slot, block_time
       FROM indexed_events
       WHERE user_pubkey = $1
         AND event_name <> 'VaultActivated'
         ${eventVisibilitySql()}
       ORDER BY block_time DESC NULLS LAST, slot DESC
       LIMIT 20`,
      [pubkey]
    ),
    runtime.query(
      `SELECT *
       FROM indexed_ride_attestations
       WHERE rider_pubkey = $1
       ORDER BY completed_at DESC, chain_slot DESC
       LIMIT 20`,
      [pubkey]
    ),
    runtime.query('SELECT cal_mint, dung_mint FROM indexed_program_config WHERE id = 1'),
    runtime.query(
      `SELECT username, display_name, wallet
       FROM users
       WHERE wallet = $1
         AND username IS NOT NULL
         AND COALESCE(is_public, true) = true
       ORDER BY updated_at DESC NULLS LAST
       LIMIT 1`,
      [pubkey]
    ),
    buildApiFreshness('account_detail', [
      'indexed_accounts',
      'indexed_rider_souls',
      'indexed_beetle_cards',
      'indexed_stakes',
      'indexed_completions',
      'indexed_ride_attestations',
      'indexed_events',
      'users',
    ]),
  ]);

  if (accountResult.rows.length === 0 && riderSoulResult.rows.length === 0) {
    json(res, 404, { error: 'Not found' });
    return;
  }

  const programConfig = programConfigResult.rows[0] || {};
  const splBalances = await fetchSplBalances(
    pubkey,
    programConfig.cal_mint ?? null,
    programConfig.dung_mint ?? null
  );

  const canon = await runtime.query(`${CANON_CLIMB_SELECT.replace("SELECT canon.id", "SELECT ST_AsGeoJSON(canon.centerline_geom)::json AS geometry, canon.id")} WHERE canon.status = 'ratified'`);
  const pageData = await buildAccountPageData(runtime.query, pubkey, freshness, canon.rows, splBalances.token_accounts ?? []);
  json(res, 200, {
    room: pageData,
    pubkey,
    profile: profileResult.rows[0]
      ? {
          username: profileResult.rows[0].username,
          display_name: profileResult.rows[0].display_name ?? null,
          wallet: profileResult.rows[0].wallet,
        }
      : null,
    user_state: accountResult.rows[0] ? serializeUserStateRow(accountResult.rows[0]) : null,
    rider_soul: riderSoulResult.rows[0] ? serializeRiderSoulRow(riderSoulResult.rows[0]) : null,
    beetle_cards: beetleResult.rows.map(serializeBeetleCard),
    active_stakes: stakesResult.rows,
    completions: completionsResult.rows,
    recent_ride_attestations: rideAttestationResult.rows.map(serializeRideAttestationRow),
    spl_balances: splBalances,
    recent_events: visibleEvents(eventsResult.rows).map(serializeEventRow),
    freshness,
  });
}

/**
 * GET /v1/accounts/resolve?username=name -- Resolve a public username to wallet pubkey
 */
async function handleAccountResolve(
  res: http.ServerResponse,
  params: url.URLSearchParams
): Promise<void> {
  const usernameRaw = (params.get('username') || '').trim();
  const username = usernameRaw.replace(/^@/, '').toLowerCase();

  if (!username) {
    json(res, 400, { error: 'username is required' });
    return;
  }

  if (!isValidUsername(username)) {
    json(res, 400, { error: 'Invalid username format' });
    return;
  }

  const result = await runtime.query(
    `SELECT username, wallet
     FROM users
     WHERE username = $1 AND COALESCE(is_public, true) = true
     LIMIT 1`,
    [username]
  );

  if (result.rows.length === 0) {
    json(res, 404, { error: 'Not found' });
    return;
  }

  json(res, 200, {
    username: result.rows[0].username,
    pubkey: result.rows[0].wallet,
  });
}

/**
 * GET /v1/ride-attestations?user=pubkey&ride_hash=hex&limit=20&offset=0
 */
async function handleRideAttestationList(
  res: http.ServerResponse,
  params: url.URLSearchParams
): Promise<void> {
  const limit = parseLimit(params.get('limit'));
  const offset = parseOffset(params.get('offset'));
  const userRaw = (params.get('user') || '').trim();
  const rideHashRaw = (params.get('ride_hash') || '').trim().toLowerCase();

  if (!userRaw && !rideHashRaw) {
    json(res, 400, { error: 'user or ride_hash is required' });
    return;
  }

  if (userRaw && !isValidPubkey(userRaw)) {
    json(res, 400, { error: 'Invalid pubkey format' });
    return;
  }

  if (rideHashRaw && !isValidHex32(rideHashRaw)) {
    json(res, 400, { error: 'ride_hash must be a 32-byte hex digest' });
    return;
  }

  const user = userRaw || null;
  const rideHash = rideHashRaw || null;

  const [result, countResult, freshness] = await Promise.all([
    runtime.query(
      `SELECT *
       FROM indexed_ride_attestations
       WHERE ($1::text IS NULL OR rider_pubkey = $1)
         AND ($2::text IS NULL OR ride_hash_hex = $2)
       ORDER BY completed_at DESC, chain_slot DESC
       LIMIT $3 OFFSET $4`,
      [user, rideHash, limit, offset]
    ),
    runtime.query(
      `SELECT COUNT(*) AS total
       FROM indexed_ride_attestations
       WHERE ($1::text IS NULL OR rider_pubkey = $1)
         AND ($2::text IS NULL OR ride_hash_hex = $2)`,
      [user, rideHash]
    ),
    buildApiFreshness('ride_attestation_list', ['indexed_ride_attestations']),
  ]);

  json(res, 200, {
    attestations: result.rows.map(serializeRideAttestationRow),
    total: parseCount(countResult.rows[0]?.total),
    freshness,
  });
}

/**
 * GET /v1/events?vault_id=N&user=pubkey&name=EventName&limit=20&offset=0
 */
async function handleEventList(
  res: http.ServerResponse,
  params: url.URLSearchParams
): Promise<void> {
  const limit = parseLimit(params.get('limit'));
  const offset = parseOffset(params.get('offset'));

  const vaultIdRaw = params.get('vault_id');
  const userRaw = params.get('user');
  const nameRaw = params.get('name');

  // Validate vault_id if provided
  let vaultId: number | null = null;
  if (vaultIdRaw !== null && vaultIdRaw !== '') {
    vaultId = parseInt(vaultIdRaw, 10);
    if (isNaN(vaultId)) {
      json(res, 400, { error: 'vault_id must be a number' });
      return;
    }
  }

  // Validate user pubkey if provided
  let user: string | null = null;
  if (userRaw !== null && userRaw !== '') {
    if (!isValidPubkey(userRaw)) {
      json(res, 400, { error: 'Invalid pubkey format' });
      return;
    }
    user = userRaw;
  }

  const name = nameRaw || null;

  const [result, freshness] = await Promise.all([
    runtime.query(
      `SELECT * FROM indexed_events
       WHERE ($1::bigint IS NULL OR vault_id = $1)
         AND ($2::text IS NULL OR user_pubkey = $2)
         AND ($3::text IS NULL OR event_name = $3)
         ${eventVisibilitySql()}
       ORDER BY block_time DESC
       LIMIT $4 OFFSET $5`,
      [vaultId, user, name, limit, offset]
    ),
    buildApiFreshness('event_list', ['indexed_events']),
  ]);

  json(res, 200, {
    events: visibleEvents(result.rows),
    freshness,
  });
}

/**
 * GET /v1/supply -- DUNG supply state
 */
async function handleSupply(res: http.ServerResponse): Promise<void> {
  const [result, freshness] = await Promise.all([
    runtime.query('SELECT * FROM indexed_supply WHERE id = 1'),
    buildApiFreshness('supply', ['indexed_supply']),
  ]);

  if (result.rows.length === 0) {
    json(res, 404, { error: 'Not found' });
    return;
  }

  json(res, 200, {
    ...serializeSupplyRow(result.rows[0]),
    freshness,
  });
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

/**
 * Handle an API request for paths starting with /v1/.
 * Returns true if the request was handled, false if the path was not recognized.
 */
export async function handleApiRequest(
  req: http.IncomingMessage,
  res: http.ServerResponse
): Promise<boolean> {
  const parsed = url.parse(req.url || '', true);
  const pathname = parsed.pathname || '';
  const params = new url.URLSearchParams(parsed.search || '');

  try {
    if (pathname === '/v1/stage1' || pathname.startsWith('/v1/stage1/')
        || (pathname === '/v1/events' && params.get('name')?.startsWith('Stage1'))) {
      await requireIndexerProgramCompatibility(runtime.getRpcConnection());
      if (!programVersionWindow.stage1Available) {
        json(res, 503, { error: STAGE1_UNAVAILABLE });
        return true;
      }
    }
    try {
      programVersionWindow.assertNoFailure();
    } catch (error) {
      json(res, 503, { error: error instanceof Error ? error.message : 'Program compatibility is unavailable' });
      return true;
    }
    // GET /v1/observatory
    if (pathname === '/v1/observatory') {
      await handleObservatory(res, params);
      return true;
    }

    // GET /v1/climbs/:id  (canonical public object; checked before /v1/climbs)
    const climbDetailMatch = pathname.match(/^\/v1\/climbs\/([^/]+)$/);
    if (climbDetailMatch) {
      let climbId = climbDetailMatch[1];
      // Numeric links are legacy Vault aliases, never canon identities.
      if (/^\d+$/.test(climbId)) {
        const references = await resolveClimbReferences([], [climbId]);
        const ids = new Set(references.map(row => row.id));
        if (ids.size !== 1) {
          json(res, 404, { error: 'Not found' });
          return true;
        }
        climbId = references[0].id;
      }
      if (!isValidUuid(climbId)) {
        json(res, 400, { error: 'Invalid climb ID' });
        return true;
      }
      await handleClimbDetail(res, climbId);
      return true;
    }

    // GET /v1/climbs
    if (pathname === '/v1/climbs') {
      await handleClimbList(res, params);
      return true;
    }

    // GET /v1/vaults/:id  (must check before /v1/vaults to avoid false match)
    const vaultDetailMatch = pathname.match(/^\/v1\/vaults\/(\d+)$/);
    if (vaultDetailMatch) {
      const vaultId = parseInt(vaultDetailMatch[1], 10);
      if (isNaN(vaultId)) {
        json(res, 400, { error: 'Invalid vault ID' });
        return true;
      }
      await handleVaultDetail(res, vaultId);
      return true;
    }

    // GET /v1/vaults
    if (pathname === '/v1/vaults') {
      await handleVaultList(res, params);
      return true;
    }

    // GET /v1/proofs/:id
    const proofMatch = pathname.match(/^\/v1\/proofs\/([^/]+)$/);
    if (proofMatch) {
      await handleProofDetail(res, proofMatch[1]);
      return true;
    }

    // GET /v1/transactions/:signature
    const txDetailMatch = pathname.match(/^\/v1\/transactions\/([^/]+)$/);
    if (txDetailMatch) {
      const sig = txDetailMatch[1];
      if (!isValidSignature(sig)) {
        json(res, 400, { error: 'Invalid transaction signature' });
        return true;
      }
      await handleTransactionDetail(res, sig);
      return true;
    }

    // GET /v1/transactions
    if (pathname === '/v1/transactions') {
      await handleTransactionList(res, params);
      return true;
    }

    // GET /v1/accounts/resolve
    if (pathname === '/v1/accounts/resolve') {
      await handleAccountResolve(res, params);
      return true;
    }

    // GET /v1/ride-attestations
    if (pathname === '/v1/ride-attestations') {
      await handleRideAttestationList(res, params);
      return true;
    }

    // GET /v1/accounts/:pubkey
    const accountMatch = pathname.match(/^\/v1\/accounts\/([^/]+)$/);
    if (accountMatch) {
      const pubkey = accountMatch[1];
      if (!isValidPubkey(pubkey)) {
        json(res, 400, { error: 'Invalid pubkey format' });
        return true;
      }
      await handleAccountDetail(req, res, pubkey);
      return true;
    }

    // GET /v1/events
    if (pathname === '/v1/events') {
      await handleEventList(res, params);
      return true;
    }

    // GET /v1/supply
    if (pathname === '/v1/supply') {
      await handleSupply(res);
      return true;
    }

    // Not a recognized /v1/ route
    json(res, 404, { error: 'Not found' });
    return true;
  } catch (err) {
    console.error(`[API] Error handling ${pathname}:`, err);
    json(res, 500, { error: 'Internal server error' });
    return true;
  }
}
