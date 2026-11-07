/** Migrate legacy Local Legend accounts to the explicit bootstrap layout. */
// Usage: NODE_OPTIONS='--loader ts-node/esm --no-warnings' node
//   scripts/migrate_local_legends.ts --expected-legacy <count> [--apply]

import {
  Connection,
  Keypair,
  PublicKey,
  SystemProgram,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
} from '@solana/web3.js';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

import {
  CURRENT_PROGRAM_VERSION,
  PREVIOUS_PROGRAM_VERSION,
  PROGRAM_ABI_SHA256,
} from '../generated-program-version.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_ADDRESSES_FILE = path.join(__dirname, '..', 'addresses.devnet.json');
const DEFAULT_ADMIN_KEYPAIR = path.join(
  process.env.HOME ?? '',
  '.config',
  'solana',
  'boulderroller-admin-upgrade-authority.json',
);
const DEFAULT_FEE_PAYER_KEYPAIR = path.join(
  process.env.HOME ?? '',
  '.config',
  'solana',
  'boulderroller-fee-payer.json',
);

export const LEGACY_LOCAL_LEGEND_SIZE = 122;
export const CURRENT_LOCAL_LEGEND_SIZE = 123;
const VAULT_ID_OFFSET = 8;
const ELECTION_PERIOD_OFFSET = 48;
const COMPLETIONS_AT_ELECTION_OFFSET = 72;
const IS_ACTIVE_OFFSET = 120;
const IS_BOOTSTRAP_OFFSET = 121;
const LEGACY_BUMP_OFFSET = 121;
const CURRENT_BUMP_OFFSET = 122;
const PROGRAM_CONFIG_VERSION_OFFSET = 72;
const PROGRAM_CONFIG_INITIALIZED_OFFSET = 73;

export type LocalLegendLayout =
  | { kind: 'legacy'; isBootstrap: boolean; bump: number }
  | { kind: 'current'; isBootstrap: boolean; bump: number };

export interface LocalLegendSnapshot {
  vaultId: number;
  pubkey: PublicKey;
  data: Buffer;
  lamports: number;
  layout: LocalLegendLayout;
  sha256: string;
}

interface Options {
  rpcUrl: string;
  programId: PublicKey;
  apply: boolean;
  expectedLegacy?: number;
  batchSize: number;
  adminKeypair: string;
  feePayerKeypair: string;
}

interface AppliedMigrationBatch {
  vault_ids: number[];
  serialized_bytes: number;
  signature: string;
}

function discriminator(namespace: 'account' | 'global', name: string): Buffer {
  return crypto.createHash('sha256').update(`${namespace}:${name}`).digest().subarray(0, 8);
}

function sha256(data: Buffer): string {
  return crypto.createHash('sha256').update(data).digest('hex');
}

function u64(value: number): Buffer {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`vault id is not a safe unsigned integer: ${value}`);
  }
  const data = Buffer.alloc(8);
  data.writeBigUInt64LE(BigInt(value));
  return data;
}

function readSafeU64(data: Buffer, offset: number, field: string): number {
  const value = data.readBigUInt64LE(offset);
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error(`${field} exceeds JavaScript's safe integer range`);
  }
  return Number(value);
}

export function inspectLocalLegend(
  data: Buffer,
  expectedVaultId: number,
  expectedBump: number,
): LocalLegendLayout {
  if (![LEGACY_LOCAL_LEGEND_SIZE, CURRENT_LOCAL_LEGEND_SIZE].includes(data.length)) {
    throw new Error(`unsupported Local Legend length ${data.length}`);
  }
  if (!data.subarray(0, 8).equals(discriminator('account', 'LocalLegend'))) {
    throw new Error('Local Legend discriminator mismatch');
  }
  const vaultId = readSafeU64(data, VAULT_ID_OFFSET, 'vault_id');
  if (vaultId !== expectedVaultId) {
    throw new Error(`Local Legend vault id ${vaultId} does not match ${expectedVaultId}`);
  }
  if (![0, 1].includes(data[IS_ACTIVE_OFFSET])) {
    throw new Error('Local Legend is_active byte is noncanonical');
  }

  if (data.length === CURRENT_LOCAL_LEGEND_SIZE) {
    if (![0, 1].includes(data[IS_BOOTSTRAP_OFFSET])) {
      throw new Error('Local Legend is_bootstrap byte is noncanonical');
    }
    if (data[CURRENT_BUMP_OFFSET] !== expectedBump) {
      throw new Error('Local Legend current-layout bump mismatch');
    }
    return {
      kind: 'current',
      isBootstrap: data[IS_BOOTSTRAP_OFFSET] === 1,
      bump: data[CURRENT_BUMP_OFFSET],
    };
  }

  if (data[LEGACY_BUMP_OFFSET] !== expectedBump) {
    throw new Error('Local Legend legacy-layout bump mismatch');
  }
  const electionPeriod = data.readBigUInt64LE(ELECTION_PERIOD_OFFSET);
  const completionsAtElection = data.readUInt32LE(COMPLETIONS_AT_ELECTION_OFFSET);
  return {
    kind: 'legacy',
    isBootstrap:
      data[IS_ACTIVE_OFFSET] === 1
      && electionPeriod === 0n
      && completionsAtElection === 0,
    bump: data[LEGACY_BUMP_OFFSET],
  };
}

export function assertMigrationOutcome(
  before: LocalLegendSnapshot,
  after: LocalLegendSnapshot,
  minimumCurrentRent: number,
): void {
  if (!after.pubkey.equals(before.pubkey) || after.vaultId !== before.vaultId) {
    throw new Error(`Local Legend identity changed for vault ${before.vaultId}`);
  }

  if (before.layout.kind === 'current') {
    if (!after.data.equals(before.data) || after.lamports !== before.lamports) {
      throw new Error(`current Local Legend ${before.vaultId} changed during migration`);
    }
    return;
  }

  if (after.layout.kind !== 'current') {
    throw new Error(`legacy Local Legend ${before.vaultId} did not migrate`);
  }
  if (!after.data.subarray(0, IS_BOOTSTRAP_OFFSET).equals(
    before.data.subarray(0, IS_BOOTSTRAP_OFFSET),
  )) {
    throw new Error(`Local Legend ${before.vaultId} changed before byte 121`);
  }
  if (after.data[IS_BOOTSTRAP_OFFSET] !== Number(before.layout.isBootstrap)) {
    throw new Error(`Local Legend ${before.vaultId} bootstrap inference changed`);
  }
  if (after.data[CURRENT_BUMP_OFFSET] !== before.data[LEGACY_BUMP_OFFSET]) {
    throw new Error(`Local Legend ${before.vaultId} bump was not relocated exactly`);
  }
  const expectedLamports = Math.max(before.lamports, minimumCurrentRent);
  if (after.lamports !== expectedLamports) {
    throw new Error(
      `Local Legend ${before.vaultId} rent changed to ${after.lamports}, expected ${expectedLamports}`,
    );
  }
}

function loadKeypair(filePath: string): Keypair {
  return Keypair.fromSecretKey(
    Uint8Array.from(JSON.parse(fs.readFileSync(filePath, 'utf-8'))),
  );
}

function loadDefaultProgramId(): PublicKey {
  const addresses = JSON.parse(fs.readFileSync(DEFAULT_ADDRESSES_FILE, 'utf-8'));
  return new PublicKey(addresses.programs.boulder_rollers);
}

function parseArgs(): Options {
  const args = process.argv.slice(2);
  let rpcUrl = process.env.SOLANA_RPC_URL ?? 'https://api.devnet.solana.com';
  let programId = loadDefaultProgramId();
  let apply = false;
  let expectedLegacy: number | undefined;
  let batchSize = 4;
  let adminKeypair = process.env.ADMIN_KEYPAIR ?? DEFAULT_ADMIN_KEYPAIR;
  let feePayerKeypair = process.env.FEE_PAYER_KEYPAIR ?? DEFAULT_FEE_PAYER_KEYPAIR;

  for (let index = 0; index < args.length; index += 1) {
    const value = args[index + 1];
    if (args[index] === '--apply') {
      apply = true;
    } else if (args[index] === '--rpc' && value) {
      rpcUrl = value;
      index += 1;
    } else if (args[index] === '--program-id' && value) {
      programId = new PublicKey(value);
      index += 1;
    } else if (args[index] === '--expected-legacy' && value) {
      expectedLegacy = Number(value);
      index += 1;
    } else if (args[index] === '--batch-size' && value) {
      batchSize = Number(value);
      index += 1;
    } else if (args[index] === '--admin-keypair' && value) {
      adminKeypair = value;
      index += 1;
    } else if (args[index] === '--fee-payer' && value) {
      feePayerKeypair = value;
      index += 1;
    } else {
      throw new Error(`unknown or incomplete argument: ${args[index]}`);
    }
  }

  if (expectedLegacy !== undefined && (!Number.isInteger(expectedLegacy) || expectedLegacy < 0)) {
    throw new Error('--expected-legacy must be a nonnegative integer');
  }
  if (!Number.isInteger(batchSize) || batchSize < 1 || batchSize > 8) {
    throw new Error('--batch-size must be an integer from 1 through 8');
  }
  if (apply && expectedLegacy === undefined) {
    throw new Error('--apply requires --expected-legacy from a reviewed finalized census');
  }
  return {
    rpcUrl,
    programId,
    apply,
    expectedLegacy,
    batchSize,
    adminKeypair,
    feePayerKeypair,
  };
}

async function readVaultCount(
  connection: Connection,
  programId: PublicKey,
): Promise<{ count: number; slot: number }> {
  const [vaultCounter] = PublicKey.findProgramAddressSync(
    [Buffer.from('vault_counter')],
    programId,
  );
  const response = await connection.getAccountInfoAndContext(vaultCounter, 'finalized');
  if (!response.value || !response.value.owner.equals(programId) || response.value.data.length < 16) {
    throw new Error('VaultCounter is missing or invalid');
  }
  if (!response.value.data.subarray(0, 8).equals(discriminator('account', 'VaultCounter'))) {
    throw new Error('VaultCounter discriminator mismatch');
  }
  return {
    count: readSafeU64(response.value.data, 8, 'VaultCounter.count'),
    slot: response.context.slot,
  };
}

async function readProgramVersion(
  connection: Connection,
  programId: PublicKey,
): Promise<{ programConfig: PublicKey; version: number; slot: number }> {
  const [programConfig] = PublicKey.findProgramAddressSync(
    [Buffer.from('program_config')],
    programId,
  );
  const response = await connection.getAccountInfoAndContext(programConfig, 'finalized');
  const account = response.value;
  if (!account || !account.owner.equals(programId) || account.data.length <= PROGRAM_CONFIG_INITIALIZED_OFFSET) {
    throw new Error('ProgramConfig is missing or invalid');
  }
  if (!account.data.subarray(0, 8).equals(discriminator('account', 'ProgramConfig'))) {
    throw new Error('ProgramConfig discriminator mismatch');
  }
  if (account.data[PROGRAM_CONFIG_INITIALIZED_OFFSET] !== 1) {
    throw new Error('ProgramConfig is not initialized');
  }
  const version = account.data[PROGRAM_CONFIG_VERSION_OFFSET];
  if (version !== PREVIOUS_PROGRAM_VERSION && version !== CURRENT_PROGRAM_VERSION) {
    throw new Error(`unsupported live ProgramConfig version 0x${version.toString(16)}`);
  }
  return { programConfig, version, slot: response.context.slot };
}

async function readCensus(
  connection: Connection,
  programId: PublicKey,
  count: number,
): Promise<{ slot: number; rows: LocalLegendSnapshot[] }> {
  const identities = Array.from({ length: count }, (_, vaultId) => {
    const [pubkey, bump] = PublicKey.findProgramAddressSync(
      [Buffer.from('local_legend'), u64(vaultId)],
      programId,
    );
    return { vaultId, pubkey, bump };
  });
  const response = await connection.getMultipleAccountsInfoAndContext(
    identities.map(({ pubkey }) => pubkey),
    { commitment: 'finalized' },
  );
  const rows = identities.map(({ vaultId, pubkey, bump }, index) => {
    const account = response.value[index];
    if (!account || !account.owner.equals(programId)) {
      throw new Error(`Local Legend ${vaultId} is missing or has the wrong owner`);
    }
    const data = Buffer.from(account.data);
    return {
      vaultId,
      pubkey,
      data,
      lamports: account.lamports,
      layout: inspectLocalLegend(data, vaultId, bump),
      sha256: sha256(data),
    };
  });
  return { slot: response.context.slot, rows };
}

function migrationInstruction(
  programId: PublicKey,
  programConfig: PublicKey,
  row: LocalLegendSnapshot,
  authority: PublicKey,
  payer: PublicKey,
): TransactionInstruction {
  return new TransactionInstruction({
    programId,
    keys: [
      { pubkey: row.pubkey, isSigner: false, isWritable: true },
      { pubkey: authority, isSigner: true, isWritable: false },
      { pubkey: payer, isSigner: true, isWritable: true },
      { pubkey: programConfig, isSigner: false, isWritable: false },
      { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
    ],
    data: Buffer.concat([discriminator('global', 'migrate_local_legend'), u64(row.vaultId)]),
  });
}

async function applyMigration(
  connection: Connection,
  options: Options,
  programConfig: PublicKey,
  legacyRows: LocalLegendSnapshot[],
): Promise<AppliedMigrationBatch[]> {
  const admin = loadKeypair(options.adminKeypair);
  const feePayer = loadKeypair(options.feePayerKeypair);
  if (admin.publicKey.equals(feePayer.publicKey)) {
    throw new Error('ProgramConfig admin cannot be used as the transaction fee payer');
  }

  const programConfigAccount = await connection.getAccountInfo(programConfig, 'finalized');
  if (!programConfigAccount) throw new Error('ProgramConfig disappeared');
  const storedAdmin = new PublicKey(programConfigAccount.data.subarray(8, 40));
  if (!storedAdmin.equals(admin.publicKey)) {
    throw new Error('admin key does not match ProgramConfig admin authority');
  }

  const batches: AppliedMigrationBatch[] = [];
  for (let offset = 0; offset < legacyRows.length; offset += options.batchSize) {
    const batch = legacyRows.slice(offset, offset + options.batchSize);
    const instructions = batch.map((row) => migrationInstruction(
      options.programId,
      programConfig,
      row,
      admin.publicKey,
      feePayer.publicKey,
    ));
    const latest = await connection.getLatestBlockhash('confirmed');
    const message = new TransactionMessage({
      payerKey: feePayer.publicKey,
      recentBlockhash: latest.blockhash,
      instructions,
    }).compileToLegacyMessage();
    const transaction = new VersionedTransaction(message);
    transaction.sign([feePayer, admin]);
    const serialized = transaction.serialize();
    if (serialized.length > 1232) {
      throw new Error(
        `migration transaction for vaults ${batch.map(({ vaultId }) => vaultId).join(',')} `
        + `is ${serialized.length} bytes`,
      );
    }
    const simulation = await connection.simulateTransaction(transaction, {
      commitment: 'confirmed',
      sigVerify: true,
    });
    if (simulation.value.err) {
      throw new Error(
        `migration simulation failed for vaults ${batch.map(({ vaultId }) => vaultId).join(',')}: `
        + `${JSON.stringify(simulation.value.err)}\n${(simulation.value.logs ?? []).join('\n')}`,
      );
    }
    const signature = await connection.sendRawTransaction(serialized, {
      skipPreflight: false,
      preflightCommitment: 'confirmed',
    });
    await connection.confirmTransaction({ signature, ...latest }, 'finalized');
    batches.push({
      vault_ids: batch.map(({ vaultId }) => vaultId),
      serialized_bytes: serialized.length,
      signature,
    });
  }
  return batches;
}

function summarizedRows(
  before: LocalLegendSnapshot[],
  after?: LocalLegendSnapshot[],
): Array<Record<string, unknown>> {
  return before.map((row, index) => ({
    vault_id: row.vaultId,
    pubkey: row.pubkey.toBase58(),
    before_length: row.data.length,
    before_layout: row.layout.kind,
    inferred_bootstrap: row.layout.isBootstrap,
    before_sha256: row.sha256,
    after_length: after?.[index].data.length ?? null,
    after_layout: after?.[index].layout.kind ?? null,
    after_sha256: after?.[index].sha256 ?? null,
    changed_offsets: after
      ? Array.from({ length: after[index].data.length }, (_, offset) => offset)
        .filter((offset) => row.data[offset] !== after[index].data[offset])
      : null,
  }));
}

async function main(): Promise<void> {
  const options = parseArgs();
  const connection = new Connection(options.rpcUrl, 'finalized');
  const counter = await readVaultCount(connection, options.programId);
  const version = await readProgramVersion(connection, options.programId);
  const before = await readCensus(connection, options.programId, counter.count);
  const legacyRows = before.rows.filter(({ layout }) => layout.kind === 'legacy');
  if (options.expectedLegacy !== undefined && legacyRows.length !== options.expectedLegacy) {
    throw new Error(
      `finalized census found ${legacyRows.length} legacy accounts, expected ${options.expectedLegacy}`,
    );
  }

  if (!options.apply) {
    console.log(JSON.stringify({
      status: 'dry_run',
      program_id: options.programId.toBase58(),
      program_version: version.version,
      program_abi_sha256: PROGRAM_ABI_SHA256,
      finalized_slots: {
        program_config: version.slot,
        vault_counter: counter.slot,
        local_legends: before.slot,
      },
      vault_count: counter.count,
      legacy_count: legacyRows.length,
      current_count: before.rows.length - legacyRows.length,
      rows: summarizedRows(before.rows),
    }, null, 2));
    return;
  }

  const transactionBatches = await applyMigration(
    connection,
    options,
    version.programConfig,
    legacyRows,
  );
  const after = await readCensus(connection, options.programId, counter.count);
  const minimumCurrentRent = await connection.getMinimumBalanceForRentExemption(
    CURRENT_LOCAL_LEGEND_SIZE,
    'finalized',
  );
  before.rows.forEach((row, index) => {
    assertMigrationOutcome(row, after.rows[index], minimumCurrentRent);
  });
  if (after.rows.some(({ layout }) => layout.kind !== 'current')) {
    throw new Error('finalized census still contains a legacy Local Legend account');
  }

  console.log(JSON.stringify({
    status: legacyRows.length === 0 ? 'already_current' : 'migrated',
    program_id: options.programId.toBase58(),
    program_version: version.version,
    program_abi_sha256: PROGRAM_ABI_SHA256,
    before_finalized_slot: before.slot,
    after_finalized_slot: after.slot,
    vault_count: counter.count,
    migrated_count: legacyRows.length,
    current_count: after.rows.length,
    transaction_batches: transactionBatches,
    rows: summarizedRows(before.rows, after.rows),
  }, null, 2));
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
