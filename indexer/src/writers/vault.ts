import crypto from 'crypto';
import { PublicKey } from '@solana/web3.js';
import { pubkeyToString, bytesToHex, isDefaultPubkey, bnToString, safeInt } from '../decoder';
import { upsert } from './common';
import * as db from '../db';
import { config } from '../config';
import {
  enqueueCanonDependency,
  parseCanonCommitment,
  quarantineCanonAccount,
  requireCanonIndexerProgramVersion,
  validateVaultClimbBinding,
} from './canon';
import {
  CURRENT_PROGRAM_VERSION,
  PROGRAM_VERSION_FAMILY,
} from '../generated-program-version';

// Full Record Board + Local Legend + separate payer/authority reaches the
// 1,232-byte legacy transaction ceiling at four VaultStake accounts.
export const SETTLEMENT_STAKER_TRIPWIRE_THRESHOLD = 4;
export const STAKER_REMAINDER_POLICY_MARKER = 0x5354_414B_4552_0001n;
const STAKER_REMAINDER_POLICY_VERSION = 1;

export function decodeStakerRemainderPolicyVersion(value: unknown): number {
  try {
    return BigInt(bnToString(value)) === STAKER_REMAINDER_POLICY_MARKER
      ? STAKER_REMAINDER_POLICY_VERSION
      : 0;
  } catch {
    return 0;
  }
}

/**
 * Write a decoded Vault account to indexed_vaults.
 *
 * Vault IDL fields:
 *   id: u64, signature: [u8;64], signatureHash: [u8;32], minter: PublicKey,
 *   mintEpoch: u64, rightsExpiresEpoch: u64, komHolder: PublicKey,
 *   komTimeS: u32, komSetEpoch: u64, name: [u8;64], avatarIpfs: [u8;46],
 *   slogan: [u8;128], calTributeAccumulated: u64, calTributeAccumulatedNext: u64,
 *   totalCalBurned: u64, totalDungEmitted: u64, totalCompletions: u64,
 *   totalCalStaked: u64, stakerCount: u32,
 *   rewardPerTokenStored/lastUpdateTime: deprecated Synthetix slots,
 *   rewardRate: retired slot reused as the staker-remainder policy marker,
 *   pendingRewards: u64,
 *   pendingRewardsNextWeek: u64, openSettlementWeek: u64,
 *   carryRecordRoyalty: u64, carryStakers: u64, carryLocalLegend: u64,
 *   carryPol: u64, carryTreasury: u64, totalStaked: u64,
 *   lastDistributionEpoch: u64, vertM: u32 (meters * 10), distanceM: u32,
 *   avgGradientPct: u16 (percent * 100), createdAt: i64, bump: u8
 */
export function decodeVaultMetricScalars(fields: Record<string, any>): {
  vertM: number;
  distanceM: number;
  avgGradientPct: number;
} {
  return {
    vertM: safeInt(fields.vertM) / 10,
    distanceM: safeInt(fields.distanceM),
    avgGradientPct: safeInt(fields.avgGradientPct) / 100,
  };
}

export function maybeWarnSettlementStakerTripwire(args: {
  vaultId: string;
  stakerCount: number;
  pda: string;
  slot: number;
}): void {
  if (args.stakerCount < SETTLEMENT_STAKER_TRIPWIRE_THRESHOLD) {
    return;
  }

  console.warn(
    '[SettlementTripwire] vault staker count reached legacy capacity threshold',
    {
      vault_id: args.vaultId,
      staker_count: args.stakerCount,
      threshold: SETTLEMENT_STAKER_TRIPWIRE_THRESHOLD,
      pda: args.pda,
      slot: args.slot,
      action: 'land settlement ALT or chunking before a fifth inventory account',
    }
  );
}

class CanonVaultProjectionError extends Error {}
class CanonVaultDependencyPending extends Error {}

function expectedVaultActivationPda(vaultId: string): { pda: string; bump: number } {
  let parsed: bigint;
  try {
    parsed = BigInt(vaultId);
  } catch {
    throw new CanonVaultProjectionError('Vault id cannot derive its activation PDA');
  }
  if (parsed < 0n || parsed > 0xffff_ffff_ffff_ffffn) {
    throw new CanonVaultProjectionError('Vault id cannot derive its activation PDA');
  }
  const idBytes = Buffer.alloc(8);
  idBytes.writeBigUInt64LE(parsed);
  const [pda, bump] = PublicKey.findProgramAddressSync(
    [Buffer.from('vault_activation'), idBytes],
    new PublicKey(config.programId)
  );
  return { pda: pda.toBase58(), bump };
}

async function writeCanonicalVaultProjection(args: {
  fields: Record<string, any>;
  pda: string;
  slot: number;
  vaultId: string;
  columns: string[];
  values: any[];
  programVersion: number;
}): Promise<boolean> {
  let binding: ReturnType<typeof validateVaultClimbBinding>;
  try {
    const parsed = parseCanonCommitment(args.fields.signature);
    const [expectedClimbPda] = PublicKey.findProgramAddressSync(
      [Buffer.from('climb'), Buffer.from(parsed.commitmentHashHex, 'hex')],
      new PublicKey(config.programId)
    );
    binding = validateVaultClimbBinding(
      args.fields,
      expectedClimbPda.toBase58()
    );
  } catch (error) {
    throw new CanonVaultProjectionError(
      error instanceof Error ? error.message : 'invalid V4-B Vault binding'
    );
  }
  const client = await db.getClient();
  try {
    await client.query('BEGIN');
    const resolution = await client.query(
      `SELECT indexed.canon_climb_id
       FROM public.indexed_climbs AS indexed
       JOIN public.canon_climbs AS canon
         ON canon.id = indexed.canon_climb_id
        AND canon.record_continuity_policy = 'new_record_board'
       WHERE indexed.pda = $1
         AND indexed.canon_commitment_hex = $2
         AND indexed.commitment_hash_hex = $3
         AND indexed.vault_pda = $4
         AND indexed.quarantined IS FALSE
       FOR SHARE OF indexed`,
      [
        binding.climbPda,
        binding.commitmentHex,
        binding.commitmentHashHex,
        args.pda,
      ]
    );
    if (resolution.rowCount !== 1) {
      throw new CanonVaultDependencyPending(
        'Vault is waiting for its exact finalized Climb projection'
      );
    }
    const canonClimbId = String(resolution.rows[0].canon_climb_id);
    const expectedActivation = expectedVaultActivationPda(args.vaultId);
    const expectedActivationPda = expectedActivation.pda;
    const expectedConstructorEvidenceHash = crypto
      .createHash('sha256')
      .update(Buffer.from('BR_VAULT_EMPTY_HISTORY_V2'))
      .update(new PublicKey(binding.climbPda).toBuffer())
      .update(new PublicKey(args.pda).toBuffer())
      .digest('hex');
    const activation = await client.query(
      `SELECT activation_status, vault_activation_pda, chain_slot
       FROM public.canon_vault_activations
       WHERE canon_climb_id = $1::uuid
         AND climb_pda = $2
         AND vault_id = $3::bigint
         AND vault_pda = $4
         AND activation_status IN ('reserved', 'confirmed', 'finalized')
       FOR UPDATE`,
      [canonClimbId, binding.climbPda, args.vaultId, args.pda]
    );
    if (activation.rowCount !== 1) {
      throw new CanonVaultProjectionError(
        'Vault has no exact backend activation reservation'
      );
    }
    const activationStatus = String(activation.rows[0].activation_status);
    if (String(activation.rows[0].vault_activation_pda) !== expectedActivationPda) {
      throw new CanonVaultProjectionError(
        'backend reservation has the wrong VaultActivation PDA'
      );
    }
    if (activationStatus === 'reserved') {
      throw new CanonVaultDependencyPending(
        'Vault is waiting for backend transaction confirmation'
      );
    }
    if (!['confirmed', 'finalized'].includes(activationStatus)) {
      throw new CanonVaultProjectionError(
        'Vault activation reservation is not confirmable'
      );
    }
    const chainActivation = await client.query(
      `SELECT vault_id, pda, is_active, seed_generation,
              leaderboard_seeded, seed_cutoff_at, economics_start_epoch,
              matched_users, matched_completions, activated_at,
              lower(btrim(evidence_hash::text)) AS evidence_hash, chain_slot
       FROM public.indexed_vault_activations
       WHERE vault_id = $1::bigint
         AND pda = $2
         AND is_active IS TRUE
         AND seed_generation = 2
         AND seed_completions_written = 0
         AND leaderboard_seeded IS TRUE
         AND matched_users = 0
         AND matched_completions = 0
         AND created_at > 0
         AND created_at = activated_at
         AND created_at = last_seed_at
         AND created_at = seed_cutoff_at
         AND lower(btrim(evidence_hash::text)) = $3
         AND bump = $4
       FOR SHARE`,
      [
        args.vaultId,
        expectedActivationPda,
        expectedConstructorEvidenceHash,
        expectedActivation.bump,
      ]
    );
    if (chainActivation.rowCount !== 1) {
      const observedActivation = await client.query(
        `SELECT vault_id, pda, is_active, seed_generation,
                leaderboard_seeded, evidence_hash, chain_slot
         FROM public.indexed_vault_activations
         WHERE vault_id = $1::bigint
         FOR SHARE`,
        [args.vaultId]
      );
      if (observedActivation.rowCount === 0) {
        throw new CanonVaultDependencyPending(
          'Vault is waiting for its chain-derived VaultActivation projection'
        );
      }
      throw new CanonVaultProjectionError(
        'VaultActivation projection does not authorize this exact Vault slot'
      );
    }
    const chainActivationRow = chainActivation.rows[0];
    const activatedAtUnix = Number(chainActivationRow.activated_at);
    if (!Number.isSafeInteger(activatedAtUnix) || activatedAtUnix <= 0) {
      throw new CanonVaultProjectionError(
        'VaultActivation projection has an invalid activation timestamp'
      );
    }
    const activatedAt = new Date(activatedAtUnix * 1000);
    const columns = [
      ...args.columns,
      'climb_pda',
      'canon_climb_id',
      'canon_commitment_hex',
      'canon_binding_status',
      'backfill_status',
      'backfill_started_at',
      'backfill_completed_at',
      'backfill_completions_found',
      'backfill_error',
      'on_chain_seeding_status',
      'on_chain_seeded_at',
      'on_chain_activated_at',
      'on_chain_seeding_error',
      'activation_seed_generation',
      'activation_seed_cutoff_at',
      'activation_economics_start_epoch',
      'activation_matched_users',
      'activation_matched_completions',
      'activation_evidence_hash',
    ];
    const values = [
      ...args.values,
      binding.climbPda,
      canonClimbId,
      binding.commitmentHex,
      'active',
      'completed',
      activatedAt,
      activatedAt,
      safeInt(chainActivationRow.matched_completions),
      null,
      'active',
      activatedAt,
      activatedAt,
      null,
      safeInt(chainActivationRow.seed_generation),
      bnToString(chainActivationRow.seed_cutoff_at),
      bnToString(chainActivationRow.economics_start_epoch),
      safeInt(chainActivationRow.matched_users),
      safeInt(chainActivationRow.matched_completions),
      String(chainActivationRow.evidence_hash),
    ];
    const placeholders = values.map((_, index) => `$${index + 1}`).join(', ');
    const updates = columns
      .filter((column) => column !== 'id')
      .map((column) => `${column} = EXCLUDED.${column}`)
      .join(', ');
    const projected = await client.query(
      `INSERT INTO public.indexed_vaults (${columns.join(', ')})
       VALUES (${placeholders})
       ON CONFLICT (id) DO UPDATE SET ${updates}
       WHERE EXCLUDED.chain_slot > public.indexed_vaults.chain_slot
          OR (
            EXCLUDED.chain_slot = public.indexed_vaults.chain_slot
            AND EXCLUDED.indexed_at >= public.indexed_vaults.indexed_at
          )
       RETURNING id`,
      values
    );
    if (projected.rowCount !== 1) {
      throw new CanonVaultProjectionError('canonical Vault projection did not advance');
    }
    const finalized = await client.query(
      `SELECT preparation_id, activation_status
       FROM public.finalize_canon_vault_activation($1, $2, $3, $4)`,
      [
        binding.climbPda,
        args.pda,
        args.slot,
        expectedConstructorEvidenceHash,
      ]
    );
    if (
      finalized.rowCount !== 1
      || finalized.rows[0].activation_status !== 'finalized'
    ) {
      throw new CanonVaultProjectionError('canonical Vault activation did not finalize');
    }
    await client.query(
      'DELETE FROM public.canon_indexer_pending WHERE account_pda = $1',
      [args.pda]
    );
    await client.query('COMMIT');
    return true;
  } catch (error) {
    await client.query('ROLLBACK');
    if (error instanceof CanonVaultDependencyPending) {
      await enqueueCanonDependency({
        pda: args.pda,
        reason: error.message,
        slot: args.slot,
      });
      return false;
    }
    if (error instanceof CanonVaultProjectionError) {
      await quarantineCanonAccount({
        pda: args.pda,
        accountType: 'Vault',
        reason: error.message,
        programVersion: args.programVersion,
        slot: args.slot,
        fields: args.fields,
      });
      return false;
    }
    throw error;
  } finally {
    client.release();
  }
}

export async function writeVaultForProgram(
  fields: Record<string, any>,
  pda: string,
  slot: number,
  programVersion: number,
  programFamily: string
): Promise<boolean> {
  const signatureHex = bytesToHex(fields.signature);
  const signatureHashHex = bytesToHex(fields.signatureHash);
  const minter = pubkeyToString(fields.minter);
  const komHolder = isDefaultPubkey(fields.komHolder)
    ? null
    : pubkeyToString(fields.komHolder);

  // Decode name from fixed-size byte array, trimming null bytes
  const nameBytes = Buffer.from(fields.name);
  const name = nameBytes.toString('utf-8').replace(/\0/g, '').trim();

  // Decode optional metadata fields
  const avatarBytes = Buffer.from(fields.avatarIpfs);
  const avatarIpfs = avatarBytes.every((b: number) => b === 0)
    ? null
    : avatarBytes.toString('utf-8').replace(/\0/g, '').trim();

  const sloganBytes = Buffer.from(fields.slogan);
  const slogan = sloganBytes.every((b: number) => b === 0)
    ? null
    : sloganBytes.toString('utf-8').replace(/\0/g, '').trim();

  // createdAt is an i64 Unix timestamp — safe to use Number() for Date
  // conversion since Unix timestamps fit well within Number.MAX_SAFE_INTEGER.
  const createdAt = new Date(Number(fields.createdAt) * 1000);
  const metrics = decodeVaultMetricScalars(fields);
  const vaultId = bnToString(fields.id);
  const stakerCount = safeInt(fields.stakerCount);

  maybeWarnSettlementStakerTripwire({
    vaultId,
    stakerCount,
    pda,
    slot,
  });

  const columns = [
    'id', 'signature_hex', 'signature_hash_hex', 'pda',
    'minter', 'mint_epoch', 'rights_expires_epoch',
    'kom_holder', 'kom_time_s', 'kom_set_epoch',
    'name', 'avatar_ipfs', 'slogan',
    'cal_tribute_accumulated', 'cal_tribute_accumulated_next',
    'total_cal_burned', 'total_dung_emitted',
    'total_completions', 'total_cal_staked', 'staker_count',
    'pending_rewards', 'pending_rewards_next_week', 'open_settlement_week',
    'carry_record_royalty', 'carry_stakers', 'staker_remainder_policy_version',
    'carry_local_legend',
    'carry_pol', 'carry_treasury',
    'total_staked', 'last_distribution_epoch',
    'vert_m', 'distance_m', 'avg_gradient_pct',
    'created_at', 'chain_slot', 'indexed_at', 'bump',
  ];

  // C1 fix: All u64 token/economic amounts use bnToString() -> NUMERIC columns.
  // Only small counters (u32, u16, u8) and timestamps (i64, safe range) use Number().
  // Retired Synthetix slots remain in account/table layout compatibility. Keep
  // their raw values private while projecting the rewardRate policy marker as
  // a versioned carry interpretation for current read models.
  const values = [
    vaultId,
    signatureHex,
    signatureHashHex,
    pda,
    minter,
    bnToString(fields.mintEpoch),
    bnToString(fields.rightsExpiresEpoch),
    komHolder,
    safeInt(fields.komTimeS),         // u32
    bnToString(fields.komSetEpoch),
    name,
    avatarIpfs,
    slogan,
    bnToString(fields.calTributeAccumulated),
    bnToString(fields.calTributeAccumulatedNext),
    bnToString(fields.totalCalBurned),
    bnToString(fields.totalDungEmitted),
    bnToString(fields.totalCompletions),
    bnToString(fields.totalCalStaked),
    stakerCount,                      // u32
    bnToString(fields.pendingRewards),
    bnToString(fields.pendingRewardsNextWeek),
    bnToString(fields.openSettlementWeek),
    bnToString(fields.carryRecordRoyalty),
    bnToString(fields.carryStakers),
    decodeStakerRemainderPolicyVersion(fields.rewardRate),
    bnToString(fields.carryLocalLegend),
    bnToString(fields.carryPol),
    bnToString(fields.carryTreasury),
    bnToString(fields.totalStaked),
    bnToString(fields.lastDistributionEpoch),
    metrics.vertM,
    metrics.distanceM,
    metrics.avgGradientPct,
    createdAt,
    slot,
    new Date(),
    safeInt(fields.bump),             // u8
  ];

  const canonFamilyClaimed = programFamily === 'V4-B' || programVersion >= 0x4b;
  if (canonFamilyClaimed) {
    try {
      requireCanonIndexerProgramVersion(programVersion, programFamily);
    } catch (error) {
      await quarantineCanonAccount({
        pda,
        accountType: 'Vault',
        reason: error instanceof Error ? error.message : 'invalid V4-B program family',
        programVersion,
        slot,
        fields,
      });
      return false;
    }
    try {
      return await writeCanonicalVaultProjection({
        fields,
        pda,
        slot,
        vaultId,
        columns,
        values,
        programVersion,
      });
    } catch (error) {
      if (!(error instanceof CanonVaultProjectionError)) {
        throw error;
      }
      await quarantineCanonAccount({
        pda,
        accountType: 'Vault',
        reason: error.message,
        programVersion,
        slot,
        fields,
      });
      return false;
    }
  }

  await upsert('indexed_vaults', columns, values, ['id']);
  return true;
}

export async function writeVault(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<boolean> {
  return writeVaultForProgram(
    fields,
    pda,
    slot,
    CURRENT_PROGRAM_VERSION,
    PROGRAM_VERSION_FAMILY
  );
}

/**
 * Write a decoded VaultCounter singleton.
 */
export async function writeVaultCounter(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_vault_counter',
    ['id', 'count', 'pda', 'chain_slot', 'indexed_at', 'bump'],
    [1, bnToString(fields.count), pda, slot, new Date(), safeInt(fields.bump)],
    ['id']
  );
}
