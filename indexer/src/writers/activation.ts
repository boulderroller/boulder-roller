import { bnToString, bytesToHex, safeInt } from '../decoder';
import { upsert } from './common';

/**
 * Write a decoded VaultActivation account to indexed_vault_activations.
 *
 * The on-chain account stores both operational seed counters and the canonical
 * activation audit boundary. BoulderScan joins this with indexed_vaults'
 * backend job mirror for progress display only.
 */
export async function writeActivation(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  const evidenceHash = fields.evidenceHash ? bytesToHex(fields.evidenceHash) : null;

  await upsert(
    'indexed_vault_activations',
    [
      'vault_id',
      'pda',
      'is_active',
      'seed_completions_written',
      'leaderboard_seeded',
      'created_at',
      'activated_at',
      'last_seed_at',
      'seed_generation',
      'seed_cutoff_at',
      'economics_start_epoch',
      'matched_users',
      'matched_completions',
      'evidence_hash',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      bnToString(fields.vaultId),
      pda,
      Boolean(fields.isActive),
      safeInt(fields.seedCompletionsWritten),
      Boolean(fields.leaderboardSeeded),
      bnToString(fields.createdAt),
      bnToString(fields.activatedAt),
      bnToString(fields.lastSeedAt),
      safeInt(fields.seedGeneration),
      bnToString(fields.seedCutoffAt),
      bnToString(fields.economicsStartEpoch),
      safeInt(fields.matchedUsers),
      safeInt(fields.matchedCompletions),
      evidenceHash,
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['vault_id']
  );
}
