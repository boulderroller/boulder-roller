// Finalized-only operator for the bounded V4-B settlement-clock lineage bridge.
import crypto from 'node:crypto';
import fs from 'node:fs';
import {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js';

const V4B_PROGRAM_ID = new PublicKey(
  'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH',
);
const V4B_ADMIN_AUTHORITY = new PublicKey(
  'G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH',
);
const V4B_BACKEND_AUTHORITY = new PublicKey(
  'CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha',
);
const PROGRAM_CONFIG = new PublicKey(
  '59baJ2JF7WBjMp8xTtvyw5uaiN9K8R3NX868kGyWZq2D',
);
const VAULT_COUNTER = new PublicKey(
  '8qcexnhoo8YYfh73yLY54ng9vfpBG8YdJkA1w7E6C3dT',
);
const CAL_MINT = new PublicKey('4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh');
const DUNG_MINT = new PublicKey('CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk');
const BPF_UPGRADEABLE_LOADER = new PublicKey(
  'BPFLoaderUpgradeab1e11111111111111111111111',
);
const PROGRAMDATA_METADATA_LEN = 45;
const PROGRAM_CONFIG_SIZE = 334;
const VAULT_COUNTER_SIZE = 17;
const PROGRAM_CONFIG_DISCRIMINATOR = Buffer.from('c4d25ae790958c3f', 'hex');
const VAULT_COUNTER_DISCRIMINATOR = Buffer.from('b47f7ae69a7e7e62', 'hex');
const PROGRAM_CONFIG_ADMIN_OFFSET = 8;
const PROGRAM_CONFIG_BACKEND_OFFSET = PROGRAM_CONFIG_ADMIN_OFFSET + 32;
const PROGRAM_CONFIG_VERSION_OFFSET = PROGRAM_CONFIG_BACKEND_OFFSET + 32;
const PROGRAM_CONFIG_INITIALIZED_OFFSET = PROGRAM_CONFIG_VERSION_OFFSET + 1;
const PROGRAM_CONFIG_CAL_MINT_OFFSET = PROGRAM_CONFIG_INITIALIZED_OFFSET + 2;
const PROGRAM_CONFIG_DUNG_MINT_OFFSET = PROGRAM_CONFIG_CAL_MINT_OFFSET + 32;
const PROGRAM_CONFIG_CLOCK_OFFSET = 325;
const PROGRAM_CONFIG_CLOCK_VERSION_OFFSET = PROGRAM_CONFIG_CLOCK_OFFSET + 8;
const V4B_PROGRAM_VERSION = 0x4b;
const SETTLEMENT_CLOCK_VERSION_V2 = 2;
const FRESH_V2_ONLY_ANCHOR = 1_704_110_400n;
const RATIFIED_PRODUCTION_CUTOVER = 1_784_548_800n;

function usage() {
  return [
    'Usage: node execute_v4b_settlement_clock_handoff.mjs',
    '  --admin-keypair <V4-B admin keypair path>',
    '  --fee-payer <powerless fee-payer keypair path>',
    '  --bridge-artifact <reviewed v4b_settlement_clock_handoff.so path>',
    '  [--rpc <finalized RPC URL>] [--send]',
    '',
    'Dry-run is the default. --send performs the exact finalized lineage handoff.',
  ].join('\n');
}

function parseArgs(argv) {
  const values = {
    rpc: 'https://api.devnet.solana.com',
    send: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--help' || arg === '-h') {
      values.help = true;
      continue;
    }
    if (arg === '--send') {
      values.send = true;
      continue;
    }
    if (
      ['--rpc', '--admin-keypair', '--fee-payer', '--bridge-artifact'].includes(arg)
      && argv[index + 1]
    ) {
      values[arg.slice(2).replaceAll('-', '_')] = argv[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`Unknown or incomplete argument: ${arg}`);
  }
  if (values.help) return values;
  for (const required of ['admin_keypair', 'fee_payer', 'bridge_artifact']) {
    if (!values[required]) throw new Error(`Missing --${required.replaceAll('_', '-')}`);
  }
  return values;
}

function loadKeypair(filePath) {
  const bytes = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  if (!Array.isArray(bytes) || bytes.length !== 64) {
    throw new Error(`Invalid keypair file: ${filePath}`);
  }
  return Keypair.fromSecretKey(Uint8Array.from(bytes));
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function readPubkey(data, start) {
  return new PublicKey(data.subarray(start, start + 32));
}

async function assertBridgeArtifact(connection, artifactPath) {
  const artifact = fs.readFileSync(artifactPath);
  const programAccount = await connection.getAccountInfo(V4B_PROGRAM_ID, 'finalized');
  if (
    !programAccount
    || !programAccount.executable
    || !programAccount.owner.equals(BPF_UPGRADEABLE_LOADER)
    || programAccount.data.length < 36
    || programAccount.data.readUInt32LE(0) !== 2
  ) {
    throw new Error('V4-B program is not an executable upgradeable-loader Program account');
  }
  const programDataAddress = new PublicKey(programAccount.data.subarray(4, 36));
  const programData = await connection.getAccountInfo(programDataAddress, 'finalized');
  if (
    !programData
    || !programData.owner.equals(BPF_UPGRADEABLE_LOADER)
    || programData.data.length < PROGRAMDATA_METADATA_LEN + artifact.length
    || programData.data.readUInt32LE(0) !== 3
  ) {
    throw new Error('V4-B ProgramData account is unavailable or malformed');
  }
  const deployedPrefix = programData.data.subarray(
    PROGRAMDATA_METADATA_LEN,
    PROGRAMDATA_METADATA_LEN + artifact.length,
  );
  const deployedRemainder = programData.data.subarray(
    PROGRAMDATA_METADATA_LEN + artifact.length,
  );
  if (!deployedPrefix.equals(artifact) || deployedRemainder.some((byte) => byte !== 0)) {
    throw new Error('deployed V4-B bytes do not equal the reviewed lineage bridge');
  }
  return {
    program_data: programDataAddress.toBase58(),
    artifact_sha256: sha256(artifact),
  };
}

async function readRuntimeState(connection) {
  const response = await connection.getMultipleAccountsInfoAndContext(
    [PROGRAM_CONFIG, VAULT_COUNTER],
    { commitment: 'finalized' },
  );
  const [config, counter] = response.value;
  if (
    !config
    || !config.owner.equals(V4B_PROGRAM_ID)
    || config.data.length !== PROGRAM_CONFIG_SIZE
    || !config.data.subarray(0, 8).equals(PROGRAM_CONFIG_DISCRIMINATOR)
  ) {
    throw new Error('V4-B ProgramConfig is unavailable or malformed');
  }
  if (
    !counter
    || !counter.owner.equals(V4B_PROGRAM_ID)
    || counter.data.length !== VAULT_COUNTER_SIZE
    || !counter.data.subarray(0, 8).equals(VAULT_COUNTER_DISCRIMINATOR)
  ) {
    throw new Error('V4-B VaultCounter is unavailable or malformed');
  }

  const state = {
    finalized_slot: response.context.slot,
    program_config: PROGRAM_CONFIG.toBase58(),
    vault_counter: VAULT_COUNTER.toBase58(),
    admin: readPubkey(config.data, PROGRAM_CONFIG_ADMIN_OFFSET).toBase58(),
    backend: readPubkey(config.data, PROGRAM_CONFIG_BACKEND_OFFSET).toBase58(),
    program_version: config.data[PROGRAM_CONFIG_VERSION_OFFSET],
    initialized: config.data[PROGRAM_CONFIG_INITIALIZED_OFFSET] === 1,
    cal_mint: readPubkey(config.data, PROGRAM_CONFIG_CAL_MINT_OFFSET).toBase58(),
    dung_mint: readPubkey(config.data, PROGRAM_CONFIG_DUNG_MINT_OFFSET).toBase58(),
    settlement_clock_v2_starts_at:
      config.data.readBigInt64LE(PROGRAM_CONFIG_CLOCK_OFFSET),
    settlement_clock_version: config.data[PROGRAM_CONFIG_CLOCK_VERSION_OFFSET],
    vault_count: counter.data.readBigUInt64LE(8),
  };
  if (
    state.admin !== V4B_ADMIN_AUTHORITY.toBase58()
    || state.backend !== V4B_BACKEND_AUTHORITY.toBase58()
    || state.program_version !== V4B_PROGRAM_VERSION
    || !state.initialized
    || state.cal_mint !== CAL_MINT.toBase58()
    || state.dung_mint !== DUNG_MINT.toBase58()
    || state.settlement_clock_version !== SETTLEMENT_CLOCK_VERSION_V2
    || state.vault_count !== 0n
  ) {
    throw new Error('V4-B runtime identity or zero-history gate does not match');
  }
  if (
    state.settlement_clock_v2_starts_at !== FRESH_V2_ONLY_ANCHOR
    && state.settlement_clock_v2_starts_at !== RATIFIED_PRODUCTION_CUTOVER
  ) {
    throw new Error('V4-B settlement clock is neither the fresh nor ratified lineage');
  }
  return state;
}

function printableState(state) {
  return {
    ...state,
    settlement_clock_v2_starts_at: state.settlement_clock_v2_starts_at.toString(),
    vault_count: state.vault_count.toString(),
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }
  const connection = new Connection(args.rpc, 'finalized');
  const admin = loadKeypair(args.admin_keypair);
  const feePayer = loadKeypair(args.fee_payer);
  if (!admin.publicKey.equals(V4B_ADMIN_AUTHORITY)) {
    throw new Error(`admin keypair must resolve to ${V4B_ADMIN_AUTHORITY.toBase58()}`);
  }
  if (admin.publicKey.equals(feePayer.publicKey)) {
    throw new Error('admin authority and fee payer must remain separate');
  }

  const before = await readRuntimeState(connection);
  const bridge = await assertBridgeArtifact(connection, args.bridge_artifact);
  const plan = {
    mode: args.send ? 'send' : 'dry_run',
    rpc: args.rpc,
    program: V4B_PROGRAM_ID.toBase58(),
    admin: admin.publicKey.toBase58(),
    fee_payer: feePayer.publicKey.toBase58(),
    from_cutover: FRESH_V2_ONLY_ANCHOR.toString(),
    to_cutover: RATIFIED_PRODUCTION_CUTOVER.toString(),
    before: printableState(before),
    bridge,
  };
  if (!args.send) {
    console.log(JSON.stringify(plan, null, 2));
    return;
  }

  const instruction = new TransactionInstruction({
    programId: V4B_PROGRAM_ID,
    keys: [
      { pubkey: admin.publicKey, isSigner: true, isWritable: false },
      { pubkey: PROGRAM_CONFIG, isSigner: false, isWritable: true },
      { pubkey: VAULT_COUNTER, isSigner: false, isWritable: false },
    ],
    data: Buffer.from([1]),
  });
  const latest = await connection.getLatestBlockhash('finalized');
  const transaction = new Transaction({
    feePayer: feePayer.publicKey,
    blockhash: latest.blockhash,
    lastValidBlockHeight: latest.lastValidBlockHeight,
  }).add(instruction);
  transaction.sign(feePayer, admin);
  const signature = await connection.sendRawTransaction(transaction.serialize(), {
    preflightCommitment: 'finalized',
    skipPreflight: false,
  });
  await connection.confirmTransaction({ signature, ...latest }, 'finalized');

  const after = await readRuntimeState(connection);
  if (
    after.settlement_clock_v2_starts_at !== RATIFIED_PRODUCTION_CUTOVER
    || after.vault_count !== 0n
  ) {
    throw new Error('finalized V4-B settlement clock lineage handoff did not persist');
  }
  const finalizedTransaction = await connection.getTransaction(signature, {
    commitment: 'finalized',
    maxSupportedTransactionVersion: 0,
  });
  console.log(JSON.stringify({
    ...plan,
    signature,
    transaction_slot: finalizedTransaction?.slot ?? null,
    after: printableState(after),
    finalized: true,
  }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
