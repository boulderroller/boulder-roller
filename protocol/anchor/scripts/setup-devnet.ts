#!/usr/bin/env ts-node
/**
 * Bootstrap a Boulder Rollers devnet program lane.
 *
 * Dry-run by default:
 *   npx ts-node scripts/setup-devnet.ts
 *
 * Execute writes:
 *   npx ts-node scripts/setup-devnet.ts --execute
 *
 * Optional overrides:
 *   --program-id <pubkey>
 *   --cal-mint <pubkey>
 *   --dung-mint <pubkey>
 *   --program-keypair <path>
 *   --admin-keypair <path>
 *   --backend-authority-keypair <path>
 *   --defer-mint-authority-handoff-from <program-id>
 *   --cluster <rpc-url>
 *   --settlement-clock-cutover <unix-seconds>  (must equal the bound cutover)
 */

import * as anchor from "@coral-xyz/anchor";
import BN from "bn.js";
import {
  AuthorityType,
  createAssociatedTokenAccountInstruction,
  getAssociatedTokenAddressSync,
  getMint,
  setAuthority,
} from "@solana/spl-token";
import {
  Connection,
  Keypair,
  LAMPORTS_PER_SOL,
  PublicKey,
  SystemProgram,
} from "@solana/web3.js";
import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import { chooseSettlementClockCutover } from "./configure_program_mints.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DEFAULT_CLUSTER = process.env.SOLANA_CLUSTER || "https://api.devnet.solana.com";
const DEFAULT_ADDRESSES_PATH = path.join(__dirname, "..", "addresses.devnet.json");
const DEFAULT_PROGRAM_KEYPAIR = path.join(__dirname, "..", "target", "deploy", "boulder_rollers-keypair.json");
const DEFAULT_ADMIN_KEYPAIR =
  process.env.DEPLOYER_KEYPAIR || `${process.env.HOME}/.config/solana/devnet-deployer.json`;
const DEFAULT_BACKEND_AUTHORITY_KEYPAIR =
  process.env.BACKEND_AUTHORITY_KEYPAIR || `${process.env.HOME}/.config/solana/boulderroller-backend-authority.json`;
const BPF_UPGRADEABLE_LOADER_ID = new PublicKey("BPFLoaderUpgradeab1e11111111111111111111111");
const LEGACY_DUNG_MINT_STATE_SIZE = 121;
const CLAIM_ONLY_DUNG_MINT_STATE_SIZE = 129;
const CURRENT_DUNG_MINT_STATE_SIZE = 130;

function accountDiscriminator(name: string): Buffer {
  return crypto.createHash("sha256").update(`account:${name}`).digest().subarray(0, 8);
}

type Options = {
  execute: boolean;
  cluster: string;
  programId: PublicKey;
  calMint: PublicKey;
  dungMint: PublicKey;
  polOwner?: PublicKey;
  treasuryOwner?: PublicKey;
  programKeypairPath: string;
  adminKeypairPath: string;
  backendAuthorityKeypairPath: string;
  deferMintAuthorityHandoffFrom?: PublicKey;
  settlementClockCutover: bigint | null;
};

function readJson(filePath: string): any {
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

function readKeypair(filePath: string): Keypair {
  return Keypair.fromSecretKey(Uint8Array.from(readJson(filePath)));
}

function parseArgs(): Options {
  const args = process.argv.slice(2);
  const addresses = readJson(DEFAULT_ADDRESSES_PATH);

  let execute = false;
  let cluster = DEFAULT_CLUSTER;
  let programId = addresses.programs?.boulder_rollers;
  let calMint = addresses.mints?.cal_mint?.address;
  let dungMint = addresses.mints?.dung_mint?.address;
  let polOwner: string | undefined;
  let treasuryOwner: string | undefined;
  let programKeypairPath = DEFAULT_PROGRAM_KEYPAIR;
  let adminKeypairPath = DEFAULT_ADMIN_KEYPAIR;
  let backendAuthorityKeypairPath = DEFAULT_BACKEND_AUTHORITY_KEYPAIR;
  let deferMintAuthorityHandoffFrom: string | undefined;
  let settlementClockCutover: bigint | null = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--execute") {
      execute = true;
    } else if (args[i] === "--cluster" && args[i + 1]) {
      cluster = args[++i];
    } else if (args[i] === "--program-id" && args[i + 1]) {
      programId = args[++i];
    } else if (args[i] === "--cal-mint" && args[i + 1]) {
      calMint = args[++i];
    } else if (args[i] === "--dung-mint" && args[i + 1]) {
      dungMint = args[++i];
    } else if (args[i] === "--pol-owner" && args[i + 1]) {
      polOwner = args[++i];
    } else if (args[i] === "--treasury-owner" && args[i + 1]) {
      treasuryOwner = args[++i];
    } else if (args[i] === "--program-keypair" && args[i + 1]) {
      programKeypairPath = args[++i];
    } else if (args[i] === "--admin-keypair" && args[i + 1]) {
      adminKeypairPath = args[++i];
    } else if (args[i] === "--backend-authority-keypair" && args[i + 1]) {
      backendAuthorityKeypairPath = args[++i];
    } else if (args[i] === "--defer-mint-authority-handoff-from" && args[i + 1]) {
      deferMintAuthorityHandoffFrom = args[++i];
    } else if (args[i] === "--settlement-clock-cutover" && args[i + 1]) {
      try {
        settlementClockCutover = BigInt(args[++i]);
      } catch {
        throw new Error(`Invalid --settlement-clock-cutover value: ${args[i]}`);
      }
    } else {
      console.error(`Unknown argument: ${args[i]}`);
      process.exit(1);
    }
  }

  if (!programId || !calMint || !dungMint) {
    console.error("Missing program/mint addresses. Pass flags explicitly or populate addresses.devnet.json.");
    process.exit(1);
  }

  return {
    execute,
    cluster,
    programId: new PublicKey(programId),
    calMint: new PublicKey(calMint),
    dungMint: new PublicKey(dungMint),
    polOwner: polOwner ? new PublicKey(polOwner) : undefined,
    treasuryOwner: treasuryOwner ? new PublicKey(treasuryOwner) : undefined,
    programKeypairPath,
    adminKeypairPath,
    backendAuthorityKeypairPath,
    deferMintAuthorityHandoffFrom: deferMintAuthorityHandoffFrom
      ? new PublicKey(deferMintAuthorityHandoffFrom)
      : undefined,
    settlementClockCutover,
  };
}

function formatOutcome(execute: boolean, action: string, skippedReason?: string): string {
  if (!execute) {
    return `DRY RUN: would ${action}`;
  }
  return skippedReason ? `SKIP: ${skippedReason}` : `DONE: ${action}`;
}

async function fetchProgramConfig(program: anchor.Program, pda: PublicKey): Promise<any | null> {
  try {
    return await (program.account as any).programConfig.fetch(pda);
  } catch {
    return null;
  }
}

async function fetchProgramDataAddress(connection: Connection, programId: PublicKey): Promise<PublicKey> {
  const programAccount = await connection.getAccountInfo(programId);
  if (!programAccount?.executable) {
    throw new Error("target program account is missing or not executable");
  }
  if (!programAccount.owner.equals(BPF_UPGRADEABLE_LOADER_ID)) {
    throw new Error(`target program is not upgradeable-loader owned: ${programAccount.owner.toBase58()}`);
  }

  const loaderStateTag = programAccount.data.readUInt32LE(0);
  if (loaderStateTag !== 2) {
    throw new Error(`target program account is not an upgradeable Program state: ${loaderStateTag}`);
  }
  return new PublicKey(programAccount.data.subarray(4, 36));
}

function readProgramKeypairPubkey(filePath: string): PublicKey | null {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  try {
    return readKeypair(filePath).publicKey;
  } catch {
    return null;
  }
}

async function main() {
  const opts = parseArgs();
  const admin = readKeypair(opts.adminKeypairPath);
  const backendAuthority = readKeypair(opts.backendAuthorityKeypairPath);
  const localProgramKeypair = readProgramKeypairPubkey(opts.programKeypairPath);
  const polOwner = opts.polOwner ?? backendAuthority.publicKey;
  const treasuryOwner = opts.treasuryOwner ?? admin.publicKey;
  const polAta = getAssociatedTokenAddressSync(opts.dungMint, polOwner);
  const treasuryAta = getAssociatedTokenAddressSync(opts.dungMint, treasuryOwner);

  const connection = new Connection(opts.cluster, "finalized");
  const balance = await connection.getBalance(admin.publicKey);

  console.log("=== Boulder Rollers Devnet Bootstrap ===");
  console.log("Mode:", opts.execute ? "EXECUTE" : "DRY RUN");
  console.log("Cluster:", opts.cluster);
  console.log("Program:", opts.programId.toBase58());
  console.log(
    "Local program keypair:",
    localProgramKeypair?.toBase58() ?? `missing/unreadable (${opts.programKeypairPath})`
  );
  console.log("Admin:", admin.publicKey.toBase58(), `(${(balance / LAMPORTS_PER_SOL).toFixed(3)} SOL)`);
  console.log("Backend authority:", backendAuthority.publicKey.toBase58());
  console.log("CAL mint:", opts.calMint.toBase58());
  console.log("DUNG mint:", opts.dungMint.toBase58());
  console.log(
    "Deferred mint handoff source:",
    opts.deferMintAuthorityHandoffFrom?.toBase58() ?? "none",
  );
  console.log("POL owner:", polOwner.toBase58());
  console.log("Treasury owner:", treasuryOwner.toBase58());
  console.log("POL DUNG ATA:", polAta.toBase58());
  console.log("Treasury DUNG ATA:", treasuryAta.toBase58());
  console.log("");

  const idlPath = path.join(__dirname, "..", "idl", "boulder_rollers.json");
  const idl = readJson(idlPath);
  const wallet = new anchor.Wallet(admin);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "finalized",
    preflightCommitment: "confirmed",
  });
  anchor.setProvider(provider);
  const program = new anchor.Program(idl as anchor.Idl, opts.programId, provider);

  const [programConfigPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("program_config")],
    opts.programId,
  );
  const [vaultCounterPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_counter")],
    opts.programId,
  );
  const [dungMintStatePda] = PublicKey.findProgramAddressSync(
    [Buffer.from("dung_mint_state")],
    opts.programId,
  );
  const [calMintAuthPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("cal_mint_auth")],
    opts.programId,
  );
  const [dungMintAuthPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("dung_mint_auth")],
    opts.programId,
  );

  console.log("ProgramConfig PDA:", programConfigPda.toBase58());
  console.log("VaultCounter PDA:", vaultCounterPda.toBase58());
  console.log("DungMintState PDA:", dungMintStatePda.toBase58());
  console.log("");

  if (localProgramKeypair && !localProgramKeypair.equals(opts.programId)) {
    const message =
      `Local program keypair ${localProgramKeypair.toBase58()} does not match target program ${opts.programId.toBase58()} (${opts.programKeypairPath})`;
    if (opts.execute) {
      throw new Error(`${message}. Refusing to bootstrap a lane with mismatched deploy identity.`);
    }
    console.log("WARNING:", message);
    console.log("         Dry run will continue, but deploy/upgrade commands must use the intended program keypair.");
    console.log("");
  }

  const programAccount = await connection.getAccountInfo(opts.programId);
  if (!programAccount?.executable) {
    console.error("ERROR: target program account is missing or not executable.");
    process.exit(1);
  }
  const programDataAddress = await fetchProgramDataAddress(connection, opts.programId);

  const configInfoBefore = await connection.getAccountInfo(programConfigPda);
  const configBefore = configInfoBefore ? await fetchProgramConfig(program, programConfigPda) : null;

  console.log("Step 1: ProgramConfig");
  if (!configInfoBefore) {
    console.log("  - missing");
    console.log(`  - ${formatOutcome(opts.execute, "initialize program config")}`);
    if (opts.execute) {
      const sig = await program.methods
        .initializeProgramConfig(backendAuthority.publicKey)
        .accounts({
          programConfig: programConfigPda,
          program: opts.programId,
          programData: programDataAddress,
          admin: admin.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .rpc();
      console.log("  - initializeProgramConfig tx:", sig);
    }
  } else {
    console.log(`  - present (${configInfoBefore.data.length} bytes)`);
    if (configBefore) {
      console.log("  - admin authority:", configBefore.adminAuthority.toBase58());
      console.log("  - backend authority:", configBefore.backendAuthority.toBase58());
      console.log("  - CAL mint:", configBefore.calMint.toBase58());
      console.log("  - DUNG mint:", configBefore.dungMint.toBase58());
      if (!configBefore.adminAuthority.equals(admin.publicKey)) {
        console.log(
          "  - WARNING: current admin authority does not match local admin keypair:",
          admin.publicKey.toBase58(),
        );
      }
      if (!configBefore.backendAuthority.equals(backendAuthority.publicKey)) {
        console.log(
          "  - WARNING: current backend authority does not match requested backend authority:",
          backendAuthority.publicKey.toBase58(),
        );
      }
    }
  }

  const configAfterInit = await fetchProgramConfig(program, programConfigPda);
  if (
    configAfterInit &&
    configAfterInit.adminAuthority.equals(admin.publicKey) &&
    !configAfterInit.backendAuthority.equals(backendAuthority.publicKey)
  ) {
    console.log("  - backend authority drift detected");
    console.log(`  - ${formatOutcome(opts.execute, "update backend authority")}`);
    if (opts.execute) {
      const sig = await program.methods
        .updateProgramConfig(null, backendAuthority.publicKey)
        .accounts({
          programConfig: programConfigPda,
          adminAuthority: admin.publicKey,
        })
        .rpc();
      console.log("  - updateProgramConfig tx:", sig);
    }
  }

  const configInfoAfterInit = await connection.getAccountInfo(programConfigPda);
  if (!configInfoAfterInit) {
    console.error("ERROR: ProgramConfig still missing after initialize step.");
    process.exit(1);
  }

  console.log("\nStep 2: ProgramConfig layout");
  console.log(`  - current size: ${configInfoAfterInit.data.length} bytes`);
  // The program no longer migrates ProgramConfig; initialize_program_config
  // writes the current layout and binds the settlement clock.
  const settlementClockCutover = chooseSettlementClockCutover(
    configInfoAfterInit.data,
    opts.settlementClockCutover,
  );
  console.log(`  - settlement clock cutover: ${settlementClockCutover.toString()} (bound)`);

  const currentConfig = await fetchProgramConfig(program, programConfigPda);
  console.log("\nStep 3: Mint configuration");
  const calMatches = currentConfig?.calMint?.equals(opts.calMint) ?? false;
  const dungMatches = currentConfig?.dungMint?.equals(opts.dungMint) ?? false;
  if (calMatches && dungMatches) {
    console.log("  - mints already configured correctly");
  } else {
    console.log(
      `  - expected CAL=${opts.calMint.toBase58()} DUNG=${opts.dungMint.toBase58()}`
    );
    if (currentConfig) {
      console.log(
        `  - current  CAL=${currentConfig.calMint.toBase58()} DUNG=${currentConfig.dungMint.toBase58()}`
      );
    }
    console.log(`  - ${formatOutcome(opts.execute, "configure mints")}`);
    if (opts.execute) {
      try {
        const sig = await program.methods
          .configureMints(opts.calMint, opts.dungMint)
          .accounts({
            programConfig: programConfigPda,
            admin: admin.publicKey,
          })
          .rpc();
        console.log("  - configureMints tx:", sig);
      } catch (error) {
        console.log("  - configureMints skipped/error:", String(error));
      }
    }
  }

  console.log("\nStep 4: Mint authority alignment");
  const calMintInfo = await getMint(connection, opts.calMint);
  const dungMintInfo = await getMint(connection, opts.dungMint);
  const calAuthorityMatches = calMintInfo.mintAuthority?.equals(calMintAuthPda) ?? false;
  const dungAuthorityMatches = dungMintInfo.mintAuthority?.equals(dungMintAuthPda) ?? false;
  console.log("  - expected CAL authority:", calMintAuthPda.toBase58());
  console.log("  - expected DUNG authority:", dungMintAuthPda.toBase58());
  console.log("  - current  CAL authority:", calMintInfo.mintAuthority?.toBase58() || "NONE");
  console.log("  - current  DUNG authority:", dungMintInfo.mintAuthority?.toBase58() || "NONE");

  if (calAuthorityMatches && dungAuthorityMatches) {
    console.log("  - mint authorities already aligned");
  } else if (opts.deferMintAuthorityHandoffFrom) {
    const [deferredCalAuthority] = PublicKey.findProgramAddressSync(
      [Buffer.from("cal_mint_auth")],
      opts.deferMintAuthorityHandoffFrom,
    );
    const [deferredDungAuthority] = PublicKey.findProgramAddressSync(
      [Buffer.from("dung_mint_auth")],
      opts.deferMintAuthorityHandoffFrom,
    );
    if (!calMintInfo.mintAuthority?.equals(deferredCalAuthority)) {
      throw new Error(
        `CAL mint authority cannot be deferred: expected prior-program PDA ${deferredCalAuthority.toBase58()}, ` +
        `got ${calMintInfo.mintAuthority?.toBase58() || "NONE"}.`,
      );
    }
    if (!dungMintInfo.mintAuthority?.equals(deferredDungAuthority)) {
      throw new Error(
        `DUNG mint authority cannot be deferred: expected prior-program PDA ${deferredDungAuthority.toBase58()}, ` +
        `got ${dungMintInfo.mintAuthority?.toBase58() || "NONE"}.`,
      );
    }
    console.log("  - CAL mint authority handoff deferred to the reviewed bridge");
    console.log("  - DUNG mint authority handoff deferred to the reviewed bridge");
  } else {
    if (!calAuthorityMatches) {
      if (calMintInfo.mintAuthority?.equals(admin.publicKey)) {
        console.log(`  - ${formatOutcome(opts.execute, "transfer CAL mint authority to program PDA")}`);
        if (opts.execute) {
          await setAuthority(
            connection,
            admin,
            opts.calMint,
            admin.publicKey,
            AuthorityType.MintTokens,
            calMintAuthPda,
          );
          console.log("  - CAL mint authority transferred");
        }
      } else {
        throw new Error(
          `CAL mint authority mismatch: expected ${calMintAuthPda.toBase58()}, got ${calMintInfo.mintAuthority?.toBase58() || "NONE"}. ` +
          "Create a fresh mint controlled by the lane admin or provide the current authority."
        );
      }
    }

    if (!dungAuthorityMatches) {
      if (dungMintInfo.mintAuthority?.equals(admin.publicKey)) {
        console.log(`  - ${formatOutcome(opts.execute, "transfer DUNG mint authority to program PDA")}`);
        if (opts.execute) {
          await setAuthority(
            connection,
            admin,
            opts.dungMint,
            admin.publicKey,
            AuthorityType.MintTokens,
            dungMintAuthPda,
          );
          console.log("  - DUNG mint authority transferred");
        }
      } else {
        throw new Error(
          `DUNG mint authority mismatch: expected ${dungMintAuthPda.toBase58()}, got ${dungMintInfo.mintAuthority?.toBase58() || "NONE"}. ` +
          "Create a fresh mint controlled by the lane admin or provide the current authority."
        );
      }
    }
  }

  console.log("\nStep 5: Treasury account configuration");
  const ataInstructions = [];
  const polAtaInfo = await connection.getAccountInfo(polAta);
  if (!polAtaInfo) {
    console.log(`  - POL ATA missing: ${polAta.toBase58()}`);
    console.log(`  - ${formatOutcome(opts.execute, "create POL ATA")}`);
    ataInstructions.push(
      createAssociatedTokenAccountInstruction(
        admin.publicKey,
        polAta,
        polOwner,
        opts.dungMint,
      )
    );
  }
  const treasuryAtaInfo = await connection.getAccountInfo(treasuryAta);
  if (!treasuryAtaInfo) {
    console.log(`  - treasury ATA missing: ${treasuryAta.toBase58()}`);
    console.log(`  - ${formatOutcome(opts.execute, "create treasury ATA")}`);
    ataInstructions.push(
      createAssociatedTokenAccountInstruction(
        admin.publicKey,
        treasuryAta,
        treasuryOwner,
        opts.dungMint,
      )
    );
  }
  if (opts.execute && ataInstructions.length > 0) {
    const sig = await provider.sendAndConfirm(new anchor.web3.Transaction().add(...ataInstructions));
    console.log("  - create ATA tx:", sig);
  }

  const configAfterMints = await fetchProgramConfig(program, programConfigPda);
  const polMatches = configAfterMints?.polTokenAccount?.equals(polAta) ?? false;
  const treasuryMatches = configAfterMints?.treasuryTokenAccount?.equals(treasuryAta) ?? false;
  if (polMatches && treasuryMatches) {
    console.log("  - treasury accounts already configured correctly");
  } else {
    if (configAfterMints) {
      console.log(
        `  - current  POL=${configAfterMints.polTokenAccount.toBase58()} TREASURY=${configAfterMints.treasuryTokenAccount.toBase58()}`
      );
    }
    console.log(
      `  - expected POL=${polAta.toBase58()} TREASURY=${treasuryAta.toBase58()}`
    );
    console.log(`  - ${formatOutcome(opts.execute, "configure treasury accounts")}`);
    if (opts.execute) {
      const sig = await program.methods
        .configureTreasuryAccounts(polAta, treasuryAta)
        .accounts({
          programConfig: programConfigPda,
          admin: admin.publicKey,
        })
        .rpc();
      console.log("  - configureTreasuryAccounts tx:", sig);
    }
  }

  console.log("\nStep 6: VaultCounter");
  const vaultCounterInfo = await connection.getAccountInfo(vaultCounterPda);
  if (!vaultCounterInfo) {
    console.log("  - missing");
    console.log(`  - ${formatOutcome(opts.execute, "initialize vault counter")}`);
    if (opts.execute) {
      const sig = await program.methods
        .initializeVaultCounter()
        .accounts({
          vaultCounter: vaultCounterPda,
          authority: admin.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .rpc();
      console.log("  - initializeVaultCounter tx:", sig);
    }
  } else {
    console.log(`  - present (${vaultCounterInfo.data.length} bytes)`);
  }

  console.log("\nStep 7: DungMintState");
  const dungMintStateInfo = await connection.getAccountInfo(dungMintStatePda);
  if (!dungMintStateInfo) {
    console.log("  - missing");
    console.log(`  - ${formatOutcome(opts.execute, "initialize DungMintState")}`);
    if (opts.execute) {
      const sig = await program.methods
        .initializeDungMintState()
        .accounts({
          dungMintState: dungMintStatePda,
          programConfig: programConfigPda,
          authority: admin.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .rpc();
      console.log("  - initializeDungMintState tx:", sig);
    }
  } else {
    console.log(`  - present (${dungMintStateInfo.data.length} bytes)`);
    if (!dungMintStateInfo.owner.equals(opts.programId)) {
      throw new Error("DungMintState owner does not match the target program");
    }
    if (!dungMintStateInfo.data.subarray(0, 8).equals(accountDiscriminator("DungMintState"))) {
      throw new Error("DungMintState discriminator is invalid");
    }
    if (
      dungMintStateInfo.data.length === LEGACY_DUNG_MINT_STATE_SIZE
      || dungMintStateInfo.data.length === CLAIM_ONLY_DUNG_MINT_STATE_SIZE
    ) {
      throw new Error(
        `DungMintState uses the ${dungMintStateInfo.data.length}-byte pre-policy layout. `
        + "Run migrate_dung_liability_reservation.ts --prepare-alt first. Pause DUNG writers; "
        + "run the read-only census with --lookup-table; review its VaultStake count, Vault "
        + "count, liability total, and manifest hash; run --simulate-only --operations-paused "
        + "with all four expectations; then run --execute --operations-paused with the same "
        + "expectations, lookup table, and reviewed plan hash before setup-devnet.",
      );
    }
    if (dungMintStateInfo.data.length !== CURRENT_DUNG_MINT_STATE_SIZE) {
      throw new Error(
        `DungMintState has unsupported size ${dungMintStateInfo.data.length}; expected ${CURRENT_DUNG_MINT_STATE_SIZE}`,
      );
    }
  }

  const finalConfigInfo = await connection.getAccountInfo(programConfigPda);
  const finalVaultCounterInfo = await connection.getAccountInfo(vaultCounterPda);
  const finalDungMintStateInfo = await connection.getAccountInfo(dungMintStatePda);
  console.log("\n=== Bootstrap Summary ===");
  console.log("ProgramConfig bytes:", finalConfigInfo?.data.length ?? 0);
  console.log("VaultCounter present:", Boolean(finalVaultCounterInfo));
  console.log("DungMintState present:", Boolean(finalDungMintStateInfo));
  console.log("\nSuggested runtime env fragment:");
  console.log(`BOULDER_ROLLERS_PROGRAM_ID=${opts.programId.toBase58()}`);
  console.log(`CAL_MINT_ADDRESS=${opts.calMint.toBase58()}`);
  console.log(`DUNG_MINT_ADDRESS=${opts.dungMint.toBase58()}`);
  console.log(`POL_DUNG_TOKEN_ACCOUNT=${polAta.toBase58()}`);
  console.log(`TREASURY_DUNG_TOKEN_ACCOUNT=${treasuryAta.toBase58()}`);
  console.log(`SOLANA_BACKEND_AUTHORITY_PATH=${opts.backendAuthorityKeypairPath}`);
  console.log(`SOLANA_PAYER_PATH=${opts.adminKeypairPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
