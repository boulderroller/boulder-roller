import { finalizedHeads } from '../finalized-head';
import { Connection, PublicKey } from '@solana/web3.js';
import { BorshAccountsCoder } from '@coral-xyz/anchor';
import bs58 from 'bs58';
import { config, redactEndpoint } from '../config';
import { decodeAccount, getAccountTypeNames, DecodedAccount } from '../decoder';
import { routeAccount } from '../writers';
import { updateSyncState } from '../writers/common';
import { refreshDungMintSupply } from '../supply';
import { retryTransientRpc, SNAPSHOT_RPC_RETRY_MS } from '../rpc-retry';
import { programVersionWindow } from '../program-version-window';

const WRITE_BATCH_SIZE = 50;

export interface SnapshotResult {
  total: number;
  indexed: number;
  skipped: number;
  decodeFailures: number;
  writeFailures: number;
  fetchFailures: number;
}

export type SnapshotRuntimeStatus =
  | 'not_required'
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed';

export interface SnapshotRuntimeState {
  status: SnapshotRuntimeStatus;
  total: number;
  indexed: number;
  skipped: number;
  decode_failures: number;
  write_failures: number;
  fetch_failures: number;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

function emptySnapshotResult(): SnapshotResult {
  return {
    total: 0,
    indexed: 0,
    skipped: 0,
    decodeFailures: 0,
    writeFailures: 0,
    fetchFailures: 0,
  };
}

function runtimeState(
  status: SnapshotRuntimeStatus,
  result: SnapshotResult,
  startedAt: string | null,
  completedAt: string | null,
  error: string | null
): SnapshotRuntimeState {
  return {
    status,
    total: result.total,
    indexed: result.indexed,
    skipped: result.skipped,
    decode_failures: result.decodeFailures,
    write_failures: result.writeFailures,
    fetch_failures: result.fetchFailures,
    started_at: startedAt,
    completed_at: completedAt,
    error,
  };
}

let snapshotRuntimeState = runtimeState(
  config.mode === 'replay' ? 'not_required' : 'pending',
  emptySnapshotResult(),
  null,
  null,
  null
);

export function getSnapshotRuntimeState(): SnapshotRuntimeState {
  return { ...snapshotRuntimeState };
}

export function assertSnapshotProjectionComplete(result: SnapshotResult): void {
  const failures: string[] = [];
  const describe = (count: number, kind: string) =>
    `${count} ${kind} failure${count === 1 ? '' : 's'}`;

  if (result.decodeFailures > 0) {
    failures.push(describe(result.decodeFailures, 'decode'));
  }
  if (result.writeFailures > 0) {
    failures.push(describe(result.writeFailures, 'write'));
  }
  if (result.fetchFailures > 0) {
    failures.push(describe(result.fetchFailures, 'fetch'));
  }
  if (failures.length > 0) {
    throw new Error(`[Snapshot] Projection incomplete: ${failures.join(', ')}`);
  }
}

/**
 * Fetch every program account and replace the Postgres projection at one
 * finalized slot floor. Any decode, write, or account-type fetch failure makes
 * the snapshot unhealthy and prevents the sync cursor from advancing.
 */
export async function runSnapshot(options: {includeStage1?:boolean} = {}): Promise<SnapshotResult> {
  const result = emptySnapshotResult();
  const startedAt = new Date().toISOString();
  snapshotRuntimeState = runtimeState('running', result, startedAt, null, null);

  try {
    const connection = new Connection(config.rpcUrl, 'finalized');
    const programId = new PublicKey(config.programId);

    console.log('[Snapshot] Starting full program account snapshot...');
    console.log(`[Snapshot] Program: ${config.programId}`);
    console.log(`[Snapshot] RPC: ${redactEndpoint(config.rpcUrl)}`);

    let snapshotMinSlot: number;
    try {
      snapshotMinSlot = (await finalizedHeads.read(connection)).slot;
    } catch (err) {
      throw new Error(`[Snapshot] Could not get current slot before snapshot write: ${err}`);
    }
    let currentSlot = snapshotMinSlot;

    const accountTypes = getAccountTypeNames().filter(
      name => !name.startsWith('Stage1') || (options.includeStage1!==false && programVersionWindow.stage1Available)
    );
    console.log(`[Snapshot] Will fetch ${accountTypes.length} account types`);
    const fetchRetryDeadline = Date.now() + SNAPSHOT_RPC_RETRY_MS;

    for (const typeName of accountTypes) {
      try {
        const discriminator = BorshAccountsCoder.accountDiscriminator(typeName);
        const discBytes = Buffer.from(discriminator);
        let decodeFailuresForType = 0;
        let ignoredForType = 0;
        let writtenForType = 0;

        console.log(
          `[Snapshot] Fetching ${typeName} accounts (disc: ${discBytes.toString('hex').slice(0, 16)}...)...`
        );

        const response = await retryTransientRpc(() => connection.getProgramAccounts(programId, {
          commitment: 'finalized',
          minContextSlot: snapshotMinSlot,
          withContext: true,
          filters: [
            {
              memcmp: {
                offset: 0,
                bytes: bs58.encode(discBytes),
              },
            },
          ],
        }), { label: `snapshot ${typeName}`, deadline: fetchRetryDeadline });
        const accounts = response.value;
        const responseSlot = response.context.slot;
        currentSlot = Math.max(currentSlot, responseSlot);

        console.log(`[Snapshot] Found ${accounts.length} ${typeName} accounts`);
        result.total += accounts.length;

        const decodedBatch: Array<{ decoded: DecodedAccount; pubkey: string }> = [];
        for (const { pubkey, account } of accounts) {
          const data = Buffer.from(account.data);
          const pubkeyStr = pubkey.toBase58();
          const decoded = decodeAccount(data);

          if (!decoded || decoded.type !== typeName) {
            decodeFailuresForType++;
            result.decodeFailures++;
            result.skipped++;
            console.warn(
              `[Snapshot] Failed to decode ${typeName} ${pubkeyStr} (len=${data.length})`
            );
            continue;
          }
          decodedBatch.push({ decoded, pubkey: pubkeyStr });
        }

        for (let i = 0; i < decodedBatch.length; i += WRITE_BATCH_SIZE) {
          const chunk = decodedBatch.slice(i, i + WRITE_BATCH_SIZE);
          const results = await Promise.allSettled(
            chunk.map(({ decoded, pubkey }) =>
              routeAccount(decoded, pubkey, responseSlot, { connection })
            )
          );

          for (let j = 0; j < results.length; j++) {
            const writeResult = results[j];
            if (writeResult.status === 'fulfilled' && writeResult.value) {
              result.indexed++;
              writtenForType++;
            } else if (writeResult.status === 'fulfilled') {
              result.skipped++;
              ignoredForType++;
            } else {
              result.writeFailures++;
              console.error(
                `[Snapshot] Failed to write ${typeName} ${chunk[j].pubkey}:`,
                writeResult.reason
              );
            }
          }
        }

        if (decodedBatch.length > 0) {
          console.log(
            `[Snapshot] Wrote ${writtenForType}/${decodedBatch.length} ${typeName} accounts in ${Math.ceil(decodedBatch.length / WRITE_BATCH_SIZE)} batches`
          );
        }
        if (decodeFailuresForType > 0 || ignoredForType > 0) {
          console.log(
            `[Snapshot] ${typeName} decode_failures=${decodeFailuresForType} intentionally_ignored=${ignoredForType}`
          );
        }
      } catch (err) {
        result.fetchFailures++;
        console.error(`[Snapshot] Failed to fetch ${typeName} accounts:`, err);
      } finally {
        snapshotRuntimeState = runtimeState('running', result, startedAt, null, null);
      }
    }

    assertSnapshotProjectionComplete(result);

    const mintSupply = await refreshDungMintSupply(connection);
    if (!mintSupply.written) {
      throw new Error('[Snapshot] DungMintState row is missing; canonical SPL supply was not projected');
    }
    currentSlot = Math.max(currentSlot, mintSupply.slot);

    await updateSyncState({
      last_account_slot: currentSlot,
      last_account_sync_at: new Date(),
      last_snapshot_at: new Date(),
      last_snapshot_slot: currentSlot,
      snapshot_account_count: result.indexed,
    });

    const completedAt = new Date().toISOString();
    snapshotRuntimeState = runtimeState('succeeded', result, startedAt, completedAt, null);
    console.log(
      `[Snapshot] Complete: ${result.indexed}/${result.total} accounts indexed at slot ${currentSlot} (${result.skipped} intentionally skipped)`
    );
    return result;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    snapshotRuntimeState = runtimeState(
      'failed',
      result,
      startedAt,
      new Date().toISOString(),
      message
    );
    throw err;
  }
}
