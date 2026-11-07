// Creates CAL SPL token mint on devnet
// Usage: npx ts-node scripts/setup_cal_mint.ts

import { Connection, Keypair, LAMPORTS_PER_SOL } from "@solana/web3.js";
import { createMint, getMint } from "@solana/spl-token";
import * as fs from "fs";
import * as path from "path";

const CLUSTER = process.env.SOLANA_CLUSTER || "https://api.devnet.solana.com";

async function main() {
  const connection = new Connection(CLUSTER, "confirmed");

  // Load deployer keypair (same pattern as setup_devnet.ts)
  const deployerPath = path.join(
    process.env.HOME!,
    ".config/solana/devnet-deployer.json"
  );
  if (!fs.existsSync(deployerPath)) {
    console.error("ERROR: Deployer keypair not found at", deployerPath);
    console.error("Run: solana-keygen new -o", deployerPath);
    process.exit(1);
  }
  const deployerJson = JSON.parse(fs.readFileSync(deployerPath, "utf-8"));
  const deployer = Keypair.fromSecretKey(Uint8Array.from(deployerJson));

  console.log("=== CAL Mint Setup ===");
  console.log("Deployer:", deployer.publicKey.toBase58());

  const balance = await connection.getBalance(deployer.publicKey);
  console.log("Balance:", balance / LAMPORTS_PER_SOL, "SOL");

  if (balance < 0.01 * LAMPORTS_PER_SOL) {
    console.error("ERROR: Insufficient SOL balance for mint creation");
    console.error("Run: solana airdrop 2 --url devnet", deployer.publicKey.toBase58());
    process.exit(1);
  }

  console.log("\nCreating CAL SPL token mint (9 decimals)...");
  const calMint = await createMint(
    connection,
    deployer,
    deployer.publicKey, // Temporary mint authority (will be transferred later)
    null,               // No freeze authority
    9,                  // 9 decimals
  );

  console.log("\n=== CAL Mint Created ===");
  console.log("CAL_MINT_ADDRESS=" + calMint.toBase58());
  console.log("\nMint authority:", deployer.publicKey.toBase58(), "(temporary - will be transferred to PDA)");

  // Verify
  const mintInfo = await getMint(connection, calMint);
  console.log("Decimals:", mintInfo.decimals);
  console.log("Supply:", mintInfo.supply.toString());

  console.log("\nNext steps:");
  console.log("1. Set CAL_MINT_ADDRESS in .env");
  console.log("2. Run: npx ts-node scripts/configure_program_mints.ts --cal-mint", calMint.toBase58());
  console.log("3. Run: npx ts-node scripts/transfer_mint_authorities.ts --dry-run");
}

main().catch(console.error);
