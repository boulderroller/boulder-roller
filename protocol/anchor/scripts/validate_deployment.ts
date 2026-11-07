// Read-only deployment validation script
// Usage:
//   npx ts-node scripts/validate_deployment.ts
//   npx ts-node scripts/validate_deployment.ts --program-id <address>
//   npx ts-node scripts/validate_deployment.ts --cal-mint <address> --dung-mint <address>
//   npx ts-node scripts/validate_deployment.ts --program-keypair <path>
//   npx ts-node scripts/validate_deployment.ts --strict-program-keypair
//   npx ts-node scripts/validate_deployment.ts --configuration-only
//
// Checks:
//   0. Runtime config matches the target program ID
//   1. Program account exists and is executable
//   2. ProgramConfig PDA is initialized
//   3. ProgramConfig has cal_mint and dung_mint set
//   4. CAL mint authority == CAL_MINT_AUTH_PDA
//   5. DUNG mint authority == DUNG_MINT_AUTH_PDA
//   6. DungMintState is initialized
//   7. VaultCounter is initialized
//   8. Sample vault account (if present) matches the current Vault layout
//
// Exit 0 if all pass, exit 1 if any fail.

import {
  Connection,
  Keypair,
  PublicKey,
} from "@solana/web3.js";
import { getMint } from "@solana/spl-token";
import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import { CURRENT_PROGRAM_VERSION } from "../generated-program-version.js";
import { chooseSettlementClockCutover } from "./configure_program_mints.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const CLUSTER = process.env.SOLANA_CLUSTER || "https://api.devnet.solana.com";
const DEFAULT_ADDRESSES_FILE = path.join(__dirname, "..", "addresses.devnet.json");
const DEFAULT_BACKEND_ENV = path.resolve(__dirname, "..", "..", "..", "backend", ".env");
const DEFAULT_ROOT_ENV_EXAMPLE = path.resolve(__dirname, "..", "..", "..", ".env.example");
const DEFAULT_ANCHOR_TOML = path.resolve(__dirname, "..", "Anchor.toml");
const DEFAULT_PROGRAM_KEYPAIR = path.resolve(
  __dirname,
  "..",
  "target",
  "deploy",
  "boulder_rollers-keypair.json",
);
const EXPECTED_VAULT_ACCOUNT_SIZE = 649;
const LEGACY_DUNG_MINT_STATE_SIZE = 121;
const EXPECTED_PROGRAM_CONFIG_SIZE = 334;
const PROGRAM_CONFIG_VERSION_OFFSET = 72;
const PROGRAM_CONFIG_CAL_MINT_OFFSET = 75;
const PROGRAM_CONFIG_DUNG_MINT_OFFSET = 107;
const PROGRAM_CONFIG_CLOCK_OFFSET = 325;
const CLAIM_ONLY_DUNG_MINT_STATE_SIZE = 129;
const CURRENT_DUNG_MINT_STATE_SIZE = 130;
const DUNG_RESERVATION_POLICY_VERSION = 1;
const MAX_DUNG_SUPPLY = 1_000_000_000_000_000_000n;
const COMMUNITY_DUNG_CAP = 400_000_000_000_000_000n;
const VAULT_SEED = Buffer.from("vault");

// ANSI color codes
const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const RESET = "\x1b[0m";

function pass(msg: string) {
  console.log(`${GREEN}  [PASS]${RESET} ${msg}`);
}

function fail(msg: string) {
  console.log(`${RED}  [FAIL]${RESET} ${msg}`);
}

type Options = {
  programId: PublicKey;
  calMint: PublicKey;
  dungMint: PublicKey;
  addressesFile: string;
  backendEnv: string;
  rootEnvExample: string;
  anchorToml: string;
  programKeypair: string;
  strictProgramKeypair: boolean;
  configurationOnly: boolean;
  sampleVaultId: number | null;
};

function loadAddresses(filePath: string): {
  programId: string;
  calMint: string;
  dungMint: string;
} {
  const raw = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  return {
    programId: raw.programs?.boulder_rollers,
    calMint: raw.mints?.cal_mint?.address,
    dungMint: raw.mints?.dung_mint?.address,
  };
}

function parseEnvFile(filePath: string): Record<string, string> {
  if (!fs.existsSync(filePath)) {
    return {};
  }
  const result: Record<string, string> = {};
  for (const line of fs.readFileSync(filePath, "utf-8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const index = trimmed.indexOf("=");
    if (index <= 0) {
      continue;
    }
    const key = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim().replace(/^['"]|['"]$/g, "");
    result[key] = value;
  }
  return result;
}

function parseAnchorTomlProgramIds(filePath: string): string[] {
  if (!fs.existsSync(filePath)) {
    return [];
  }
  const ids = new Set<string>();
  const content = fs.readFileSync(filePath, "utf-8");
  const matches = content.matchAll(/^\s*boulder_rollers\s*=\s*"([^"]+)"/gm);
  for (const match of matches) {
    ids.add(match[1]);
  }
  return [...ids];
}

function readKeypairPubkey(filePath: string): string | null {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  try {
    const secret = JSON.parse(fs.readFileSync(filePath, "utf-8"));
    return Keypair.fromSecretKey(Uint8Array.from(secret)).publicKey.toBase58();
  } catch {
    return null;
  }
}

function discriminator(name: string): Buffer {
  return crypto.createHash("sha256").update(`account:${name}`).digest().subarray(0, 8);
}

function leU64(value: number): Buffer {
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64LE(BigInt(value), 0);
  return buf;
}

function parseArgs(): Options {
  const args = process.argv.slice(2);
  let calMintStr: string | null = null;
  let dungMintStr: string | null = null;
  let programIdStr: string | null = null;
  let addressesFile = DEFAULT_ADDRESSES_FILE;
  let backendEnv = DEFAULT_BACKEND_ENV;
  let rootEnvExample = DEFAULT_ROOT_ENV_EXAMPLE;
  let anchorToml = DEFAULT_ANCHOR_TOML;
  let programKeypair = DEFAULT_PROGRAM_KEYPAIR;
  let strictProgramKeypair = false;
  let configurationOnly = false;
  let sampleVaultId: number | null = null;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--cal-mint" && args[i + 1]) {
      calMintStr = args[++i];
    } else if (args[i] === "--dung-mint" && args[i + 1]) {
      dungMintStr = args[++i];
    } else if (args[i] === "--program-id" && args[i + 1]) {
      programIdStr = args[++i];
    } else if (args[i] === "--addresses-file" && args[i + 1]) {
      addressesFile = args[++i];
    } else if (args[i] === "--backend-env" && args[i + 1]) {
      backendEnv = args[++i];
    } else if (args[i] === "--root-env-example" && args[i + 1]) {
      rootEnvExample = args[++i];
    } else if (args[i] === "--anchor-toml" && args[i + 1]) {
      anchorToml = args[++i];
    } else if (args[i] === "--program-keypair" && args[i + 1]) {
      programKeypair = args[++i];
      strictProgramKeypair = true;
    } else if (args[i] === "--strict-program-keypair") {
      strictProgramKeypair = true;
    } else if (args[i] === "--configuration-only") {
      configurationOnly = true;
    } else if (args[i] === "--vault-id" && args[i + 1]) {
      sampleVaultId = Number.parseInt(args[++i], 10);
    }
  }

  const defaults = loadAddresses(addressesFile);
  programIdStr = programIdStr || defaults.programId;
  calMintStr = calMintStr || defaults.calMint;
  dungMintStr = dungMintStr || defaults.dungMint;

  if (!programIdStr || !calMintStr || !dungMintStr) {
    console.error(
      "Usage: npx ts-node scripts/validate_deployment.ts [--program-id <address>] [--cal-mint <address>] [--dung-mint <address>] [--program-keypair <path>]"
    );
    process.exit(1);
  }

  try {
    return {
      programId: new PublicKey(programIdStr),
      calMint: new PublicKey(calMintStr),
      dungMint: new PublicKey(dungMintStr),
      addressesFile,
      backendEnv,
      rootEnvExample,
      anchorToml,
      programKeypair,
      strictProgramKeypair,
      configurationOnly,
      sampleVaultId,
    };
  } catch (err) {
    console.error("ERROR: Invalid public key provided");
    console.error(err);
    process.exit(1);
  }
}

async function main() {
  const {
    programId,
    calMint,
    dungMint,
    addressesFile,
    backendEnv,
    rootEnvExample,
    anchorToml,
    programKeypair,
    strictProgramKeypair,
    configurationOnly,
    sampleVaultId,
  } = parseArgs();
  const connection = new Connection(CLUSTER, "finalized");

  let failures = 0;

  console.log("=== Boulder Rollers Deployment Validation ===");
  console.log("Cluster:", CLUSTER);
  console.log("Program ID:", programId.toBase58());
  console.log("CAL Mint:", calMint.toBase58());
  console.log("DUNG Mint:", dungMint.toBase58());
  console.log("");

  // Derive all PDAs
  const [programConfigPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("program_config")],
    programId,
  );
  const [calMintAuthPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("cal_mint_auth")],
    programId,
  );
  const [dungMintAuthPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("dung_mint_auth")],
    programId,
  );
  const [dungMintStatePda, dungMintStateBump] = PublicKey.findProgramAddressSync(
    [Buffer.from("dung_mint_state")],
    programId,
  );
  const [vaultCounterPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("vault_counter")],
    programId,
  );

  console.log("PDAs:");
  console.log("  ProgramConfig:", programConfigPda.toBase58());
  console.log("  CAL Mint Auth:", calMintAuthPda.toBase58());
  console.log("  DUNG Mint Auth:", dungMintAuthPda.toBase58());
  console.log("  DungMintState:", dungMintStatePda.toBase58());
  console.log("  VaultCounter:", vaultCounterPda.toBase58());
  console.log("");

  // ---------------------------------------------------------------
  // Check 0: Runtime config alignment
  // ---------------------------------------------------------------
  console.log("--- Check 0: Runtime config alignment ---");
  const addresses = loadAddresses(addressesFile);
  if (addresses.programId === programId.toBase58()) {
    pass(`addresses file matches target program ID (${addressesFile})`);
  } else {
    fail(
      `addresses file mismatch: expected ${programId.toBase58()} got ${addresses.programId || "NONE"}`
    );
    failures++;
  }

  const backendEnvVars = parseEnvFile(backendEnv);
  if (!fs.existsSync(backendEnv)) {
    pass(`backend env not present (${backendEnv})`);
  } else if (!backendEnvVars.BOULDER_ROLLERS_PROGRAM_ID) {
    pass(`backend env has no BOULDER_ROLLERS_PROGRAM_ID override (${backendEnv})`);
  } else if (backendEnvVars.BOULDER_ROLLERS_PROGRAM_ID === programId.toBase58()) {
    pass(`backend env matches target program ID (${backendEnv})`);
  } else {
    fail(
      `backend env mismatch: expected ${programId.toBase58()} got ${backendEnvVars.BOULDER_ROLLERS_PROGRAM_ID}`
    );
    failures++;
  }

  const exampleEnvVars = parseEnvFile(rootEnvExample);
  if (!fs.existsSync(rootEnvExample)) {
    pass(`root env example not present (${rootEnvExample})`);
  } else if (exampleEnvVars.BOULDER_ROLLERS_PROGRAM_ID === programId.toBase58()) {
    pass(`root .env.example matches target program ID`);
  } else {
    fail(
      `root .env.example mismatch: expected ${programId.toBase58()} got ${exampleEnvVars.BOULDER_ROLLERS_PROGRAM_ID || "NONE"}`
    );
    failures++;
  }

  const anchorProgramIds = parseAnchorTomlProgramIds(anchorToml);
  if (
    anchorProgramIds.length > 0 &&
    anchorProgramIds.every((value) => value === programId.toBase58())
  ) {
    pass("Anchor.toml matches target program ID");
  } else {
    fail(
      `Anchor.toml mismatch: expected only ${programId.toBase58()} got [${anchorProgramIds.join(", ") || "NONE"}]`
    );
    failures++;
  }

  const localProgramKeypairPubkey = strictProgramKeypair || programKeypair !== DEFAULT_PROGRAM_KEYPAIR
    ? readKeypairPubkey(programKeypair) : null;
  if (!strictProgramKeypair && programKeypair === DEFAULT_PROGRAM_KEYPAIR) {
    pass(
      `local deploy keypair check skipped for generated build artifact (${programKeypair})`
    );
  } else if (!fs.existsSync(programKeypair)) {
    pass(`local deploy keypair not present (${programKeypair})`);
  } else if (localProgramKeypairPubkey === programId.toBase58()) {
    pass(`local deploy keypair matches target program ID (${programKeypair})`);
  } else if (localProgramKeypairPubkey) {
    fail(
      `local deploy keypair mismatch: expected ${programId.toBase58()} got ${localProgramKeypairPubkey} (${programKeypair})`
    );
    failures++;
  } else {
    fail(`local deploy keypair could not be parsed (${programKeypair})`);
    failures++;
  }

  if (configurationOnly) {
    console.log("\n=== Configuration-Only Summary ===");
    if (failures === 0) {
      console.log(`${GREEN}All local deployment configuration checks passed.${RESET}`);
      return;
    }
    console.log(`${RED}${failures} local deployment configuration checks failed.${RESET}`);
    process.exit(1);
  }

  // ---------------------------------------------------------------
  // Check 1: Program account exists
  // ---------------------------------------------------------------
  console.log("\n--- Check 1: Program account ---");
  const programAccount = await connection.getAccountInfo(programId);
  if (programAccount && programAccount.executable) {
    pass(`Program account exists and is executable (${programId.toBase58()})`);
  } else {
    fail("Program account not found or not executable");
    failures++;
  }

  // ---------------------------------------------------------------
  // Check 2: ProgramConfig is initialized
  // ---------------------------------------------------------------
  console.log("\n--- Check 2: ProgramConfig PDA ---");
  const configAccount = await connection.getAccountInfo(programConfigPda);
  if (configAccount?.data.length === EXPECTED_PROGRAM_CONFIG_SIZE) {
    pass("ProgramConfig is initialized (334-byte settlement-clock layout)");
  } else if (configAccount) {
    fail(
      `ProgramConfig requires migration: expected ${EXPECTED_PROGRAM_CONFIG_SIZE} bytes, `
      + `got ${configAccount.data.length}`,
    );
    failures++;
  } else {
    fail("ProgramConfig PDA not found or empty");
    failures++;
  }

  if (
    configAccount
    && configAccount.owner.equals(programId)
    && configAccount.data.length > PROGRAM_CONFIG_VERSION_OFFSET
    && configAccount.data.subarray(0, 8).equals(discriminator("ProgramConfig"))
  ) {
    const observedProgramVersion = configAccount.data.readUInt8(PROGRAM_CONFIG_VERSION_OFFSET);
    if (observedProgramVersion === CURRENT_PROGRAM_VERSION) {
      pass(`ProgramConfig version is current (0x${CURRENT_PROGRAM_VERSION.toString(16).padStart(2, "0")})`);
    } else {
      fail(
        `ProgramConfig version mismatch: expected 0x${CURRENT_PROGRAM_VERSION.toString(16).padStart(2, "0")}, `
        + `got 0x${observedProgramVersion.toString(16).padStart(2, "0")}`,
      );
      failures++;
    }
  } else if (configAccount) {
    fail("ProgramConfig stable version prefix is invalid");
    failures++;
  }

  // ---------------------------------------------------------------
  // Check 3: ProgramConfig mint and settlement-clock fields decode exactly
  // ---------------------------------------------------------------
  console.log("\n--- Check 3: ProgramConfig typed fields ---");
  if (configAccount?.data.length === EXPECTED_PROGRAM_CONFIG_SIZE) {
    const data = configAccount.data;
    const storedCalMint = new PublicKey(
      data.subarray(PROGRAM_CONFIG_CAL_MINT_OFFSET, PROGRAM_CONFIG_CAL_MINT_OFFSET + 32),
    );
    const storedDungMint = new PublicKey(
      data.subarray(PROGRAM_CONFIG_DUNG_MINT_OFFSET, PROGRAM_CONFIG_DUNG_MINT_OFFSET + 32),
    );
    const storedCutover = data.readBigInt64LE(PROGRAM_CONFIG_CLOCK_OFFSET);
    const storedClockVersion = data.readUInt8(PROGRAM_CONFIG_CLOCK_OFFSET + 8);

    if (storedCalMint.equals(calMint)) {
      pass("ProgramConfig contains CAL mint: " + calMint.toBase58());
    } else {
      fail("ProgramConfig does not contain expected CAL mint");
      failures++;
    }

    if (storedDungMint.equals(dungMint)) {
      pass("ProgramConfig contains DUNG mint: " + dungMint.toBase58());
    } else {
      fail("ProgramConfig does not contain expected DUNG mint");
      failures++;
    }
    try {
      const validatedCutover = chooseSettlementClockCutover(data, null);
      if (validatedCutover !== storedCutover) {
        throw new Error("decoded cutover does not match the validated layout");
      }
      pass(
        `ProgramConfig settlement clock v${storedClockVersion}: `
        + `${storedCutover.toString()} (${new Date(Number(storedCutover) * 1000).toISOString()})`,
      );
    } catch (error) {
      fail(
        `ProgramConfig settlement clock invalid: version=${storedClockVersion} `
        + `cutover=${storedCutover.toString()} (${String(error)})`,
      );
      failures++;
    }
  } else {
    fail("Cannot decode typed fields until ProgramConfig is migrated to 334 bytes");
    failures += 3;
  }

  // ---------------------------------------------------------------
  // Check 4: CAL mint authority == CAL_MINT_AUTH_PDA
  // ---------------------------------------------------------------
  console.log("\n--- Check 4: CAL mint authority ---");
  try {
    const calMintInfo = await getMint(connection, calMint);
    const calAuth = calMintInfo.mintAuthority;
    if (calAuth && calAuth.equals(calMintAuthPda)) {
      pass("CAL mint authority is CAL_MINT_AUTH_PDA: " + calMintAuthPda.toBase58());
    } else {
      fail("CAL mint authority mismatch: expected " + calMintAuthPda.toBase58() + " got " + (calAuth?.toBase58() || "NONE"));
      failures++;
    }
  } catch (err) {
    fail("Failed to read CAL mint: " + (err as Error).message);
    failures++;
  }

  // ---------------------------------------------------------------
  // Check 5: DUNG mint authority == DUNG_MINT_AUTH_PDA
  // ---------------------------------------------------------------
  console.log("\n--- Check 5: DUNG mint authority ---");
  try {
    const dungMintInfo = await getMint(connection, dungMint);
    const dungAuth = dungMintInfo.mintAuthority;
    if (dungAuth && dungAuth.equals(dungMintAuthPda)) {
      pass("DUNG mint authority is DUNG_MINT_AUTH_PDA: " + dungMintAuthPda.toBase58());
    } else {
      fail("DUNG mint authority mismatch: expected " + dungMintAuthPda.toBase58() + " got " + (dungAuth?.toBase58() || "NONE"));
      failures++;
    }
  } catch (err) {
    fail("Failed to read DUNG mint: " + (err as Error).message);
    failures++;
  }

  // ---------------------------------------------------------------
  // Check 6: DungMintState is initialized
  // ---------------------------------------------------------------
  console.log("\n--- Check 6: DungMintState ---");
  const dungMintStateAccount = await connection.getAccountInfo(dungMintStatePda);
  if (dungMintStateAccount && dungMintStateAccount.data.length > 0) {
    const data = dungMintStateAccount.data;
    const expectedDiscriminator = discriminator("DungMintState");
    const actualDiscriminator = data.subarray(0, 8);
    const totalMinted = data.length >= LEGACY_DUNG_MINT_STATE_SIZE
      ? data.readBigUInt64LE(48)
      : 0n;
    const communityMinted = data.length >= LEGACY_DUNG_MINT_STATE_SIZE
      ? data.readBigUInt64LE(64)
      : 0n;
    const treasuryMinted = data.length >= LEGACY_DUNG_MINT_STATE_SIZE
      ? data.readBigUInt64LE(72)
      : 0n;
    const teamMinted = data.length >= LEGACY_DUNG_MINT_STATE_SIZE
      ? data.readBigUInt64LE(80)
      : 0n;
    const investorMinted = data.length >= LEGACY_DUNG_MINT_STATE_SIZE
      ? data.readBigUInt64LE(88)
      : 0n;
    const polMinted = data.length >= LEGACY_DUNG_MINT_STATE_SIZE
      ? data.readBigUInt64LE(96)
      : 0n;
    const bucketTotal = communityMinted + treasuryMinted + teamMinted + investorMinted + polMinted;

    if (!dungMintStateAccount.owner.equals(programId)) {
      fail(`DungMintState owner mismatch: expected ${programId.toBase58()} got ${dungMintStateAccount.owner.toBase58()}`);
      failures++;
    } else if (!actualDiscriminator.equals(expectedDiscriminator)) {
      fail(`DungMintState discriminator mismatch: expected ${expectedDiscriminator.toString("hex")} got ${actualDiscriminator.toString("hex")}`);
      failures++;
    } else if (
      data.length === LEGACY_DUNG_MINT_STATE_SIZE
      || data.length === CLAIM_ONLY_DUNG_MINT_STATE_SIZE
    ) {
      fail(`DungMintState still uses the ${data.length}-byte pre-policy layout; run the authority-gated full-liability migration`);
      failures++;
    } else if (data.length !== CURRENT_DUNG_MINT_STATE_SIZE) {
      fail(`DungMintState size mismatch: expected ${CURRENT_DUNG_MINT_STATE_SIZE} got ${data.length}`);
      failures++;
    } else {
      const storedAuthority = new PublicKey(data.subarray(8, 40));
      const maxSupply = data.readBigUInt64LE(40);
      const communityReserved = data.readBigUInt64LE(121);
      const reservationPolicyVersion = data.readUInt8(129);
      const storedBump = data.readUInt8(120);
      const committedTotal = totalMinted + communityReserved;
      const committedCommunity = communityMinted + communityReserved;
      const configuredAdmin = configAccount && configAccount.data.length >= 40
        ? new PublicKey(configAccount.data.subarray(8, 40))
        : null;

      if (totalMinted !== bucketTotal) {
        fail(`DungMintState accounting mismatch: total_minted=${totalMinted} bucket_sum=${bucketTotal}`);
        failures++;
      } else if (!configuredAdmin || !storedAuthority.equals(configuredAdmin)) {
        fail(`DungMintState authority does not match ProgramConfig admin: stored=${storedAuthority.toBase58()} configured=${configuredAdmin?.toBase58() ?? "unavailable"}`);
        failures++;
      } else if (storedBump !== dungMintStateBump) {
        fail(`DungMintState bump mismatch: expected ${dungMintStateBump} got ${storedBump}`);
        failures++;
      } else if (reservationPolicyVersion !== DUNG_RESERVATION_POLICY_VERSION) {
        fail(`DungMintState reservation policy mismatch: expected ${DUNG_RESERVATION_POLICY_VERSION} got ${reservationPolicyVersion}`);
        failures++;
      } else if (maxSupply !== MAX_DUNG_SUPPLY) {
        fail(`DungMintState max_supply mismatch: expected ${MAX_DUNG_SUPPLY} got ${maxSupply}`);
        failures++;
      } else if (committedTotal > maxSupply || committedCommunity > COMMUNITY_DUNG_CAP) {
        fail(`DungMintState insolvent: committed_total=${committedTotal}/${maxSupply} committed_community=${committedCommunity}/${COMMUNITY_DUNG_CAP}`);
        failures++;
      } else {
        pass(`DungMintState reservation policy v${reservationPolicyVersion} is solvent (${data.length} bytes, minted=${totalMinted}, reserved=${communityReserved})`);
      }
    }
  } else {
    fail("DungMintState PDA not found or empty");
    failures++;
  }

  // ---------------------------------------------------------------
  // Check 7: VaultCounter is initialized
  // ---------------------------------------------------------------
  console.log("\n--- Check 7: VaultCounter ---");
  const vaultCounterAccount = await connection.getAccountInfo(vaultCounterPda);
  let currentVaultCount = 0n;
  if (vaultCounterAccount && vaultCounterAccount.data.length > 0) {
    pass("VaultCounter is initialized (" + vaultCounterAccount.data.length + " bytes)");
    // Parse vault count (after 8-byte discriminator)
    if (vaultCounterAccount.data.length >= 16) {
      currentVaultCount = vaultCounterAccount.data.readBigUInt64LE(8);
      console.log("         Current vault count:", currentVaultCount.toString());
    }
  } else {
    fail("VaultCounter PDA not found or empty");
    failures++;
  }

  // ---------------------------------------------------------------
  // Check 8: Sample vault layout compatibility
  // ---------------------------------------------------------------
  console.log("\n--- Check 8: Sample vault layout ---");
  const resolvedVaultId =
    sampleVaultId !== null
      ? sampleVaultId
      : currentVaultCount > 1n
        ? 1
        : currentVaultCount === 1n
          ? 0
          : null;

  if (resolvedVaultId === null) {
    pass("No vaults exist yet; sample vault compatibility check skipped");
  } else {
    const [vaultPda] = PublicKey.findProgramAddressSync(
      [VAULT_SEED, leU64(resolvedVaultId)],
      programId,
    );
    const vaultAccount = await connection.getAccountInfo(vaultPda);
    if (!vaultAccount) {
      pass(`Sample vault ${resolvedVaultId} not present on-chain; compatibility check skipped`);
    } else {
      const expectedDiscriminator = discriminator("Vault");
      const actualDiscriminator = vaultAccount.data.subarray(0, 8);
      if (!actualDiscriminator.equals(expectedDiscriminator)) {
        fail(
          `Sample vault ${resolvedVaultId} discriminator mismatch: expected ${expectedDiscriminator.toString("hex")} got ${actualDiscriminator.toString("hex")}`
        );
        failures++;
      } else if (vaultAccount.data.length !== EXPECTED_VAULT_ACCOUNT_SIZE) {
        fail(
          `Sample vault ${resolvedVaultId} size mismatch: expected ${EXPECTED_VAULT_ACCOUNT_SIZE} got ${vaultAccount.data.length}`
        );
        failures++;
      } else {
        pass(
          `Sample vault ${resolvedVaultId} matches current Vault layout (${vaultAccount.data.length} bytes)`
        );
      }
    }
  }

  // ---------------------------------------------------------------
  // Summary
  // ---------------------------------------------------------------
  console.log("\n=== Validation Summary ===");
  const totalChecks = 14;
  const passed = totalChecks - failures;

  if (failures === 0) {
    console.log(`${GREEN}All ${totalChecks}/${totalChecks} checks passed.${RESET}`);
    process.exit(0);
  } else {
    console.log(`${RED}${failures}/${totalChecks} checks failed.${RESET} (${passed} passed)`);
    process.exit(1);
  }
}

// Stage1 mode is explicit-only and bypasses every legacy env/keypair default.
const work = process.argv.includes('--stage1')
  ? import('./stage1_operator.js').then(async ({ runOperator, args }) => {
      const { validateStage1 } = await import('./stage1_validation.js');
      const argv = process.argv.slice(2).filter(x => x !== '--stage1');
      await runOperator('stage1-validation', validateStage1, args(argv));
    })
  : main();
work.catch((err) => {
  console.error('Validation failed:', err.message);
  process.exitCode = 1;
});
