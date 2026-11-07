#!/usr/bin/env ts-node
/**
 * Migration sequence:
 * 1. `--prepare-alt` before the program upgrade or writer pause.
 * 2. Pause settlement, staking, collection, and other DUNG writers.
 * 3. Run read-only with `--lookup-table`; review the census and hashes.
 * 4. Run `--simulate-only --operations-paused` with the reviewed census hash.
 * 5. Run `--execute --operations-paused` with the reviewed census and plan hashes.
 *
 * The admin authorizes only. A separate powerless fee payer funds ALT setup,
 * transaction fees, and DungMintState rent.
 */

import * as anchor from "@coral-xyz/anchor";
import BN from "bn.js";
import {
  AddressLookupTableAccount,
  AddressLookupTableProgram,
  ComputeBudgetProgram,
  Connection,
  Keypair,
  PACKET_DATA_SIZE,
  PublicKey,
  sendAndConfirmTransaction,
  SystemProgram,
  Transaction,
  TransactionMessage,
  VersionedTransaction,
} from "@solana/web3.js";
import type { AccountInfo, TransactionInstruction } from "@solana/web3.js";
import * as crypto from "crypto";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_CLUSTER = process.env.SOLANA_CLUSTER || "https://api.devnet.solana.com";
const DEFAULT_ADDRESSES = path.join(__dirname, "..", "addresses.devnet.json");
const DEFAULT_AUTHORITY = path.join(
  os.homedir(),
  ".config",
  "solana",
  "boulderroller-admin-upgrade-authority.json",
);
const DEFAULT_PAYER = path.join(
  os.homedir(),
  ".config",
  "solana",
  "boulderroller-fee-payer.json",
);
const DEFAULT_PAYER_PUBKEY = new PublicKey(
  process.env.DUNG_MINT_MIGRATION_PAYER_PUBKEY
    || "9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP",
);

const DUNG_MINT_STATE_SEED = Buffer.from("dung_mint_state");
const PROGRAM_CONFIG_SEED = Buffer.from("program_config");
const VAULT_COUNTER_SEED = Buffer.from("vault_counter");
const VAULT_SEED = Buffer.from("vault");
const VAULT_STAKE_SEED = Buffer.from("vault_stake");
const VAULT_STAKE_SIZE = 105;
const LEGACY_DUNG_MINT_STATE_SIZE = 121;
const CLAIM_ONLY_DUNG_MINT_STATE_SIZE = 129;
const CURRENT_DUNG_MINT_STATE_SIZE = 130;
const DUNG_RESERVATION_POLICY_VERSION = 1;
const U32_MAX = 0xffff_ffff;
const U64_MAX = (1n << 64n) - 1n;
const COMMUNITY_CAP = 400_000_000_000_000_000n;
const LOOKUP_TABLE_CREATE_SEND_OPTIONS = {
  commitment: "finalized",
  preflightCommitment: "confirmed",
} as const;

type Options = {
  cluster: string;
  programId: PublicKey;
  authorityPath: string;
  payerPath: string;
  payerPubkey: PublicKey;
  lookupTable: PublicKey | null;
  expectedCount: number | null;
  expectedVaultCount: number | null;
  expectedTotal: bigint | null;
  expectedManifestSha256: string | null;
  expectedPlanSha256: string | null;
  prepareAlt: boolean;
  simulateOnly: boolean;
  operationsPaused: boolean;
  execute: boolean;
};

type StakeClaim = {
  pubkey: PublicKey;
  user: PublicKey;
  vaultId: bigint;
  rewardsEarned: bigint;
  active: boolean;
};

type StakeCensus = {
  accounts: StakeClaim[];
  activeCount: number;
  totalRewards: bigint;
};

type VaultCarry = {
  pubkey: PublicKey;
  id: bigint;
  carryRecordRoyalty: bigint;
  carryStakers: bigint;
  carryLocalLegend: bigint;
};

type VaultCensus = {
  accounts: VaultCarry[];
  totalCommunityCarry: bigint;
};

type DecodedVault = {
  id: BN;
  carryRecordRoyalty: BN;
  carryStakers: BN;
  carryLocalLegend: BN;
  carryPol: BN;
  carryTreasury: BN;
  bump: number;
};

type DungMintStateSnapshot = {
  size: number;
  prefix: Buffer;
  authority: PublicKey;
  maxSupply: bigint;
  totalMinted: bigint;
  totalBurned: bigint;
  communityMinted: bigint;
  treasuryMinted: bigint;
  teamMinted: bigint;
  investorMinted: bigint;
  polMinted: bigint;
  emissionRateBps: bigint;
  lastHalvingEpoch: bigint;
  bump: number;
  communityReserved: bigint | null;
  reservationPolicyVersion: number | null;
};

function accountDiscriminator(name: string): Buffer {
  return crypto.createHash("sha256").update(`account:${name}`).digest().subarray(0, 8);
}

function readJson(filePath: string): any {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readU64(data: Buffer, offset: number): bigint {
  return data.readBigUInt64LE(offset);
}

function leU64(value: bigint): Buffer {
  const data = Buffer.alloc(8);
  data.writeBigUInt64LE(value);
  return data;
}

function parseUnsigned(value: string, name: string): bigint {
  if (!/^\d+$/.test(value)) {
    throw new Error(`${name} must be an unsigned integer`);
  }
  const parsed = BigInt(value);
  if (parsed > U64_MAX) {
    throw new Error(`${name} exceeds u64`);
  }
  return parsed;
}

function parseSha256(value: string, name: string): string {
  const normalized = value.toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(normalized)) {
    throw new Error(`${name} must be a 64-character SHA-256 hex digest`);
  }
  return normalized;
}

function parseArgs(): Options {
  const addresses = readJson(DEFAULT_ADDRESSES);
  let cluster = DEFAULT_CLUSTER;
  let programId = new PublicKey(addresses.programs.boulder_rollers);
  let authorityPath = process.env.DUNG_MINT_MIGRATION_AUTHORITY || DEFAULT_AUTHORITY;
  let payerPath = process.env.DUNG_MINT_MIGRATION_PAYER || DEFAULT_PAYER;
  let payerPubkey = DEFAULT_PAYER_PUBKEY;
  let lookupTable: PublicKey | null = null;
  let expectedCount: number | null = null;
  let expectedVaultCount: number | null = null;
  let expectedTotal: bigint | null = null;
  let expectedManifestSha256: string | null = null;
  let expectedPlanSha256: string | null = null;
  let prepareAlt = false;
  let simulateOnly = false;
  let operationsPaused = false;
  let execute = false;

  const args = process.argv.slice(2);
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    const next = () => {
      const value = args[index + 1];
      if (!value) throw new Error(`Missing value for ${arg}`);
      index += 1;
      return value;
    };

    if (arg === "--cluster") cluster = next();
    else if (arg === "--program-id") programId = new PublicKey(next());
    else if (arg === "--authority") authorityPath = next();
    else if (arg === "--payer") payerPath = next();
    else if (arg === "--payer-pubkey") payerPubkey = new PublicKey(next());
    else if (arg === "--lookup-table") lookupTable = new PublicKey(next());
    else if (arg === "--expected-count") {
      const count = parseUnsigned(next(), "expected-count");
      if (count > BigInt(U32_MAX)) throw new Error("expected-count exceeds u32");
      expectedCount = Number(count);
    } else if (arg === "--expected-vault-count") {
      const count = parseUnsigned(next(), "expected-vault-count");
      if (count > BigInt(U32_MAX)) throw new Error("expected-vault-count exceeds u32");
      expectedVaultCount = Number(count);
    } else if (arg === "--expected-total") {
      expectedTotal = parseUnsigned(next(), "expected-total");
    } else if (arg === "--expected-manifest-sha256") {
      expectedManifestSha256 = parseSha256(next(), "expected-manifest-sha256");
    } else if (arg === "--expected-plan-sha256") {
      expectedPlanSha256 = parseSha256(next(), "expected-plan-sha256");
    } else if (arg === "--prepare-alt") prepareAlt = true;
    else if (arg === "--simulate-only") simulateOnly = true;
    else if (arg === "--operations-paused") operationsPaused = true;
    else if (arg === "--execute") execute = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  const mutatingModes = [prepareAlt, simulateOnly, execute].filter(Boolean).length;
  if (mutatingModes > 1) {
    throw new Error("--prepare-alt, --simulate-only, and --execute are mutually exclusive");
  }

  return {
    cluster,
    programId,
    authorityPath,
    payerPath,
    payerPubkey,
    lookupTable,
    expectedCount,
    expectedVaultCount,
    expectedTotal,
    expectedManifestSha256,
    expectedPlanSha256,
    prepareAlt,
    simulateOnly,
    operationsPaused,
    execute,
  };
}

function loadKeypair(filePath: string): Keypair {
  const expanded = filePath.startsWith("~/")
    ? path.join(os.homedir(), filePath.slice(2))
    : filePath;
  return Keypair.fromSecretKey(Uint8Array.from(readJson(expanded)));
}

function checkedAddU64(left: bigint, right: bigint, label: string): bigint {
  const result = left + right;
  if (result > U64_MAX) throw new Error(`${label} exceeds u64`);
  return result;
}

function decodeDungMintState(
  account: AccountInfo<Buffer> | null,
  programId: PublicKey,
): DungMintStateSnapshot {
  if (!account) throw new Error("DungMintState is missing");
  if (!account.owner.equals(programId)) throw new Error("DungMintState owner mismatch");
  const data = account.data;
  if (
    data.length !== LEGACY_DUNG_MINT_STATE_SIZE
    && data.length !== CLAIM_ONLY_DUNG_MINT_STATE_SIZE
    && data.length !== CURRENT_DUNG_MINT_STATE_SIZE
  ) {
    throw new Error(`Unexpected DungMintState size ${data.length}`);
  }
  if (!data.subarray(0, 8).equals(accountDiscriminator("DungMintState"))) {
    throw new Error("DungMintState discriminator mismatch");
  }

  const snapshot: DungMintStateSnapshot = {
    size: data.length,
    prefix: Buffer.from(data.subarray(0, LEGACY_DUNG_MINT_STATE_SIZE)),
    authority: new PublicKey(data.subarray(8, 40)),
    maxSupply: readU64(data, 40),
    totalMinted: readU64(data, 48),
    totalBurned: readU64(data, 56),
    communityMinted: readU64(data, 64),
    treasuryMinted: readU64(data, 72),
    teamMinted: readU64(data, 80),
    investorMinted: readU64(data, 88),
    polMinted: readU64(data, 96),
    emissionRateBps: readU64(data, 104),
    lastHalvingEpoch: readU64(data, 112),
    bump: data[120],
    communityReserved: data.length >= CLAIM_ONLY_DUNG_MINT_STATE_SIZE
      ? readU64(data, 121)
      : null,
    reservationPolicyVersion: data.length === CURRENT_DUNG_MINT_STATE_SIZE
      ? data[129]
      : null,
  };

  const bucketTotal = [
    snapshot.communityMinted,
    snapshot.treasuryMinted,
    snapshot.teamMinted,
    snapshot.investorMinted,
    snapshot.polMinted,
  ].reduce((sum, amount) => checkedAddU64(sum, amount, "minted bucket sum"), 0n);
  if (snapshot.totalMinted !== bucketTotal) {
    throw new Error(
      `DungMintState accounting mismatch: total=${snapshot.totalMinted} buckets=${bucketTotal}`,
    );
  }

  const reservation = snapshot.communityReserved ?? 0n;
  const committedTotal = checkedAddU64(
    snapshot.totalMinted,
    reservation,
    "committed total",
  );
  const committedCommunity = checkedAddU64(
    snapshot.communityMinted,
    reservation,
    "committed Community",
  );
  if (committedTotal > snapshot.maxSupply || committedCommunity > COMMUNITY_CAP) {
    throw new Error("DungMintState committed supply exceeds a cap");
  }
  if (
    snapshot.reservationPolicyVersion !== null
    && snapshot.reservationPolicyVersion !== DUNG_RESERVATION_POLICY_VERSION
  ) {
    throw new Error(
      `Unsupported DUNG reservation policy version ${snapshot.reservationPolicyVersion}`,
    );
  }

  return snapshot;
}

async function fetchStakeCensus(
  connection: Connection,
  programId: PublicKey,
  minContextSlot?: number,
): Promise<StakeCensus> {
  const discriminator = accountDiscriminator("VaultStake");
  const candidates = await connection.getProgramAccounts(programId, {
    commitment: "finalized",
    minContextSlot,
    filters: [{
      memcmp: {
        offset: 0,
        bytes: anchor.utils.bytes.bs58.encode(discriminator),
      },
    }],
  });
  const seenPdas = new Set<string>();
  const seenPositions = new Set<string>();
  const accounts: StakeClaim[] = [];
  let activeCount = 0;
  let totalRewards = 0n;

  for (const candidate of candidates) {
    const { account, pubkey } = candidate;
    if (!account.data.subarray(0, 8).equals(discriminator)) {
      throw new Error(`VaultStake ${pubkey.toBase58()} discriminator mismatch`);
    }
    if (!account.owner.equals(programId)) {
      throw new Error(`VaultStake ${pubkey.toBase58()} owner mismatch`);
    }
    if (account.data.length !== VAULT_STAKE_SIZE) {
      throw new Error(`VaultStake ${pubkey.toBase58()} size mismatch`);
    }

    const pdaKey = pubkey.toBase58();
    if (seenPdas.has(pdaKey)) throw new Error(`Duplicate VaultStake PDA ${pdaKey}`);
    seenPdas.add(pdaKey);

    const user = new PublicKey(account.data.subarray(8, 40));
    const vaultId = readU64(account.data, 40);
    const positionKey = `${user.toBase58()}:${vaultId}`;
    if (seenPositions.has(positionKey)) {
      throw new Error(`Duplicate VaultStake position ${positionKey}`);
    }
    seenPositions.add(positionKey);

    const [expectedPda, expectedBump] = PublicKey.findProgramAddressSync(
      [VAULT_STAKE_SEED, user.toBuffer(), leU64(vaultId)],
      programId,
    );
    if (!expectedPda.equals(pubkey) || account.data[104] !== expectedBump) {
      throw new Error(`VaultStake ${pdaKey} PDA or bump mismatch`);
    }

    const calStaked = readU64(account.data, 48);
    const lpTokens = readU64(account.data, 56);
    const rewardsEarned = readU64(account.data, 88);
    const active = calStaked > 0n && lpTokens > 0n;
    if (active) activeCount += 1;
    totalRewards = checkedAddU64(totalRewards, rewardsEarned, "VaultStake rewards sum");
    accounts.push({ pubkey, user, vaultId, rewardsEarned, active });
  }

  if (accounts.length > U32_MAX) throw new Error("VaultStake count exceeds u32");
  accounts.sort((left, right) => left.pubkey.toBase58().localeCompare(right.pubkey.toBase58()));
  return { accounts, activeCount, totalRewards };
}

async function fetchVaultCensus(
  connection: Connection,
  programId: PublicKey,
  coder: anchor.BorshAccountsCoder,
  minContextSlot?: number,
): Promise<VaultCensus> {
  const candidates = await connection.getProgramAccounts(programId, {
    commitment: "finalized",
    minContextSlot,
    filters: [{ memcmp: coder.memcmp("Vault") }],
  });
  const seenPdas = new Set<string>();
  const seenIds = new Set<string>();
  const accounts: VaultCarry[] = [];
  let totalCommunityCarry = 0n;

  for (const candidate of candidates) {
    const { account, pubkey } = candidate;
    if (!account.owner.equals(programId)) {
      throw new Error(`Vault ${pubkey.toBase58()} owner mismatch`);
    }
    const decoded = coder.decode<DecodedVault>("Vault", account.data);
    const id = BigInt(decoded.id.toString());
    const pdaKey = pubkey.toBase58();
    if (seenPdas.has(pdaKey)) throw new Error(`Duplicate Vault PDA ${pdaKey}`);
    seenPdas.add(pdaKey);

    const idKey = id.toString();
    if (seenIds.has(idKey)) throw new Error(`Duplicate Vault id ${idKey}`);
    seenIds.add(idKey);

    const [expectedPda, expectedBump] = PublicKey.findProgramAddressSync(
      [VAULT_SEED, leU64(id)],
      programId,
    );
    if (!expectedPda.equals(pubkey) || decoded.bump !== expectedBump) {
      throw new Error(`Vault ${pdaKey} PDA or bump mismatch`);
    }

    const carryRecordRoyalty = BigInt(decoded.carryRecordRoyalty.toString());
    const carryStakers = BigInt(decoded.carryStakers.toString());
    const carryLocalLegend = BigInt(decoded.carryLocalLegend.toString());
    const carryPol = BigInt(decoded.carryPol.toString());
    const carryTreasury = BigInt(decoded.carryTreasury.toString());
    if (carryPol !== 0n || carryTreasury !== 0n) {
      throw new Error(
        `Vault ${id} has unreserved protocol carry: POL=${carryPol} Treasury=${carryTreasury}`,
      );
    }

    totalCommunityCarry = checkedAddU64(
      totalCommunityCarry,
      carryRecordRoyalty,
      "Vault Community carry sum",
    );
    totalCommunityCarry = checkedAddU64(
      totalCommunityCarry,
      carryStakers,
      "Vault Community carry sum",
    );
    totalCommunityCarry = checkedAddU64(
      totalCommunityCarry,
      carryLocalLegend,
      "Vault Community carry sum",
    );
    accounts.push({
      pubkey,
      id,
      carryRecordRoyalty,
      carryStakers,
      carryLocalLegend,
    });
  }

  if (accounts.length > U32_MAX) throw new Error("Vault count exceeds u32");
  accounts.sort((left, right) => left.pubkey.toBase58().localeCompare(right.pubkey.toBase58()));
  return { accounts, totalCommunityCarry };
}

function decodeVaultCounter(
  account: AccountInfo<Buffer> | null,
  programId: PublicKey,
  coder: anchor.BorshAccountsCoder,
): number {
  if (!account) throw new Error("VaultCounter is missing");
  if (!account.owner.equals(programId)) throw new Error("VaultCounter owner mismatch");
  const decoded = coder.decode<{ count: BN }>("VaultCounter", account.data);
  const count = BigInt(decoded.count.toString());
  if (count > BigInt(U32_MAX)) throw new Error("VaultCounter count exceeds u32");
  return Number(count);
}

function combinedCommunityLiability(stakes: StakeCensus, vaults: VaultCensus): bigint {
  return checkedAddU64(
    stakes.totalRewards,
    vaults.totalCommunityCarry,
    "combined Community liability",
  );
}

function inventoryManifestSha256(stakes: StakeCensus, vaults: VaultCensus): string {
  const entries = [
    ...stakes.accounts.map((stake) => [
      "VaultStake",
      stake.pubkey.toBase58(),
      stake.user.toBase58(),
      stake.vaultId.toString(),
      stake.rewardsEarned.toString(),
    ].join(":")),
    ...vaults.accounts.map((vault) => [
      "Vault",
      vault.pubkey.toBase58(),
      vault.id.toString(),
      vault.carryRecordRoyalty.toString(),
      vault.carryStakers.toString(),
      vault.carryLocalLegend.toString(),
    ].join(":")),
  ].sort();
  return crypto
    .createHash("sha256")
    .update("boulder-roller-dung-liability-manifest-v1\n")
    .update(entries.join("\n"))
    .digest("hex");
}

function assertExpectedCensus(
  options: Options,
  stakes: StakeCensus,
  vaults: VaultCensus,
  vaultCounterCount: number,
): { total: bigint; manifestSha256: string } {
  if (options.expectedCount !== null && options.expectedCount !== stakes.accounts.length) {
    throw new Error(
      `Expected ${options.expectedCount} VaultStake accounts, found ${stakes.accounts.length}`,
    );
  }
  if (
    options.expectedVaultCount !== null
    && options.expectedVaultCount !== vaults.accounts.length
  ) {
    throw new Error(
      `Expected ${options.expectedVaultCount} Vault accounts, found ${vaults.accounts.length}`,
    );
  }
  if (vaultCounterCount !== vaults.accounts.length) {
    throw new Error(
      `VaultCounter says ${vaultCounterCount}, but census found ${vaults.accounts.length} Vaults`,
    );
  }
  const total = combinedCommunityLiability(stakes, vaults);
  if (options.expectedTotal !== null && options.expectedTotal !== total) {
    throw new Error(
      `Expected ${options.expectedTotal} reserved units, computed ${total}`,
    );
  }
  const manifestSha256 = inventoryManifestSha256(stakes, vaults);
  if (
    options.expectedManifestSha256 !== null
    && options.expectedManifestSha256 !== manifestSha256
  ) {
    throw new Error(
      `Expected manifest ${options.expectedManifestSha256}, computed ${manifestSha256}`,
    );
  }
  if (
    (options.simulateOnly || options.execute)
    && (
      options.expectedCount === null
      || options.expectedVaultCount === null
      || options.expectedTotal === null
      || options.expectedManifestSha256 === null
    )
  ) {
    throw new Error(
      "--simulate-only/--execute require --expected-count, --expected-vault-count, "
      + "--expected-total, and --expected-manifest-sha256",
    );
  }
  return { total, manifestSha256 };
}

function decodeProgramConfigAdmin(
  account: AccountInfo<Buffer> | null,
  programId: PublicKey,
): PublicKey {
  if (!account) throw new Error("ProgramConfig is missing");
  if (!account.owner.equals(programId)) throw new Error("ProgramConfig owner mismatch");
  if (!account.data.subarray(0, 8).equals(accountDiscriminator("ProgramConfig"))) {
    throw new Error("ProgramConfig discriminator mismatch");
  }
  const admin = new PublicKey(account.data.subarray(8, 40));
  return admin;
}

async function fetchLookupTable(
  connection: Connection,
  address: PublicKey,
): Promise<AddressLookupTableAccount> {
  const response = await connection.getAddressLookupTable(address, {
    commitment: "finalized",
  });
  if (!response.value) {
    throw new Error(`Address lookup table ${address.toBase58()} is missing`);
  }
  return response.value;
}

function assertLookupTableCovers(
  lookupTable: AddressLookupTableAccount,
  requiredAddresses: PublicKey[],
): void {
  const tableAddresses = new Set(
    lookupTable.state.addresses.map((address) => address.toBase58()),
  );
  const missing = requiredAddresses.filter(
    (address) => !tableAddresses.has(address.toBase58()),
  );
  if (missing.length > 0) {
    throw new Error(
      `Lookup table ${lookupTable.key.toBase58()} is missing ${missing.length} inventory accounts: `
      + missing.map((address) => address.toBase58()).join(", "),
    );
  }
}

async function prepareInventoryLookupTable(
  connection: Connection,
  payer: Keypair,
  requiredAddresses: PublicKey[],
  existingAddress: PublicKey | null,
): Promise<AddressLookupTableAccount> {
  const uniqueAddresses = Array.from(
    new Map(requiredAddresses.map((address) => [address.toBase58(), address])).values(),
  );
  let lookupTableAddress = existingAddress;
  let lookupTable: AddressLookupTableAccount | null = null;
  if (lookupTableAddress) {
    lookupTable = await fetchLookupTable(connection, lookupTableAddress);
    if (!lookupTable.state.authority?.equals(payer.publicKey)) {
      throw new Error(
        `Lookup table ${lookupTableAddress.toBase58()} is not controlled by payer `
        + payer.publicKey.toBase58(),
      );
    }
  } else {
    const recentSlot = await connection.getSlot("finalized");
    const [createInstruction, createdAddress] =
      AddressLookupTableProgram.createLookupTable({
        authority: payer.publicKey,
        payer: payer.publicKey,
        recentSlot,
      });
    lookupTableAddress = createdAddress;
    const createSignature = await sendAndConfirmTransaction(
      connection,
      new Transaction().add(createInstruction),
      [payer],
      LOOKUP_TABLE_CREATE_SEND_OPTIONS,
    );
    console.log(JSON.stringify({
      lookup_table_created: lookupTableAddress.toBase58(),
      signature: createSignature,
    }));
  }
  if (!lookupTableAddress) throw new Error("Lookup table preparation did not produce an address");

  const existing = new Set(
    (lookupTable?.state.addresses ?? []).map((address) => address.toBase58()),
  );
  const missingAddresses = uniqueAddresses.filter(
    (address) => !existing.has(address.toBase58()),
  );
  for (let offset = 0; offset < missingAddresses.length; offset += 20) {
    const addresses = missingAddresses.slice(offset, offset + 20);
    const extendInstruction = AddressLookupTableProgram.extendLookupTable({
      authority: payer.publicKey,
      payer: payer.publicKey,
      lookupTable: lookupTableAddress,
      addresses,
    });
    const signature = await sendAndConfirmTransaction(
      connection,
      new Transaction().add(extendInstruction),
      [payer],
      { commitment: "finalized", preflightCommitment: "finalized" },
    );
    console.log(JSON.stringify({
      lookup_table_extended: lookupTableAddress.toBase58(),
      address_count: addresses.length,
      signature,
    }));
  }

  lookupTable = await fetchLookupTable(connection, lookupTableAddress);
  assertLookupTableCovers(lookupTable, requiredAddresses);
  const currentSlot = await connection.getSlot("finalized");
  if (currentSlot <= lookupTable.state.lastExtendedSlot) {
    throw new Error(
      `Lookup table ${lookupTableAddress.toBase58()} is not active yet; rerun with `
      + `--lookup-table ${lookupTableAddress.toBase58()} after the next finalized slot`,
    );
  }
  return lookupTable;
}

function migrationPlanSha256(
  instruction: TransactionInstruction,
  payer: PublicKey,
  lookupTable: PublicKey,
  manifestSha256: string,
): string {
  const hash = crypto.createHash("sha256");
  hash.update("boulder-roller-dung-liability-plan-v1\n");
  hash.update(payer.toBuffer());
  hash.update(lookupTable.toBuffer());
  hash.update(Buffer.from(manifestSha256, "hex"));
  hash.update(instruction.programId.toBuffer());
  for (const key of instruction.keys) {
    hash.update(key.pubkey.toBuffer());
    hash.update(Buffer.from([key.isSigner ? 1 : 0, key.isWritable ? 1 : 0]));
  }
  hash.update(instruction.data);
  hash.update(Buffer.from("compute-unit-limit:400000"));
  return hash.digest("hex");
}

function loadAndValidatePayer(options: Options, admin: PublicKey): Keypair {
  const payer = loadKeypair(options.payerPath);
  if (!payer.publicKey.equals(options.payerPubkey)) {
    throw new Error(
      `Payer key ${payer.publicKey.toBase58()} does not match expected payer `
      + options.payerPubkey.toBase58(),
    );
  }
  if (payer.publicKey.equals(admin)) {
    throw new Error("The ProgramConfig admin cannot be used as the migration fee payer");
  }
  return payer;
}

function snapshotJson(snapshot: DungMintStateSnapshot): Record<string, string | number | null> {
  return {
    size: snapshot.size,
    authority: snapshot.authority.toBase58(),
    max_supply: snapshot.maxSupply.toString(),
    total_minted: snapshot.totalMinted.toString(),
    total_burned: snapshot.totalBurned.toString(),
    community_minted: snapshot.communityMinted.toString(),
    treasury_minted: snapshot.treasuryMinted.toString(),
    team_minted: snapshot.teamMinted.toString(),
    investor_minted: snapshot.investorMinted.toString(),
    pol_minted: snapshot.polMinted.toString(),
    emission_rate_bps: snapshot.emissionRateBps.toString(),
    last_halving_epoch: snapshot.lastHalvingEpoch.toString(),
    bump: snapshot.bump,
    community_reserved: snapshot.communityReserved?.toString() ?? null,
    reservation_policy_version: snapshot.reservationPolicyVersion,
  };
}

async function main(): Promise<void> {
  const options = parseArgs();
  if ((options.simulateOnly || options.execute) && !options.operationsPaused) {
    throw new Error("--simulate-only/--execute require --operations-paused");
  }
  if ((options.simulateOnly || options.execute) && !options.lookupTable) {
    throw new Error("--simulate-only/--execute require a pre-created --lookup-table");
  }
  if (options.execute && options.expectedPlanSha256 === null) {
    throw new Error("--execute requires --expected-plan-sha256 from the reviewed simulation");
  }
  const connection = new Connection(options.cluster, "finalized");
  const idlPath = fs.existsSync(path.join(__dirname, "..", "target", "idl", "boulder_rollers.json"))
    ? path.join(__dirname, "..", "target", "idl", "boulder_rollers.json")
    : path.join(__dirname, "..", "idl", "boulder_rollers.json");
  const idl = readJson(idlPath) as anchor.Idl;
  const coder = new anchor.BorshAccountsCoder(idl);
  const [dungMintState, dungMintStateBump] = PublicKey.findProgramAddressSync(
    [DUNG_MINT_STATE_SEED],
    options.programId,
  );
  const [programConfig] = PublicKey.findProgramAddressSync(
    [PROGRAM_CONFIG_SEED],
    options.programId,
  );
  const [vaultCounter] = PublicKey.findProgramAddressSync(
    [VAULT_COUNTER_SEED],
    options.programId,
  );

  const censusMinSlot = await connection.getSlot("finalized");
  const readConfig = { commitment: "finalized" as const, minContextSlot: censusMinSlot };
  const [dungAccount, configAccount, vaultCounterAccount, stakeCensus, vaultCensus] =
    await Promise.all([
    connection.getAccountInfo(dungMintState, readConfig),
    connection.getAccountInfo(programConfig, readConfig),
    connection.getAccountInfo(vaultCounter, readConfig),
    fetchStakeCensus(connection, options.programId, censusMinSlot),
    fetchVaultCensus(connection, options.programId, coder, censusMinSlot),
  ]);
  const before = decodeDungMintState(dungAccount, options.programId);
  const programConfigAdmin = decodeProgramConfigAdmin(configAccount, options.programId);
  if (!before.authority.equals(programConfigAdmin)) {
    throw new Error(
      `Stored DungMintState authority ${before.authority.toBase58()} does not match `
      + `ProgramConfig admin ${programConfigAdmin.toBase58()}`,
    );
  }
  if (before.bump !== dungMintStateBump) {
    throw new Error(
      `Stored DungMintState bump ${before.bump} does not match canonical bump ${dungMintStateBump}`,
    );
  }
  if (before.reservationPolicyVersion === null && before.emissionRateBps !== 10_000n) {
    throw new Error(
      `Legacy emission rate ${before.emissionRateBps} cannot prove an unmodified start week`,
    );
  }
  const vaultCounterCount = decodeVaultCounter(vaultCounterAccount, options.programId, coder);
  const { total: communityLiability, manifestSha256 } = assertExpectedCensus(
    options,
    stakeCensus,
    vaultCensus,
    vaultCounterCount,
  );
  if (
    before.reservationPolicyVersion === null
    && before.communityReserved !== null
    && before.communityReserved > communityLiability
  ) {
    throw new Error(
      `Claim-only reservation ${before.communityReserved} exceeds full liability `
      + communityLiability.toString(),
    );
  }
  if (
    before.reservationPolicyVersion === DUNG_RESERVATION_POLICY_VERSION
    && before.communityReserved !== communityLiability
  ) {
    throw new Error(
      `Current reservation ${before.communityReserved} does not equal liability `
      + communityLiability.toString(),
    );
  }
  const remainingAccounts = [
    ...stakeCensus.accounts.map(({ pubkey }) => pubkey),
    ...vaultCensus.accounts.map(({ pubkey }) => pubkey),
  ]
    .sort((left, right) => left.toBase58().localeCompare(right.toBase58()))
    .map((pubkey) => ({ pubkey, isWritable: false, isSigner: false }));
  const inventoryAddresses = remainingAccounts.map(({ pubkey }) => pubkey);
  if (options.payerPubkey.equals(programConfigAdmin)) {
    throw new Error("The ProgramConfig admin cannot be used as the migration fee payer");
  }
  if (options.prepareAlt) {
    const payer = loadAndValidatePayer(options, programConfigAdmin);
    const lookupTable = await prepareInventoryLookupTable(
      connection,
      payer,
      inventoryAddresses,
      options.lookupTable,
    );
    console.log(JSON.stringify({
      mode: "prepare-alt",
      lookup_table: lookupTable.key.toBase58(),
      payer: payer.publicKey.toBase58(),
      inventory_account_count: inventoryAddresses.length,
      inventory_manifest_sha256: manifestSha256,
      next_step: "Pause DUNG writers, then rerun read-only with this --lookup-table.",
    }, null, 2));
    return;
  }
  const planningWallet = {
    publicKey: programConfigAdmin,
    signTransaction: async (transaction: any) => transaction,
    signAllTransactions: async (transactions: any[]) => transactions,
  } as anchor.Wallet;
  const planningProvider = new anchor.AnchorProvider(
    connection,
    planningWallet,
    { commitment: "finalized" },
  );
  const program = new anchor.Program(idl, options.programId, planningProvider);
  const migrationInstruction = await program.methods
    .migrateDungMintState(
      stakeCensus.accounts.length,
      vaultCensus.accounts.length,
      new BN(communityLiability.toString()),
    )
    .accounts({
      dungMintState,
      authority: programConfigAdmin,
      payer: options.payerPubkey,
      programConfig,
      vaultCounter,
      systemProgram: SystemProgram.programId,
    })
    .remainingAccounts(remainingAccounts)
    .instruction();
  const lookupTable = options.lookupTable
    ? await fetchLookupTable(connection, options.lookupTable)
    : new AddressLookupTableAccount({
      key: PublicKey.default,
      state: {
        deactivationSlot: U64_MAX,
        lastExtendedSlot: 0,
        lastExtendedSlotStartIndex: 0,
        authority: options.payerPubkey,
        addresses: inventoryAddresses,
      },
    });
  assertLookupTableCovers(lookupTable, inventoryAddresses);
  if (options.lookupTable) {
    const currentSlot = await connection.getSlot("finalized");
    if (currentSlot <= lookupTable.state.lastExtendedSlot) {
      throw new Error(`Lookup table ${lookupTable.key.toBase58()} is not active yet`);
    }
  }
  const planSha256 = migrationPlanSha256(
    migrationInstruction,
    options.payerPubkey,
    lookupTable.key,
    manifestSha256,
  );
  if (options.expectedPlanSha256 !== null && options.expectedPlanSha256 !== planSha256) {
    throw new Error(`Expected plan ${options.expectedPlanSha256}, computed ${planSha256}`);
  }
  const plannedMessage = new TransactionMessage({
    payerKey: options.payerPubkey,
    recentBlockhash: PublicKey.default.toBase58(),
    instructions: [
      ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 }),
      migrationInstruction,
    ],
  }).compileToV0Message([lookupTable]);
  const plannedSerializedLength = new VersionedTransaction(plannedMessage).serialize().length;
  if (plannedSerializedLength > PACKET_DATA_SIZE) {
    throw new Error(
      `Planned migration is ${plannedSerializedLength} bytes; packet limit is ${PACKET_DATA_SIZE}`,
    );
  }

  const nonzeroClaims = stakeCensus.accounts
    .filter((claim) => claim.rewardsEarned > 0n)
    .map((claim) => ({
      pda: claim.pubkey.toBase58(),
      user: claim.user.toBase58(),
      vault_id: claim.vaultId.toString(),
      rewards_earned: claim.rewardsEarned.toString(),
      active: claim.active,
    }));
  const nonzeroCarries = vaultCensus.accounts
    .filter((vault) => (
      vault.carryRecordRoyalty > 0n
      || vault.carryStakers > 0n
      || vault.carryLocalLegend > 0n
    ))
    .map((vault) => ({
      pda: vault.pubkey.toBase58(),
      vault_id: vault.id.toString(),
      carry_record_royalty: vault.carryRecordRoyalty.toString(),
      carry_stakers: vault.carryStakers.toString(),
      carry_local_legend: vault.carryLocalLegend.toString(),
    }));
  console.log(JSON.stringify({
    mode: options.execute ? "execute" : options.simulateOnly ? "simulate-only" : "read-only",
    cluster: options.cluster,
    census_min_slot: censusMinSlot,
    program_id: options.programId.toBase58(),
    dung_mint_state: dungMintState.toBase58(),
    program_config_admin: programConfigAdmin.toBase58(),
    fee_payer: options.payerPubkey.toBase58(),
    legacy_dung_authority: before.authority.toBase58(),
    before: snapshotJson(before),
    stake_census: {
      count: stakeCensus.accounts.length,
      active_count: stakeCensus.activeCount,
      inactive_count: stakeCensus.accounts.length - stakeCensus.activeCount,
      rewards_earned_sum: stakeCensus.totalRewards.toString(),
      nonzero_claims: nonzeroClaims,
    },
    vault_census: {
      count: vaultCensus.accounts.length,
      vault_counter_count: vaultCounterCount,
      community_carry_sum: vaultCensus.totalCommunityCarry.toString(),
      nonzero_carries: nonzeroCarries,
    },
    combined_community_liability: communityLiability.toString(),
    inventory_manifest_sha256: manifestSha256,
    migration_plan_sha256: planSha256,
    migration_transport: {
      versioned_transaction: true,
      inventory_lookup_table_required: true,
      lookup_table: options.lookupTable?.toBase58() ?? null,
      synthetic_lookup_table: options.lookupTable === null,
      planned_serialized_bytes: plannedSerializedLength,
      packet_limit_bytes: PACKET_DATA_SIZE,
    },
  }, null, 2));

  if (!options.simulateOnly && !options.execute) return;

  const authority = loadKeypair(options.authorityPath);
  if (!authority.publicKey.equals(programConfigAdmin)) {
    throw new Error(
      `Authority key ${authority.publicKey.toBase58()} does not match ProgramConfig admin ${programConfigAdmin.toBase58()}`,
    );
  }
  const payer = loadAndValidatePayer(options, programConfigAdmin);

  const latestBlockhash = await connection.getLatestBlockhash("finalized");
  const message = new TransactionMessage({
    payerKey: payer.publicKey,
    recentBlockhash: latestBlockhash.blockhash,
    instructions: [
      ComputeBudgetProgram.setComputeUnitLimit({ units: 400_000 }),
      migrationInstruction,
    ],
  }).compileToV0Message([lookupTable]);
  const transaction = new VersionedTransaction(message);
  transaction.sign([payer, authority]);
  const serializedLength = transaction.serialize().length;
  if (serializedLength > PACKET_DATA_SIZE) {
    throw new Error(
      `Migration transaction is ${serializedLength} bytes; packet limit is ${PACKET_DATA_SIZE}`,
    );
  }

  const simulation = await connection.simulateTransaction(transaction, {
    commitment: "finalized",
    sigVerify: true,
  });
  if (simulation.value.err) {
    throw new Error(
      `Migration simulation failed: ${JSON.stringify(simulation.value.err)}\n`
      + (simulation.value.logs ?? []).join("\n"),
    );
  }
  console.log(JSON.stringify({
    mode: options.simulateOnly ? "simulate-only" : "execute-preflight",
    migration_plan_sha256: planSha256,
    inventory_manifest_sha256: manifestSha256,
    serialized_transaction_bytes: serializedLength,
    simulated_compute_units: simulation.value.unitsConsumed ?? null,
    simulation_logs: simulation.value.logs ?? [],
  }, null, 2));
  if (options.simulateOnly) return;

  const signature = await connection.sendTransaction(transaction, {
    maxRetries: 3,
    preflightCommitment: "finalized",
    skipPreflight: false,
  });
  const confirmation = await connection.confirmTransaction(
    { signature, ...latestBlockhash },
    "finalized",
  );
  if (confirmation.value.err) {
    throw new Error(`Migration transaction failed: ${JSON.stringify(confirmation.value.err)}`);
  }

  const migrationSlot = confirmation.context.slot;
  const postReadConfig = { commitment: "finalized" as const, minContextSlot: migrationSlot };
  const [postAccount, postVaultCounterAccount, postStakeCensus, postVaultCensus] =
    await Promise.all([
    connection.getAccountInfo(dungMintState, postReadConfig),
    connection.getAccountInfo(vaultCounter, postReadConfig),
    fetchStakeCensus(connection, options.programId, migrationSlot),
    fetchVaultCensus(connection, options.programId, coder, migrationSlot),
  ]);
  const after = decodeDungMintState(postAccount, options.programId);
  const postVaultCounterCount = decodeVaultCounter(
    postVaultCounterAccount,
    options.programId,
    coder,
  );
  const {
    total: postCommunityLiability,
    manifestSha256: postManifestSha256,
  } = assertExpectedCensus(
    options,
    postStakeCensus,
    postVaultCensus,
    postVaultCounterCount,
  );
  if (after.size !== CURRENT_DUNG_MINT_STATE_SIZE) {
    throw new Error(`Post-migration size is ${after.size}, expected ${CURRENT_DUNG_MINT_STATE_SIZE}`);
  }
  if (!after.prefix.equals(before.prefix)) {
    throw new Error("Migration changed one or more legacy DungMintState bytes");
  }
  if (after.communityReserved !== postCommunityLiability) {
    throw new Error(
      `Post-migration reservation ${after.communityReserved} != liabilities ${postCommunityLiability}`,
    );
  }
  if (after.reservationPolicyVersion !== DUNG_RESERVATION_POLICY_VERSION) {
    throw new Error(
      `Post-migration reservation policy is ${after.reservationPolicyVersion}, `
      + `expected ${DUNG_RESERVATION_POLICY_VERSION}`,
    );
  }
  for (const field of [
    "maxSupply",
    "totalMinted",
    "totalBurned",
    "communityMinted",
    "treasuryMinted",
    "teamMinted",
    "investorMinted",
    "polMinted",
    "emissionRateBps",
    "lastHalvingEpoch",
    "bump",
  ] as const) {
    if (after[field] !== before[field]) {
      throw new Error(`Migration changed legacy field ${field}`);
    }
  }

  console.log(JSON.stringify({
    signature,
    migration_slot: migrationSlot,
    lookup_table: lookupTable.key.toBase58(),
    serialized_transaction_bytes: serializedLength,
    simulated_compute_units: simulation.value.unitsConsumed ?? null,
    post_migration: snapshotJson(after),
    verified_stake_claim_sum: postStakeCensus.totalRewards.toString(),
    verified_community_carry_sum: postVaultCensus.totalCommunityCarry.toString(),
    verified_community_liability: postCommunityLiability.toString(),
    verified_inventory_manifest_sha256: postManifestSha256,
    verified_migration_plan_sha256: planSha256,
    legacy_prefix_preserved: true,
  }, null, 2));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
