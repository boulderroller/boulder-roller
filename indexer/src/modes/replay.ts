import {
  Connection,
  PublicKey,
  ConfirmedSignatureInfo,
  type VersionedTransactionResponse,
} from '@solana/web3.js';
import { finalizedHeads } from '../finalized-head';
import { recordReplayCoverage } from '../lag-monitor';
import { config } from '../config';
import { runStage1ProgramStream, stage1Connection } from '../stage1-program-stream';
import { decodeInstruction, decodeEvents, getInstructionAccountMeta } from '../decoder';
import { query as databaseQuery } from '../db';
import { programVersionWindow, isStage1Instruction } from '../program-version-window';
import { requireIndexedReleaseSettlementWeek } from '../releaseWeek';
import { routeFinalizedExpectedAccount } from '../writers';
import { updateSyncState as persistSyncState, getSyncState } from '../writers/common';

const query: typeof databaseQuery = async (...args) => {
  programVersionWindow.assertNoFailure();
  return databaseQuery(...args);
};
const updateSyncState: typeof persistSyncState = async (...args) => {
  programVersionWindow.assertNoFailure();
  return persistSyncState(...args);
};

/**
 * Replay mode: fetch historical transactions via getSignaturesForAddress
 * and getTransaction, decode instructions and events, and store them
 * in indexed_transactions and indexed_events.
 *
 * This fills two gaps that programSubscribe cannot:
 *   1. Transaction/event history (programSubscribe only delivers account state)
 *   2. Missed account updates during WebSocket disconnects
 *
 * Uses cursor-based pagination from last processed signature.
 */

const BATCH_SIZE = 100; // Signatures per getSignaturesForAddress call
const TX_FETCH_CONCURRENCY = 5; // Parallel getTransaction calls
const TX_FETCH_RETRY_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

type ProcessTransactionResult = {
  events: number;
  processed: boolean;
};

export function summarizeReplayResults(
  results: ProcessTransactionResult[]
): { processed: number; events: number; allProcessed: boolean } {
  return {
    processed: results.filter((result) => result.processed).length,
    events: results.reduce((total, result) => total + result.events, 0),
    allProcessed: results.every((result) => result.processed),
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function runReplay(): Promise<{ processed: number; events: number }> {
  programVersionWindow.assertNoFailure();
  const sync = await getSyncState(), cursor = sync?.last_tx_signature;
  if (cursor && programVersionWindow.stage1Available) return runStage1ProgramStream(stage1Connection(), processTransaction);
  const connection = new Connection(config.rpcUrl, 'finalized'), programId = new PublicKey(config.programId);
  let head;
  try { head = await finalizedHeads.read(connection); }
  catch (error) { recordReplayCoverage(connection, programId); throw error; }
  let processed = 0, events = 0, before: string | undefined, newest: ConfirmedSignatureInfo | undefined;
  let complete = false, allProcessed = true;
  while (!complete) {
    let page: ConfirmedSignatureInfo[];
    try {
      // Include the cursor in the page: an empty or pruned response must not
      // masquerade as an idle, fully covered history after a restart.
      page = await connection.getSignaturesForAddress(programId, {
        limit: BATCH_SIZE, minContextSlot: head.slot, ...(before ? { before } : {}),
      }, 'finalized');
      if (before || page[0]?.signature !== cursor) recordReplayCoverage(connection, programId);
      newest ??= page[0];
      const stop = cursor ? page.findIndex(info => info.signature === cursor) : -1;
      if (stop >= 0) {
        if (page[stop].slot !== Number(sync!.last_tx_slot)) throw new Error('Replay cursor slot mismatch');
        complete = true;
        page = page.slice(0, stop);
      } else if (page.length < BATCH_SIZE) {
        if (cursor) throw new Error('Finalized replay cursor missing');
        complete = true;
      }
    } catch {
      recordReplayCoverage(connection, programId);
      console.warn('[Replay] Signature range unavailable; cursor and coverage held');
      break;
    }
    for (let i = 0; i < page.length; i += TX_FETCH_CONCURRENCY) {
      const results = await Promise.all(page.slice(i, i + TX_FETCH_CONCURRENCY).map(async info => {
        try { return await processTransaction(connection, info); }
        catch { return { processed: false, events: 0 }; }
      }));
      const summary = summarizeReplayResults(results);
      processed += summary.processed; events += summary.events; allProcessed &&= summary.allProcessed;
    }
    before = page[page.length - 1]?.signature;
  }
  if (complete && allProcessed && newest) {
    await updateSyncState({ last_tx_signature: newest.signature, last_tx_slot: newest.slot, last_tx_sync_at: new Date() });
    recordReplayCoverage(connection, programId, { head, signature: newest.signature, slot: newest.slot });
  }
  return { processed, events };
}

/**
 * Process a single transaction: fetch, decode instruction + events, store.
 */
export async function processTransaction(
  connection: Connection,
  sigInfo: ConfirmedSignatureInfo,
  retained?: VersionedTransactionResponse
): Promise<ProcessTransactionResult> {
  const { signature, slot, blockTime, err } = sigInfo;

  // Fetch the full transaction
  const tx = retained ?? await fetchTransactionWithRetry(connection, signature);

  if (!tx) {
    console.warn(`[Replay] Transaction ${signature} is not available yet; leaving cursor unchanged for retry`);
    return { events: 0, processed: false };
  }

  const transactionError = tx.meta?.err ?? err;
  const status = transactionError ? 'failed' : 'success';
  const errorMessage = transactionError ? JSON.stringify(transactionError) : null;
  const feeLamports = tx.meta?.fee || 0;
  const computeUnits = tx.meta?.computeUnitsConsumed || null;

  // Find boulder_rollers instructions in the transaction
  const programId = config.programId;
  const message = tx.transaction.message;

  // For versioned transactions, we need to handle both legacy and v0
  let instructionCount = 0;

  // Get the compiled instructions
  const compiledInstructions = message.compiledInstructions || [];
  const staticKeys = message.staticAccountKeys || [];

  // Legacy transaction format fallback
  const legacyInstructions = (message as any).instructions || [];

  const allInstructions = compiledInstructions.length > 0
    ? compiledInstructions
    : legacyInstructions;

  for (let idx = 0; idx < allInstructions.length; idx++) {
    const ix = allInstructions[idx];
    const programIdIndex = ix.programIdIndex;

    // Check if this instruction is for our program
    let ixProgramId: string;
    if (staticKeys.length > programIdIndex) {
      ixProgramId = staticKeys[programIdIndex].toBase58();
    } else {
      continue;
    }

    if (ixProgramId !== programId) continue;

    // Decode the instruction data
    const ixData = Buffer.from(ix.data);
    const decoded = decodeInstruction(ixData);

    if (!decoded) continue;

    // Build labeled instruction accounts from IDL metadata
    const accountKeyIndexes = ix.accounts || ix.accountKeyIndexes || [];
    const ixAccountMeta = getInstructionAccountMeta(decoded.name);
    const labeledAccounts: Record<string, { pubkey: string; isMut: boolean; isSigner: boolean }> = {};

    for (let ai = 0; ai < accountKeyIndexes.length; ai++) {
      const pubkey = staticKeys[accountKeyIndexes[ai]]?.toBase58() || `index:${accountKeyIndexes[ai]}`;
      const meta = ixAccountMeta?.[ai];
      const label = meta?.name || `account_${ai}`;
      labeledAccounts[label] = {
        pubkey,
        isMut: meta?.isMut ?? false,
        isSigner: meta?.isSigner ?? false,
      };
    }

    // Store the decoded instruction
    await query(
      `INSERT INTO indexed_transactions
        (signature, slot, block_time, status, error_message,
         fee_lamports, compute_units,
         instruction_index, instruction_name, instruction_args, instruction_accounts,
         indexed_at)
       SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now()
       ${programVersionWindow.stage1Available ? `WHERE stage1_indexer_filter_checkpoint(jsonb_build_object('args',$10::jsonb,'accounts',$11::jsonb))=jsonb_build_object('args',$10::jsonb,'accounts',$11::jsonb)` : ''}
       ON CONFLICT (signature, instruction_index)
       DO UPDATE SET
         status = EXCLUDED.status,
         instruction_args = EXCLUDED.instruction_args,
         indexed_at = now()`,
      [
        signature,
        slot,
        blockTime,
        status,
        errorMessage,
        feeLamports,
        computeUnits,
        idx,
        decoded.name,
        JSON.stringify(isStage1Instruction(decoded.name) ? {} : decoded.data),
        JSON.stringify(isStage1Instruction(decoded.name) ? {} : labeledAccounts),
      ]
    );

    instructionCount++;
  }

  // Parse events from logs
  let eventCount = 0;
  if (tx.meta?.logMessages) {
    const events = decodeEvents(tx.meta.logMessages);

    for (let i = 0; i < events.length; i++) {
      const event = events[i];
      const serializedFields = serializeEventFields(event.data);

      // Extract denormalized fields for query performance
      const vaultId = extractVaultId(event);
      const userPubkey = extractUserPubkey(event);

      const stored=await query(
        `INSERT INTO indexed_events
          (tx_signature, event_index, event_name, fields, slot, block_time,
           vault_id, user_pubkey, indexed_at)
         SELECT $1, $2, $3, $4, $5, $6, $7, $8, now()
         ${programVersionWindow.stage1Available ? `WHERE stage1_indexer_filter_checkpoint(jsonb_build_object('fields',$4::jsonb,'person',$8::text))=jsonb_build_object('fields',$4::jsonb,'person',$8::text)` : ''}
         ON CONFLICT (tx_signature,event_index) DO UPDATE SET fields=EXCLUDED.fields,user_pubkey=EXCLUDED.user_pubkey
         RETURNING fields`,
        [
          signature,
          i,
          event.name,
          JSON.stringify(serializedFields),
          slot,
          blockTime,
          vaultId,
          userPubkey,
        ]
      );
      // The SQL predicate holds deletion's wallet locks through insertion.
      // A permanent tombstone omits only this personal event; pending deletion
      // raises and remains retryable. Other events still project normally.
      if(programVersionWindow.stage1Available&&!stored.rows.length)continue;
      if (shouldProjectCanonicalEvent(transactionError)) {
        try {
        await projectEventProjection(
          connection,
          signature,
          i,
          event.name,
          serializedFields,
          slot,
          blockTime ?? null
        );
        }catch(error){
          // Deletion may finish between the receipt and its derived projection.
          // Only the authoritative permanent-tombstone error is terminal.
          if((error as any)?.code!=='55000'||(error as Error).message!=='account_deleted')throw error;
        }
      }
      eventCount++;
    }
  }

  return { events: eventCount, processed: true };
}

async function fetchTransactionWithRetry(
  connection: Connection,
  signature: string
): Promise<VersionedTransactionResponse | null> {
  for (let attempt = 0; attempt <= TX_FETCH_RETRY_DELAYS_MS.length; attempt++) {
    const tx = await connection.getTransaction(signature, {
      maxSupportedTransactionVersion: 0,
      commitment: 'finalized',
    });

    if (tx) return tx;

    if (attempt < TX_FETCH_RETRY_DELAYS_MS.length) {
      await sleep(TX_FETCH_RETRY_DELAYS_MS[attempt]);
    }
  }

  return null;
}

/**
 * Extract vault_id from event fields for denormalization.
 */
function extractVaultId(event: { name: string; data: Record<string, any> }): string | null {
  // Events that have vaultId field
  if (event.data.vaultId !== undefined) return String(event.data.vaultId);
  // VaultCreated uses 'id'
  if (event.name === 'VaultCreated' && event.data.id !== undefined) return String(event.data.id);
  return null;
}

/**
 * Extract user pubkey from event fields for denormalization.
 */
function extractUserPubkey(event: { name: string; data: Record<string, any> }): string | null {
  // Different events use different field names for the user
  const userFields = ['user', 'rider', 'person', 'staker', 'owner', 'minter', 'winner', 'holder', 'recipient'];
  for (const field of userFields) {
    if (event.data[field]) {
      const pk = event.data[field];
      if (typeof pk === 'string') return pk;
      if (pk.toBase58) return pk.toBase58();
    }
  }
  return null;
}

/**
 * Serialize event fields to JSON-safe format.
 * Converts PublicKey objects to base58, BN/bigint to string, byte arrays to hex.
 * C1 fix: BN.toNumber() overflows for u64 values > 2^53. Use .toString() instead.
 */
export function serializeEventFields(data: Record<string, any>): Record<string, any> {
  const result: Record<string, any> = {};
  for (const [key, value] of Object.entries(data)) {
    if (value === null || value === undefined) {
      result[key] = null;
    } else if (value.toBase58) {
      result[key] = value.toBase58();
    } else if (typeof value === 'bigint') {
      result[key] = value.toString();
    } else if (Buffer.isBuffer(value) || (Array.isArray(value) && value.every(
      (v: any) => Number.isInteger(v) && v >= 0 && v <= 255
    ))) {
      result[key] = Buffer.from(value).toString('hex');
    } else if (Array.isArray(value)) {
      result[key] = value.map(item => serializeEventFields({ value: item }).value);
    } else if (value.toString && value.toString !== Object.prototype.toString
        && typeof value === 'object') {
      // BN.js values retain their full decimal precision.
      result[key] = value.toString();
    } else if (typeof value === 'object') {
      // Anchor enums and nested structs must remain structured JSON.
      result[key] = serializeEventFields(value);
    } else {
      result[key] = value;
    }
  }
  return result;
}

function readField<T = any>(
  fields: Record<string, any>,
  ...keys: string[]
): T | null {
  for (const key of keys) {
    if (fields[key] !== undefined && fields[key] !== null) {
      return fields[key] as T;
    }
  }
  return null;
}

function parseNumericString(value: unknown): string {
  if (value === null || value === undefined || value === '') return '0';
  return String(value);
}

function parseIntField(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
}

export function shouldProjectCanonicalEvent(transactionError: unknown): boolean {
  return transactionError === null || transactionError === undefined;
}

export function decodeStakerAllocationEpochs(fields: Record<string, any>): {
  epoch: number;
  eligibleFromEpoch: number;
  snapshotEpoch: number;
} {
  const epoch = parseIntField(readField(fields, 'epoch'));
  return {
    epoch,
    eligibleFromEpoch: parseIntField(
      readField(fields, 'eligibleFromEpoch', 'eligible_from_epoch')
    ),
    snapshotEpoch: epoch,
  };
}

function parseBoundedIntegerString(
  value: unknown,
  fieldName: string,
  maximum: bigint
): string {
  const encoded = String(value ?? '');
  if (!/^\d+$/.test(encoded)) {
    throw new Error(`${fieldName} must be a non-negative integer`);
  }
  const parsed = BigInt(encoded);
  if (parsed > maximum) {
    throw new Error(`${fieldName} exceeds its supported integer range`);
  }
  return parsed.toString();
}

function parseNonNegativeIntegerString(value: unknown, fieldName: string): string {
  return parseBoundedIntegerString(value, fieldName, (1n << 64n) - 1n);
}

export function decodeClimbCompletionFlow(fields: Record<string, any>): {
  evidenceVersion: number;
  releaseAuthority: string | null;
  vaultId: string;
  rideAttestation: string;
  completionEvidenceHash: Buffer;
  creditedSettlementWeek: string;
  calTributed: string;
} {
  const evidenceVersion = parseIntField(
    readField(fields, 'evidenceVersion', 'evidence_version') ?? 1
  );
  if (evidenceVersion !== 1 && evidenceVersion !== 2 && evidenceVersion !== 3) {
    throw new Error('evidenceVersion must be 1, 2, or 3');
  }
  const rawReleaseAuthority = readField(
    fields,
    'releaseAuthority',
    'release_authority'
  );
  const releaseAuthority = rawReleaseAuthority === null
    ? null
    : new PublicKey(String(rawReleaseAuthority)).toBase58();
  if (evidenceVersion === 3 && releaseAuthority === null) {
    throw new Error('evidenceVersion 3 requires releaseAuthority');
  }
  if (evidenceVersion !== 3 && releaseAuthority !== null) {
    throw new Error('releaseAuthority is valid only for evidenceVersion 3');
  }
  const rideAttestation = new PublicKey(
    String(readField(fields, 'rideAttestation', 'ride_attestation') ?? '')
  ).toBase58();
  const evidenceHex = String(
    readField(fields, 'completionEvidenceHash', 'completion_evidence_hash') ?? ''
  );
  if (!/^[0-9a-fA-F]{64}$/.test(evidenceHex)) {
    throw new Error('completionEvidenceHash must encode exactly 32 bytes');
  }

  return {
    evidenceVersion,
    releaseAuthority,
    vaultId: parseBoundedIntegerString(
      readField(fields, 'vaultId', 'vault_id'),
      'vaultId',
      (1n << 64n) - 1n
    ),
    rideAttestation,
    completionEvidenceHash: Buffer.from(evidenceHex, 'hex'),
    creditedSettlementWeek: parseBoundedIntegerString(
      readField(fields, 'creditedSettlementWeek', 'credited_settlement_week'),
      'creditedSettlementWeek',
      (1n << 64n) - 1n
    ),
    calTributed: parseNonNegativeIntegerString(
      readField(fields, 'calTributed', 'cal_tributed'),
      'calTributed'
    ),
  };
}

const completionFlowEventVersions: Record<string, { evidenceVersion: 1 | 2 | 3 }> = {
  ClimbCompletionFlowAssigned: { evidenceVersion: 1 },
  ClimbCompletionFlowAssignedV2: { evidenceVersion: 2 },
  ReleasedClimbCompletionFlowAssigned: { evidenceVersion: 3 },
};

export function decodeClimbCompletionFlowEvent(
  eventName: string,
  fields: Record<string, any>
): ReturnType<typeof decodeClimbCompletionFlow> {
  const expectedEvidenceVersion = completionFlowEventVersions[eventName]?.evidenceVersion;
  if (expectedEvidenceVersion === undefined) {
    throw new Error(`${eventName} is not a completion-flow event`);
  }
  const flow = decodeClimbCompletionFlow(fields);
  if (flow.evidenceVersion !== expectedEvidenceVersion) {
    throw new Error(
      `${eventName} declared evidence version ${flow.evidenceVersion}, expected ${expectedEvidenceVersion}`
    );
  }
  return flow;
}

async function projectEventProjection(
  connection: Connection,
  signature: string,
  eventIndex: number,
  eventName: string,
  fields: Record<string, any>,
  slot: number,
  blockTime: number | null
): Promise<void> {
  if (eventName === 'HeldRideReleaseAuthorized') {
    const releaseAuthority = readEventPublicKey(
      fields,
      'releaseAuthority',
      'release_authority'
    );
    await routeFinalizedExpectedAccount(
      connection,
      releaseAuthority,
      'HeldRideReleaseAuthority',
      slot
    );
    return;
  }
  if (eventName === 'ReleasedCalCredited') {
    const releaseAuthority = readEventPublicKey(
      fields,
      'releaseAuthority',
      'release_authority'
    );
    await routeFinalizedExpectedAccount(
      connection,
      releaseAuthority,
      'HeldRideReleaseAuthority',
      slot
    );
    await requireIndexedReleaseSettlementWeek(
      releaseAuthority,
      parseBoundedIntegerString(
        readField(fields, 'releaseSettlementWeek', 'release_settlement_week'),
        'releaseSettlementWeek',
        (1n << 64n) - 1n
      )
    );
    await routeFinalizedExpectedAccount(
      connection,
      readEventPublicKey(fields, 'calMintReceipt', 'cal_mint_receipt'),
      'ReleasedCalMintReceipt',
      slot
    );
    return;
  }
  if (eventName === 'ReleasedClimbCompleted') {
    const releaseAuthority = readEventPublicKey(
      fields,
      'releaseAuthority',
      'release_authority'
    );
    await routeFinalizedExpectedAccount(
      connection,
      releaseAuthority,
      'HeldRideReleaseAuthority',
      slot
    );
    await routeFinalizedExpectedAccount(
      connection,
      readEventPublicKey(
        fields,
        'climbCompletionReceipt',
        'climb_completion_receipt'
      ),
      'ReleasedClimbCompletionReceipt',
      slot
    );
    return;
  }
  if (eventName in completionFlowEventVersions) {
    const flow = decodeClimbCompletionFlowEvent(eventName, fields);
    if (flow.evidenceVersion === 3) {
      await routeFinalizedExpectedAccount(
        connection,
        flow.releaseAuthority as string,
        'HeldRideReleaseAuthority',
        slot
      );
      await requireIndexedReleaseSettlementWeek(
        flow.releaseAuthority as string,
        flow.creditedSettlementWeek
      );
    }
    await query(
      `INSERT INTO indexed_climb_completion_flows
        (tx_signature, event_index, release_authority_pda,
         vault_id, ride_attestation,
         completion_evidence_hash, completion_evidence_version,
         credited_settlement_week, cal_tributed,
         slot, block_time, indexed_at)
       VALUES
        ($1, $2, $3,
         $4, $5,
         $6, $7,
         $8, $9,
         $10, $11, now())
       ON CONFLICT (tx_signature, event_index)
       DO UPDATE SET
         release_authority_pda = EXCLUDED.release_authority_pda,
         vault_id = EXCLUDED.vault_id,
         ride_attestation = EXCLUDED.ride_attestation,
         completion_evidence_hash = EXCLUDED.completion_evidence_hash,
         completion_evidence_version = EXCLUDED.completion_evidence_version,
         credited_settlement_week = EXCLUDED.credited_settlement_week,
         cal_tributed = EXCLUDED.cal_tributed,
         slot = EXCLUDED.slot,
         block_time = EXCLUDED.block_time,
         indexed_at = now()`,
      [
        signature,
        eventIndex,
        flow.releaseAuthority,
        flow.vaultId,
        flow.rideAttestation,
        flow.completionEvidenceHash,
        flow.evidenceVersion,
        flow.creditedSettlementWeek,
        flow.calTributed,
        slot,
        blockTime,
      ]
    );
    return;
  }

  if (eventName === 'EpochRewardsDistributed') {
    await query(
      `INSERT INTO indexed_epoch_distributions
        (tx_signature, event_index, vault_id, epoch,
         total_distributed, leaderboard_distributed, staker_distributed,
         local_legend_distributed, pol_distributed, protocol_distributed,
         staker_count, unlock_pct, locked_staker_amount,
         slot, block_time, indexed_at)
       VALUES
        ($1, $2, $3, $4,
         $5, $6, $7,
         $8, $9, $10,
         $11, $12, $13,
         $14, $15, now())
       ON CONFLICT (tx_signature, event_index)
       DO UPDATE SET
         vault_id = EXCLUDED.vault_id,
         epoch = EXCLUDED.epoch,
         total_distributed = EXCLUDED.total_distributed,
         leaderboard_distributed = EXCLUDED.leaderboard_distributed,
         staker_distributed = EXCLUDED.staker_distributed,
         local_legend_distributed = EXCLUDED.local_legend_distributed,
         pol_distributed = EXCLUDED.pol_distributed,
         protocol_distributed = EXCLUDED.protocol_distributed,
         staker_count = EXCLUDED.staker_count,
         unlock_pct = EXCLUDED.unlock_pct,
         locked_staker_amount = EXCLUDED.locked_staker_amount,
         slot = EXCLUDED.slot,
         block_time = EXCLUDED.block_time,
         indexed_at = now()`,
      [
        signature,
        eventIndex,
        parseIntField(readField(fields, 'vaultId', 'vault_id')),
        parseIntField(readField(fields, 'epoch')),
        parseNumericString(readField(fields, 'totalDistributed', 'total_distributed')),
        parseNumericString(readField(fields, 'leaderboardDistributed', 'leaderboard_distributed')),
        parseNumericString(readField(fields, 'stakerDistributed', 'staker_distributed')),
        parseNumericString(readField(fields, 'localLegendDistributed', 'local_legend_distributed')),
        parseNumericString(readField(fields, 'polDistributed', 'pol_distributed')),
        parseNumericString(readField(fields, 'protocolDistributed', 'protocol_distributed')),
        parseIntField(readField(fields, 'stakerCount', 'staker_count')),
        parseIntField(readField(fields, 'unlockPct', 'unlock_pct')),
        parseNumericString(readField(fields, 'lockedStakerAmount', 'locked_staker_amount')),
        slot,
        blockTime,
      ]
    );
    return;
  }

  if (eventName === 'StakerAllocation') {
    const epochs = decodeStakerAllocationEpochs(fields);
    await query(
      `INSERT INTO indexed_staker_allocations
        (tx_signature, event_index, vault_id, epoch, staker,
         amount, lp_tokens, eligible_from_epoch, snapshot_epoch,
         slot, block_time, indexed_at)
       VALUES
        ($1, $2, $3, $4, $5,
         $6, $7, $8, $9,
         $10, $11, now())
       ON CONFLICT (tx_signature, event_index)
       DO UPDATE SET
         vault_id = EXCLUDED.vault_id,
         epoch = EXCLUDED.epoch,
         staker = EXCLUDED.staker,
         amount = EXCLUDED.amount,
         lp_tokens = EXCLUDED.lp_tokens,
         eligible_from_epoch = EXCLUDED.eligible_from_epoch,
         snapshot_epoch = EXCLUDED.snapshot_epoch,
         slot = EXCLUDED.slot,
         block_time = EXCLUDED.block_time,
         indexed_at = now()`,
      [
        signature,
        eventIndex,
        parseIntField(readField(fields, 'vaultId', 'vault_id')),
        epochs.epoch,
        String(readField(fields, 'staker') ?? ''),
        parseNumericString(readField(fields, 'amount')),
        parseNumericString(readField(fields, 'lpTokens', 'lp_tokens')),
        epochs.eligibleFromEpoch,
        epochs.snapshotEpoch,
        slot,
        blockTime,
      ]
    );
  }
}

function readEventPublicKey(
  fields: Record<string, any>,
  ...keys: string[]
): string {
  const value = readField(fields, ...keys);
  if (value === null) {
    throw new Error(`${keys[0]} is required for release projection`);
  }
  return new PublicKey(String(value)).toBase58();
}

/**
 * Run a replay sweep that drains the full backlog (for periodic use alongside stream).
 * Loops through all batches of transactions newer than the last cursor,
 * so that backlogs of >100 transactions are never silently dropped.
 */
export async function runReplaySweep(): Promise<{ processed: number; events: number }> {
  return runReplay();
}
