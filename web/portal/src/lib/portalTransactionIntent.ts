import { Buffer } from 'buffer';
import { PublicKey, Transaction, VersionedTransaction, TransactionMessage, AddressLookupTableAccount, AddressLookupTableProgram, type TransactionInstruction } from '@solana/web3.js';

import type {
  PreparedVaultTransaction,
  VaultCreationPaymentMethod,
} from './api';
import { STAGE1_CASH_MINT } from './stage1.ts';

export type BalanceFundingAsset = 'CAL' | 'USDC';
export type BalanceWalletAsset = BalanceFundingAsset | 'DUNG';

export type Stage1TestPool = { mint: string; provider: string };
export type Stage1LockWeeks = 0 | 13 | 26 | 52;
export type Stage1ClaimProof = { hash: string; sum: string };
export type Stage1ClaimLeaf = {
  hill: string; week: string; index: number; amountBaseUnits: string;
  proof: Stage1ClaimProof[];
};
export type Stage1CashLeaf = Stage1ClaimLeaf & {
  capBaseUnits: string; frozenAt: string; auditHash: string;
};
export type Stage1DungLeaf = Stage1ClaimLeaf & { role: 0 | 1 };
// Screens must construct pledge, notice and convert intents from the person's
// own inputs and independently loaded context. Never adopt the prepare
// response's echoed `intent`: doing so would let a compromised backend choose
// the amount, lock or hill that this checker is supposed to protect.
export type Stage1TransactionIntent =
  | { kind: 'stage1_registration' }
  | { kind: 'stage1_cancel_pledge'; hill: string; mint: string; depositId: string }
  | { kind: 'stage1_claim_transport'; mode: 'create'; recentSlot: string; lookupTable: string; addresses: string[] }
  | { kind: 'stage1_claim_transport'; mode: 'deactivate' | 'close'; lookupTable: string }
  | { kind: 'stage1_pledge'; hill: string; climb: string; mint: string; depositId: string;
      amountBaseUnits: string; lockWeeks: Stage1LockWeeks;
      providerMode: 'prebond' | 'bonded'; backingMints: string[] }
  | { kind: 'stage1_withdrawal_notice'; hill: string; depositId: string; requestId: string; basisLamports: string }
  | { kind: 'stage1_cancel_notice'; depositId: string; requestId: string }
  | { kind: 'stage1_begin_withdrawal' | 'stage1_complete_withdrawal'; hill: string; mint: string;
      depositId: string; requestId: string; week: string; refreshRate?: boolean }
  | { kind: 'stage1_convert_pledge'; hill: string; mint: string; depositId: string; lockWeeks: Stage1LockWeeks; refreshRate?: boolean }
  | { kind: 'stage1_self_claim'; mint: string; claimType: 'cash'; claims: Stage1CashLeaf[]; single?: boolean }
  | { kind: 'stage1_self_claim'; mint: string; claimType: 'dung'; claims: Stage1DungLeaf[]; single?: boolean };

export type PreparedTransactionIntent =
  | Stage1TransactionIntent
  | {
      kind: 'create_vault';
      paymentMethod: VaultCreationPaymentMethod;
      climbId: string;
      canonId: string;
      canonVersion: number;
    }
  | {
      kind: 'stake';
      vaultId: number;
      amountBaseUnits: string;
    }
  | {
      kind: 'unstake';
      vaultId: number;
      lpAmountBaseUnits: string;
    }
  | {
      kind: 'balance_add_funds';
      asset: BalanceFundingAsset;
      amountBaseUnits: string;
    }
  | {
      kind: 'balance_withdraw';
      asset: BalanceWalletAsset;
      amountBaseUnits: string;
    };

export function vaultWithdrawalIntent(
  vaultId: number,
  lpAmountBaseUnits: string,
): PreparedTransactionIntent {
  return {
    kind: 'unstake',
    vaultId,
    lpAmountBaseUnits,
  };
}

export class PreparedTransactionIntentError extends Error {
  constructor() {
    super('Prepared Balance transaction does not match the requested action.');
    this.name = 'PreparedTransactionIntentError';
  }
}

// This is intentionally release-pinned. Rotating a key, mint, treasury, or
// program requires a portal release; an unexpected backend response fails
// closed instead of silently broadening wallet authority.
const RELEASE_REGISTRY = {
  program: 'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH',
  feePayer: '9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP',
  backendAuthority: 'CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha',
  calMint: '4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh',
  dungMint: 'CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk',
  dungTreasury: '9wkFkPSH9eL1XdifxzM7ASfqyVtSZWAuLGUXTx5ijwPr',
  usdcMint: 'DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne',
  usdcTreasury: 'GEL1JhavEKPuqVBvUiezUgNG2VYK1jtzsUazo2Scm1jA',
  tokenProgram: 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
  associatedTokenProgram: 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL',
  systemProgram: '11111111111111111111111111111111',
  rentSysvar: 'SysvarRent111111111111111111111111111111111',
} as const;

const DISCRIMINATORS = {
  createVault: '1dedf7d0c1523687',
  createVaultWithUsdc: '1514224260a15779',
  initializeVaultLpMint: '61c288eef6ff4781',
  initializeVaultCalEscrow: '4db2d097d8221bd0',
  initializeVaultPositionLp: '14c0ccb7e4becef4',
  stakeCalInVault: '93965b0c13fabd6a',
  collectStakeRewardsFor: 'dc76b7f5d1ed423d',
  unstakeCalFromVault: '8f48926ca6362c10',
  withdrawToWallet: '5dbed152738c90e1',
} as const;

const MAX_U64 = (1n << 64n) - 1n;
const textEncoder = new TextEncoder();

type RegistryPublicKeys = ReturnType<typeof publicKeyRegistry>;

function reject(): never {
  throw new PreparedTransactionIntentError();
}

function publicKey(value: string): PublicKey {
  const result = new PublicKey(value);
  if (result.toBase58() !== value) reject();
  return result;
}

function publicKeyRegistry() {
  return {
    program: publicKey(RELEASE_REGISTRY.program),
    feePayer: publicKey(RELEASE_REGISTRY.feePayer),
    backendAuthority: publicKey(RELEASE_REGISTRY.backendAuthority),
    calMint: publicKey(RELEASE_REGISTRY.calMint),
    dungMint: publicKey(RELEASE_REGISTRY.dungMint),
    dungTreasury: publicKey(RELEASE_REGISTRY.dungTreasury),
    usdcMint: publicKey(RELEASE_REGISTRY.usdcMint),
    usdcTreasury: publicKey(RELEASE_REGISTRY.usdcTreasury),
    tokenProgram: publicKey(RELEASE_REGISTRY.tokenProgram),
    associatedTokenProgram: publicKey(RELEASE_REGISTRY.associatedTokenProgram),
    systemProgram: publicKey(RELEASE_REGISTRY.systemProgram),
    rentSysvar: publicKey(RELEASE_REGISTRY.rentSysvar),
  };
}

function exactU64(value: string, positive = true): bigint {
  if (!/^(0|[1-9][0-9]*)$/u.test(value)) reject();
  const parsed = BigInt(value);
  if (parsed > MAX_U64 || (positive && parsed === 0n)) reject();
  return parsed;
}

function exactVaultId(value: number): bigint {
  if (!Number.isSafeInteger(value) || value < 0) reject();
  return BigInt(value);
}

function u64Le(value: bigint): Buffer {
  const result = Buffer.alloc(8);
  result.writeBigUInt64LE(value);
  return result;
}

function discriminator(value: keyof typeof DISCRIMINATORS): Buffer {
  return Buffer.from(DISCRIMINATORS[value], 'hex');
}

function instructionData(prefix: keyof typeof DISCRIMINATORS, amount?: bigint): Buffer {
  return amount === undefined
    ? discriminator(prefix)
    : Buffer.concat([discriminator(prefix), u64Le(amount)]);
}

function pda(program: PublicKey, seed: string, ...remaining: Uint8Array[]): PublicKey {
  return PublicKey.findProgramAddressSync(
    [textEncoder.encode(seed), ...remaining],
    program,
  )[0];
}

function ata(owner: PublicKey, mint: PublicKey, registry: RegistryPublicKeys): PublicKey {
  return PublicKey.findProgramAddressSync(
    [owner.toBytes(), registry.tokenProgram.toBytes(), mint.toBytes()],
    registry.associatedTokenProgram,
  )[0];
}

function sameKey(left: PublicKey, right: PublicKey): boolean {
  return left.equals(right);
}

function keySet(values: PublicKey[]): Set<string> {
  return new Set(values.map((value) => value.toBase58()));
}

function requireSameSet(actual: Set<string>, expected: Set<string>) {
  if (actual.size !== expected.size) reject();
  for (const value of expected) {
    if (!actual.has(value)) reject();
  }
}

function requireInstruction(
  instructions: TransactionInstruction[],
  index: number,
  programId: PublicKey,
  data: Uint8Array,
  accounts: PublicKey[],
): TransactionInstruction {
  const instruction = instructions[index];
  if (
    !instruction
    || !sameKey(instruction.programId, programId)
    || !Buffer.from(instruction.data).equals(Buffer.from(data))
    || instruction.keys.length !== accounts.length
  ) {
    reject();
  }

  const actualAccounts = instruction.keys.map((entry) => entry.pubkey);
  if (keySet(actualAccounts).size !== actualAccounts.length) reject();
  for (let accountIndex = 0; accountIndex < accounts.length; accountIndex += 1) {
    if (!sameKey(actualAccounts[accountIndex], accounts[accountIndex])) reject();
  }
  return instruction;
}

function hasData(
  instructions: TransactionInstruction[],
  index: number,
  data: Uint8Array,
): boolean {
  const instruction = instructions[index];
  return Boolean(instruction && Buffer.from(instruction.data).equals(Buffer.from(data)));
}

function isCreateAta(
  instructions: TransactionInstruction[],
  index: number,
  mint: PublicKey,
  registry: RegistryPublicKeys,
): boolean {
  const instruction = instructions[index];
  return Boolean(
    instruction
    && sameKey(instruction.programId, registry.associatedTokenProgram)
    && instruction.data.length === 0
    && instruction.keys.length === 7
    && sameKey(instruction.keys[3].pubkey, mint)
  );
}

function requireCreateAta(
  instructions: TransactionInstruction[],
  index: number,
  owner: PublicKey,
  mint: PublicKey,
  destination: PublicKey,
  registry: RegistryPublicKeys,
) {
  requireInstruction(
    instructions,
    index,
    registry.associatedTokenProgram,
    Buffer.alloc(0),
    [
      registry.feePayer,
      destination,
      owner,
      mint,
      registry.systemProgram,
      registry.tokenProgram,
      registry.rentSysvar,
    ],
  );
}

function requireGlobalRoles(
  transaction: Transaction,
  expectedSigners: PublicKey[],
  expectedWritable: PublicKey[],
) {
  const message = transaction.compileMessage();
  const { numRequiredSignatures, numReadonlySignedAccounts, numReadonlyUnsignedAccounts } = message.header;
  const writableSignedCount = numRequiredSignatures - numReadonlySignedAccounts;
  const writableUnsignedLimit = message.accountKeys.length - numReadonlyUnsignedAccounts;
  const actualSigners = new Set<string>();
  const actualWritable = new Set<string>();

  message.accountKeys.forEach((key, index) => {
    if (index < numRequiredSignatures) actualSigners.add(key.toBase58());
    if (
      index < writableSignedCount
      || (index >= numRequiredSignatures && index < writableUnsignedLimit)
    ) {
      actualWritable.add(key.toBase58());
    }
  });

  requireSameSet(actualSigners, keySet(expectedSigners));
  requireSameSet(actualWritable, keySet(expectedWritable));
}

function requireEveryStaticKeyIsUsed(transaction: Transaction) {
  const message = transaction.compileMessage();
  const used = new Set<string>([message.accountKeys[0].toBase58()]);
  for (const instruction of transaction.instructions) {
    used.add(instruction.programId.toBase58());
    for (const account of instruction.keys) used.add(account.pubkey.toBase58());
  }
  requireSameSet(used, keySet(message.accountKeys));
}

function strictLegacyTransaction(prepared: PreparedVaultTransaction): Transaction {
  if (
    typeof prepared.transaction !== 'string'
    || prepared.transaction.length === 0
    || prepared.transaction.length % 4 !== 0
    || !/^[A-Za-z0-9+/]+={0,2}$/u.test(prepared.transaction)
    || typeof prepared.blockhash !== 'string'
    || !Number.isSafeInteger(prepared.lastValidBlockHeight)
    || prepared.lastValidBlockHeight <= 0
  ) {
    reject();
  }

  const wire = Buffer.from(prepared.transaction, 'base64');
  if (wire.length === 0 || wire.toString('base64') !== prepared.transaction) reject();

  let transaction: Transaction;
  try {
    transaction = Transaction.from(wire);
  } catch {
    reject();
  }

  const canonicalWire = transaction.serialize({
    requireAllSignatures: false,
    verifySignatures: false,
  });
  if (!Buffer.from(canonicalWire).equals(wire)) reject();

  const message = transaction.compileMessage();
  if (message.recentBlockhash !== prepared.blockhash) reject();
  if (message.accountKeys.length === 0) reject();
  if (keySet(message.accountKeys).size !== message.accountKeys.length) reject();
  if (!sameKey(message.accountKeys[0], publicKey(RELEASE_REGISTRY.feePayer))) reject();
  return transaction;
}

function contextForVault(
  vaultId: number,
  wallet: PublicKey,
  registry: RegistryPublicKeys,
) {
  const vaultIdBytes = u64Le(exactVaultId(vaultId));
  return {
    vaultIdBytes,
    vault: pda(registry.program, 'vault', vaultIdBytes),
    vaultStake: pda(registry.program, 'vault_stake', wallet.toBytes(), vaultIdBytes),
    vaultActivation: pda(registry.program, 'vault_activation', vaultIdBytes),
    programConfig: pda(registry.program, 'program_config'),
    vaultCalEscrow: pda(registry.program, 'vault_cal_escrow', vaultIdBytes),
    vaultLpMint: pda(registry.program, 'vault_lp', vaultIdBytes),
    positionLp: pda(registry.program, 'vault_position_lp', wallet.toBytes(), vaultIdBytes),
    walletCalAta: ata(wallet, registry.calMint, registry),
    walletDungAta: ata(wallet, registry.dungMint, registry),
    dungMintState: pda(registry.program, 'dung_mint_state'),
    dungMintAuthority: pda(registry.program, 'dung_mint_auth'),
  };
}

function validateStake(
  transaction: Transaction,
  wallet: PublicKey,
  vaultId: number,
  amountBaseUnits: string,
  registry: RegistryPublicKeys,
) {
  const amount = exactU64(amountBaseUnits);
  const context = contextForVault(vaultId, wallet, registry);
  const instructions = transaction.instructions;
  let cursor = 0;

  if (hasData(instructions, cursor, discriminator('initializeVaultLpMint'))) {
    requireInstruction(
      instructions,
      cursor,
      registry.program,
      discriminator('initializeVaultLpMint'),
      [
        context.vault,
        context.vaultLpMint,
        registry.feePayer,
        registry.tokenProgram,
        registry.systemProgram,
        registry.rentSysvar,
      ],
    );
    cursor += 1;
  }

  if (hasData(instructions, cursor, discriminator('initializeVaultCalEscrow'))) {
    requireInstruction(
      instructions,
      cursor,
      registry.program,
      discriminator('initializeVaultCalEscrow'),
      [
        context.vault,
        context.programConfig,
        context.vaultCalEscrow,
        registry.calMint,
        registry.feePayer,
        registry.tokenProgram,
        registry.systemProgram,
        registry.rentSysvar,
      ],
    );
    cursor += 1;
  }

  requireInstruction(
    instructions,
    cursor,
    registry.program,
    discriminator('initializeVaultPositionLp'),
    [
      context.vault,
      wallet,
      context.vaultStake,
      context.vaultLpMint,
      context.positionLp,
      registry.backendAuthority,
      registry.tokenProgram,
      registry.systemProgram,
    ],
  );
  cursor += 1;

  requireInstruction(
    instructions,
    cursor,
    registry.program,
    instructionData('stakeCalInVault', amount),
    [
      context.vault,
      context.vaultStake,
      context.vaultActivation,
      context.programConfig,
      registry.backendAuthority,
      wallet,
      context.walletCalAta,
      context.vaultCalEscrow,
      context.vaultLpMint,
      context.positionLp,
      registry.tokenProgram,
      registry.systemProgram,
    ],
  );
  cursor += 1;
  if (cursor !== instructions.length) reject();

  requireGlobalRoles(
    transaction,
    [registry.feePayer, registry.backendAuthority, wallet],
    [
      registry.feePayer,
      registry.backendAuthority,
      wallet,
      context.vault,
      context.vaultStake,
      context.walletCalAta,
      context.vaultCalEscrow,
      context.vaultLpMint,
      context.positionLp,
    ],
  );
}

function validateUnstake(
  transaction: Transaction,
  wallet: PublicKey,
  vaultId: number,
  lpAmountBaseUnits: string,
  registry: RegistryPublicKeys,
) {
  const amount = exactU64(lpAmountBaseUnits);
  const context = contextForVault(vaultId, wallet, registry);
  const instructions = transaction.instructions;
  let cursor = 0;
  let createdDungAta = false;
  let collected = false;

  if (isCreateAta(instructions, cursor, registry.dungMint, registry)) {
    requireCreateAta(
      instructions,
      cursor,
      wallet,
      registry.dungMint,
      context.walletDungAta,
      registry,
    );
    createdDungAta = true;
    cursor += 1;
  }

  if (
    hasData(instructions, cursor, discriminator('collectStakeRewardsFor'))
  ) {
    requireInstruction(
      instructions,
      cursor,
      registry.program,
      discriminator('collectStakeRewardsFor'),
      [
        context.vault,
        context.vaultStake,
        context.vaultActivation,
        wallet,
        registry.feePayer,
        registry.dungMint,
        context.walletDungAta,
        registry.dungTreasury,
        context.dungMintState,
        context.programConfig,
        context.dungMintAuthority,
        registry.tokenProgram,
      ],
    );
    collected = true;
    cursor += 1;
  } else if (createdDungAta) {
    reject();
  }

  if (isCreateAta(instructions, cursor, registry.calMint, registry)) {
    requireCreateAta(
      instructions,
      cursor,
      wallet,
      registry.calMint,
      context.walletCalAta,
      registry,
    );
    cursor += 1;
  }

  requireInstruction(
    instructions,
    cursor,
    registry.program,
    instructionData('unstakeCalFromVault', amount),
    [
      context.vault,
      context.vaultStake,
      context.vaultActivation,
      context.programConfig,
      wallet,
      context.walletCalAta,
      context.vaultCalEscrow,
      registry.calMint,
      context.vaultLpMint,
      context.positionLp,
      registry.tokenProgram,
    ],
  );
  cursor += 1;
  if (cursor !== instructions.length) reject();

  const writable = [
    registry.feePayer,
    wallet,
    context.vault,
    context.vaultStake,
    context.walletCalAta,
    context.vaultCalEscrow,
    registry.calMint,
    context.vaultLpMint,
    context.positionLp,
  ];
  if (collected) {
    writable.push(
      registry.dungMint,
      context.walletDungAta,
      registry.dungTreasury,
      context.dungMintState,
    );
  }
  requireGlobalRoles(transaction, [registry.feePayer, wallet], writable);
}

function balanceContext(
  wallet: PublicKey,
  asset: BalanceWalletAsset,
  registry: RegistryPublicKeys,
) {
  const mint = asset === 'CAL'
    ? registry.calMint
    : asset === 'USDC'
      ? registry.usdcMint
      : asset === 'DUNG'
        ? registry.dungMint
        : reject();
  return {
    mint,
    decimals: asset === 'USDC' ? 6 : 9,
    walletAta: ata(wallet, mint, registry),
    riderBalance: pda(registry.program, 'rider_balance', wallet.toBytes()),
    riderBalanceAuthority: pda(registry.program, 'rider_balance_auth', wallet.toBytes()),
    riderBalanceToken: pda(
      registry.program,
      'rider_balance_token',
      wallet.toBytes(),
      mint.toBytes(),
    ),
    programConfig: pda(registry.program, 'program_config'),
  };
}

function validateBalanceAddFunds(
  transaction: Transaction,
  prepared: PreparedVaultTransaction,
  wallet: PublicKey,
  asset: BalanceFundingAsset,
  amountBaseUnits: string,
  registry: RegistryPublicKeys,
) {
  if (asset !== 'CAL' && asset !== 'USDC') reject();
  const amount = exactU64(amountBaseUnits);
  const context = balanceContext(wallet, asset, registry);
  if (prepared.pda !== context.riderBalanceToken.toBase58()) reject();
  requireInstruction(
    transaction.instructions,
    0,
    registry.tokenProgram,
    Buffer.concat([
      Buffer.from([12]),
      u64Le(amount),
      Buffer.from([context.decimals]),
    ]),
    [context.walletAta, context.mint, context.riderBalanceToken, wallet],
  );
  if (transaction.instructions.length !== 1) reject();
  requireGlobalRoles(
    transaction,
    [registry.feePayer, wallet],
    [registry.feePayer, context.walletAta, context.riderBalanceToken],
  );
}

function validateBalanceWithdraw(
  transaction: Transaction,
  prepared: PreparedVaultTransaction,
  wallet: PublicKey,
  asset: BalanceWalletAsset,
  amountBaseUnits: string,
  registry: RegistryPublicKeys,
) {
  if (asset !== 'CAL' && asset !== 'USDC' && asset !== 'DUNG') reject();
  const amount = exactU64(amountBaseUnits);
  const context = balanceContext(wallet, asset, registry);
  if (prepared.pda !== context.riderBalanceToken.toBase58()) reject();
  let cursor = 0;
  if (isCreateAta(transaction.instructions, cursor, context.mint, registry)) {
    requireCreateAta(
      transaction.instructions,
      cursor,
      wallet,
      context.mint,
      context.walletAta,
      registry,
    );
    cursor += 1;
  }
  requireInstruction(
    transaction.instructions,
    cursor,
    registry.program,
    instructionData('withdrawToWallet', amount),
    [
      context.riderBalance,
      wallet,
      context.riderBalanceAuthority,
      context.programConfig,
      context.riderBalanceToken,
      context.walletAta,
      context.mint,
      registry.tokenProgram,
    ],
  );
  cursor += 1;
  if (cursor !== transaction.instructions.length) reject();
  requireGlobalRoles(
    transaction,
    [registry.feePayer, wallet],
    [registry.feePayer, context.riderBalanceToken, context.walletAta],
  );
}

function parseCanonCommitment(
  value: unknown,
  intent: Extract<PreparedTransactionIntent, { kind: 'create_vault' }>,
): Buffer {
  if (typeof value !== 'string' || !/^[0-9a-f]{128}$/u.test(value)) reject();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u.test(intent.canonId)) {
    reject();
  }
  if (!Number.isInteger(intent.canonVersion) || intent.canonVersion <= 0 || intent.canonVersion > 0xffff) {
    reject();
  }
  const commitment = Buffer.from(value, 'hex');
  const canonIdBytes = Buffer.from(intent.canonId.replace(/-/g, ''), 'hex');
  if (
    commitment[0] !== 1
    || !commitment.subarray(1, 17).equals(canonIdBytes)
    || commitment.readUInt16BE(17) !== intent.canonVersion
    || commitment.subarray(19, 32).some((byte) => byte !== 0)
    || commitment.subarray(32, 64).every((byte) => byte === 0)
  ) {
    reject();
  }
  return commitment;
}

async function sha256(value: Uint8Array): Promise<Uint8Array> {
  if (!globalThis.crypto?.subtle) reject();
  return new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new Uint8Array(value)));
}

async function validateCreateVault(
  transaction: Transaction,
  prepared: PreparedVaultTransaction,
  wallet: PublicKey,
  intent: Extract<PreparedTransactionIntent, { kind: 'create_vault' }>,
  registry: RegistryPublicKeys,
) {
  const createPrepared = prepared as PreparedVaultTransaction & {
    climbId?: unknown;
    canonCommitmentHex?: unknown;
  };
  if (createPrepared.climbId !== intent.climbId) reject();
  if (!Number.isSafeInteger(prepared.vaultId) || prepared.vaultId === null || prepared.vaultId! < 0) {
    reject();
  }
  const vaultIdBytes = u64Le(exactVaultId(prepared.vaultId!));
  const vault = pda(registry.program, 'vault', vaultIdBytes);
  if (prepared.pda !== vault.toBase58()) reject();

  const commitment = parseCanonCommitment(createPrepared.canonCommitmentHex, intent);
  const climb = pda(registry.program, 'climb', await sha256(commitment));
  const counter = pda(registry.program, 'vault_counter');
  const leaderboard = pda(registry.program, 'vault_leaderboard', vaultIdBytes);
  const localLegend = pda(registry.program, 'local_legend', vaultIdBytes);
  const activation = pda(registry.program, 'vault_activation', vaultIdBytes);
  const programConfig = pda(registry.program, 'program_config');
  const baseAccounts = [
    counter,
    vault,
    climb,
    leaderboard,
    localLegend,
    activation,
    registry.backendAuthority,
    wallet,
  ];
  const baseWritable = [
    registry.feePayer,
    counter,
    vault,
    climb,
    leaderboard,
    localLegend,
    activation,
    registry.backendAuthority,
    wallet,
  ];

  if (intent.paymentMethod === 'dung') {
    const dungState = pda(registry.program, 'dung_mint_state');
    const walletDungAta = ata(wallet, registry.dungMint, registry);
    requireInstruction(
      transaction.instructions,
      0,
      registry.program,
      discriminator('createVault'),
      [
        ...baseAccounts,
        dungState,
        registry.tokenProgram,
        registry.systemProgram,
        programConfig,
        registry.dungMint,
        walletDungAta,
      ],
    );
    requireGlobalRoles(
      transaction,
      [registry.feePayer, registry.backendAuthority, wallet],
      [...baseWritable, dungState, registry.dungMint, walletDungAta],
    );
  } else if (intent.paymentMethod === 'cal_usdc') {
    const walletCalAta = ata(wallet, registry.calMint, registry);
    const walletUsdcAta = ata(wallet, registry.usdcMint, registry);
    requireInstruction(
      transaction.instructions,
      0,
      registry.program,
      discriminator('createVaultWithUsdc'),
      [
        ...baseAccounts,
        walletCalAta,
        registry.usdcTreasury,
        registry.tokenProgram,
        registry.systemProgram,
        registry.calMint,
        programConfig,
        walletUsdcAta,
      ],
    );
    requireGlobalRoles(
      transaction,
      [registry.feePayer, registry.backendAuthority, wallet],
      [
        ...baseWritable,
        walletCalAta,
        registry.usdcTreasury,
        registry.calMint,
        walletUsdcAta,
      ],
    );
  } else {
    reject();
  }
  if (transaction.instructions.length !== 1) reject();
}

// ABI c0811f476ca9deaf5942e574588bbd68181d701cdc5bfc1719e6fc27a18cd441.
// These provider identities come from that release's stage1_providers.rs.
// A response can select an already pinned identity, never add another one.
const STAGE1_PROVIDERS: Readonly<Record<string, string>> = {
  J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn: 'Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb',
  mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So: '8szGkuLTAux9XMgZ2vtY39jVSowEcpBfFfD8hXSEqdGC',
  jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v: '8VpRhuxa7sUUepdY3kQiTmX9rS5vx4WgaXiAnXq4KCtr',
};

type Stage1Meta = { pubkey: PublicKey; isSigner: boolean; isWritable: boolean };
type Stage1Instruction = { program: PublicKey; data: Buffer; keys: Stage1Meta[] };

function validateStage1(
  transaction: Transaction, prepared: PreparedVaultTransaction, intent: Stage1TransactionIntent,
  wallet: PublicKey, registry: RegistryPublicKeys, testPool?: Stage1TestPool,
) {
  const providers = { ...STAGE1_PROVIDERS, ...(testPool ? { [testPool.mint]: testPool.provider } : {}) };
  const ro = (pubkey: PublicKey): Stage1Meta => ({ pubkey, isSigner: false, isWritable: false });
  const rw = (pubkey: PublicKey): Stage1Meta => ({ pubkey, isSigner: false, isWritable: true });
  const signer = (pubkey: PublicKey, writable = false): Stage1Meta => ({ pubkey, isSigner: true, isWritable: writable });
  const derive = (seed: string, ...parts: Uint8Array[]) => pda(registry.program, seed, ...parts);
  const keyBytes = (value: PublicKey) => value.toBytes();
  const number = (value: string, positive = false) => u64Le(exactU64(value, positive));
  const hex = (value: string) => {
    if (!/^[0-9a-f]{64}$/u.test(value)) reject();
    return Buffer.from(value, 'hex');
  };
  const lock = (value: Stage1LockWeeks) => {
    if (![0, 13, 26, 52].includes(value)) reject();
    const result = Buffer.alloc(2); result.writeUInt16LE(value); return result;
  };
  const asset = (mint: PublicKey) => derive('s1v1_asset', keyBytes(mint));
  const custody = (lot: PublicKey) => derive('s1v1_custody', keyBytes(lot));
  const reserve = (lot: PublicKey) => derive('s1v1_owner', keyBytes(lot));
  const earnings = (mint: PublicKey) => derive('s1v1_earnings', keyBytes(mint));
  const provider = (mint: PublicKey) => {
    const value = providers[mint.toBase58()];
    if (!value) reject();
    return [ro(publicKey(value)), ro(mint)];
  };
  const city = derive('s1v1_city');
  const registration = derive('s1v1_recipient', keyBytes(wallet));
  const expected: Stage1Instruction[] = [];
  let reference: PublicKey;
  const add = (discriminator: string, data: Uint8Array[], keys: Stage1Meta[]) => {
    expected.push({ program: registry.program, data: Buffer.concat([Buffer.from(discriminator, 'hex'), ...data]), keys });
  };
  const createAta = (mint: PublicKey) => {
    expected.push({ program: registry.associatedTokenProgram, data: Buffer.from([1]),
      keys: [signer(wallet, true), rw(ata(wallet, mint, registry)), ro(wallet), ro(mint), ro(registry.systemProgram), ro(registry.tokenProgram)] });
  };
  const fund = (hill: PublicKey, mint: PublicKey, week: string) => {
    const cursor = derive('s1v1_cursor', keyBytes(hill), keyBytes(mint));
    const funding = derive('s1v1_funding', keyBytes(hill), keyBytes(mint), number(week));
    add('f44e381663dfd514', [], [ro(city), rw(hill), ro(asset(mint)), rw(cursor), signer(registry.feePayer, true), ro(registry.systemProgram)]);
    add('2efe77a2baab5945', [number(week)], [ro(city), rw(hill), ro(asset(mint)), rw(funding), signer(registry.feePayer, true), ro(registry.systemProgram), ro(cursor)]);
    return funding;
  };

  if (['stage1_convert_pledge', 'stage1_begin_withdrawal', 'stage1_complete_withdrawal'].includes(intent.kind)) {
    const priced = intent as Extract<Stage1TransactionIntent, { refreshRate?: boolean }>;
    if (priced.refreshRate !== false) {
      const mint = publicKey(priced.mint);
      add('e1281bbd5a27f453', [], [rw(city), rw(asset(mint)), ...provider(mint)]);
    }
  }

  if (intent.kind === 'stage1_claim_transport') {
    reference = publicKey(intent.lookupTable);
    const collect = (ix: TransactionInstruction) => expected.push({ program: ix.programId, data: ix.data, keys: ix.keys });
    if (intent.mode === 'create') {
      const slot = exactU64(intent.recentSlot);
      if (slot > BigInt(Number.MAX_SAFE_INTEGER) || intent.addresses.length < 1 || intent.addresses.length > 11
          || new Set(intent.addresses).size !== intent.addresses.length) reject();
      const [create, address] = AddressLookupTableProgram.createLookupTable({ authority: wallet, payer: wallet, recentSlot: Number(slot) });
      if (!sameKey(address, reference)) reject();
      collect(create);
      collect(AddressLookupTableProgram.extendLookupTable({ lookupTable: address, authority: wallet, payer: wallet, addresses: intent.addresses.map(publicKey) }));
    } else if (intent.mode === 'deactivate') {
      collect(AddressLookupTableProgram.deactivateLookupTable({ lookupTable: reference, authority: wallet }));
    } else if (intent.mode === 'close') {
      collect(AddressLookupTableProgram.closeLookupTable({ lookupTable: reference, authority: wallet, recipient: wallet }));
    } else reject();
  } else if (intent.kind === 'stage1_registration') {
    reference = registration;
    add('a71e21623cbb3b94', [keyBytes(wallet)], [rw(registration), signer(wallet), signer(registry.feePayer, true), ro(registry.systemProgram)]);
  } else if (intent.kind === 'stage1_self_claim') {
    reference = registration;
    const mint = publicKey(intent.mint);
    if (intent.claimType === 'dung') {
      if (!sameKey(mint, registry.dungMint)) reject();
    } else if (intent.claimType === 'cash') {
      if (!sameKey(mint, registry.usdcMint) && intent.mint !== STAGE1_CASH_MINT && !providers[intent.mint]) reject();
    } else reject();
    if (intent.claims.length < 1 || intent.claims.length > 4) reject();
    createAta(mint);
    const count = Buffer.alloc(4); count.writeUInt32LE(intent.claims.length);
    const parts: Uint8Array[] = [keyBytes(wallet), count];
    const remaining: Stage1Meta[] = [];
    const sets = new Set<string>();
    let total = 0n;
    for (const leaf of intent.claims) {
      const hill = publicKey(leaf.hill);
      const index = Buffer.alloc(4);
      if (!Number.isInteger(leaf.index) || leaf.index < 0 || leaf.index > 65535 || leaf.proof.length > 16) reject();
      index.writeUInt32LE(leaf.index);
      const proofLength = Buffer.alloc(4); proofLength.writeUInt32LE(leaf.proof.length);
      total += exactU64(leaf.amountBaseUnits);
      if (total > MAX_U64) reject();
      parts.push(index, number(leaf.amountBaseUnits, true), proofLength);
      for (const node of leaf.proof) {
        if (!/^(0|[1-9][0-9]*)$/u.test(node.sum)) reject();
        const sum = BigInt(node.sum);
        if (sum >= 1n << 128n) reject();
        parts.push(hex(node.hash), u64Le(sum & MAX_U64), u64Le(sum >> 64n));
      }
      let claimSet: PublicKey;
      if (intent.claimType === 'cash') {
        const cash = leaf as Stage1CashLeaf;
        if (!/^-?(0|[1-9][0-9]*)$/u.test(cash.frozenAt) || cash.frozenAt === '-0') reject();
        const timestamp = BigInt(cash.frozenAt);
        if (timestamp < -(1n << 63n) || timestamp >= 1n << 63n) reject();
        const frozen = Buffer.alloc(8); frozen.writeBigInt64LE(timestamp);
        parts.push(number(cash.capBaseUnits, true), frozen, hex(cash.auditHash));
        claimSet = derive('s1v1_claims', keyBytes(hill), keyBytes(mint), number(leaf.week));
      } else {
        const dungLeaf = leaf as Stage1DungLeaf;
        if (dungLeaf.role !== 0 && dungLeaf.role !== 1) reject();
        const dung = derive('s1v1_dung', keyBytes(hill), number(leaf.week));
        claimSet = derive('s1v1_dung_claims', keyBytes(dung), Buffer.from([dungLeaf.role]));
        remaining.push(rw(dung));
      }
      if (sets.has(claimSet.toBase58())) reject();
      sets.add(claimSet.toBase58()); remaining.push(rw(claimSet));
    }
    if (intent.single) {
      if (intent.claims.length !== 1) reject();
      const batch = Buffer.concat(parts);
      const single = [batch.subarray(36, 40), batch.subarray(0, 32), batch.subarray(40)];
      if (intent.claimType === 'cash') {
        add('c09b05588b5182fd', single, [ro(city), rw(asset(mint)), remaining[0], ro(registration), rw(earnings(mint)), rw(ata(wallet, mint, registry)), ro(registry.tokenProgram)]);
      } else {
        add('ba1c8b56d8a8f876', single, [ro(city), ...remaining, rw(derive('s1v1_dung_state')), ro(registration), ro(derive('program_config')), rw(mint), ro(derive('dung_mint_auth')), rw(ata(wallet, mint, registry)), ro(registry.tokenProgram)]);
      }
    } else if (intent.claimType === 'cash') {
      add('b7ea102a587362ad', parts, [ro(city), rw(asset(mint)), ro(registration), rw(earnings(mint)), rw(ata(wallet, mint, registry)), ro(registry.tokenProgram), ...remaining]);
    } else {
      add('b784485ccc8d595a', parts, [ro(city), rw(derive('s1v1_dung_state')), ro(registration), ro(derive('program_config')), rw(mint), ro(derive('dung_mint_auth')), rw(ata(wallet, mint, registry)), ro(registry.tokenProgram), ...remaining]);
    }
  } else {
    const lot = derive('s1v1_lot', keyBytes(wallet), number(intent.depositId));
    reference = lot;
    if (intent.kind === 'stage1_pledge') {
      const hill = publicKey(intent.hill), mint = publicKey(intent.mint);
      const remaining: Stage1Meta[] = [];
      provider(mint);
      if (intent.providerMode === 'bonded') {
        if (intent.backingMints.length !== 0) reject();
        remaining.push(...provider(mint));
      } else if (intent.providerMode === 'prebond') {
        if (intent.backingMints.length > (testPool ? 4 : 3) || !intent.backingMints.includes(intent.mint)
            || new Set(intent.backingMints).size !== intent.backingMints.length) reject();
        for (const entry of intent.backingMints) {
          const backing = publicKey(entry); remaining.push(rw(asset(backing)), ...provider(backing));
        }
      } else reject();
      add('eb2f9cfe0058d48e', [number(intent.depositId), number(intent.amountBaseUnits, true), lock(intent.lockWeeks)],
        [rw(city), rw(hill), ro(publicKey(intent.climb)), rw(asset(mint)), ro(mint), rw(lot), rw(custody(lot)), rw(reserve(lot)), rw(ata(wallet, mint, registry)), signer(wallet, true), ro(registry.tokenProgram), ro(registry.systemProgram), ro(registry.rentSysvar), ...remaining]);
    } else if (intent.kind === 'stage1_cancel_pledge') {
      const mint = publicKey(intent.mint);
      createAta(mint);
      add('28693d7e979934d9', [], [rw(city), rw(publicKey(intent.hill)), rw(lot), rw(asset(mint)), rw(custody(lot)), rw(reserve(lot)), rw(ata(wallet, mint, registry)), signer(wallet), ro(registry.tokenProgram)]);
    } else if (intent.kind === 'stage1_convert_pledge') {
      const mint = publicKey(intent.mint);
      add('a275daef01463ec0', [lock(intent.lockWeeks)], [ro(city), ro(publicKey(intent.hill)), rw(lot), ro(asset(mint)), rw(custody(lot)), rw(reserve(lot)), signer(wallet), ro(registry.tokenProgram), ...provider(mint)]);
    } else {
      const request = derive('s1v1_request', keyBytes(lot), number(intent.requestId));
      reference = request;
      if (intent.kind === 'stage1_withdrawal_notice') {
        add('fb5579cd38c90cb1', [number(intent.requestId), number(intent.basisLamports, true)], [ro(city), rw(publicKey(intent.hill)), rw(lot), rw(request), signer(wallet, true), ro(registry.systemProgram)]);
      } else if (intent.kind === 'stage1_cancel_notice') {
        add('b768b5fa1c80d246', [], [rw(lot), rw(request), signer(wallet)]);
      } else {
        const hill = publicKey(intent.hill), mint = publicKey(intent.mint);
        const funding = fund(hill, mint, intent.week);
        const exit = derive('s1v1_exit', keyBytes(request));
        if (intent.kind === 'stage1_begin_withdrawal') {
          add('6c74f43791619c74', [], [rw(city), rw(hill), rw(lot), rw(request), ro(mint), rw(asset(mint)), rw(custody(lot)), rw(reserve(lot)), rw(earnings(mint)), rw(exit), rw(custody(exit)), rw(reserve(exit)), signer(wallet, true), ro(registry.tokenProgram), ro(registry.systemProgram), ro(registry.rentSysvar), ...provider(mint), rw(funding)]);
        } else {
          createAta(mint);
          add('6b6286834a78ae79', [], [rw(city), rw(hill), rw(exit), rw(request), rw(asset(mint)), rw(custody(exit)), rw(reserve(exit)), rw(earnings(mint)), rw(ata(wallet, mint, registry)), signer(wallet), ro(registry.tokenProgram), ...provider(mint), rw(funding)]);
        }
      }
    }
  }
  if (prepared.pda && prepared.pda !== reference.toBase58()) reject();
  if (transaction.instructions.length !== expected.length) reject();
  const signers = [registry.feePayer], writable = [registry.feePayer];
  expected.forEach((spec, i) => {
    const actual = transaction.instructions[i];
    if (!sameKey(actual.programId, spec.program) || !Buffer.from(actual.data).equals(spec.data) || actual.keys.length !== spec.keys.length) reject();
    spec.keys.forEach((entry, j) => {
      if (!sameKey(actual.keys[j].pubkey, entry.pubkey)) reject();
      if (entry.isSigner) signers.push(entry.pubkey);
      if (entry.isWritable) writable.push(entry.pubkey);
    });
  });
  requireGlobalRoles(transaction, signers, writable);
}

async function validatePreparedTransactionIntentInner(
  prepared: PreparedVaultTransaction,
  intent: PreparedTransactionIntent,
  authenticatedWallet: string,
  testPool?: Stage1TestPool,
): Promise<Transaction> {
  const registry = publicKeyRegistry();
  const wallet = publicKey(authenticatedWallet);
  const forbiddenWallets = keySet(Object.values(registry));
  if (forbiddenWallets.has(wallet.toBase58())) reject();
  const transaction = strictLegacyTransaction(prepared);

  if (prepared.vaultId !== null && prepared.vaultId !== undefined) {
    if (!Number.isSafeInteger(prepared.vaultId) || prepared.vaultId < 0) reject();
    if (
      (intent.kind === 'stake' || intent.kind === 'unstake')
      && prepared.vaultId !== intent.vaultId
    ) {
      reject();
    }
  }

  switch (intent.kind) {
    case 'stage1_claim_transport':
    case 'stage1_cancel_pledge':
    case 'stage1_registration':
    case 'stage1_pledge':
    case 'stage1_withdrawal_notice':
    case 'stage1_cancel_notice':
    case 'stage1_begin_withdrawal':
    case 'stage1_complete_withdrawal':
    case 'stage1_convert_pledge':
    case 'stage1_self_claim':
      validateStage1(transaction, prepared, intent, wallet, registry, testPool);
      break;
    case 'create_vault':
      await validateCreateVault(transaction, prepared, wallet, intent, registry);
      break;
    case 'stake':
      validateStake(transaction, wallet, intent.vaultId, intent.amountBaseUnits, registry);
      break;
    case 'unstake':
      validateUnstake(transaction, wallet, intent.vaultId, intent.lpAmountBaseUnits, registry);
      break;
    case 'balance_add_funds':
      validateBalanceAddFunds(
        transaction,
        prepared,
        wallet,
        intent.asset,
        intent.amountBaseUnits,
        registry,
      );
      break;
    case 'balance_withdraw':
      validateBalanceWithdraw(
        transaction,
        prepared,
        wallet,
        intent.asset,
        intent.amountBaseUnits,
        registry,
      );
      break;
    default:
      reject();
  }

  requireEveryStaticKeyIsUsed(transaction);
  return transaction;
}

export async function validatePreparedTransactionIntent(
  prepared: PreparedVaultTransaction,
  intent: PreparedTransactionIntent,
  authenticatedWallet: string,
  testPool?: Stage1TestPool,
): Promise<Transaction> {
  try {
    return await validatePreparedTransactionIntentInner(prepared, intent, authenticatedWallet, testPool);
  } catch (error) {
    if (error instanceof PreparedTransactionIntentError) throw error;
    throw new PreparedTransactionIntentError();
  }
}

export async function validateAndSignPreparedTransaction<T>(
  prepared: PreparedVaultTransaction,
  intent: PreparedTransactionIntent,
  authenticatedWallet: string,
  sign: (transaction: Transaction) => Promise<T>,
  testPool?: Stage1TestPool,
): Promise<T> {
  const transaction = await validatePreparedTransactionIntent(
    prepared,
    intent,
    authenticatedWallet,
    testPool,
  );
  return sign(transaction);
}

export async function validateAndSignPreparedTransactionBytes<T>(
  prepared: PreparedVaultTransaction,
  intent: PreparedTransactionIntent,
  authenticatedWallet: string,
  sign: (validatedTransaction: string) => Promise<T>,
  testPool?: Stage1TestPool,
): Promise<T> {
  const transaction = await validatePreparedTransactionIntent(
    prepared,
    intent,
    authenticatedWallet,
    testPool,
  );
  const validatedTransaction = Buffer.from(transaction.serialize({
    requireAllSignatures: false,
    verifySignatures: false,
  })).toString('base64');
  return sign(validatedTransaction);
}

/** Resolve from the client's independently configured RPC, never from prepared
 * response addresses. Only the Stage1 fallback admits v0; older flows stay legacy. */
export async function validateStage1VersionedTransaction(
  prepared: PreparedVaultTransaction,
  intent: Extract<Stage1TransactionIntent, { kind: 'stage1_self_claim' }>,
  authenticatedWallet: string,
  resolveLookup: (address: PublicKey) => Promise<AddressLookupTableAccount | null>,
  testPool?: Stage1TestPool,
): Promise<VersionedTransaction> {
  try {
    if (typeof prepared.transaction !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/u.test(prepared.transaction)
        || prepared.transaction.length % 4 !== 0 || !Number.isSafeInteger(prepared.lastValidBlockHeight) || prepared.lastValidBlockHeight <= 0) reject();
    const raw = Buffer.from(prepared.transaction, 'base64');
    if (raw.toString('base64') !== prepared.transaction) reject();
    const tx = VersionedTransaction.deserialize(raw);
    if (raw.length > 1232 || !Buffer.from(tx.serialize()).equals(raw) || tx.version !== 0 || !intent.single
        || tx.message.addressTableLookups.length !== 1 || tx.signatures.length !== tx.message.header.numRequiredSignatures
        || tx.message.recentBlockhash !== prepared.blockhash) reject();
    const wallet = publicKey(authenticatedWallet), registry = publicKeyRegistry();
    if (keySet(Object.values(registry)).has(wallet.toBase58())) reject();
    const tableKey = tx.message.addressTableLookups[0].accountKey;
    const table = await resolveLookup(tableKey);
    if (!table || !sameKey(table.key, tableKey) || !table.isActive() || !table.state.authority?.equals(wallet)) reject();
    const decoded = TransactionMessage.decompile(tx.message, { addressLookupTableAccounts: [table] });
    const all = tx.message.getAccountKeys({ addressLookupTableAccounts: [table] });
    const keys = Array.from({ length: all.length }, (_, i) => all.get(i)!);
    const used = keySet([decoded.payerKey, ...decoded.instructions.flatMap(ix => [ix.programId, ...ix.keys.map(k => k.pubkey)])]);
    if (keySet(keys).size !== keys.length) reject();
    requireSameSet(keySet(keys), used);
    const normalized = new Transaction({ feePayer: decoded.payerKey, recentBlockhash: decoded.recentBlockhash });
    normalized.add(...decoded.instructions);
    validateStage1(normalized, prepared, intent, wallet, registry, testPool);
    const checked = normalized.compileMessage();
    keys.forEach((key, index) => {
      const canonical = checked.accountKeys.findIndex(k => k.equals(key));
      if (canonical < 0 || tx.message.isAccountSigner(index) !== checked.isAccountSigner(canonical)
          || tx.message.isAccountWritable(index) !== checked.isAccountWritable(canonical)) reject();
    });
    return tx;
  } catch { throw new PreparedTransactionIntentError(); }
}

export async function validateAndSignStage1VersionedTransactionBytes<T>(
  prepared: PreparedVaultTransaction,
  intent: Extract<Stage1TransactionIntent, { kind: 'stage1_self_claim' }>,
  wallet: string,
  resolveLookup: (address: PublicKey) => Promise<AddressLookupTableAccount | null>,
  sign: (validatedTransaction: string) => Promise<T>,
  testPool?: Stage1TestPool,
): Promise<T> {
  const tx = await validateStage1VersionedTransaction(prepared, intent, wallet, resolveLookup, testPool);
  return sign(Buffer.from(tx.serialize()).toString('base64'));
}
