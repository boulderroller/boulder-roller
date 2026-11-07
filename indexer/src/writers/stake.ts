import { pubkeyToString, bnToString, safeInt } from '../decoder';
import { upsert } from './common';

/**
 * Write a decoded VaultStake account to indexed_stakes.
 *
 * VaultStake IDL fields:
 *   user: PublicKey, vaultId: u64, calStaked: u64, lpTokens: u64,
 *   stakedAt: i64, pendingEffectiveWeekPlusOne: u64,
 *   effectiveLpTokens: u64, rewardsEarned: u64, pendingLpTokens: u64,
 *   bump: u8
 * Accounts not yet touched by the snapshot program still expose the former
 * eligibleFromEpoch value through the pending-week byte slot. Keep that value
 * in the legacy projection column until the chain lazily migrates the account.
 */
export async function writeStake(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  const lpTokens = bnToString(fields.lpTokens);
  const rawPendingWeek = bnToString(fields.pendingEffectiveWeekPlusOne);
  const effectiveLpTokens = bnToString(fields.effectiveLpTokens);
  const pendingLpTokens = bnToString(fields.pendingLpTokens);
  const legacyLayout =
    BigInt(effectiveLpTokens) === 0n &&
    BigInt(pendingLpTokens) === 0n &&
    (BigInt(lpTokens) > 0n || BigInt(rawPendingWeek) > 0n);

  await upsert(
    'indexed_stakes',
    [
      'user_pubkey', 'vault_id',
      'cal_staked', 'lp_tokens', 'staked_at',
      'eligible_from_epoch',
      'user_reward_per_token_paid', 'amount',
      'pending_effective_week_plus_one',
      'effective_lp_tokens', 'rewards_earned',
      'pending_lp_tokens',
      'pda', 'chain_slot', 'indexed_at', 'bump',
    ],
    [
      pubkeyToString(fields.user),
      bnToString(fields.vaultId),           // u64
      bnToString(fields.calStaked),
      lpTokens,
      bnToString(fields.stakedAt),          // i64
      legacyLayout ? rawPendingWeek : '0',
      '0',
      '0',
      legacyLayout ? '0' : rawPendingWeek,
      legacyLayout ? '0' : effectiveLpTokens,
      bnToString(fields.rewardsEarned),
      legacyLayout ? '0' : pendingLpTokens,
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),                 // u8
    ],
    ['user_pubkey', 'vault_id']
  );
}

/**
 * Write a decoded VaultCompletion account to indexed_completions.
 *
 * VaultCompletion IDL fields:
 *   user: PublicKey, vaultId: u64, completions: u32, bestTimeS: u32,
 *   lastCompletedAt: i64, totalCalTributed: u64, bump: u8
 */
export async function writeCompletion(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_completions',
    [
      'user_pubkey', 'vault_id',
      'completions', 'best_time_s', 'last_completed_at',
      'total_cal_tributed',
      'pda', 'chain_slot', 'indexed_at', 'bump',
    ],
    [
      pubkeyToString(fields.user),
      bnToString(fields.vaultId),           // u64
      safeInt(fields.completions),          // u32
      safeInt(fields.bestTimeS),            // u32
      bnToString(fields.lastCompletedAt),   // i64
      bnToString(fields.totalCalTributed),
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),                 // u8
    ],
    ['user_pubkey', 'vault_id']
  );
}
