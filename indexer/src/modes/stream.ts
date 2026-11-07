import { Connection, PublicKey } from '@solana/web3.js';
import { config, redactEndpoint } from '../config';
import { decodeAccount, identifyAccountType } from '../decoder';
import { routeAccount } from '../writers';
import { updateSyncState } from '../writers/common';
import { refreshDungMintSupply, resolveCanonicalDungMint } from '../supply';
import { programVersionWindow } from '../program-version-window';

/**
 * Stream mode: subscribe to program account changes via WebSocket
 * (programSubscribe) and upsert them in real-time.
 *
 * Handles:
 *   - Real-time account state changes
 *   - Automatic reconnection with exponential backoff
 *   - Gap detection on reconnect (triggers replay)
 *
 * Limitations:
 *   - Only delivers account state, not transactions or events
 *   - No guaranteed delivery -- notifications can be dropped
 *   - Must be supplemented by periodic replay sweeps
 */

let activeConnection: Connection | null = null;
let subscriptionId: number | null = null;
let mintSubscriptionId: number | null = null;
let reconnectAttempts = 0;
const MAX_BACKOFF_MS = 60000;
class ProjectionIncompleteError extends Error {}

/** Per-type counters for observability. Reset each log interval. */
const typeCounters: Map<string, number> = new Map();
const TYPE_LOG_INTERVAL = 60_000; // Log type breakdown every 60s
const SYNC_STATE_UPDATE_INTERVAL = 30_000;
let lastTypeLogAt = Date.now();

export async function startStream(
  onGapDetected?: (lastSlot: number, currentSlot: number) => void,
  options: {includeStage1?:boolean} = {}
): Promise<void> {
  const connection = new Connection(config.rpcUrl, {
    wsEndpoint: config.wsUrl,
    commitment: 'finalized',
  });
  activeConnection = connection;
  const programId = new PublicKey(config.programId);
  const [programConfigId] = PublicKey.findProgramAddressSync([Buffer.from('program_config')], programId);

  console.log('[Stream] Starting programSubscribe...');
  console.log(`[Stream] WebSocket: ${redactEndpoint(config.wsUrl)}`);

  let lastProcessedSlot = 0;
  let projectionIncomplete = false;
  // A malformed account must win even over a healthy cursor write already
  // awaiting the database. Preserve ordering without serializing projections.
  let stateWrites: Promise<void> = Promise.resolve();
  const writeStreamState = (fields: Parameters<typeof updateSyncState>[0]) => {
    const write = stateWrites.then(async () => {
      if (projectionIncomplete && fields.stream_connected !== false) return;
      await updateSyncState(fields);
    });
    stateWrites = write.catch(() => {});
    return write;
  };
  let accountsProcessed = 0;
  let errorsInWindow = 0;
  let lastErrorWindowReset = Date.now();
  let lastSyncStateUpdateAt = 0;

  try {
    // ProgramConfig is the immutable mint authority. Fail before subscribing
    // if deploy configuration points at any other token mint.
    const canonicalDungMint = await resolveCanonicalDungMint(connection);

    subscriptionId = connection.onProgramAccountChange(
      programId,
      async (accountInfo, context) => {
        reconnectAttempts = 0; // Reset backoff on successful notification
        const slot = context.slot;
        if (projectionIncomplete) return;

        // Gap detection only moves forward. Older callbacks may finish after
        // newer ones, but they must not move the in-memory cursor backward.
        if (lastProcessedSlot > 0 && slot - lastProcessedSlot > 100) {
          console.warn(`[Stream] Gap detected: last=${lastProcessedSlot}, current=${slot}`);
          onGapDetected?.(lastProcessedSlot, slot);
        }

        lastProcessedSlot = Math.max(lastProcessedSlot, slot);

        const data = Buffer.from(accountInfo.accountInfo.data);
        const pubkey = accountInfo.accountId.toBase58();
        const isProgramConfig = accountInfo.accountId.equals(programConfigId);

        if (identifyAccountType(data)?.startsWith('Stage1') && (options.includeStage1===false || !programVersionWindow.stage1Available)) return;

        let decoded = decodeAccount(data);
        if (isProgramConfig && (decoded?.type !== 'ProgramConfig' || !accountInfo.accountInfo.owner.equals(programId))) {
          programVersionWindow.invalidate(new Error('ProgramConfig notification could not be verified'));
          decoded = null;
        }
        if (!decoded) {
          // Log unrecognized accounts at debug level (may be non-boulder_rollers)
          const identified = isProgramConfig ? 'ProgramConfig' : identifyAccountType(data);
          if (identified) {
            projectionIncomplete = true;
            console.error(`[Stream] Projection incomplete: failed to decode ${identified} ${pubkey}; restart with a healthy snapshot required`);
            await writeStreamState({ stream_connected: false });
            onGapDetected?.(lastProcessedSlot, slot);
          }
          return;
        }

        // Track per-type counts
        typeCounters.set(decoded.type, (typeCounters.get(decoded.type) || 0) + 1);

        try {
          const wrote = await routeAccount(decoded, pubkey, slot, {
            connection,
          });
          if (projectionIncomplete) return;
          if (wrote) {
            accountsProcessed++;
            if (accountsProcessed % 100 === 0) {
              console.log(`[Stream] Processed ${accountsProcessed} account updates (slot ${slot})`);
            }

            const now = Date.now();
            if (accountsProcessed === 1 || accountsProcessed % 10 === 0 || now - lastSyncStateUpdateAt >= SYNC_STATE_UPDATE_INTERVAL) {
              await writeStreamState({
                last_account_slot: slot,
                last_account_sync_at: new Date(),
                stream_connected: true,
              }).catch(() => {}); // Non-critical
              lastSyncStateUpdateAt = now;
            }
          }
        } catch (err) {
          errorsInWindow++;
          console.error(`[Stream] Failed to write ${decoded.type} ${pubkey}:`, err);
        }

        // Log type breakdown periodically
        const now = Date.now();
        if (now - lastTypeLogAt > TYPE_LOG_INTERVAL && typeCounters.size > 0) {
          const breakdown = Array.from(typeCounters.entries())
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => `${type}=${count}`)
            .join(', ');
          console.log(`[Stream] Type breakdown (last ${Math.round((now - lastTypeLogAt) / 1000)}s): ${breakdown}`);
          typeCounters.clear();
          lastTypeLogAt = now;
        }

        // Log error rate
        if (now - lastErrorWindowReset > 60_000) {
          if (errorsInWindow > 0) {
            console.warn(`[Stream] ${errorsInWindow} write errors in last 60s`);
          }
          errorsInWindow = 0;
          lastErrorWindowReset = now;
        }
      },
      'finalized'
    );

    mintSubscriptionId = connection.onAccountChange(
      canonicalDungMint.address,
      async (_accountInfo, context) => {
        try {
          const observation = await refreshDungMintSupply(connection, canonicalDungMint);
          if (!observation.written) {
            throw new Error('DungMintState projection row is missing');
          }
          console.log(
            `[Stream] DUNG mint supply ${observation.amount} at slot ${observation.slot} (notification ${context.slot})`
          );
        } catch (err) {
          console.error('[Stream] Failed to project DUNG mint supply:', err);
        }
      },
      'finalized'
    );

    // Close the snapshot-to-subscribe gap. A burn before this subscription was
    // established is captured here; a later callback wins by mint-supply slot.
    const initialMintSupply = await refreshDungMintSupply(connection, canonicalDungMint);
    if (!initialMintSupply.written) {
      throw new Error('DungMintState projection row is missing');
    }

    await writeStreamState({
      stream_connected: true,
      stream_connected_since: new Date(),
    });

    console.log(`[Stream] Subscribed (program: ${subscriptionId}, DUNG mint: ${mintSubscriptionId})`);
  } catch (err) {
    console.error('[Stream] Failed to subscribe:', err);
    const failedProgramSubscriptionId = subscriptionId;
    const failedMintSubscriptionId = mintSubscriptionId;
    subscriptionId = null;
    mintSubscriptionId = null;
    if (activeConnection === connection) {
      activeConnection = null;
    }
    await removeSubscriptions(
      connection,
      failedProgramSubscriptionId,
      failedMintSubscriptionId
    );
    if (projectionIncomplete) {
      // Startup may fail while a malformed notification is being fenced.
      // A reconnect would reset that fence without a successful snapshot.
      await writeStreamState({ stream_connected: false }).catch(() => {});
      throw new ProjectionIncompleteError('Projection incomplete: malformed known account during subscription startup');
    }
    await scheduleReconnect(onGapDetected,options);
  }
}

async function removeSubscriptions(
  connection: Connection,
  programSubscriptionId: number | null,
  dungMintSubscriptionId: number | null
): Promise<void> {
  const removals: Promise<void>[] = [];
  if (programSubscriptionId !== null) {
    removals.push(connection.removeProgramAccountChangeListener(programSubscriptionId));
  }
  if (dungMintSubscriptionId !== null) {
    removals.push(connection.removeAccountChangeListener(dungMintSubscriptionId));
  }

  const results = await Promise.allSettled(removals);
  for (const result of results) {
    if (result.status === 'rejected') {
      console.warn('[Stream] Error unsubscribing:', result.reason);
    }
  }
}

/**
 * Stop the stream subscription.
 */
export async function stopStream(): Promise<void> {
  const connection = activeConnection;
  const programSubscriptionId = subscriptionId;
  const dungMintSubscriptionId = mintSubscriptionId;
  subscriptionId = null;
  mintSubscriptionId = null;
  activeConnection = null;

  if (connection) {
    await removeSubscriptions(
      connection,
      programSubscriptionId,
      dungMintSubscriptionId
    );
    console.log('[Stream] Unsubscribed');
  }

  await updateSyncState({
    stream_connected: false,
  }).catch(() => {});
}

/**
 * Reconnect with exponential backoff.
 */
async function scheduleReconnect(
  onGapDetected?: (lastSlot: number, currentSlot: number) => void,
  options: {includeStage1?:boolean} = {}
): Promise<void> {
  reconnectAttempts++;
  const backoffMs = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), MAX_BACKOFF_MS);

  await updateSyncState({
    stream_connected: false,
    stream_disconnects: reconnectAttempts,
  }).catch(() => {});

  console.log(`[Stream] Reconnecting in ${backoffMs}ms (attempt ${reconnectAttempts})...`);

  setTimeout(async () => {
    try {
      await startStream(onGapDetected,options);
    } catch (err) {
      console.error('[Stream] Reconnection failed:', err);
      if (err instanceof ProjectionIncompleteError) return;
      await scheduleReconnect(onGapDetected,options);
    }
  }, backoffMs);
}
