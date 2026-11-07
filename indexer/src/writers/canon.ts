import crypto from 'crypto';
import { PublicKey } from '@solana/web3.js';

import * as db from '../db';
import { config } from '../config';
import { pubkeyToString, safeInt } from '../decoder';
import { CURRENT_PROGRAM_VERSION } from '../generated-program-version';

const CANON_COMMITMENT_LENGTH = 64;
const CANON_COMMITMENT_PREFIX = 0x01;
// Canon projection follows the deployed V4-B build; the family pin below is the invariant.
const CANON_RUNTIME_PROGRAM_VERSION: number = CURRENT_PROGRAM_VERSION;
const CANON_RUNTIME_PROGRAM_FAMILY = 'V4-B';
const DEFAULT_PUBKEY = PublicKey.default.toBase58();

export interface ParsedCanonCommitment {
  commitmentHex: string;
  commitmentHashHex: string;
  canonId: string;
  canonVersion: number;
  canonicalProfileHashHex: string;
}

export interface ValidatedClimbAccount extends ParsedCanonCommitment {
  predecessorClimbPda: string | null;
  successorClimbPda: string | null;
  recordContinuityPolicy: 'new_record_board';
  vaultPda: string | null;
  name: string;
  vertMFixed: number;
  vertM: number;
  distanceM: number;
  avgGradientPctFixed: number;
  avgGradientPct: number;
  registeredAt: Date;
  registeredBy: string;
}

function exactBytes(value: unknown, length: number, label: string): Buffer {
  let bytes: Buffer;
  try {
    bytes = Buffer.from(value as any);
  } catch {
    throw new Error(`${label} must be ${length} bytes`);
  }
  if (bytes.length !== length) {
    throw new Error(`${label} must be ${length} bytes`);
  }
  return bytes;
}

function uuidFromBytes(bytes: Buffer): string {
  const hex = bytes.toString('hex');
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join('-');
}

function nullablePubkey(value: unknown, label: string): string | null {
  let encoded: string;
  try {
    encoded = pubkeyToString(value);
  } catch {
    throw new Error(`${label} is not a public key`);
  }
  return encoded === DEFAULT_PUBKEY ? null : encoded;
}

function exactFixedName(value: unknown): string {
  const bytes = exactBytes(value, 64, 'Climb name');
  const firstZero = bytes.indexOf(0);
  const content = firstZero === -1 ? bytes : bytes.subarray(0, firstZero);
  if (firstZero !== -1 && bytes.subarray(firstZero).some((byte) => byte !== 0)) {
    throw new Error('Climb name has a noncanonical byte layout');
  }
  const name = content.toString('utf8');
  if (
    content.length < 3
    || content.length > 64
    || Buffer.from(name, 'utf8').compare(content) !== 0
  ) {
    throw new Error('Climb name is invalid UTF-8');
  }
  return name;
}

function exactUnsigned(value: unknown, minimum: number, maximum: number, label: string): number {
  const parsed = safeInt(value);
  if (parsed < minimum || parsed > maximum) {
    throw new Error(`${label} is outside its on-chain encoding`);
  }
  return parsed;
}

export function parseCanonCommitment(value: unknown): ParsedCanonCommitment {
  const bytes = exactBytes(value, CANON_COMMITMENT_LENGTH, 'canon commitment');
  if (bytes[0] !== CANON_COMMITMENT_PREFIX) {
    throw new Error('canon commitment prefix is invalid');
  }
  const canonIdBytes = bytes.subarray(1, 17);
  if (canonIdBytes.every((byte) => byte === 0)) {
    throw new Error('canon commitment canon_id must not be zero');
  }
  const canonVersion = bytes.readUInt16BE(17);
  if (canonVersion === 0) {
    throw new Error('canon commitment version is invalid');
  }
  if (bytes.subarray(19, 32).some((byte) => byte !== 0)) {
    throw new Error('canon commitment reserved bytes must be zero');
  }
  const profileHash = bytes.subarray(32, 64);
  if (profileHash.every((byte) => byte === 0)) {
    throw new Error('canon commitment profile hash must not be zero');
  }
  return {
    commitmentHex: bytes.toString('hex'),
    commitmentHashHex: crypto.createHash('sha256').update(bytes).digest('hex'),
    canonId: uuidFromBytes(canonIdBytes),
    canonVersion,
    canonicalProfileHashHex: profileHash.toString('hex'),
  };
}

export function requireCanonIndexerProgramVersion(
  programVersion: number,
  family: string
): void {
  if (
    !Number.isInteger(programVersion)
    || programVersion !== CANON_RUNTIME_PROGRAM_VERSION
    || family !== CANON_RUNTIME_PROGRAM_FAMILY
  ) {
    throw new Error('canon projection requires the exact V4-B program family');
  }
}

export function validateClimbAccount(fields: Record<string, any>): ValidatedClimbAccount {
  const parsed = parseCanonCommitment(fields.canonCommitment);
  const commitmentHash = exactBytes(fields.commitmentHash, 32, 'commitment hash');
  const canonId = exactBytes(fields.canonId, 16, 'canon id');
  const profileHash = exactBytes(fields.canonicalProfileHash, 32, 'profile hash');
  if (commitmentHash.toString('hex') !== parsed.commitmentHashHex) {
    throw new Error('Climb commitment hash does not match D12 bytes');
  }
  if (uuidFromBytes(canonId) !== parsed.canonId) {
    throw new Error('Climb canon id does not match D12 bytes');
  }
  if (exactUnsigned(fields.canonVersion, 1, 0xffff, 'Climb canon version') !== parsed.canonVersion) {
    throw new Error('Climb canon version does not match D12 bytes');
  }
  if (profileHash.toString('hex') !== parsed.canonicalProfileHashHex) {
    throw new Error('Climb profile hash does not match D12 bytes');
  }
  if (!fields.recordContinuityPolicy?.newRecordBoard) {
    throw new Error('carry_records_forward is unavailable until record migration is proven');
  }
  const registeredAt = new Date(Number(fields.registeredAt) * 1000);
  if (Number.isNaN(registeredAt.getTime())) {
    throw new Error('Climb registration timestamp is invalid');
  }
  const vertMFixed = exactUnsigned(
    fields.vertM,
    1,
    0xffffffff,
    'Climb vertical gain'
  );
  const avgGradientPctFixed = exactUnsigned(
    fields.avgGradientPct,
    0,
    0xffff,
    'Climb average gradient'
  );
  return {
    ...parsed,
    predecessorClimbPda: nullablePubkey(fields.predecessorClimb, 'predecessor Climb'),
    successorClimbPda: nullablePubkey(fields.successorClimb, 'successor Climb'),
    recordContinuityPolicy: 'new_record_board',
    vaultPda: nullablePubkey(fields.vault, 'Vault'),
    name: exactFixedName(fields.name),
    vertMFixed,
    vertM: vertMFixed / 10,
    distanceM: exactUnsigned(fields.distanceM, 1, 0xffffffff, 'Climb distance'),
    avgGradientPctFixed,
    avgGradientPct: avgGradientPctFixed / 100,
    registeredAt,
    registeredBy: pubkeyToString(fields.registeredBy),
  };
}

export function validateVaultClimbBinding(
  fields: Record<string, any>,
  expectedClimbPda: string
): { climbPda: string; commitmentHex: string; commitmentHashHex: string } {
  const parsed = parseCanonCommitment(fields.signature);
  const signatureHash = exactBytes(fields.signatureHash, 32, 'Vault commitment hash');
  if (signatureHash.toString('hex') !== parsed.commitmentHashHex) {
    throw new Error('Vault commitment hash does not match D12 bytes');
  }
  if (fields.climb == null) {
    throw new Error('Vault Climb link is unavailable');
  }
  const climbPda = pubkeyToString(fields.climb);
  if (climbPda === DEFAULT_PUBKEY || climbPda !== expectedClimbPda) {
    throw new Error('Vault Climb link does not match the canonical Climb');
  }
  return {
    climbPda,
    commitmentHex: parsed.commitmentHex,
    commitmentHashHex: parsed.commitmentHashHex,
  };
}

function payloadHash(fields: Record<string, any>): string | null {
  try {
    const commitment = Buffer.from(fields.canonCommitment ?? fields.signature);
    return crypto.createHash('sha256').update(commitment).digest('hex');
  } catch {
    return null;
  }
}

export async function quarantineCanonAccount(args: {
  pda: string;
  accountType: 'Climb' | 'Vault';
  reason: string;
  programVersion: number;
  slot: number;
  fields: Record<string, any>;
}): Promise<void> {
  await db.query(
    `WITH quarantine_write AS (
       INSERT INTO public.canon_indexer_quarantine (
         account_pda, account_type, reason, observed_program_version,
         chain_slot, payload_hash_hex, first_observed_at, last_observed_at
       ) VALUES ($1, $2, $3, $4, $5, $6, now(), now())
       ON CONFLICT (account_pda) DO UPDATE SET
         account_type = EXCLUDED.account_type,
         reason = EXCLUDED.reason,
         observed_program_version = EXCLUDED.observed_program_version,
         chain_slot = EXCLUDED.chain_slot,
         payload_hash_hex = EXCLUDED.payload_hash_hex,
         last_observed_at = now()
       WHERE EXCLUDED.chain_slot >= public.canon_indexer_quarantine.chain_slot
       RETURNING account_pda, account_type, chain_slot
     ), deactivated_climb AS (
       UPDATE public.indexed_climbs AS indexed
       SET quarantined = TRUE,
           chain_slot = quarantine.chain_slot,
           indexed_at = now()
       FROM quarantine_write AS quarantine
       WHERE quarantine.account_type = 'Climb'
         AND indexed.pda = quarantine.account_pda
         AND indexed.chain_slot <= quarantine.chain_slot
       RETURNING indexed.pda
     ), deactivated_vaults_for_climb AS (
       UPDATE public.indexed_vaults AS vault
       SET canon_binding_status = 'quarantined',
           chain_slot = GREATEST(vault.chain_slot, quarantine.chain_slot),
           indexed_at = now()
       FROM quarantine_write AS quarantine
       WHERE quarantine.account_type = 'Climb'
         AND vault.climb_pda = quarantine.account_pda
         AND vault.canon_binding_status = 'active'
         AND EXISTS (
           SELECT 1
           FROM deactivated_climb AS climb
           WHERE climb.pda = quarantine.account_pda
         )
       RETURNING vault.pda
     ), deactivated_vault AS (
       UPDATE public.indexed_vaults AS vault
       SET canon_binding_status = 'quarantined',
           chain_slot = quarantine.chain_slot,
           indexed_at = now()
       FROM quarantine_write AS quarantine
       WHERE quarantine.account_type = 'Vault'
         AND vault.pda = quarantine.account_pda
         AND vault.chain_slot <= quarantine.chain_slot
       RETURNING vault.pda
     )
     SELECT
       (SELECT count(*) FROM quarantine_write) AS quarantine_writes,
       (SELECT count(*) FROM deactivated_climb) AS climbs_deactivated,
       (SELECT count(*) FROM deactivated_vaults_for_climb) AS dependent_vaults_deactivated,
       (SELECT count(*) FROM deactivated_vault) AS vaults_deactivated`,
    [
      args.pda,
      args.accountType,
      args.reason.slice(0, 500),
      args.programVersion,
      args.slot,
      payloadHash(args.fields),
    ]
  );
}

export async function enqueueCanonDependency(args: {
  pda: string;
  reason: string;
  slot: number;
}): Promise<void> {
  await db.query(
    `INSERT INTO public.canon_indexer_pending (
       account_pda, account_type, reason, chain_slot, attempts,
       next_retry_at, first_observed_at, last_observed_at
     ) VALUES ($1, 'Vault', $2, $3, 1, now(), now(), now())
     ON CONFLICT (account_pda) DO UPDATE SET
       reason = EXCLUDED.reason,
       chain_slot = GREATEST(
         public.canon_indexer_pending.chain_slot,
         EXCLUDED.chain_slot
       ),
       attempts = public.canon_indexer_pending.attempts + 1,
       next_retry_at = now() + LEAST(
         interval '60 seconds',
         public.canon_indexer_pending.attempts * interval '1 second'
       ),
       last_observed_at = now()`,
    [args.pda, args.reason.slice(0, 500), args.slot]
  );
}

export async function writeClimb(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<boolean> {
  let climb: ValidatedClimbAccount;
  try {
    climb = validateClimbAccount(fields);
    const [expectedPda] = PublicKey.findProgramAddressSync(
      [Buffer.from('climb'), Buffer.from(climb.commitmentHashHex, 'hex')],
      new PublicKey(config.programId)
    );
    if (expectedPda.toBase58() !== pda) {
      throw new Error('Climb PDA does not match its commitment hash');
    }
  } catch (error) {
    await quarantineCanonAccount({
      pda,
      accountType: 'Climb',
      reason: error instanceof Error ? error.message : 'invalid Climb account',
      programVersion: CANON_RUNTIME_PROGRAM_VERSION,
      slot,
      fields,
    });
    return false;
  }

  const result = await db.query(
    `INSERT INTO public.indexed_climbs (
       pda, canon_climb_id, canon_commitment_hex, commitment_hash_hex,
       canon_id, canon_version, canonical_profile_hash_hex,
       predecessor_climb_pda, successor_climb_pda, record_continuity_policy,
       vault_pda, name, vert_m, distance_m, avg_gradient_pct,
       registered_at, registered_by, chain_slot, indexed_at, quarantined
     )
     SELECT $1, canon.id, $2, $3, $4::uuid, $5, $6,
            $7, $8, $9, $10, $11, $12, $13, $14,
            $15, $16, $17, $18, FALSE
     FROM (VALUES (1)) AS exact_source(marker)
     JOIN public.canon_climbs AS canon
       ON canon.canon_id = $4::uuid
      AND canon.version = $5
      AND canon.record_continuity_policy = 'new_record_board'
      AND canon.provenance #>> '{canonical_profile_hash,algorithm}'
            = 'blake3_canonical_profile_v1'
      AND lower(canon.provenance #>> '{canonical_profile_hash,value}') = $6
      AND canon.display_name = $11
      AND canon.vert_m > 0
      AND canon.length_m > 0
      AND canon.avg_gradient_pct >= 0
      AND canon.vert_m <> 'NaN'::numeric
      AND canon.length_m <> 'NaN'::numeric
      AND canon.avg_gradient_pct <> 'NaN'::numeric
      AND round(canon.vert_m * 10) = $19::numeric
      AND round(canon.length_m) = $13::numeric
      AND round(canon.avg_gradient_pct * 100) = $20::numeric
     WHERE (
       (
         canon.status = 'ratified'
         AND $8::text IS NULL
         AND NOT EXISTS (
           SELECT 1 FROM public.canon_climbs AS other
           WHERE other.canon_id = canon.canon_id
             AND other.status = 'ratified'
             AND other.id <> canon.id
         )
       )
       OR (
         canon.status = 'retired'
         AND $8::text IS NOT NULL
         AND EXISTS (
           SELECT 1 FROM public.canon_climbs AS successor
           WHERE successor.canon_id = canon.canon_id
             AND successor.version = canon.version + 1
             AND successor.supersedes_climb_id = canon.id
             AND successor.status = 'ratified'
             AND successor.record_continuity_policy = 'new_record_board'
         )
       )
     )
     ON CONFLICT (pda) DO UPDATE SET
       canon_climb_id = EXCLUDED.canon_climb_id,
       canon_commitment_hex = EXCLUDED.canon_commitment_hex,
       commitment_hash_hex = EXCLUDED.commitment_hash_hex,
       canon_id = EXCLUDED.canon_id,
       canon_version = EXCLUDED.canon_version,
       canonical_profile_hash_hex = EXCLUDED.canonical_profile_hash_hex,
       predecessor_climb_pda = EXCLUDED.predecessor_climb_pda,
       successor_climb_pda = EXCLUDED.successor_climb_pda,
       record_continuity_policy = EXCLUDED.record_continuity_policy,
       vault_pda = EXCLUDED.vault_pda,
       name = EXCLUDED.name,
       vert_m = EXCLUDED.vert_m,
       distance_m = EXCLUDED.distance_m,
       avg_gradient_pct = EXCLUDED.avg_gradient_pct,
       registered_at = EXCLUDED.registered_at,
       registered_by = EXCLUDED.registered_by,
       chain_slot = EXCLUDED.chain_slot,
       indexed_at = EXCLUDED.indexed_at,
       quarantined = FALSE
     WHERE EXCLUDED.chain_slot >= public.indexed_climbs.chain_slot
     RETURNING canon_climb_id`,
    [
      pda,
      climb.commitmentHex,
      climb.commitmentHashHex,
      climb.canonId,
      climb.canonVersion,
      climb.canonicalProfileHashHex,
      climb.predecessorClimbPda,
      climb.successorClimbPda,
      climb.recordContinuityPolicy,
      climb.vaultPda,
      climb.name,
      climb.vertM,
      climb.distanceM,
      climb.avgGradientPct,
      climb.registeredAt,
      climb.registeredBy,
      slot,
      new Date(),
      climb.vertMFixed,
      climb.avgGradientPctFixed,
    ]
  );
  if (result.rowCount !== 1) {
    await quarantineCanonAccount({
      pda,
      accountType: 'Climb',
      reason: 'Climb does not resolve to one current ratified registry row',
      programVersion: CANON_RUNTIME_PROGRAM_VERSION,
      slot,
      fields,
    });
    return false;
  }
  return true;
}
