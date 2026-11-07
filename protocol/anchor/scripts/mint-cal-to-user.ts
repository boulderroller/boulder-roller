#!/usr/bin/env ts-node
/**
 * Mint daily CAL to a user wallet
 *
 * Usage: npx ts-node --esm scripts/mint-cal-to-user.ts <wallet_address>
 */

import { Connection, Keypair, PublicKey, Transaction, TransactionInstruction, SystemProgram } from '@solana/web3.js';
import * as fs from 'fs';
import { fileURLToPath } from 'url';
import * as path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEVNET_ADDRESSES = JSON.parse(
  fs.readFileSync(path.join(__dirname, '../addresses.devnet.json'), 'utf-8'),
);

// Boulder Rollers program ID
const BOULDER_ROLLERS_PROGRAM_ID = new PublicKey(
  process.env.BOULDER_ROLLERS_PROGRAM_ID || DEVNET_ADDRESSES.programs.boulder_rollers,
);

// Pre-computed discriminators
const DISCRIMINATORS = {
  initialize_user: Buffer.from([0x6f, 0x11, 0xb9, 0xfa, 0x3c, 0x7a, 0x26, 0xfe]),
  mint_daily_cal: Buffer.from([0x44, 0x84, 0x71, 0x80, 0xd4, 0xa8, 0x0d, 0xfd]),
};

function deriveUserStatePDA(owner: PublicKey): [PublicKey, number] {
  return PublicKey.findProgramAddressSync(
    [Buffer.from('user'), owner.toBuffer()],
    BOULDER_ROLLERS_PROGRAM_ID
  );
}

async function main() {
  const args = process.argv.slice(2);

  if (args.length < 1) {
    console.log('Usage: npx ts-node --esm scripts/mint-cal-to-user.ts <wallet_address>');
    process.exit(1);
  }

  const userWallet = new PublicKey(args[0]);
  console.log(`⚡ Minting daily CAL for ${userWallet.toBase58()}\n`);

  // Connect to devnet
  const connection = new Connection(
    process.env.SOLANA_CLUSTER || 'https://api.devnet.solana.com',
    'confirmed',
  );

  // Load user keypair (for signing)
  // Note: This requires the user's keypair to sign the transaction
  // In production, the user signs via their wallet
  const userKeypairPath = process.env.USER_KEYPAIR || `${process.env.HOME}/.config/solana/id.json`;

  if (!fs.existsSync(userKeypairPath)) {
    console.error(`❌ User keypair not found at ${userKeypairPath}`);
    console.error('Set USER_KEYPAIR env var to point to your keypair file');
    process.exit(1);
  }

  const userKeypair = Keypair.fromSecretKey(
    Uint8Array.from(JSON.parse(fs.readFileSync(userKeypairPath, 'utf-8')))
  );

  if (!userKeypair.publicKey.equals(userWallet)) {
    console.error(`❌ Keypair public key (${userKeypair.publicKey.toBase58()}) doesn't match wallet (${userWallet.toBase58()})`);
    console.error('The user must sign this transaction themselves via their wallet');
    process.exit(1);
  }

  const [userStatePDA] = deriveUserStatePDA(userWallet);
  console.log(`📍 UserState PDA: ${userStatePDA.toBase58()}`);

  // Check if UserState exists
  const accountInfo = await connection.getAccountInfo(userStatePDA);

  const instructions: TransactionInstruction[] = [];

  if (!accountInfo) {
    console.log('📦 UserState not found, will initialize...');

    // Add initialize_user instruction
    instructions.push(new TransactionInstruction({
      programId: BOULDER_ROLLERS_PROGRAM_ID,
      keys: [
        { pubkey: userStatePDA, isSigner: false, isWritable: true },
        { pubkey: userWallet, isSigner: true, isWritable: true },
        { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
      ],
      data: DISCRIMINATORS.initialize_user,
    }));
  } else {
    console.log('✅ UserState exists');

    // Parse current CAL balance
    if (accountInfo.data.length >= 48) {
      const calBalance = accountInfo.data.readBigUInt64LE(40);
      console.log(`   Current CAL: ${calBalance.toString()}`);
    }
  }

  // Add mint_daily_cal instruction
  instructions.push(new TransactionInstruction({
    programId: BOULDER_ROLLERS_PROGRAM_ID,
    keys: [
      { pubkey: userStatePDA, isSigner: false, isWritable: true },
      { pubkey: userWallet, isSigner: true, isWritable: false },
    ],
    data: DISCRIMINATORS.mint_daily_cal,
  }));

  console.log('\n💰 Minting 2,500 daily CAL...');

  // Build and send transaction
  const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash();

  const transaction = new Transaction({
    blockhash,
    lastValidBlockHeight,
    feePayer: userWallet,
  });

  transaction.add(...instructions);
  transaction.sign(userKeypair);

  const signature = await connection.sendRawTransaction(transaction.serialize());

  await connection.confirmTransaction({
    signature,
    blockhash,
    lastValidBlockHeight,
  });

  console.log(`\n✅ CAL minted!`);
  console.log(`   Signature: ${signature}`);
  console.log(`   Explorer: https://explorer.solana.com/tx/${signature}?cluster=devnet`);

  // Read updated balance
  const updatedAccount = await connection.getAccountInfo(userStatePDA);
  if (updatedAccount && updatedAccount.data.length >= 48) {
    const newBalance = updatedAccount.data.readBigUInt64LE(40);
    console.log(`\n⚡ New CAL balance: ${newBalance.toString()}`);
  }
}

main().catch(console.error);
