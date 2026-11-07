#!/usr/bin/env ts-node
/**
 * Mint DUNG to a user for testing
 *
 * Usage: npx ts-node --esm scripts/mint-dung-to-user.ts <wallet_address> <amount>
 *
 * Example: npx ts-node --esm scripts/mint-dung-to-user.ts jPBYXEaVpGHGJ3SHkFZS6LB5R92MYTQpgvTDR9FGaWk 100
 */

import {
  getOrCreateAssociatedTokenAccount,
  mintTo,
} from '@solana/spl-token';
import { Connection, Keypair, PublicKey } from '@solana/web3.js';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ONE_DUNG = BigInt(1_000_000_000);

// Load deployer keypair
const deployerPath = process.env.DEPLOYER_KEYPAIR || `${process.env.HOME}/.config/solana/devnet-deployer.json`;

async function main() {
  const args = process.argv.slice(2);

  if (args.length < 2) {
    console.log('Usage: npx ts-node --esm scripts/mint-dung-to-user.ts <wallet_address> <amount>');
    console.log('Example: npx ts-node --esm scripts/mint-dung-to-user.ts jPBYXEaVpGHGJ3SHkFZS6LB5R92MYTQpgvTDR9FGaWk 100');
    process.exit(1);
  }

  const recipientWallet = new PublicKey(args[0]);
  const amount = parseInt(args[1]);

  if (isNaN(amount) || amount <= 0) {
    console.error('Amount must be a positive number');
    process.exit(1);
  }

  console.log(`🪙 Minting ${amount} DUNG to ${recipientWallet.toBase58()}\n`);

  // Load deployer keypair
  const deployerKeypair = Keypair.fromSecretKey(
    Uint8Array.from(JSON.parse(fs.readFileSync(deployerPath, 'utf-8')))
  );
  console.log(`📍 Minter: ${deployerKeypair.publicKey.toBase58()}`);

  // Connect to devnet
  const connection = new Connection('https://api.devnet.solana.com', 'confirmed');

  // Load DUNG mint from config
  const dungMintPath = path.join(__dirname, '..', '.devnet-dung-mint.json');
  if (!fs.existsSync(dungMintPath)) {
    console.error('❌ DUNG mint not found. Run setup-devnet.ts first.');
    process.exit(1);
  }

  const dungMint = new PublicKey(JSON.parse(fs.readFileSync(dungMintPath, 'utf-8')).mint);
  console.log(`📦 DUNG Mint: ${dungMint.toBase58()}`);

  // Get or create recipient's token account
  console.log('\n📭 Getting or creating recipient token account...');
  const recipientATA = await getOrCreateAssociatedTokenAccount(
    connection,
    deployerKeypair,
    dungMint,
    recipientWallet
  );
  console.log(`   Token Account: ${recipientATA.address.toBase58()}`);

  // Mint DUNG
  console.log(`\n💰 Minting ${amount} DUNG...`);
  const amountRaw = BigInt(amount) * ONE_DUNG;

  const signature = await mintTo(
    connection,
    deployerKeypair,
    dungMint,
    recipientATA.address,
    deployerKeypair.publicKey,
    amountRaw
  );

  console.log(`\n✅ Minted ${amount} DUNG!`);
  console.log(`   Signature: ${signature}`);
  console.log(`   Explorer: https://explorer.solana.com/tx/${signature}?cluster=devnet`);

  // Check balance
  const balance = await connection.getTokenAccountBalance(recipientATA.address);
  console.log(`\n💼 New balance: ${balance.value.uiAmount} DUNG`);
}

main().catch(console.error);
