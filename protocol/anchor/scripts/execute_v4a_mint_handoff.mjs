// Finalized-only operator for the bounded V4-A mint-authority bridge.
import crypto from 'node:crypto';
import fs from 'node:fs';
import {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js';
import { getMint, TOKEN_PROGRAM_ID } from '@solana/spl-token';

const V4A_PROGRAM_ID = new PublicKey('HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst');
const V4A_ADMIN_AUTHORITY = new PublicKey(
  'G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH',
);
const V4B_BACKEND_AUTHORITY = new PublicKey(
  'CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha',
);
const CAL_MINT = new PublicKey('4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh');
const DUNG_MINT = new PublicKey('CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk');
const BPF_UPGRADEABLE_LOADER = new PublicKey(
  'BPFLoaderUpgradeab1e11111111111111111111111',
);
const PROGRAM_CONFIG_SEED = Buffer.from('program_config');
const CAL_MINT_AUTH_SEED = Buffer.from('cal_mint_auth');
const DUNG_MINT_AUTH_SEED = Buffer.from('dung_mint_auth');
const PROGRAMDATA_METADATA_LEN = 45;
const V4B_PROGRAM_VERSION = 0x4b;
const PROGRAM_CONFIG_DISCRIMINATOR = Buffer.from('c4d25ae790958c3f', 'hex');
const PROGRAM_CONFIG_ADMIN_OFFSET = 8;
const PROGRAM_CONFIG_BACKEND_OFFSET = PROGRAM_CONFIG_ADMIN_OFFSET + 32;
const PROGRAM_CONFIG_VERSION_OFFSET = PROGRAM_CONFIG_BACKEND_OFFSET + 32;
const PROGRAM_CONFIG_INITIALIZED_OFFSET = PROGRAM_CONFIG_VERSION_OFFSET + 1;
const PROGRAM_CONFIG_CAL_MINT_OFFSET = PROGRAM_CONFIG_INITIALIZED_OFFSET + 2;
const PROGRAM_CONFIG_DUNG_MINT_OFFSET = PROGRAM_CONFIG_CAL_MINT_OFFSET + 32;
const PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET = PROGRAM_CONFIG_DUNG_MINT_OFFSET + 32;
const PROGRAM_CONFIG_DUNG_MINT_AUTH_BUMP_OFFSET =
  PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET + 1;
const PROGRAM_CONFIG_MIN_LEN = PROGRAM_CONFIG_DUNG_MINT_AUTH_BUMP_OFFSET + 1;

function usage() {
  return [
    'Usage: node execute_v4a_mint_handoff.mjs',
    '  --target-program <fresh V4-B program ID>',
    '  --admin-keypair <V4-A admin keypair path>',
    '  --fee-payer <powerless fee-payer keypair path>',
    '  --bridge-artifact <reviewed v4a_mint_handoff.so path>',
    '  [--rpc <finalized RPC URL>] [--send]',
    '',
    'Dry-run is the default. --send performs the atomic finalized handoff.',
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
      ['--rpc', '--target-program', '--admin-keypair', '--fee-payer', '--bridge-artifact']
        .includes(arg)
      && argv[index + 1]
    ) {
      values[arg.slice(2).replaceAll('-', '_')] = argv[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`Unknown or incomplete argument: ${arg}`);
  }
  if (values.help) return values;
  for (const required of [
    'target_program',
    'admin_keypair',
    'fee_payer',
    'bridge_artifact',
  ]) {
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

async function assertBridgeArtifact(connection, artifactPath) {
  const artifact = fs.readFileSync(artifactPath);
  const programAccount = await connection.getAccountInfo(V4A_PROGRAM_ID, 'finalized');
  if (
    !programAccount
    || !programAccount.executable
    || !programAccount.owner.equals(BPF_UPGRADEABLE_LOADER)
    || programAccount.data.length < 36
    || programAccount.data.readUInt32LE(0) !== 2
  ) {
    throw new Error('V4-A program is not an executable upgradeable-loader Program account');
  }
  const programDataAddress = new PublicKey(programAccount.data.subarray(4, 36));
  const programData = await connection.getAccountInfo(programDataAddress, 'finalized');
  if (
    !programData
    || !programData.owner.equals(BPF_UPGRADEABLE_LOADER)
    || programData.data.length < PROGRAMDATA_METADATA_LEN + artifact.length
    || programData.data.readUInt32LE(0) !== 3
  ) {
    throw new Error('V4-A ProgramData account is unavailable or malformed');
  }
  const deployedPrefix = programData.data.subarray(
    PROGRAMDATA_METADATA_LEN,
    PROGRAMDATA_METADATA_LEN + artifact.length,
  );
  const deployedRemainder = programData.data.subarray(
    PROGRAMDATA_METADATA_LEN + artifact.length,
  );
  if (!deployedPrefix.equals(artifact) || deployedRemainder.some((byte) => byte !== 0)) {
    throw new Error('deployed V4-A bytes do not equal the reviewed handoff bridge');
  }
  return {
    program_data: programDataAddress.toBase58(),
    artifact_sha256: sha256(artifact),
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }
  const connection = new Connection(args.rpc, 'finalized');
  const targetProgram = new PublicKey(args.target_program);
  if (targetProgram.equals(V4A_PROGRAM_ID)) {
    throw new Error('target program must be a fresh V4-B program');
  }

  const admin = loadKeypair(args.admin_keypair);
  const feePayer = loadKeypair(args.fee_payer);
  if (!admin.publicKey.equals(V4A_ADMIN_AUTHORITY)) {
    throw new Error(`admin keypair must resolve to ${V4A_ADMIN_AUTHORITY.toBase58()}`);
  }
  if (admin.publicKey.equals(feePayer.publicKey)) {
    throw new Error('admin authority and fee payer must remain separate');
  }

  const [targetProgramConfig] = PublicKey.findProgramAddressSync(
    [PROGRAM_CONFIG_SEED],
    targetProgram,
  );
  const [oldCalAuthority] = PublicKey.findProgramAddressSync(
    [CAL_MINT_AUTH_SEED],
    V4A_PROGRAM_ID,
  );
  const [oldDungAuthority] = PublicKey.findProgramAddressSync(
    [DUNG_MINT_AUTH_SEED],
    V4A_PROGRAM_ID,
  );
  const [newCalAuthority, newCalBump] = PublicKey.findProgramAddressSync(
    [CAL_MINT_AUTH_SEED],
    targetProgram,
  );
  const [newDungAuthority, newDungBump] = PublicKey.findProgramAddressSync(
    [DUNG_MINT_AUTH_SEED],
    targetProgram,
  );

  const targetProgramAccount = await connection.getAccountInfo(targetProgram, 'finalized');
  if (!targetProgramAccount?.executable) {
    throw new Error('fresh V4-B target program is not finalized and executable');
  }
  const targetConfigAccount = await connection.getAccountInfo(
    targetProgramConfig,
    'finalized',
  );
  if (
    !targetConfigAccount
    || !targetConfigAccount.owner.equals(targetProgram)
    || targetConfigAccount.data.length < PROGRAM_CONFIG_MIN_LEN
  ) {
    throw new Error('fresh V4-B ProgramConfig is not initialized and owned by the target');
  }
  const targetConfigAdmin = new PublicKey(
    targetConfigAccount.data.subarray(
      PROGRAM_CONFIG_ADMIN_OFFSET,
      PROGRAM_CONFIG_BACKEND_OFFSET,
    ),
  );
  const targetConfigBackend = new PublicKey(
    targetConfigAccount.data.subarray(
      PROGRAM_CONFIG_BACKEND_OFFSET,
      PROGRAM_CONFIG_VERSION_OFFSET,
    ),
  );
  const targetConfigCalMint = new PublicKey(
    targetConfigAccount.data.subarray(
      PROGRAM_CONFIG_CAL_MINT_OFFSET,
      PROGRAM_CONFIG_DUNG_MINT_OFFSET,
    ),
  );
  const targetConfigDungMint = new PublicKey(
    targetConfigAccount.data.subarray(
      PROGRAM_CONFIG_DUNG_MINT_OFFSET,
      PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET,
    ),
  );
  if (
    !targetConfigAccount.data
      .subarray(0, PROGRAM_CONFIG_DISCRIMINATOR.length)
      .equals(PROGRAM_CONFIG_DISCRIMINATOR)
    || !targetConfigAdmin.equals(V4A_ADMIN_AUTHORITY)
    || !targetConfigBackend.equals(V4B_BACKEND_AUTHORITY)
    || targetConfigAccount.data[PROGRAM_CONFIG_VERSION_OFFSET] !== V4B_PROGRAM_VERSION
    || targetConfigAccount.data[PROGRAM_CONFIG_INITIALIZED_OFFSET] !== 1
    || !targetConfigCalMint.equals(CAL_MINT)
    || !targetConfigDungMint.equals(DUNG_MINT)
    || targetConfigAccount.data[PROGRAM_CONFIG_CAL_MINT_AUTH_BUMP_OFFSET] !== newCalBump
    || targetConfigAccount.data[PROGRAM_CONFIG_DUNG_MINT_AUTH_BUMP_OFFSET] !== newDungBump
  ) {
    throw new Error(
      'fresh V4-B ProgramConfig is not version 0x4B with the exact admin, backend, mints, and authority bumps',
    );
  }

  const calBefore = await getMint(connection, CAL_MINT, 'finalized');
  const dungBefore = await getMint(connection, DUNG_MINT, 'finalized');
  if (!calBefore.mintAuthority?.equals(oldCalAuthority)) {
    throw new Error('CAL mint authority is not the exact V4-A PDA');
  }
  if (!dungBefore.mintAuthority?.equals(oldDungAuthority)) {
    throw new Error('DUNG mint authority is not the exact V4-A PDA');
  }

  const bridge = await assertBridgeArtifact(connection, args.bridge_artifact);
  const plan = {
    mode: args.send ? 'send' : 'dry_run',
    rpc: args.rpc,
    v4a_program: V4A_PROGRAM_ID.toBase58(),
    target_program: targetProgram.toBase58(),
    target_program_config: targetProgramConfig.toBase58(),
    target_program_config_version: `0x${V4B_PROGRAM_VERSION.toString(16)}`,
    target_program_config_admin: targetConfigAdmin.toBase58(),
    target_program_config_backend: targetConfigBackend.toBase58(),
    admin: admin.publicKey.toBase58(),
    fee_payer: feePayer.publicKey.toBase58(),
    cal: {
      mint: CAL_MINT.toBase58(),
      current_authority: oldCalAuthority.toBase58(),
      target_authority: newCalAuthority.toBase58(),
    },
    dung: {
      mint: DUNG_MINT.toBase58(),
      current_authority: oldDungAuthority.toBase58(),
      target_authority: newDungAuthority.toBase58(),
    },
    bridge,
  };

  if (!args.send) {
    console.log(JSON.stringify(plan, null, 2));
    return;
  }

  const instruction = new TransactionInstruction({
    programId: V4A_PROGRAM_ID,
    keys: [
      { pubkey: admin.publicKey, isSigner: true, isWritable: false },
      { pubkey: CAL_MINT, isSigner: false, isWritable: true },
      { pubkey: DUNG_MINT, isSigner: false, isWritable: true },
      { pubkey: oldCalAuthority, isSigner: false, isWritable: false },
      { pubkey: oldDungAuthority, isSigner: false, isWritable: false },
      { pubkey: targetProgram, isSigner: false, isWritable: false },
      { pubkey: targetProgramConfig, isSigner: false, isWritable: false },
      { pubkey: TOKEN_PROGRAM_ID, isSigner: false, isWritable: false },
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
  await connection.confirmTransaction(
    { signature, ...latest },
    'finalized',
  );

  const calAfter = await getMint(connection, CAL_MINT, 'finalized');
  const dungAfter = await getMint(connection, DUNG_MINT, 'finalized');
  if (!calAfter.mintAuthority?.equals(newCalAuthority)) {
    throw new Error('finalized CAL mint authority does not equal the V4-B PDA');
  }
  if (!dungAfter.mintAuthority?.equals(newDungAuthority)) {
    throw new Error('finalized DUNG mint authority does not equal the V4-B PDA');
  }
  console.log(JSON.stringify({ ...plan, signature, finalized: true }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
