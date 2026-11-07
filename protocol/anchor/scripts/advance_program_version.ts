/** Advance the live ProgramConfig compatibility byte by one exact patch. */

import {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  TransactionInstruction,
  sendAndConfirmTransaction,
} from '@solana/web3.js';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

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
const PROGRAM_CONFIG_VERSION_OFFSET = 72;
const PROGRAM_CONFIG_INITIALIZED_OFFSET = 73;
const PROGRAM_CONFIG_STABLE_PREFIX_SIZE = 75;

interface Options {
  rpcUrl: string;
  programId: PublicKey;
  adminKeypair: string;
  feePayerKeypair: string;
}

function discriminator(namespace: 'account' | 'global', name: string): Buffer {
  return crypto.createHash('sha256').update(`${namespace}:${name}`).digest().subarray(0, 8);
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
  let adminKeypair = process.env.ADMIN_KEYPAIR ?? DEFAULT_ADMIN_KEYPAIR;
  let feePayerKeypair = process.env.FEE_PAYER_KEYPAIR ?? DEFAULT_FEE_PAYER_KEYPAIR;

  for (let index = 0; index < args.length; index += 1) {
    const value = args[index + 1];
    if (args[index] === '--rpc' && value) {
      rpcUrl = value;
      index += 1;
    } else if (args[index] === '--program-id' && value) {
      programId = new PublicKey(value);
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

  return { rpcUrl, programId, adminKeypair, feePayerKeypair };
}

function decodeStablePrefix(data: Buffer): { admin: PublicKey; version: number } {
  if (data.length < PROGRAM_CONFIG_STABLE_PREFIX_SIZE) {
    throw new Error(`ProgramConfig stable prefix is truncated (${data.length} bytes)`);
  }
  if (!data.subarray(0, 8).equals(discriminator('account', 'ProgramConfig'))) {
    throw new Error('ProgramConfig discriminator mismatch');
  }
  if (data[PROGRAM_CONFIG_INITIALIZED_OFFSET] !== 1) {
    throw new Error('ProgramConfig is not initialized');
  }
  return {
    admin: new PublicKey(data.subarray(8, 40)),
    version: data[PROGRAM_CONFIG_VERSION_OFFSET],
  };
}

function assertOnlyVersionByteChanged(before: Buffer, after: Buffer): void {
  if (after.length !== before.length) {
    throw new Error(`ProgramConfig length changed from ${before.length} to ${after.length}`);
  }
  for (let offset = 0; offset < before.length; offset += 1) {
    if (offset !== PROGRAM_CONFIG_VERSION_OFFSET && before[offset] !== after[offset]) {
      throw new Error(`ProgramConfig byte ${offset} changed during version transition`);
    }
  }
}

async function main(): Promise<void> {
  const options = parseArgs();
  const admin = loadKeypair(options.adminKeypair);
  const feePayer = loadKeypair(options.feePayerKeypair);
  if (admin.publicKey.equals(feePayer.publicKey)) {
    throw new Error('ProgramConfig admin cannot be used as the transaction fee payer');
  }

  const connection = new Connection(options.rpcUrl, 'finalized');
  const [programConfig] = PublicKey.findProgramAddressSync(
    [Buffer.from('program_config')],
    options.programId,
  );
  const beforeResponse = await connection.getAccountInfoAndContext(programConfig, 'finalized');
  if (!beforeResponse.value) throw new Error('ProgramConfig is missing');
  if (!beforeResponse.value.owner.equals(options.programId)) {
    throw new Error('ProgramConfig owner mismatch');
  }
  const before = Buffer.from(beforeResponse.value.data);
  const decoded = decodeStablePrefix(before);
  if (!decoded.admin.equals(admin.publicKey)) {
    throw new Error(
      `admin key ${admin.publicKey.toBase58()} does not match ProgramConfig ${decoded.admin.toBase58()}`,
    );
  }

  if (decoded.version === CURRENT_PROGRAM_VERSION) {
    console.log(JSON.stringify({
      status: 'already_current',
      program_id: options.programId.toBase58(),
      program_config: programConfig.toBase58(),
      finalized_slot: beforeResponse.context.slot,
      current_version: CURRENT_PROGRAM_VERSION,
      previous_client_compatible: false,
      abi_sha256: PROGRAM_ABI_SHA256,
    }, null, 2));
    return;
  }
  if (decoded.version !== PREVIOUS_PROGRAM_VERSION) {
    throw new Error(
      `ProgramConfig transition requires 0x${PREVIOUS_PROGRAM_VERSION.toString(16)}, `
      + `found 0x${decoded.version.toString(16)}`,
    );
  }

  const instruction = new TransactionInstruction({
    programId: options.programId,
    keys: [
      { pubkey: programConfig, isSigner: false, isWritable: true },
      { pubkey: admin.publicKey, isSigner: true, isWritable: false },
    ],
    data: Buffer.concat([
      discriminator('global', 'advance_program_version'),
      Buffer.from([PREVIOUS_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION]),
    ]),
  });
  const transaction = new Transaction().add(instruction);
  transaction.feePayer = feePayer.publicKey;
  const signature = await sendAndConfirmTransaction(
    connection,
    transaction,
    [feePayer, admin],
    { commitment: 'finalized', preflightCommitment: 'finalized' },
  );

  const afterResponse = await connection.getAccountInfoAndContext(programConfig, 'finalized');
  if (!afterResponse.value) throw new Error('ProgramConfig disappeared after transition');
  const after = Buffer.from(afterResponse.value.data);
  assertOnlyVersionByteChanged(before, after);
  const afterDecoded = decodeStablePrefix(after);
  if (afterDecoded.version !== CURRENT_PROGRAM_VERSION) {
    throw new Error(`finalized ProgramConfig remained at 0x${afterDecoded.version.toString(16)}`);
  }

  console.log(JSON.stringify({
    status: 'advanced',
    signature,
    program_id: options.programId.toBase58(),
    program_config: programConfig.toBase58(),
    before_finalized_slot: beforeResponse.context.slot,
    after_finalized_slot: afterResponse.context.slot,
    previous_version: PREVIOUS_PROGRAM_VERSION,
    current_version: CURRENT_PROGRAM_VERSION,
    account_length: after.length,
    changed_offsets: [PROGRAM_CONFIG_VERSION_OFFSET],
    previous_client_compatible: false,
    abi_sha256: PROGRAM_ABI_SHA256,
  }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
