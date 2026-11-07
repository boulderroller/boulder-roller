import { bytesToHex, bnToString, pubkeyToString, safeInt } from '../decoder';
import { requireIndexedReleaseSettlementWeek } from '../releaseWeek';
import { upsert } from './common';

function optionalPubkey(value: any): string | null {
  return value ? pubkeyToString(value) : null;
}

export async function writeRiderSoul(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_rider_souls',
    [
      'rider_pubkey',
      'created_at',
      'total_rides',
      'total_tss',
      'total_distance_m',
      'total_vert_m',
      'total_cal_earned',
      'archetype',
      'bio_score',
      'climb_card',
      'steady_card',
      'explorer_card',
      'pda',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      pubkeyToString(fields.rider),
      bnToString(fields.createdAt),
      bnToString(fields.totalRides),
      bnToString(fields.totalTss),
      bnToString(fields.totalDistanceM),
      bnToString(fields.totalVertM),
      bnToString(fields.totalCalEarned),
      safeInt(fields.archetype),
      bnToString(fields.bioScore),
      optionalPubkey(fields.climbCard),
      optionalPubkey(fields.steadyCard),
      optionalPubkey(fields.explorerCard),
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['rider_pubkey']
  );
}

export async function writeRideAttestation(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_ride_attestations',
    [
      'rider_pubkey',
      'ride_hash_hex',
      'attestation_commitment_hex',
      'parser_version',
      'source_kind',
      'completed_at',
      'started_at',
      'total_tss',
      'total_distance_m',
      'total_vert_m',
      'cal_earned',
      'climbs_crossed',
      'attester',
      'settled_at',
      'settled_slot',
      'economic_epoch',
      'finalized',
      'pda',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      pubkeyToString(fields.rider),
      bytesToHex(fields.rideHash),
      bytesToHex(fields.attestationCommitment),
      safeInt(fields.parserVersion),
      safeInt(fields.sourceKind),
      bnToString(fields.completedAt),
      bnToString(fields.startedAt),
      safeInt(fields.totalTss),
      safeInt(fields.totalDistanceM),
      safeInt(fields.totalVertM),
      bnToString(fields.calEarned),
      safeInt(fields.climbsCrossed),
      pubkeyToString(fields.attester),
      bnToString(fields.settledAt),
      bnToString(fields.settledSlot),
      bnToString(fields.economicEpoch),
      Boolean(fields.finalized),
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['rider_pubkey', 'ride_hash_hex']
  );
}

export async function writeHeldRideReleaseAuthority(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_held_ride_release_authorities',
    [
      'pda',
      'ride_attestation_pda',
      'rider_pubkey',
      'threshold_authority_id_hex',
      'threshold_authority_commitment_hex',
      'threshold_effective_at',
      'threshold_w',
      'threshold_policy_version',
      'economic_tss',
      'cal_earned',
      'cal_tribute_budget',
      'release_plan_hash_hex',
      'released_at',
      'released_slot',
      'release_settlement_week',
      'attester',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      pda,
      pubkeyToString(fields.rideAttestation),
      pubkeyToString(fields.rider),
      bytesToHex(fields.thresholdAuthorityId),
      bytesToHex(fields.thresholdAuthorityCommitment),
      bnToString(fields.thresholdEffectiveAt),
      safeInt(fields.thresholdW),
      safeInt(fields.thresholdPolicyVersion),
      safeInt(fields.economicTss),
      bnToString(fields.calEarned),
      bnToString(fields.calTributeBudget),
      bytesToHex(fields.releasePlanHash),
      bnToString(fields.releasedAt),
      bnToString(fields.releasedSlot),
      bnToString(fields.releaseSettlementWeek),
      pubkeyToString(fields.attester),
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['pda']
  );
}

export async function writeCalMintReceipt(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_cal_mint_receipts',
    [
      'pda',
      'ride_attestation_pda',
      'rider_pubkey',
      'amount',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      pda,
      pubkeyToString(fields.rideAttestation),
      pubkeyToString(fields.rider),
      bnToString(fields.amount),
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['pda']
  );
}

export async function writeReleasedCalMintReceipt(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  const releaseAuthority = pubkeyToString(fields.releaseAuthority);
  const releaseWeek = bnToString(fields.releaseSettlementWeek);
  await requireIndexedReleaseSettlementWeek(releaseAuthority, releaseWeek);
  await upsert(
    'indexed_cal_mint_receipts',
    [
      'pda',
      'ride_attestation_pda',
      'release_authority_pda',
      'rider_pubkey',
      'amount',
      'release_settlement_week',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      pda,
      pubkeyToString(fields.rideAttestation),
      releaseAuthority,
      pubkeyToString(fields.rider),
      bnToString(fields.amount),
      releaseWeek,
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['pda']
  );
}

export async function writeClimbCompletionReceipt(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_climb_completion_receipts',
    [
      'pda',
      'ride_attestation_pda',
      'vault_pda',
      'completion_evidence_version',
      'completion_evidence_hash',
      'cal_tributed',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      pda,
      pubkeyToString(fields.rideAttestation),
      pubkeyToString(fields.vault),
      1,
      Buffer.from(fields.completionEvidenceHash),
      null,
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['pda']
  );
}

export async function writeClimbCompletionReceiptV2(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  const evidenceVersion = safeInt(fields.evidenceVersion);
  if (evidenceVersion !== 2) {
    throw new Error('ClimbCompletionReceiptV2 must declare evidence version 2');
  }
  await upsert(
    'indexed_climb_completion_receipts',
    [
      'pda',
      'ride_attestation_pda',
      'vault_pda',
      'completion_evidence_version',
      'completion_evidence_hash',
      'cal_tributed',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      pda,
      pubkeyToString(fields.rideAttestation),
      pubkeyToString(fields.vault),
      evidenceVersion,
      Buffer.from(fields.completionEvidenceHash),
      bnToString(fields.calTributed),
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['pda']
  );
}

export async function writeReleasedClimbCompletionReceipt(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  const evidenceVersion = safeInt(fields.evidenceVersion);
  if (evidenceVersion !== 3) {
    throw new Error('ReleasedClimbCompletionReceipt must declare evidence version 3');
  }
  const releaseAuthority = pubkeyToString(fields.releaseAuthority);
  const creditedSettlementWeek = bnToString(fields.creditedSettlementWeek);
  await requireIndexedReleaseSettlementWeek(
    releaseAuthority,
    creditedSettlementWeek
  );
  await upsert(
    'indexed_climb_completion_receipts',
    [
      'pda',
      'ride_attestation_pda',
      'release_authority_pda',
      'vault_pda',
      'completion_evidence_version',
      'completion_evidence_hash',
      'cal_tributed',
      'credited_settlement_week',
      'chain_slot',
      'indexed_at',
      'bump',
    ],
    [
      pda,
      pubkeyToString(fields.rideAttestation),
      releaseAuthority,
      pubkeyToString(fields.vault),
      evidenceVersion,
      Buffer.from(fields.completionEvidenceHash),
      bnToString(fields.calTributed),
      creditedSettlementWeek,
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['pda']
  );
}
