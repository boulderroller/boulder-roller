import { Connection } from '@solana/web3.js';
import { config, redactEndpoint } from './config';
import { loadIdl } from './decoder';
import { getPool, closePool } from './db';
import { ensureSyncState } from './writers/common';
import { runSnapshot } from './modes/snapshot';
import { startStream, stopStream } from './modes/stream';
import { runReplay, runReplaySweep } from './modes/replay';
import {
  reconcilePendingCanonAccounts,
  reconcileVaultCount,
  reconcileSupply,
  reconcileSampleVaults,
} from './reconciliation';
import { startHealthServer, stopHealthServer } from './health';
import { singleFlight } from './single-flight';
import { requireIndexerProgramCompatibility } from './program-compatibility';
import { startDungSupplyRefreshLoop } from './supply-refresh';
import { programVersionWindow } from './program-version-window';
import { boundaryRetryDeadlineMs, startIndexerServices } from './stage1-supervisor';
import { runStage1Replay } from './stage1';
import { stage1Connection } from './stage1-program-stream';
import { query } from './db';

let stopStage1=()=>{};

/**
 * Boulder Rollers Solana Indexer
 *
 * Reads on-chain program state using IDL-driven decoding and writes to Postgres.
 *
 * Modes:
 *   - snapshot: Bulk fetch all program accounts (cold start / recovery)
 *   - stream:   Real-time programSubscribe + periodic replay sweeps
 *   - replay:   Gap fill via getSignaturesForAddress + getTransaction
 *
 * Lifecycle:
 *   1. Load IDL
 *   2. Verify the finalized on-chain version and persist its monotonic window
 *   3. Verify the Postgres connection before projections
 *   4. Ensure sync state row exists
 *   5. Run selected mode
 *   6. Start health check server
 */

async function main(): Promise<void> {
  console.log('=== Boulder Rollers Indexer ===');
  console.log(`Mode:    ${config.mode}`);
  console.log(`Program: ${config.programId}`);
  console.log(`RPC:     ${redactEndpoint(config.rpcUrl)}`);
  console.log(`DB:      ${config.databaseUrl ? '(configured)' : '(NOT SET)'}`);
  console.log('');

  // Step 1: Load IDL
  try {
    loadIdl();
  } catch (err) {
    console.error('Failed to load IDL:', err);
    process.exit(1);
  }

  // Step 2: Fail before any projection write when the chain ABI is incompatible.
  try {
    const compatibility = await requireIndexerProgramCompatibility(
      new Connection(config.rpcUrl, 'finalized')
    );
    console.log(
      `[Chain] ProgramConfig 0x${compatibility.programVersion.toString(16).padStart(2, '0')} `
      + `verified at finalized slot ${compatibility.canonicalDungMint.programConfigSlot}`
    );
  } catch (err) {
    console.error('Program compatibility check failed:', err);
    process.exit(1);
  }

  // Step 3: Verify the projection database (the version observation is durable).
  if (!config.databaseUrl) {
    console.error('DATABASE_URL is not set. Exiting.');
    process.exit(1);
  }

  try {
    const pool = getPool();
    // Test connection
    const result = await pool.query('SELECT 1');
    console.log('[DB] Connected to Postgres');
  } catch (err) {
    console.error('Failed to connect to Postgres:', err);
    process.exit(1);
  }

  // Step 4: Ensure sync state
  await ensureSyncState();
  const supervisor=await startIndexerServices({health:startHealthServer,legacy:async()=>{
    switch (config.mode) {
    case 'snapshot':
      await runSnapshotMode();
      break;
    case 'stream':
      await runStreamMode();
      break;
    case 'replay':
      await runReplayMode();
      break;
    default:
      console.error(`Unknown mode: ${config.mode}`);
      process.exit(1);
    }
  },stage1:async()=>{
    if (programVersionWindow.stage1Available) await runStage1Replay(stage1Connection(),{shared:config.mode==='stream'});
    else await query('UPDATE stage1_indexer_network SET ready=false WHERE singleton');
  },intervalMs:config.pollIntervalMs,retryDeadlineMs:boundaryRetryDeadlineMs,
  alert:async(kind,attempts)=>query(`INSERT INTO stage1_indexer_alerts(kind,attempts) VALUES($1,$2)
    ON CONFLICT(kind) DO UPDATE SET attempts=EXCLUDED.attempts,last_seen=now()`,[kind,attempts])});
  stopStage1=supervisor.stop;
}

/**
 * Snapshot mode: run a one-time full snapshot, then exit.
 */
async function runSnapshotMode(): Promise<void> {
  console.log('[Mode] Running one-time snapshot...');
  const result = await runSnapshot({includeStage1:false});
  await reconcilePendingCanonAccounts();
  console.log(
    `[Mode] Snapshot complete: ${result.indexed}/${result.total} accounts indexed (${result.skipped} skipped)`
  );
  console.log('[Mode] Indexer will continue running for health checks. Ctrl+C to exit.');

  // Keep process alive for health checks
}

/**
 * Stream mode: run snapshot first (if needed), then stream + periodic replay.
 */
async function runStreamMode(): Promise<void> {
  console.log('[Mode] Starting stream mode (snapshot -> stream + replay)...');

  // Gap notifications and the timer can arrive while a replay is still active.
  // Share that in-flight sweep so equal-slot cursors cannot race each other.
  const runReplaySweepSingleFlight = singleFlight(runReplaySweep);

  // Run initial snapshot
  console.log('[Mode] Running initial snapshot...');
  await runSnapshot({includeStage1:false});
  await reconcilePendingCanonAccounts();

  // Start WebSocket stream
  await startStream(async (lastSlot, currentSlot) => {
    // The common program feed already runs every 30 seconds. Idle WebSocket
    // gaps must not create additional signature polls in the shared mode.
    if(programVersionWindow.stage1Available)return;
    console.log(`[Mode] Gap detected: ${lastSlot} -> ${currentSlot}, triggering replay`);
    await runReplaySweepSingleFlight();
  },{includeStage1:false});

  try {
    const result = await runReplaySweepSingleFlight();
    if (result.processed > 0) {
      console.log(`[Mode] Initial replay sweep: ${result.processed} txs, ${result.events} events`);
    }
  } catch (err) {
    console.error('[Mode] Initial replay sweep error:', err);
  }

  // Periodic replay sweep
  const replayInterval = setInterval(async () => {
    try {
      const result = await runReplaySweepSingleFlight();
      await reconcilePendingCanonAccounts();
      if (result.processed > 0) {
        console.log(`[Mode] Replay sweep: ${result.processed} txs, ${result.events} events`);
      }
    } catch (err) {
      console.error('[Mode] Replay sweep error:', err);
    }
  }, config.pollIntervalMs);

  // Periodic reconciliation
  const reconcileInterval = setInterval(async () => {
    try {
      console.log('[Mode] Running scheduled reconciliation...');
      await reconcileVaultCount();
      await reconcileSupply();
      await reconcileSampleVaults();
      await reconcilePendingCanonAccounts();
    } catch (err) {
      console.error('[Mode] Reconciliation error:', err);
    }
  }, config.reconciliationIntervalMs);

  // Mint-account notifications are lossy even when the WebSocket remains
  // connected. Refresh finalized SPL supply on its own bounded cadence.
  const supplyRefreshLoop = startDungSupplyRefreshLoop();

  // Handle shutdown
  const shutdown = async () => {
    console.log('\n[Mode] Shutting down...');
    clearInterval(replayInterval);
    clearInterval(reconcileInterval);
    supplyRefreshLoop.stop();
    stopStage1();
    await stopStream();
    stopHealthServer();
    await closePool();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  console.log('[Mode] Stream mode active. Ctrl+C to exit.');
}

/**
 * Replay mode: run a one-time transaction replay.
 */
async function runReplayMode(): Promise<void> {
  console.log('[Mode] Running one-time transaction replay...');
  const result = await runReplay();
  console.log(`[Mode] Replay complete: ${result.processed} transactions, ${result.events} events`);
  console.log('[Mode] Indexer will continue running for health checks. Ctrl+C to exit.');

  // Keep process alive for health checks
}

// Run
main().catch((err) => {
  console.error('Fatal error:', err);
  process.exit(1);
});
