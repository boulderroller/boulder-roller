#!/usr/bin/env ts-node
/**
 * Create a fresh SPL mint with the deployer as the temporary mint authority.
 *
 * Usage:
 *   npx ts-node scripts/create_spl_mint.ts --label cal
 *   npx ts-node scripts/create_spl_mint.ts --label dung --decimals 9
 */

import { Connection, Keypair, LAMPORTS_PER_SOL } from "@solana/web3.js";
import { createMint, getMint } from "@solana/spl-token";
import * as fs from "fs";
import * as path from "path";

const DEFAULT_CLUSTER = process.env.SOLANA_CLUSTER || "https://api.devnet.solana.com";
const DEFAULT_DEPLOYER_KEYPAIR =
  process.env.DEPLOYER_KEYPAIR || `${process.env.HOME}/.config/solana/devnet-deployer.json`;

type Options = {
  cluster: string;
  decimals: number;
  deployerKeypairPath: string;
  label: string;
};

function parseArgs(): Options {
  const args = process.argv.slice(2);
  let cluster = DEFAULT_CLUSTER;
  let decimals = 9;
  let deployerKeypairPath = DEFAULT_DEPLOYER_KEYPAIR;
  let label: string | null = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--cluster" && args[i + 1]) {
      cluster = args[++i];
    } else if (args[i] === "--decimals" && args[i + 1]) {
      decimals = Number.parseInt(args[++i], 10);
    } else if (args[i] === "--deployer-keypair" && args[i + 1]) {
      deployerKeypairPath = args[++i];
    } else if (args[i] === "--label" && args[i + 1]) {
      label = args[++i];
    } else {
      console.error(`Unknown argument: ${args[i]}`);
      process.exit(1);
    }
  }

  if (!label) {
    console.error("Usage: npx ts-node scripts/create_spl_mint.ts --label <name> [--decimals <n>]");
    process.exit(1);
  }

  return {
    cluster,
    decimals,
    deployerKeypairPath,
    label,
  };
}

function readKeypair(filePath: string): Keypair {
  return Keypair.fromSecretKey(
    Uint8Array.from(JSON.parse(fs.readFileSync(filePath, "utf-8"))),
  );
}

function envKeyForLabel(label: string): string {
  return `${label.replace(/[^a-zA-Z0-9]+/g, "_").toUpperCase()}_MINT_ADDRESS`;
}

async function main() {
  const opts = parseArgs();
  const deployer = readKeypair(path.resolve(opts.deployerKeypairPath));
  const connection = new Connection(opts.cluster, "confirmed");

  console.log("=== SPL Mint Creation ===");
  console.log("Label:", opts.label);
  console.log("Cluster:", opts.cluster);
  console.log("Deployer:", deployer.publicKey.toBase58());

  const balance = await connection.getBalance(deployer.publicKey);
  console.log("Balance:", balance / LAMPORTS_PER_SOL, "SOL");
  if (balance < 0.01 * LAMPORTS_PER_SOL) {
    console.error("ERROR: insufficient SOL balance for mint creation");
    process.exit(1);
  }

  const mint = await createMint(
    connection,
    deployer,
    deployer.publicKey,
    null,
    opts.decimals,
  );
  const mintInfo = await getMint(connection, mint);

  console.log("\n=== Mint Created ===");
  console.log(`MINT_ADDRESS=${mint.toBase58()}`);
  console.log(`${envKeyForLabel(opts.label)}=${mint.toBase58()}`);
  console.log(`TEMP_MINT_AUTHORITY=${deployer.publicKey.toBase58()}`);
  console.log(`DECIMALS=${mintInfo.decimals}`);
  console.log(`SUPPLY=${mintInfo.supply.toString()}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
