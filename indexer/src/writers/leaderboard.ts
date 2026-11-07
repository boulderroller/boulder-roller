import { pubkeyToString, bnToString, safeInt } from '../decoder';
import { upsert } from './common';

export interface ProjectedLeaderboardEntry {
  user: string;
  time_s: number;
  recorded_at: string;
  position: number;
  rank: number;
  tie_size: number;
  is_tied: boolean;
}

export function projectLeaderboardEntries(entries: any[]): ProjectedLeaderboardEntry[] {
  const projected = entries.map((entry: any, index: number) => ({
    user: pubkeyToString(entry.user),
    time_s: safeInt(entry.timeS),
    recorded_at: bnToString(entry.recordedAt),
    position: index + 1,
    rank: index + 1,
    tie_size: 1,
    is_tied: false,
  }));

  let groupStart = 0;
  while (groupStart < projected.length) {
    const groupTime = projected[groupStart].time_s;
    let groupEnd = groupStart + 1;
    while (groupEnd < projected.length && projected[groupEnd].time_s === groupTime) {
      groupEnd += 1;
    }

    const tieSize = groupEnd - groupStart;
    for (let index = groupStart; index < groupEnd; index += 1) {
      projected[index].rank = groupStart + 1;
      projected[index].tie_size = tieSize;
      projected[index].is_tied = tieSize > 1;
    }
    groupStart = groupEnd;
  }

  return projected;
}

/**
 * Write a decoded VaultLeaderboard account to indexed_leaderboards.
 *
 * VaultLeaderboard IDL fields:
 *   vaultId: u64, entries: Vec<LeaderEntry>, lastUpdated: i64, bump: u8
 *
 * LeaderEntry:
 *   user: PublicKey, timeS: u32, recordedAt: i64
 *
 * We store entries as JSONB for single-row reads.
 */
export async function writeLeaderboard(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  // Convert the Vec<LeaderEntry> to a JSON-friendly array.
  // C1 fix: recordedAt is i64, use bnToString() to avoid overflow.
  // timeS is u32 (safe for Number).
  const entries = projectLeaderboardEntries(fields.entries || []);

  await upsert(
    'indexed_leaderboards',
    ['vault_id', 'entries', 'last_updated', 'pda', 'chain_slot', 'indexed_at', 'bump'],
    [
      bnToString(fields.vaultId),           // u64
      JSON.stringify(entries),
      bnToString(fields.lastUpdated),       // i64
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),                 // u8
    ],
    ['vault_id']
  );
}
