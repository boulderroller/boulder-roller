import http from 'http';
import { Connection, PublicKey } from '@solana/web3.js';
import { config } from './config';
import { getSyncState } from './writers/common';
import { query } from './db';
import { handleApiRequest } from './api';
import {
  getSnapshotRuntimeState,
  SnapshotRuntimeState,
} from './modes/snapshot';
import { measureReplayLag, readReplayLag, replayLagNeedsAlert, ReplayLag, REPLAY_LAG_ALERT_SLOTS } from './lag-monitor';
import { finalizedHeads } from './finalized-head';
import { MAX_DUNG_SUPPLY_STALE_MS } from './supply-refresh';
import { requireIndexerProgramCompatibility } from './program-compatibility';
import { programVersionWindow } from './program-version-window';

/**
 * HTTP health check endpoint with slot-lag awareness.
 *
 * GET /health -> 200 only with recent replay coverage and healthy projections.
 * Replay lag >= 1,000 slots or unavailable coverage fails closed (503).
 * GET /status -> 200 with detailed sync state
 */

const MAX_LAG_SLOTS = 150;
const TX_REPLAY_STALE_MS = Math.max(config.pollIntervalMs * 3, 15 * 60 * 1000);
const healthConnection = new Connection(config.rpcUrl, 'finalized');
const healthProgram = new PublicKey(config.programId);

const DEFAULT_ALLOWED_ORIGINS = [
  'https://scan.boulderroller.xyz',
  'http://localhost:3004',
  'http://127.0.0.1:3004',
  'http://localhost:4174',
  'http://127.0.0.1:4174',
];

let server: http.Server | null = null;
let lagTimer: ReturnType<typeof setInterval> | null = null;
let checkingCoverage = false;

async function checkReplayCoverage(): Promise<void> {
  if (checkingCoverage) return;
  checkingCoverage = true;
  try {
    const replayCoverage = await measureReplayLag(
      healthConnection,
      healthProgram,
      await getSyncState()
    );
    if (replayLagNeedsAlert(replayCoverage)) {
      console.warn(JSON.stringify({ event: 'indexer_replay_lag', ...replayCoverage, threshold_slots: REPLAY_LAG_ALERT_SLOTS }));
    }
  } catch {
    console.warn(JSON.stringify({ event: 'indexer_replay_lag', status: 'unknown' }));
  } finally {
    checkingCoverage = false;
  }
}

export function attestedReplayLag(currentSlot: number | null, coverage: ReplayLag | null, ageMs: number): number | null {
  if (coverage?.status !== 'current' || coverage.checked_through_slot === null ||
      currentSlot === null || currentSlot < coverage.checked_through_slot || ageMs > 90_000) return null;
  return currentSlot - coverage.checked_through_slot;
}

type IndexerHealthPayload = {
  status: 'ok' | 'lagging' | 'starting' | 'error';
  service: string;
  lag_slots: number | null;
  account_lag_slots: number | null;
  tx_lag_slots: number | null;
  last_indexed_slot: number;
  last_account_slot: number;
  last_tx_slot: number;
  current_chain_slot: number | null;
  last_account_sync_at: unknown;
  last_tx_sync_at: unknown;
  stream_connected: boolean;
  supply: DungSupplyHealthPayload;
  snapshot: SnapshotRuntimeState;
  mode: string;
  timestamp: string;
};

type DungSupplyHealthPayload = {
  status: 'fresh' | 'stale' | 'missing' | 'unknown';
  amount: string | null;
  slot: number;
  indexed_at: unknown;
  age_ms: number | null;
  max_stale_ms: number;
  refresh_interval_ms: number;
};

function numericSlot(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function slotLag(currentSlot: number | null, lastSlot: number): number | null {
  if (!currentSlot || !lastSlot) return null;
  return Math.max(0, currentSlot - lastSlot);
}

function isRecent(value: unknown, now: Date, maxAgeMs: number): boolean {
  if (!value) return false;
  const timestamp = new Date(value as any).getTime();
  return Number.isFinite(timestamp) && now.getTime() - timestamp <= maxAgeMs;
}

export function buildDungSupplyHealthPayload(
  supplyState: Record<string, any> | null | undefined,
  now: Date
): DungSupplyHealthPayload {
  const amount = supplyState?.spl_mint_supply == null
    ? null
    : String(supplyState.spl_mint_supply);
  const slot = numericSlot(supplyState?.spl_mint_supply_slot);
  const indexedAt = supplyState?.spl_mint_supply_indexed_at ?? null;
  const indexedAtMs = indexedAt == null ? Number.NaN : new Date(indexedAt as any).getTime();
  const ageMs = Number.isFinite(indexedAtMs)
    ? Math.max(0, now.getTime() - indexedAtMs)
    : null;
  const status: DungSupplyHealthPayload['status'] = supplyState === undefined
    ? 'unknown'
    : amount === null || slot === 0 || ageMs === null
      ? 'missing'
      : ageMs > MAX_DUNG_SUPPLY_STALE_MS
        ? 'stale'
        : 'fresh';

  return {
    status,
    amount,
    slot,
    indexed_at: indexedAt,
    age_ms: ageMs,
    max_stale_ms: MAX_DUNG_SUPPLY_STALE_MS,
    refresh_interval_ms: config.dungSupplyRefreshIntervalMs,
  };
}

export function buildIndexerHealthPayload(
  syncState: Record<string, any> | null | undefined,
  currentSlot: number | null,
  now = new Date(),
  snapshot = getSnapshotRuntimeState(),
  supplyState?: Record<string, any> | null
): IndexerHealthPayload {
  const lastAccountSlot = numericSlot(syncState?.last_account_slot);
  const lastTxSlot = numericSlot(syncState?.last_tx_slot);
  const streamConnected = syncState?.stream_connected === true;
  const accountLagSlots = slotLag(currentSlot, lastAccountSlot);
  const txLagSlots = slotLag(currentSlot, lastTxSlot);
  const lagSlots = Math.max(...[accountLagSlots, txLagSlots].filter((lag): lag is number => lag !== null));
  const normalizedLagSlots = Number.isFinite(lagSlots) ? lagSlots : null;
  const accountLagging = !streamConnected && accountLagSlots !== null && accountLagSlots > MAX_LAG_SLOTS;
  const txReplayFresh = isRecent(syncState?.last_tx_sync_at, now, TX_REPLAY_STALE_MS);
  const txLagging = !txReplayFresh && txLagSlots !== null && txLagSlots > MAX_LAG_SLOTS;
  const supply = buildDungSupplyHealthPayload(supplyState, now);
  const supplyLagging = supply.status === 'stale' || supply.status === 'missing';
  const isLagging = accountLagging || txLagging || supplyLagging;
  const snapshotReady = snapshot.status === 'succeeded' || snapshot.status === 'not_required';
  const status = snapshot.status === 'failed'
    ? 'error'
    : !snapshotReady
      ? 'starting'
      : isLagging
        ? 'lagging'
        : 'ok';

  return {
    status,
    service: 'boulder-rollers-indexer',
    lag_slots: normalizedLagSlots,
    account_lag_slots: accountLagSlots,
    tx_lag_slots: txLagSlots,
    last_indexed_slot: lastAccountSlot,
    last_account_slot: lastAccountSlot,
    last_tx_slot: lastTxSlot,
    current_chain_slot: currentSlot,
    last_account_sync_at: syncState?.last_account_sync_at ?? null,
    last_tx_sync_at: syncState?.last_tx_sync_at ?? null,
    stream_connected: streamConnected,
    supply,
    snapshot: { ...snapshot },
    mode: config.mode,
    timestamp: now.toISOString(),
  };
}

export function indexerHealthStatusCode(payload: IndexerHealthPayload): number {
  return payload.status === 'ok' ? 200 : 503;
}

function getAllowedOrigins(): string[] {
  const raw = process.env.API_ALLOWED_ORIGINS?.trim();
  if (!raw) return DEFAULT_ALLOWED_ORIGINS;
  if (raw === '*') return ['*'];
  return raw
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function setCorsHeaders(
  req: http.IncomingMessage,
  res: http.ServerResponse
): void {
  const origin = req.headers.origin;
  const allowedOrigins = getAllowedOrigins();
  const allowAnyOrigin = allowedOrigins.includes('*');

  if (allowAnyOrigin) {
    res.setHeader('Access-Control-Allow-Origin', '*');
  } else if (origin && allowedOrigins.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
  }

  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
}

export function startHealthServer(): void {
  void checkReplayCoverage();
  lagTimer = setInterval(() => { void checkReplayCoverage(); }, 30_000);
  lagTimer.unref();
  server = http.createServer(async (req, res) => {
    setCorsHeaders(req, res);

    // Handle CORS preflight
    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }

    // Route /v1/* to the API handler
    const pathname = (req.url || '').split('?')[0];
    if (pathname.startsWith('/v1/')) {
      await handleApiRequest(req, res);
      return;
    }

    if (req.url === '/health') {
      try {
        const [syncState, currentSlot, supplyResult] = await Promise.all([
          getSyncState(),
          Promise.resolve(finalizedHeads.peek(healthConnection)?.slot ?? null),
          query(
            `SELECT spl_mint_supply, spl_mint_supply_slot, spl_mint_supply_indexed_at
               FROM indexed_supply
              WHERE id = 1`
          ),
        ]);
        const payload = buildIndexerHealthPayload(
          syncState,
          currentSlot,
          new Date(),
          getSnapshotRuntimeState(),
          supplyResult.rows[0] ?? null
        );
        // Activity slots remain provenance; they do not measure replay backlog.
        // Account coverage cannot be inferred from a connected WebSocket.
        const replayCoverage = readReplayLag(healthConnection, healthProgram, syncState);
        payload.lag_slots = attestedReplayLag(currentSlot, replayCoverage, 0);
        payload.tx_lag_slots = payload.lag_slots;
        payload.account_lag_slots = null;
        if (payload.status === 'ok' && (payload.lag_slots === null || payload.lag_slots >= REPLAY_LAG_ALERT_SLOTS)) {
          payload.status = replayCoverage?.status === 'behind' || payload.lag_slots !== null ? 'lagging' : 'error';
        }
        const statusCode = indexerHealthStatusCode(payload);

        res.writeHead(statusCode, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ...payload, ...programVersionWindow.status(), lag_scope: 'finalized_program_history', replay_coverage: replayCoverage }));
      } catch (err) {
        res.writeHead(503, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          status: 'error',
          service: 'boulder-rollers-indexer',
          error: String(err),
          mode: config.mode,
          timestamp: new Date().toISOString(),
        }));
      }
      return;
    }

    if (req.url === '/status') {
      try {
        const [syncState, supplyResult] = await Promise.all([
          getSyncState(),
          query(
            `SELECT spl_mint_supply, spl_mint_supply_slot, spl_mint_supply_indexed_at
               FROM indexed_supply
              WHERE id = 1`
          ),
          requireIndexerProgramCompatibility(new Connection(config.rpcUrl, 'finalized')),
        ]);

        // Get table counts
        const counts: Record<string, number> = {};
        const tables = [
          'indexed_vaults', 'indexed_leaderboards', 'indexed_legends',
          'indexed_stakes', 'indexed_completions', 'indexed_accounts',
          'indexed_beetle_cards', 'indexed_supply', 'indexed_program_config',
          'indexed_vault_counter',
          'indexed_transactions', 'indexed_events',
        ];

        for (const table of tables) {
          try {
            const result = await query(`SELECT COUNT(*) as cnt FROM ${table}`);
            counts[table] = parseInt(result.rows[0].cnt, 10);
          } catch {
            counts[table] = -1; // Table doesn't exist yet
          }
        }

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          status: 'ok',
          ...programVersionWindow.status(),
          mode: config.mode,
          sync: syncState,
          supply: buildDungSupplyHealthPayload(supplyResult.rows[0] ?? null, new Date()),
          snapshot: getSnapshotRuntimeState(),
          counts,
          timestamp: new Date().toISOString(),
        }, null, 2));
      } catch (err) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'error', error: String(err) }));
      }
      return;
    }

    res.writeHead(404);
    res.end('Not Found');
  });

  server.listen(config.healthPort, () => {
    console.log(`[Health] Server listening on port ${config.healthPort}`);
  });
}

export function stopHealthServer(): void {
  if (lagTimer) clearInterval(lagTimer);
  lagTimer = null;
  if (server) {
    server.close();
    server = null;
  }
}
