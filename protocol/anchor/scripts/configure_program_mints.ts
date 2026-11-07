// Configures CAL and DUNG mint addresses on ProgramConfig
// Usage: npx ts-node scripts/configure_program_mints.ts --cal-mint <address>
//   --dung-mint <address> [--settlement-clock-cutover <unix-seconds>]
//   [--admin-keypair <path>] [--fee-payer <path>]
// ProgramConfig must already use the current 334-byte layout with its
// settlement clock bound; the program no longer migrates older layouts. A
// supplied cutover must equal the bound value.
//
// Steps:
//   1. Verifies the ProgramConfig layout and settlement clock (read-only)
//   2. Calls configure_mints to set CAL and DUNG mint pubkeys

import {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  TransactionInstruction,
  sendAndConfirmTransaction,
  LAMPORTS_PER_SOL,
} from "@solana/web3.js";
import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const SCRIPT_DIR = path.dirname(SCRIPT_PATH);

const DEVNET_ADDRESSES = JSON.parse(
  fs.readFileSync(path.join(SCRIPT_DIR, "../addresses.devnet.json"), "utf-8")
);
const BOULDER_ROLLERS = new PublicKey(
  process.env.BOULDER_ROLLERS_PROGRAM_ID || DEVNET_ADDRESSES.programs.boulder_rollers
);
const CLUSTER = process.env.SOLANA_CLUSTER || "https://api.devnet.solana.com";
const DEFAULT_ADMIN_KEYPAIR = path.join(
  process.env.HOME || "",
  ".config/solana/boulderroller-admin-upgrade-authority.json",
);
const DEFAULT_FEE_PAYER = path.join(
  process.env.HOME || "",
  ".config/solana/boulderroller-fee-payer.json",
);
const SETTLEMENT_WEEK_V2_ANCHOR = 1_704_110_400n;
const SETTLEMENT_WEEK_DURATION_SECONDS = 604_800n;
const PROGRAM_CONFIG_CURRENT_SIZE = 334;
const PROGRAM_CONFIG_CLOCK_OFFSET = 325;
const PROGRAM_CONFIG_CLOCK_VERSION = 2;

// Anchor instruction discriminator: first 8 bytes of SHA256("global:<instruction_name>")
function getInstructionDiscriminator(name: string): Buffer {
  const hash = crypto.createHash("sha256");
  hash.update(`global:${name}`);
  return hash.digest().slice(0, 8);
}

function validateSettlementClockAlignment(cutover: bigint): void {
  if (
    cutover < SETTLEMENT_WEEK_V2_ANCHOR
    || (cutover - SETTLEMENT_WEEK_V2_ANCHOR) % SETTLEMENT_WEEK_DURATION_SECONDS !== 0n
  ) {
    throw new Error(
      `Settlement clock cutover ${cutover} is not aligned to Monday 12:00 UTC`,
    );
  }
}

export function chooseSettlementClockCutover(
  data: Buffer,
  requestedCutover: bigint | null,
): bigint {
  if (data.length !== PROGRAM_CONFIG_CURRENT_SIZE) {
    throw new Error(
      `ProgramConfig uses a ${data.length}-byte legacy layout; the program no longer migrates ProgramConfig`,
    );
  }
  const version = data.readUInt8(PROGRAM_CONFIG_CLOCK_OFFSET + 8);
  const cutover = data.readBigInt64LE(PROGRAM_CONFIG_CLOCK_OFFSET);
  if (version !== PROGRAM_CONFIG_CLOCK_VERSION) {
    throw new Error(`Unsupported settlement clock version ${version}`);
  }
  validateSettlementClockAlignment(cutover);
  if (requestedCutover !== null && requestedCutover !== cutover) {
    throw new Error(
      `ProgramConfig is already bound to cutover ${cutover}, not ${requestedCutover}`,
    );
  }
  return cutover;
}

export function parseArgs(args: string[] = process.argv.slice(2)): {
  calMint: PublicKey;
  dungMint: PublicKey;
  settlementClockCutover: bigint | null;
  adminKeypairPath: string;
  feePayerPath: string;
} {
  let calMintStr: string | null = null;
  let dungMintStr: string | null = null;
  let settlementClockCutoverStr: string | null = null;
  let adminKeypairPath = process.env.ADMIN_KEYPAIR || DEFAULT_ADMIN_KEYPAIR;
  let feePayerPath = process.env.FEE_PAYER_KEYPAIR || DEFAULT_FEE_PAYER;

  for (let i = 0; i < args.length; i++) {
    const flag = args[i];
    if (![
      "--cal-mint",
      "--dung-mint",
      "--settlement-clock-cutover",
      "--admin-keypair",
      "--fee-payer",
    ].includes(flag)) {
      throw new Error(`Unknown argument: ${flag}`);
    }
    const value = args[i + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for ${flag}`);
    }
    i++;
    if (flag === "--cal-mint") {
      if (calMintStr !== null) throw new Error("Duplicate --cal-mint");
      calMintStr = value;
    } else if (flag === "--dung-mint") {
      if (dungMintStr !== null) throw new Error("Duplicate --dung-mint");
      dungMintStr = value;
    } else {
      if (flag === "--settlement-clock-cutover") {
        if (settlementClockCutoverStr !== null) {
          throw new Error("Duplicate --settlement-clock-cutover");
        }
        settlementClockCutoverStr = value;
      } else if (flag === "--admin-keypair") {
        adminKeypairPath = value;
      } else if (flag === "--fee-payer") {
        feePayerPath = value;
      } else {
        throw new Error("Duplicate --settlement-clock-cutover");
      }
    }
  }

  if (!calMintStr || !dungMintStr) {
    throw new Error(
      "Usage: npx ts-node scripts/configure_program_mints.ts --cal-mint <address> "
      + "--dung-mint <address> [--settlement-clock-cutover <unix-seconds>]",
    );
  }

  let calMint: PublicKey;
  let dungMint: PublicKey;
  try {
    calMint = new PublicKey(calMintStr);
    dungMint = new PublicKey(dungMintStr);
  } catch (err) {
    throw new Error(`Invalid mint address: ${err}`);
  }
  let settlementClockCutover: bigint | null = null;
  if (settlementClockCutoverStr !== null) {
    try {
      settlementClockCutover = BigInt(settlementClockCutoverStr);
    } catch (err) {
      throw new Error(`Invalid settlement clock cutover: ${settlementClockCutoverStr}`);
    }
  }
  return {
    calMint,
    dungMint,
    settlementClockCutover,
    adminKeypairPath,
    feePayerPath,
  };
}

async function main() {
  const {
    calMint,
    dungMint,
    settlementClockCutover: requestedCutover,
    adminKeypairPath,
    feePayerPath,
  } = parseArgs();
  const connection = new Connection(CLUSTER, "finalized");

  const loadKeypair = (filePath: string, role: string): Keypair => {
    if (!fs.existsSync(filePath)) {
      throw new Error(`${role} keypair not found at ${filePath}`);
    }
    return Keypair.fromSecretKey(
      Uint8Array.from(JSON.parse(fs.readFileSync(filePath, "utf-8"))),
    );
  };
  const admin = loadKeypair(adminKeypairPath, "Admin");
  const feePayer = loadKeypair(feePayerPath, "Fee payer");
  if (admin.publicKey.equals(feePayer.publicKey)) {
    throw new Error("ProgramConfig admin cannot be used as the transaction fee payer");
  }

  console.log("=== Configure Program Mints ===");
  console.log("Admin:", admin.publicKey.toBase58());
  console.log("Fee payer:", feePayer.publicKey.toBase58());
  console.log("CAL Mint:", calMint.toBase58());
  console.log("DUNG Mint:", dungMint.toBase58());

  const [adminBalance, feePayerBalance] = await Promise.all([
    connection.getBalance(admin.publicKey, "finalized"),
    connection.getBalance(feePayer.publicKey, "finalized"),
  ]);
  console.log("Admin balance:", adminBalance / LAMPORTS_PER_SOL, "SOL");
  console.log("Fee payer balance:", feePayerBalance / LAMPORTS_PER_SOL, "SOL");

  // Derive ProgramConfig PDA
  const [programConfigPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("program_config")],
    BOULDER_ROLLERS,
  );
  console.log("\nProgramConfig PDA:", programConfigPda.toBase58());

  // Check if ProgramConfig exists
  const configAccount = await connection.getAccountInfo(programConfigPda);
  if (!configAccount) {
    console.error("ERROR: ProgramConfig PDA not found. Run setup_devnet.ts or initialize_program_config first.");
    process.exit(1);
  }
  if (!configAccount.owner.equals(BOULDER_ROLLERS)) {
    throw new Error("ProgramConfig owner mismatch");
  }
  const storedAdmin = new PublicKey(configAccount.data.subarray(8, 40));
  if (!storedAdmin.equals(admin.publicKey)) {
    throw new Error(
      `Admin key ${admin.publicKey.toBase58()} does not match ProgramConfig ${storedAdmin.toBase58()}`,
    );
  }
  console.log("\n--- Step 1: verify ProgramConfig layout and settlement clock ---");
  console.log("ProgramConfig data length:", configAccount.data.length, "bytes");
  const settlementClockCutover = chooseSettlementClockCutover(
    configAccount.data,
    requestedCutover,
  );
  console.log(
    "Settlement clock cutover:",
    settlementClockCutover.toString(),
    new Date(Number(settlementClockCutover) * 1000).toISOString(),
  );

  // ---------------------------------------------------------------
  // Step 2: configure_mints (sets CAL and DUNG mint addresses)
  // ---------------------------------------------------------------
  console.log("\n--- Step 2: configure_mints ---");

  const configureDiscriminator = getInstructionDiscriminator("configure_mints");
  console.log("Discriminator:", configureDiscriminator.toString("hex"));

  // Data layout: discriminator (8) + cal_mint (32) + dung_mint (32)
  const configureData = Buffer.concat([
    configureDiscriminator,
    calMint.toBuffer(),
    dungMint.toBuffer(),
  ]);

  const configureIx = new TransactionInstruction({
    programId: BOULDER_ROLLERS,
    keys: [
      { pubkey: programConfigPda, isSigner: false, isWritable: true },  // program_config (mut)
      { pubkey: admin.publicKey, isSigner: true, isWritable: false }, // admin (signer)
    ],
    data: configureData,
  });

  try {
    const configureTx = new Transaction().add(configureIx);
    configureTx.feePayer = feePayer.publicKey;
    const configureSig = await sendAndConfirmTransaction(
      connection,
      configureTx,
      [feePayer, admin],
      { commitment: "finalized", preflightCommitment: "finalized" },
    );
    console.log("configure_mints succeeded! Sig:", configureSig);
  } catch (err: any) {
    const errMsg = err?.message || String(err);
    if (errMsg.includes("MintsAlreadyConfigured")) {
      console.log("Mints already configured on ProgramConfig. Skipping.");
    } else {
      console.error("ERROR: configure_mints failed:", errMsg);
      process.exit(1);
    }
  }

  // ---------------------------------------------------------------
  // Verify
  // ---------------------------------------------------------------
  console.log("\n--- Verification ---");
  const updatedConfig = await connection.getAccountInfo(programConfigPda);
  if (updatedConfig) {
    console.log("ProgramConfig data length:", updatedConfig.data.length, "bytes");
    // After discriminator (8) + initialized (1) + admin (32) + ... the layout depends on
    // the exact Anchor struct, but we can confirm the account has grown
    console.log("ProgramConfig data (hex, first 128 bytes):", updatedConfig.data.subarray(0, 128).toString("hex"));
  }

  console.log("\n=== Configuration Complete ===");
  console.log("CAL Mint:", calMint.toBase58());
  console.log("DUNG Mint:", dungMint.toBase58());
  console.log("\nNext step:");
  console.log("  npx ts-node scripts/transfer_mint_authorities.ts --cal-mint", calMint.toBase58(), "--dung-mint", dungMint.toBase58(), "--execute");
}

if (process.argv[1] && path.resolve(process.argv[1]) === SCRIPT_PATH) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
