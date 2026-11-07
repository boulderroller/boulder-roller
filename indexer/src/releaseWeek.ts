import { query } from './db';

type ReleaseWeekQuery = (
  text: string,
  params: unknown[]
) => Promise<{ rows: Array<Record<string, unknown>> }>;

export class ReleaseAuthorityProjectionPending extends Error {
  readonly releaseAuthorityPda: string;

  constructor(releaseAuthorityPda: string) {
    super('released completion requires its indexed release authority');
    this.name = 'ReleaseAuthorityProjectionPending';
    this.releaseAuthorityPda = releaseAuthorityPda;
  }
}

export function assertFrozenReleaseSettlementWeek(
  indexedAuthorityWeek: unknown,
  creditedSettlementWeek: string
): void {
  const authorityWeek = String(indexedAuthorityWeek ?? '');
  if (!/^\d+$/.test(authorityWeek) || authorityWeek !== creditedSettlementWeek) {
    throw new Error(
      'released completion settlement week conflicts with frozen release authority'
    );
  }
}

export async function requireIndexedReleaseSettlementWeek(
  releaseAuthorityPda: string,
  creditedSettlementWeek: string,
  runQuery: ReleaseWeekQuery = query
): Promise<void> {
  const result = await runQuery(
    `SELECT release_settlement_week
       FROM indexed_held_ride_release_authorities
      WHERE pda = $1`,
    [releaseAuthorityPda]
  );
  if (result.rows.length !== 1) {
    throw new ReleaseAuthorityProjectionPending(releaseAuthorityPda);
  }
  assertFrozenReleaseSettlementWeek(
    result.rows[0].release_settlement_week,
    creditedSettlementWeek
  );
}
