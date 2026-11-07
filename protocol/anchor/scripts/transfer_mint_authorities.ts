// Transfers CAL and DUNG mint authorities to program PDAs
// Usage:
//   DRY RUN (default): npx ts-node scripts/transfer_mint_authorities.ts --cal-mint <addr> --dung-mint <addr>
//   EXECUTE:           npx ts-node scripts/transfer_mint_authorities.ts --cal-mint <addr> --dung-mint <addr> --execute
//
// WARNING: Authority transfer is IRREVERSIBLE. The --execute flag is required to
// actually perform the transfers, and DUNG transfer requires interactive confirmation.

import {
  Connection,
  Keypair,
  PublicKey,
  LAMPORTS_PER_SOL,
} from "@solana/web3.js";
import {
  AuthorityType,
  getMint,
  setAuthority,
} from "@solana/spl-token";
import * as fs from "fs";
import * as path from "path";
import * as readline from "readline";

const DEVNET_ADDRESSES = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../addresses.devnet.json"), "utf-8")
);
const BOULDER_ROLLERS = new PublicKey(
  process.env.BOULDER_ROLLERS_PROGRAM_ID || DEVNET_ADDRESSES.programs.boulder_rollers
);
const CLUSTER = process.env.SOLANA_CLUSTER || "https://api.devnet.solana.com";

function parseArgs(): { calMint: PublicKey; dungMint: PublicKey; execute: boolean } {
  const args = process.argv.slice(2);
  let calMintStr: string | null = null;
  let dungMintStr: string | null = null;
  let execute = false;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--cal-mint" && args[i + 1]) {
      calMintStr = args[++i];
    } else if (args[i] === "--dung-mint" && args[i + 1]) {
      dungMintStr = args[++i];
    } else if (args[i] === "--execute") {
      execute = true;
    }
  }

  if (!calMintStr || !dungMintStr) {
    console.error("Usage: npx ts-node scripts/transfer_mint_authorities.ts --cal-mint <address> --dung-mint <address> [--execute]");
    process.exit(1);
  }

  try {
    return {
      calMint: new PublicKey(calMintStr),
      dungMint: new PublicKey(dungMintStr),
      execute,
    };
  } catch (err) {
    console.error("ERROR: Invalid public key provided");
    console.error(err);
    process.exit(1);
  }
}

function askConfirmation(prompt: string): Promise<boolean> {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  return new Promise((resolve) => {
    rl.question(prompt, (answer) => {
      rl.close();
      resolve(answer.trim().toLowerCase() === "y");
    });
  });
}

async function main() {
  const { calMint, dungMint, execute } = parseArgs();
  const connection = new Connection(CLUSTER, "confirmed");

  // Load deployer keypair (same pattern as setup_devnet.ts)
  const deployerPath = path.join(
    process.env.HOME!,
    ".config/solana/devnet-deployer.json"
  );
  if (!fs.existsSync(deployerPath)) {
    console.error("ERROR: Deployer keypair not found at", deployerPath);
    process.exit(1);
  }
  const deployerJson = JSON.parse(fs.readFileSync(deployerPath, "utf-8"));
  const deployer = Keypair.fromSecretKey(Uint8Array.from(deployerJson));

  // Derive PDAs
  const [calMintAuthPda, calBump] = PublicKey.findProgramAddressSync(
    [Buffer.from("cal_mint_auth")],
    BOULDER_ROLLERS,
  );
  const [dungMintAuthPda, dungBump] = PublicKey.findProgramAddressSync(
    [Buffer.from("dung_mint_auth")],
    BOULDER_ROLLERS,
  );

  console.log("=== Transfer Mint Authorities ===");
  console.log("Mode:", execute ? "EXECUTE (changes will be made)" : "DRY RUN (no changes)");
  console.log("");
  console.log("Deployer:", deployer.publicKey.toBase58());
  console.log("CAL Mint:", calMint.toBase58());
  console.log("DUNG Mint:", dungMint.toBase58());
  console.log("");
  console.log("Target PDAs:");
  console.log("  CAL_MINT_AUTH:", calMintAuthPda.toBase58(), "(bump:", calBump + ")");
  console.log("  DUNG_MINT_AUTH:", dungMintAuthPda.toBase58(), "(bump:", dungBump + ")");

  const balance = await connection.getBalance(deployer.publicKey);
  console.log("\nBalance:", balance / LAMPORTS_PER_SOL, "SOL");

  // ---------------------------------------------------------------
  // Read current authorities
  // ---------------------------------------------------------------
  console.log("\n--- Current Mint Authorities ---");

  let calMintInfo;
  try {
    calMintInfo = await getMint(connection, calMint);
    const calAuth = calMintInfo.mintAuthority?.toBase58() || "NONE (disabled)";
    console.log("CAL mint authority:", calAuth);
  } catch (err) {
    console.error("ERROR: Failed to read CAL mint at", calMint.toBase58());
    console.error("Ensure the mint exists on", CLUSTER);
    process.exit(1);
  }

  let dungMintInfo;
  try {
    dungMintInfo = await getMint(connection, dungMint);
    const dungAuth = dungMintInfo.mintAuthority?.toBase58() || "NONE (disabled)";
    console.log("DUNG mint authority:", dungAuth);
  } catch (err) {
    console.error("ERROR: Failed to read DUNG mint at", dungMint.toBase58());
    console.error("Ensure the mint exists on", CLUSTER);
    process.exit(1);
  }

  // ---------------------------------------------------------------
  // Plan transfers
  // ---------------------------------------------------------------
  console.log("\n--- Planned Transfers ---");

  const calAlreadyTransferred = calMintInfo.mintAuthority?.equals(calMintAuthPda) ?? false;
  const dungAlreadyTransferred = dungMintInfo.mintAuthority?.equals(dungMintAuthPda) ?? false;

  if (calAlreadyTransferred) {
    console.log("CAL: Already transferred to CAL_MINT_AUTH_PDA (skipping)");
  } else {
    console.log("CAL:", (calMintInfo.mintAuthority?.toBase58() || "NONE"), "->", calMintAuthPda.toBase58());
  }

  if (dungAlreadyTransferred) {
    console.log("DUNG: Already transferred to DUNG_MINT_AUTH_PDA (skipping)");
  } else {
    console.log("DUNG:", (dungMintInfo.mintAuthority?.toBase58() || "NONE"), "->", dungMintAuthPda.toBase58());
  }

  if (calAlreadyTransferred && dungAlreadyTransferred) {
    console.log("\nBoth mint authorities already point to the correct PDAs. Nothing to do.");
    process.exit(0);
  }

  if (!execute) {
    console.log("\n=== DRY RUN COMPLETE ===");
    console.log("To execute these transfers, re-run with --execute flag:");
    console.log("  npx ts-node scripts/transfer_mint_authorities.ts --cal-mint", calMint.toBase58(), "--dung-mint", dungMint.toBase58(), "--execute");
    process.exit(0);
  }

  // ---------------------------------------------------------------
  // Execute: CAL mint authority transfer
  // ---------------------------------------------------------------
  if (!calAlreadyTransferred) {
    if (!calMintInfo.mintAuthority?.equals(deployer.publicKey)) {
      console.error("\nERROR: CAL mint authority is not the deployer. Cannot transfer.");
      console.error("Current authority:", calMintInfo.mintAuthority?.toBase58() || "NONE");
      process.exit(1);
    }

    console.log("\n--- Transferring CAL mint authority ---");
    try {
      await setAuthority(
        connection,
        deployer,
        calMint,
        deployer.publicKey,
        AuthorityType.MintTokens,
        calMintAuthPda,
      );
      console.log("CAL mint authority transferred to:", calMintAuthPda.toBase58());
    } catch (err: any) {
      console.error("ERROR: CAL authority transfer failed:", err?.message || err);
      process.exit(1);
    }
  }

  // ---------------------------------------------------------------
  // Execute: DUNG mint authority transfer (requires confirmation)
  // ---------------------------------------------------------------
  if (!dungAlreadyTransferred) {
    if (!dungMintInfo.mintAuthority?.equals(deployer.publicKey)) {
      console.error("\nERROR: DUNG mint authority is not the deployer. Cannot transfer.");
      console.error("Current authority:", dungMintInfo.mintAuthority?.toBase58() || "NONE");
      process.exit(1);
    }

    console.log("\n--- Transferring DUNG mint authority ---");
    console.log("WARNING: This transfer is IRREVERSIBLE.");
    console.log("DUNG mint authority will be transferred to:", dungMintAuthPda.toBase58());
    console.log("Only the boulder_rollers program will be able to mint DUNG after this.");

    const confirmed = await askConfirmation("\nType 'y' to confirm DUNG authority transfer: ");
    if (!confirmed) {
      console.log("DUNG authority transfer aborted by user.");
      process.exit(1);
    }

    try {
      await setAuthority(
        connection,
        deployer,
        dungMint,
        deployer.publicKey,
        AuthorityType.MintTokens,
        dungMintAuthPda,
      );
      console.log("DUNG mint authority transferred to:", dungMintAuthPda.toBase58());
    } catch (err: any) {
      console.error("ERROR: DUNG authority transfer failed:", err?.message || err);
      process.exit(1);
    }
  }

  // ---------------------------------------------------------------
  // Verify final state
  // ---------------------------------------------------------------
  console.log("\n--- Final Verification ---");
  const calFinal = await getMint(connection, calMint);
  const dungFinal = await getMint(connection, dungMint);

  console.log("CAL mint authority:", calFinal.mintAuthority?.toBase58() || "NONE");
  console.log("DUNG mint authority:", dungFinal.mintAuthority?.toBase58() || "NONE");

  const calOk = calFinal.mintAuthority?.equals(calMintAuthPda) ?? false;
  const dungOk = dungFinal.mintAuthority?.equals(dungMintAuthPda) ?? false;

  if (calOk && dungOk) {
    console.log("\n=== All authority transfers completed successfully ===");
  } else {
    console.error("\nWARNING: Some authorities do not match expected PDAs.");
    if (!calOk) console.error("  CAL: expected", calMintAuthPda.toBase58(), "got", calFinal.mintAuthority?.toBase58() || "NONE");
    if (!dungOk) console.error("  DUNG: expected", dungMintAuthPda.toBase58(), "got", dungFinal.mintAuthority?.toBase58() || "NONE");
    process.exit(1);
  }

  console.log("\nNext step:");
  console.log("  npx ts-node scripts/validate_deployment.ts --cal-mint", calMint.toBase58(), "--dung-mint", dungMint.toBase58());
}

main().catch(console.error);
