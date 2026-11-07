import { finalizedHeads } from './finalized-head';
import { Connection, PublicKey } from '@solana/web3.js';
import { config } from './config';
import { decodeAccount, bnToString } from './decoder';
import { query } from './db';
import { routeAccount } from './writers';
import { readDungMintSupply } from './supply';
import { writeDungMintSupply } from './writers/legend';
import { quarantineCanonAccount } from './writers/canon';
import { CURRENT_PROGRAM_VERSION } from './generated-program-version';

// Singleton PDA seeds, mirrored from protocol/anchor/programs/boulder_rollers/src/constants.rs.
const VAULT_COUNTER_SEED = Buffer.from('vault_counter');
const DUNG_MINT_STATE_SEED = Buffer.from('dung_mint_state');

function deriveSingletonPda(seed: Buffer, programId: PublicKey): PublicKey {
  const [pda] = PublicKey.findProgramAddressSync([seed], programId);
  return pda;
}

/**
 * Periodic reconciliation: verify indexed state matches chain truth.
 *
 * Reconciliation checks (ordered by cost):
 *   1. Vault count: compare VaultCounter on-chain vs indexed_vaults COUNT
 *   2. Supply state: compare DungMintState on-chain vs indexed_supply
 *   3. Sample verification: spot-check N random vaults against chain
 *   4. Full scan: compare ALL accounts (expensive, daily only)
 */

export interface ReconciliationResult {
  runType: string;
  accountsChecked: number;
  discrepanciesFound: number;
  discrepancies: Array<{
    table: string;
    key: string;
    field: string;
    indexed: any;
    chain: any;
  }>;
  autoCorrected: number;
  durationMs: number;
}

export async function reconcilePendingCanonAccounts(options: {
  connection?: Connection;
  route?: typeof routeAccount;
  decode?: typeof decodeAccount;
} = {}): Promise<{ checked: number; finalized: number }> {
  const connection = options.connection ?? new Connection(config.rpcUrl, 'finalized');
  const route = options.route ?? routeAccount;
  const decode = options.decode ?? decodeAccount;
  const pending = await query(
    `SELECT account_pda, chain_slot
     FROM public.canon_indexer_pending
     WHERE next_retry_at <= now()
     ORDER BY next_retry_at, account_pda
     LIMIT 50`
  );
  let finalized = 0;
  for (const row of pending.rows) {
    const pda = String(row.account_pda);
    const response = await connection.getAccountInfoAndContext(
      new PublicKey(pda),
      'finalized'
    );
    if (!response.value) {
      await query(
        `UPDATE public.canon_indexer_pending
         SET attempts = attempts + 1,
             reason = 'Vault account is not yet visible at finalized commitment',
             next_retry_at = now() + interval '5 seconds',
             last_observed_at = now()
         WHERE account_pda = $1`,
        [pda]
      );
      continue;
    }
    const decoded = decode(Buffer.from(response.value.data));
    if (!decoded || decoded.type !== 'Vault') {
      await quarantineCanonAccount({
        pda,
        accountType: 'Vault',
        reason: 'pending canonical account no longer decodes as a Vault',
        programVersion: CURRENT_PROGRAM_VERSION,
        slot: response.context.slot,
        fields: decoded?.fields ?? {},
      });
      await query(
        'DELETE FROM public.canon_indexer_pending WHERE account_pda = $1',
        [pda]
      );
      continue;
    }
    const wrote = await route(decoded, pda, response.context.slot);
    if (wrote) {
      finalized++;
      await query(
        'DELETE FROM public.canon_indexer_pending WHERE account_pda = $1',
        [pda]
      );
    }
  }
  return { checked: pending.rowCount ?? pending.rows.length, finalized };
}

/**
 * Run a vault count reconciliation (fast, <1s).
 */
export async function reconcileVaultCount(): Promise<ReconciliationResult> {
  const start = Date.now();
  const connection = new Connection(config.rpcUrl, 'finalized');
  const programId = new PublicKey(config.programId);

  const discrepancies: ReconciliationResult['discrepancies'] = [];
  let autoCorrected = 0;

  // Singleton PDA: direct getAccountInfo is cheaper than getProgramAccounts
  // with a discriminator filter (which scans the whole program).
  const vaultCounterPda = deriveSingletonPda(VAULT_COUNTER_SEED, programId);
  const vaultCounterResponse = await connection.getAccountInfoAndContext(
    vaultCounterPda,
    'finalized'
  );
  const accountInfo = vaultCounterResponse.value;

  if (!accountInfo || !accountInfo.data) {
    console.warn('[Reconcile] No VaultCounter found on chain');
    return { runType: 'vault_count', accountsChecked: 0, discrepanciesFound: 0, discrepancies: [], autoCorrected: 0, durationMs: Date.now() - start };
  }

  const decoded = decodeAccount(Buffer.from(accountInfo.data));
  if (!decoded) {
    console.error('[Reconcile] Failed to decode VaultCounter');
    return { runType: 'vault_count', accountsChecked: 1, discrepanciesFound: 1, discrepancies: [{ table: 'VaultCounter', key: 'singleton', field: 'data', indexed: 'decode_error', chain: 'raw' }], autoCorrected: 0, durationMs: Date.now() - start };
  }
  const chainCount = parseInt(bnToString(decoded.fields.count), 10);

  // Compare with indexed count
  const result = await query('SELECT COUNT(*) as cnt FROM indexed_vaults');
  const indexedCount = parseInt(result.rows[0].cnt, 10);

  // Also check the indexed_vault_counter table
  const counterResult = await query('SELECT count FROM indexed_vault_counter WHERE id = 1');
  const indexedCounterValue = counterResult.rows.length > 0 ? Number(counterResult.rows[0].count) : null;

  if (indexedCount !== chainCount) {
    discrepancies.push({
      table: 'indexed_vaults',
      key: 'count',
      field: 'row_count',
      indexed: indexedCount,
      chain: chainCount,
    });
    console.warn(`[Reconcile] Vault count mismatch: indexed=${indexedCount}, chain=${chainCount}`);
  }

  if (indexedCounterValue !== null && indexedCounterValue !== chainCount) {
    discrepancies.push({
      table: 'indexed_vault_counter',
      key: 'singleton',
      field: 'count',
      indexed: indexedCounterValue,
      chain: chainCount,
    });

    // Auto-correct the counter
    await routeAccount(decoded, vaultCounterPda.toBase58(), vaultCounterResponse.context.slot);
    autoCorrected++;
  }

  const duration = Date.now() - start;
  console.log(`[Reconcile] Vault count: chain=${chainCount}, indexed=${indexedCount} (${duration}ms)`);

  // Log to reconciliation_log
  await logReconciliation('vault_count', 1, discrepancies.length, discrepancies, autoCorrected, duration, chainCount, indexedCount);

  return {
    runType: 'vault_count',
    accountsChecked: 1,
    discrepanciesFound: discrepancies.length,
    discrepancies,
    autoCorrected,
    durationMs: duration,
  };
}

/**
 * Run a supply state reconciliation (fast, <1s).
 * Compares indexed_supply against on-chain DungMintState before auto-correcting.
 */
export async function reconcileSupply(): Promise<ReconciliationResult> {
  const start = Date.now();
  const connection = new Connection(config.rpcUrl, 'finalized');
  const programId = new PublicKey(config.programId);

  const discrepancies: ReconciliationResult['discrepancies'] = [];
  let autoCorrected = 0;

  const dungMintStatePda = deriveSingletonPda(DUNG_MINT_STATE_SEED, programId);
  const dungMintStateResponse = await connection.getAccountInfoAndContext(
    dungMintStatePda,
    'finalized'
  );
  const accountInfo = dungMintStateResponse.value;

  if (!accountInfo || !accountInfo.data) {
    return { runType: 'supply', accountsChecked: 0, discrepanciesFound: 0, discrepancies: [], autoCorrected: 0, durationMs: Date.now() - start };
  }

  const decoded = decodeAccount(Buffer.from(accountInfo.data));
  if (!decoded) {
    return { runType: 'supply', accountsChecked: 1, discrepanciesFound: 1, discrepancies: [{ table: 'indexed_supply', key: 'singleton', field: 'data', indexed: 'decode_error', chain: 'raw' }], autoCorrected: 0, durationMs: Date.now() - start };
  }
  const mintSupply = await readDungMintSupply(connection);

  // Fetch current indexed state to compare before correcting
  const indexedResult = await query('SELECT * FROM indexed_supply WHERE id = 1');
  const indexed = indexedResult.rows.length > 0 ? indexedResult.rows[0] : null;

  // Key supply fields to compare
  const supplyFields = [
    { chain: 'totalMinted', db: 'total_minted' },
    { chain: 'totalBurned', db: 'total_burned' },
    { chain: 'maxSupply', db: 'max_supply' },
    { chain: 'currentEmissionRateBps', db: 'current_emission_rate_bps' },
    { chain: 'lastHalvingEpoch', db: 'last_halving_epoch' },
    { chain: 'communityReserved', db: 'community_reserved' },
    { chain: 'reservationPolicyVersion', db: 'reservation_policy_version' },
  ];

  if (indexed) {
    for (const f of supplyFields) {
      // C1 fix: use bnToString() instead of String(Number()) to avoid precision loss
      const chainVal = bnToString(decoded.fields[f.chain]);
      const indexedVal = String(indexed[f.db]);
      if (chainVal !== indexedVal) {
        discrepancies.push({
          table: 'indexed_supply',
          key: 'singleton',
          field: f.db,
          indexed: indexedVal,
          chain: chainVal,
        });
        console.warn(`[Reconcile] Supply mismatch on ${f.db}: indexed=${indexedVal}, chain=${chainVal}`);
      }
    }
    const indexedMintSupply = indexed.spl_mint_supply == null
      ? null
      : String(indexed.spl_mint_supply);
    if (indexedMintSupply !== mintSupply.amount) {
      discrepancies.push({
        table: 'indexed_supply',
        key: 'singleton',
        field: 'spl_mint_supply',
        indexed: indexedMintSupply,
        chain: mintSupply.amount,
      });
      console.warn(
        `[Reconcile] Supply mismatch on spl_mint_supply: indexed=${indexedMintSupply}, chain=${mintSupply.amount}`
      );
    }
  } else {
    discrepancies.push({
      table: 'indexed_supply',
      key: 'singleton',
      field: 'row',
      indexed: null,
      chain: 'exists',
    });
    console.warn('[Reconcile] Supply row missing from indexed_supply, chain has DungMintState');
  }

  // Auto-correct by upserting the latest state
  await routeAccount(decoded, dungMintStatePda.toBase58(), dungMintStateResponse.context.slot);
  await writeDungMintSupply(mintSupply.amount, mintSupply.slot);
  if (discrepancies.length > 0) {
    autoCorrected = discrepancies.length;
    console.log(`[Reconcile] Supply auto-corrected ${autoCorrected} discrepancies`);
  }

  const duration = Date.now() - start;
  await logReconciliation('supply', 2, discrepancies.length, discrepancies, autoCorrected, duration, null, null);

  return { runType: 'supply', accountsChecked: 2, discrepanciesFound: discrepancies.length, discrepancies, autoCorrected, durationMs: duration };
}

/**
 * Sample-check 5 random vaults against on-chain state.
 * Fetches each vault's PDA from chain, decodes it, and compares key economic fields.
 */
export async function reconcileSampleVaults(): Promise<ReconciliationResult> {
  const start = Date.now();
  const connection = new Connection(config.rpcUrl, 'finalized');

  const discrepancies: ReconciliationResult['discrepancies'] = [];
  let autoCorrected = 0;
  let accountsChecked = 0;

  // Pick 5 random vaults from the indexed table
  const vaultResult = await query(
    `SELECT id, pda, total_completions, total_cal_staked, staker_count,
            pending_rewards, pending_rewards_next_week, open_settlement_week,
            carry_record_royalty
       FROM indexed_vaults
      ORDER BY RANDOM()
      LIMIT 5`
  );

  if (vaultResult.rows.length === 0) {
    console.log('[Reconcile] No indexed vaults to sample');
    return { runType: 'sample_vaults', accountsChecked: 0, discrepanciesFound: 0, discrepancies: [], autoCorrected: 0, durationMs: Date.now() - start };
  }

  for (const row of vaultResult.rows) {
    accountsChecked++;
    const vaultPda = row.pda;

    try {
      const vaultResponse = await connection.getAccountInfoAndContext(
        new PublicKey(vaultPda),
        'finalized'
      );
      const accountInfo = vaultResponse.value;
      if (!accountInfo || !accountInfo.data) {
        discrepancies.push({
          table: 'indexed_vaults',
          key: vaultPda,
          field: 'account',
          indexed: 'exists',
          chain: 'missing',
        });
        console.warn(`[Reconcile] Vault ${vaultPda} exists in DB but not on chain`);
        continue;
      }

      const decoded = decodeAccount(Buffer.from(accountInfo.data));
      if (!decoded || decoded.type !== 'Vault') {
        discrepancies.push({
          table: 'indexed_vaults',
          key: vaultPda,
          field: 'type',
          indexed: 'Vault',
          chain: decoded?.type || 'decode_error',
        });
        continue;
      }

      // Compare key economic fields
      const fieldsToCheck = [
        { chain: 'totalCompletions', db: 'total_completions' },
        { chain: 'totalCalStaked', db: 'total_cal_staked' },
        { chain: 'stakerCount', db: 'staker_count' },
        { chain: 'pendingRewards', db: 'pending_rewards' },
        { chain: 'pendingRewardsNextWeek', db: 'pending_rewards_next_week' },
        { chain: 'openSettlementWeek', db: 'open_settlement_week' },
        { chain: 'carryRecordRoyalty', db: 'carry_record_royalty' },
      ];

      let vaultHasDiscrepancy = false;
      for (const f of fieldsToCheck) {
        // C1 fix: use bnToString() instead of String(Number()) to avoid precision loss
        const chainVal = bnToString(decoded.fields[f.chain]);
        const indexedVal = String(row[f.db]);
        if (chainVal !== indexedVal) {
          discrepancies.push({
            table: 'indexed_vaults',
            key: vaultPda,
            field: f.db,
            indexed: indexedVal,
            chain: chainVal,
          });
          console.warn(`[Reconcile] Vault ${vaultPda} mismatch on ${f.db}: indexed=${indexedVal}, chain=${chainVal}`);
          vaultHasDiscrepancy = true;
        }
      }

      // Auto-correct by re-upserting from chain if any discrepancy found
      if (vaultHasDiscrepancy) {
        await routeAccount(decoded, vaultPda, vaultResponse.context.slot);
        autoCorrected++;
        console.log(`[Reconcile] Vault ${vaultPda} auto-corrected`);
      }
    } catch (err) {
      console.error(`[Reconcile] Error checking vault ${vaultPda}:`, err);
    }
  }

  const duration = Date.now() - start;
  console.log(`[Reconcile] Sample vaults: checked=${accountsChecked}, discrepancies=${discrepancies.length}, corrected=${autoCorrected} (${duration}ms)`);
  await logReconciliation('sample_vaults', accountsChecked, discrepancies.length, discrepancies, autoCorrected, duration, null, null);

  return {
    runType: 'sample_vaults',
    accountsChecked,
    discrepanciesFound: discrepancies.length,
    discrepancies,
    autoCorrected,
    durationMs: duration,
  };
}

/**
 * Log a reconciliation run to the reconciliation_log table.
 */
async function logReconciliation(
  runType: string,
  accountsChecked: number,
  discrepanciesFound: number,
  discrepancies: any[],
  autoCorrected: number,
  durationMs: number,
  vaultCountChain: number | null,
  vaultCountIndexed: number | null
): Promise<void> {
  try {
    let currentSlot: number | null = null;
    try {
      const connection = new Connection(config.rpcUrl, 'finalized');
      currentSlot = (await finalizedHeads.read(connection)).slot;
    } catch { /* non-critical */ }

    await query(
      `INSERT INTO reconciliation_log
        (run_type, accounts_checked, discrepancies_found, discrepancies,
         auto_corrected, chain_slot, vault_count_chain, vault_count_indexed,
         duration_ms, status)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'completed')`,
      [
        runType,
        accountsChecked,
        discrepanciesFound,
        discrepancies.length > 0 ? JSON.stringify(discrepancies) : null,
        autoCorrected,
        currentSlot,
        vaultCountChain,
        vaultCountIndexed,
        durationMs,
      ]
    );
  } catch (err) {
    console.error('[Reconcile] Failed to log reconciliation:', err);
  }
}
