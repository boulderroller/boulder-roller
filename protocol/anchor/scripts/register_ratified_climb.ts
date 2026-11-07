/**
 * Verify one exported, ratified canon-registry row and optionally register it.
 *
 * Dry-run is the default. `--send` accepts no identity flags: every committed
 * field must come from the post-publish registry row supplied with `--row`.
 */

import * as anchor from '@coral-xyz/anchor';
import { blake3 } from '@noble/hashes/blake3';
import {
  Connection,
  Keypair,
  PublicKey,
  sendAndConfirmTransaction,
  SystemProgram,
  Transaction,
} from '@solana/web3.js';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import { parse as parseUuid, stringify as stringifyUuid, validate as validateUuid } from 'uuid';
import {
  CURRENT_PROGRAM_VERSION,
  PROGRAM_VERSION_FAMILY,
} from '../generated-program-version.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const IDL_PATH = path.join(__dirname, '..', 'idl', 'boulder_rollers.json');
const ADDRESSES_PATH = path.join(__dirname, '..', 'addresses.devnet.json');
const PROFILE_HASH_ALGORITHM = 'blake3_canonical_profile_v1';
const PROFILE_HASH_DOMAIN = Buffer.from('boulderroller-canon-profile-v1', 'utf8');
export const CHAIN_METRIC_PROJECTION_ALGORITHM = 'boulderroller_chain_metric_projection_v1';
const CLIMB_SEED = Buffer.from('climb');
const CLIMB_VERSION_INDEX_SEED = Buffer.from('climb_version');
const PROGRAM_CONFIG_SEED = Buffer.from('program_config');

type JsonObject = Record<string, unknown>;

interface RatifiedRegistryRow {
  id: string;
  canon_id: string;
  version: number;
  status: 'ratified';
  supersedes_climb_id: string | null;
  record_continuity_policy: 'new_record_board';
  display_name: string;
  canonical_profile: Array<{ dist_m: number; elev_m: number }>;
  length_m: number;
  vert_m: number;
  avg_gradient_pct: number;
  provenance: {
    canonical_profile_hash: {
      algorithm: typeof PROFILE_HASH_ALGORITHM;
      value: string;
    };
  };
}

interface RegistrationArtifact {
  artifact: 'boulderroller.canon-registration';
  schema_version: 1;
  registry_row: RatifiedRegistryRow;
  commitment: {
    layout: 'D12';
    bytes_hex: string;
    sha256_hex: string;
  };
  chain_metric_projection: {
    algorithm: typeof CHAIN_METRIC_PROJECTION_ALGORITHM;
    vert_decimeters: number;
    distance_meters: number;
    avg_gradient_basis_points: number;
  };
}

interface VerifiedRow {
  row: RatifiedRegistryRow;
  rowId: string;
  canonId: Buffer;
  profileHash: Buffer;
  canonCommitment: Buffer;
  commitmentHash: Buffer;
  vertDecimeters: number;
  distanceMeters: number;
  gradientBasisPoints: number;
}

interface Options {
  rowPath: string;
  programId: PublicKey;
  rpcUrl?: string;
  send: boolean;
  adminKeypair?: string;
  feePayerKeypair?: string;
}

function object(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function nonzeroUuid(value: unknown, label: string): { canonical: string; bytes: Buffer } {
  if (typeof value !== 'string' || value !== value.toLowerCase() || !validateUuid(value)) {
    throw new Error(`${label} must be a lowercase hyphenated UUID`);
  }
  const bytes = Buffer.from(parseUuid(value));
  if (bytes.every((byte) => byte === 0) || stringifyUuid(bytes) !== value) {
    throw new Error(`${label} must be a canonical nonzero UUID`);
  }
  return { canonical: value, bytes };
}

export function quantizedScaledInteger(
  value: unknown,
  scale: number,
  max: number,
  label: string,
): number {
  if (
    typeof value !== 'number'
    || !Number.isFinite(value)
    || value < 0
    || !Number.isInteger(Math.log10(scale))
  ) {
    throw new Error(`${label} must be a finite nonnegative decimal`);
  }

  const match = String(value).match(/^(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i);
  if (!match) {
    throw new Error(`${label} must be a finite nonnegative decimal`);
  }
  const integerDigits = match[1];
  const fractionalDigits = match[2] ?? '';
  const exponent = Number(match[3] ?? 0);
  const scaleExponent = Math.log10(scale);
  const coefficient = BigInt(`${integerDigits}${fractionalDigits}`);
  const decimalExponent = exponent - fractionalDigits.length + scaleExponent;

  let encoded: bigint;
  if (decimalExponent >= 0) {
    encoded = coefficient * (10n ** BigInt(decimalExponent));
  } else {
    const denominator = 10n ** BigInt(-decimalExponent);
    const quotient = coefficient / denominator;
    const remainder = coefficient % denominator;
    encoded = quotient + (remainder * 2n >= denominator ? 1n : 0n);
  }

  if (encoded > BigInt(max)) {
    throw new Error(`${label} exceeds the on-chain range after half-up quantization`);
  }
  return Number(encoded);
}

function canonicalProfileBytes(profile: unknown): Buffer {
  if (!Array.isArray(profile) || profile.length < 2) {
    throw new Error('canonical_profile must contain at least two ordered samples');
  }
  const chunks: Buffer[] = [PROFILE_HASH_DOMAIN];
  let previousDistance = Number.NEGATIVE_INFINITY;
  for (const [index, sampleValue] of profile.entries()) {
    const sample = object(sampleValue, `canonical_profile[${index}]`);
    const distance = sample.dist_m;
    const elevation = sample.elev_m;
    if (
      typeof distance !== 'number'
      || typeof elevation !== 'number'
      || !Number.isFinite(distance)
      || !Number.isFinite(elevation)
    ) {
      throw new Error(`canonical_profile[${index}] coordinates must be finite numbers`);
    }
    if (distance < previousDistance) {
      throw new Error('canonical_profile distance must be nondecreasing');
    }
    previousDistance = distance;
    chunks.push(Buffer.from(`${distance.toFixed(2)}:${elevation.toFixed(2)};`, 'utf8'));
  }
  return Buffer.concat(chunks);
}

function verifyRow(raw: unknown): VerifiedRow {
  const value = object(raw, 'ratified registry row');
  const rowId = nonzeroUuid(value.id, 'id');
  const canonId = nonzeroUuid(value.canon_id, 'canon_id');
  if (value.status !== 'ratified') {
    throw new Error('row status must be ratified; pre-publish payloads are not authority');
  }
  if (!Number.isInteger(value.version) || Number(value.version) < 1 || Number(value.version) > 0xffff) {
    throw new Error('version must be an integer from 1 through 65535');
  }
  const version = Number(value.version);
  if (value.record_continuity_policy !== 'new_record_board') {
    throw new Error('only new_record_board is operational; carry-records-forward is unavailable');
  }
  if (version === 1) {
    if (value.supersedes_climb_id !== null) {
      throw new Error('canon version 1 cannot supersede another registry row');
    }
  } else {
    const predecessor = nonzeroUuid(value.supersedes_climb_id, 'supersedes_climb_id');
    if (predecessor.canonical === rowId.canonical) {
      throw new Error('a registry row cannot supersede itself');
    }
  }
  if (typeof value.display_name !== 'string') {
    throw new Error('display_name must be a string');
  }
  const nameBytes = Buffer.from(value.display_name, 'utf8');
  if (nameBytes.length < 3 || nameBytes.length > 64) {
    throw new Error('display_name must contain 3 through 64 UTF-8 bytes');
  }

  const profileBytes = canonicalProfileBytes(value.canonical_profile);
  const computedProfileHash = Buffer.from(blake3(profileBytes));
  const provenance = object(value.provenance, 'provenance');
  const hashEvidence = object(provenance.canonical_profile_hash, 'provenance.canonical_profile_hash');
  if (hashEvidence.algorithm !== PROFILE_HASH_ALGORITHM) {
    throw new Error(`canonical profile hash algorithm must be ${PROFILE_HASH_ALGORITHM}`);
  }
  if (
    typeof hashEvidence.value !== 'string'
    || !/^[0-9a-f]{64}$/.test(hashEvidence.value)
    || /^0+$/.test(hashEvidence.value)
  ) {
    throw new Error('canonical profile hash evidence must be 32 nonzero lowercase hex bytes');
  }
  const storedProfileHash = Buffer.from(hashEvidence.value, 'hex');
  if (!crypto.timingSafeEqual(computedProfileHash, storedProfileHash)) {
    throw new Error(
      `canonical profile hash mismatch: stored ${hashEvidence.value}, computed ${computedProfileHash.toString('hex')}`,
    );
  }

  const vertDecimeters = quantizedScaledInteger(value.vert_m, 10, 0xffff_ffff, 'vert_m');
  if (vertDecimeters === 0) throw new Error('vert_m must be positive');
  const distanceMeters = quantizedScaledInteger(value.length_m, 1, 0xffff_ffff, 'length_m');
  if (distanceMeters === 0) throw new Error('length_m must be positive');
  const gradientBasisPoints = quantizedScaledInteger(
    value.avg_gradient_pct,
    100,
    0xffff,
    'avg_gradient_pct',
  );

  const canonCommitment = Buffer.alloc(64);
  canonCommitment[0] = 1;
  canonId.bytes.copy(canonCommitment, 1);
  canonCommitment.writeUInt16BE(version, 17);
  storedProfileHash.copy(canonCommitment, 32);
  const commitmentHash = crypto.createHash('sha256').update(canonCommitment).digest();

  return {
    row: value as unknown as RatifiedRegistryRow,
    rowId: rowId.canonical,
    canonId: canonId.bytes,
    profileHash: storedProfileHash,
    canonCommitment,
    commitmentHash,
    vertDecimeters,
    distanceMeters,
    gradientBasisPoints,
  };
}

function verifyRegistrationArtifact(raw: unknown): VerifiedRow {
  const artifact = object(raw, 'registration artifact');
  if (
    artifact.artifact !== 'boulderroller.canon-registration'
    || artifact.schema_version !== 1
  ) {
    throw new Error('artifact must be boulderroller.canon-registration schema version 1');
  }
  const verified = verifyRow(artifact.registry_row);
  const commitment = object(artifact.commitment, 'commitment');
  if (commitment.layout !== 'D12') {
    throw new Error('commitment layout must be D12');
  }
  if (
    commitment.bytes_hex !== verified.canonCommitment.toString('hex')
    || commitment.sha256_hex !== verified.commitmentHash.toString('hex')
  ) {
    throw new Error('exported commitment evidence does not match the recomputed registry row');
  }
  const projection = object(
    artifact.chain_metric_projection,
    'chain_metric_projection',
  );
  const expectedProjectionKeys = [
    'algorithm',
    'avg_gradient_basis_points',
    'distance_meters',
    'vert_decimeters',
  ];
  if (
    JSON.stringify(Object.keys(projection).sort()) !== JSON.stringify(expectedProjectionKeys)
    || projection.algorithm !== CHAIN_METRIC_PROJECTION_ALGORITHM
    || projection.vert_decimeters !== verified.vertDecimeters
    || projection.distance_meters !== verified.distanceMeters
    || projection.avg_gradient_basis_points !== verified.gradientBasisPoints
  ) {
    throw new Error(
      'exported chain metric projection does not match the recomputed registry metrics',
    );
  }
  return verified;
}

function loadDefaultProgramId(): PublicKey {
  const addresses = JSON.parse(fs.readFileSync(ADDRESSES_PATH, 'utf8'));
  return new PublicKey(addresses.programs.boulder_rollers);
}

function parseArgs(): Options {
  const args = process.argv.slice(2);
  let rowPath: string | undefined;
  let programId = loadDefaultProgramId();
  let programIdWasExplicit = false;
  let rpcUrl = process.env.SOLANA_RPC_URL;
  let send = false;
  let adminKeypair: string | undefined;
  let feePayerKeypair: string | undefined;

  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    const next = args[index + 1];
    if (argument === '--row' && next) {
      rowPath = next;
      index += 1;
    } else if (argument === '--program-id' && next) {
      programId = new PublicKey(next);
      programIdWasExplicit = true;
      index += 1;
    } else if (argument === '--rpc' && next) {
      rpcUrl = next;
      index += 1;
    } else if (argument === '--admin-keypair' && next) {
      adminKeypair = next;
      index += 1;
    } else if (argument === '--fee-payer' && next) {
      feePayerKeypair = next;
      index += 1;
    } else if (argument === '--send') {
      send = true;
    } else if (argument === '--dry-run') {
      send = false;
    } else {
      throw new Error(`unknown or incomplete argument: ${argument}`);
    }
  }
  if (!rowPath) throw new Error('--row <exported-ratified-row.json> is required');
  if (send && !programIdWasExplicit) {
    throw new Error('--send requires an explicit --program-id for the fresh V4-B deployment');
  }
  if (send && (!rpcUrl || !adminKeypair || !feePayerKeypair)) {
    throw new Error('--send requires --rpc, --admin-keypair, and --fee-payer');
  }
  return { rowPath, programId, rpcUrl, send, adminKeypair, feePayerKeypair };
}

function loadKeypair(filePath: string): Keypair {
  return Keypair.fromSecretKey(Uint8Array.from(JSON.parse(fs.readFileSync(filePath, 'utf8'))));
}

function readonlyWallet(): anchor.Wallet {
  const fail = async (): Promise<never> => {
    throw new Error('read-only dry-run wallet cannot sign');
  };
  return {
    publicKey: SystemProgram.programId,
    signTransaction: fail,
    signAllTransactions: fail,
  } as unknown as anchor.Wallet;
}

async function main(): Promise<void> {
  const options = parseArgs();
  const verified = verifyRegistrationArtifact(
    JSON.parse(fs.readFileSync(options.rowPath, 'utf8')),
  );
  const versionBytes = Buffer.alloc(2);
  versionBytes.writeUInt16BE(verified.row.version);
  const [climb] = PublicKey.findProgramAddressSync(
    [CLIMB_SEED, verified.commitmentHash],
    options.programId,
  );
  const [climbVersionIndex] = PublicKey.findProgramAddressSync(
    [CLIMB_VERSION_INDEX_SEED, verified.canonId, versionBytes],
    options.programId,
  );
  const [programConfig] = PublicKey.findProgramAddressSync([PROGRAM_CONFIG_SEED], options.programId);

  let predecessorClimb: PublicKey | null = null;
  let predecessorVersionIndex: PublicKey | null = null;
  let connection: Connection | undefined;
  let program: anchor.Program | undefined;
  let admin: Keypair | undefined;
  let feePayer: Keypair | undefined;

  if (verified.row.version > 1 && !options.rpcUrl) {
    throw new Error('successor rows require --rpc to prove the exact current predecessor head');
  }
  if (options.rpcUrl) {
    connection = new Connection(options.rpcUrl, 'finalized');
    if (options.send) {
      admin = loadKeypair(options.adminKeypair!);
      feePayer = loadKeypair(options.feePayerKeypair!);
      if (admin.publicKey.equals(feePayer.publicKey)) {
        throw new Error('admin and fee payer must be distinct keypairs');
      }
    }
    const provider = new anchor.AnchorProvider(
      connection,
      admin ? new anchor.Wallet(admin) : readonlyWallet(),
      { commitment: 'finalized', preflightCommitment: 'finalized' },
    );
    const idl = JSON.parse(fs.readFileSync(IDL_PATH, 'utf8')) as anchor.Idl;
    program = new anchor.Program(idl, options.programId, provider);

    const existingIndex = await (program.account as any).climbVersionIndex.fetchNullable(climbVersionIndex);
    if (existingIndex) {
      if (!new PublicKey(existingIndex.climb).equals(climb)) {
        throw new Error('canon version index is already bound to a different Climb PDA');
      }
      throw new Error(`registry row is already registered at ${climb.toBase58()}`);
    }
    if (await connection.getAccountInfo(climb, 'finalized')) {
      throw new Error('commitment Climb PDA already exists without the expected version index');
    }

    if (verified.row.version > 1) {
      const predecessorVersionBytes = Buffer.alloc(2);
      predecessorVersionBytes.writeUInt16BE(verified.row.version - 1);
      [predecessorVersionIndex] = PublicKey.findProgramAddressSync(
        [CLIMB_VERSION_INDEX_SEED, verified.canonId, predecessorVersionBytes],
        options.programId,
      );
      const predecessorIndex = await (program.account as any).climbVersionIndex.fetchNullable(
        predecessorVersionIndex,
      );
      if (!predecessorIndex) throw new Error('exact predecessor version index is missing');
      predecessorClimb = new PublicKey(predecessorIndex.climb);
      const predecessor = await (program.account as any).climb.fetch(predecessorClimb);
      if (
        Number(predecessor.canonVersion) !== verified.row.version - 1
        || !Buffer.from(predecessor.canonId).equals(verified.canonId)
      ) {
        throw new Error('predecessor index does not resolve to the exact canon lineage');
      }
      if (!new PublicKey(predecessor.successorClimb).equals(PublicKey.default)) {
        throw new Error('predecessor is stale because a successor is already registered');
      }
    }
  }

  const report: JsonObject = {
    status: options.send ? 'ready_to_send' : 'verified_dry_run',
    registry_row_uuid: verified.rowId,
    canon_id: verified.row.canon_id,
    canon_version: verified.row.version,
    profile_hash_algorithm: PROFILE_HASH_ALGORITHM,
    canonical_profile_hash: verified.profileHash.toString('hex'),
    canon_commitment_hex: verified.canonCommitment.toString('hex'),
    commitment_hash: verified.commitmentHash.toString('hex'),
    program_id: options.programId.toBase58(),
    program_config_pda: programConfig.toBase58(),
    climb_pda: climb.toBase58(),
    climb_version_index_pda: climbVersionIndex.toBase58(),
    predecessor_registry_row_uuid: verified.row.supersedes_climb_id,
    predecessor_climb_pda: predecessorClimb?.toBase58() ?? null,
    predecessor_version_index_pda: predecessorVersionIndex?.toBase58() ?? null,
    record_continuity_policy: verified.row.record_continuity_policy,
    chain_metric_projection_algorithm: CHAIN_METRIC_PROJECTION_ALGORITHM,
    onchain_metrics: {
      vert_decimeters: verified.vertDecimeters,
      distance_meters: verified.distanceMeters,
      avg_gradient_basis_points: verified.gradientBasisPoints,
    },
  };

  if (options.send) {
    const programConfigAccount = await (program!.account as any).programConfig.fetch(programConfig);
    if (
      PROGRAM_VERSION_FAMILY !== 'V4-B'
      || CURRENT_PROGRAM_VERSION !== 0x4e
      || programConfigAccount.initialized !== true
      || Number(programConfigAccount.programVersion) !== CURRENT_PROGRAM_VERSION
    ) {
      throw new Error(
        `target ProgramConfig is not the initialized fresh ${PROGRAM_VERSION_FAMILY} `
        + `0x${CURRENT_PROGRAM_VERSION.toString(16).toUpperCase()} contract`,
      );
    }
    if (!new PublicKey(programConfigAccount.adminAuthority).equals(admin!.publicKey)) {
      throw new Error('admin keypair does not match ProgramConfig admin authority');
    }
    const instruction = await (program!.methods as any)
      .registerRatifiedClimb({
        commitmentHash: Array.from(verified.commitmentHash),
        canonId: Array.from(verified.canonId),
        canonVersion: verified.row.version,
        canonicalProfileHash: Array.from(verified.profileHash),
        name: verified.row.display_name,
        vertM: verified.vertDecimeters,
        distanceM: verified.distanceMeters,
        avgGradientPct: verified.gradientBasisPoints,
        recordContinuityPolicy: { newRecordBoard: {} },
      })
      .accounts({
        climb,
        climbVersionIndex,
        predecessorClimb,
        programConfig,
        admin: admin!.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .instruction();
    const transaction = new Transaction().add(instruction);
    transaction.feePayer = feePayer!.publicKey;
    const signature = await sendAndConfirmTransaction(
      connection!,
      transaction,
      [feePayer!, admin!],
      { commitment: 'finalized', preflightCommitment: 'finalized' },
    );
    const registered = await (program!.account as any).climb.fetch(climb, 'finalized');
    if (
      !Buffer.from(registered.commitmentHash).equals(verified.commitmentHash)
      || Number(registered.canonVersion) !== verified.row.version
    ) {
      throw new Error('finalized Climb does not match the verified registry artifact');
    }
    report.status = 'registered_finalized';
    report.signature = signature;
  }

  console.log(JSON.stringify(report, null, 2));
}

if (path.resolve(process.argv[1] ?? '') === __filename) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
