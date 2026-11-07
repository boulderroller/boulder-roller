import { BorshCoder, BorshAccountsCoder, EventParser } from '@coral-xyz/anchor';
import { PublicKey } from '@solana/web3.js';
import fs from 'fs';
import { config } from './config';
import { isStage1Instruction, programVersionWindow } from './program-version-window';

/**
 * IDL-driven decoder for the boulder_rollers program.
 *
 * All account types are discovered directly from the committed Anchor IDL.
 * Keep this decoder IDL-driven so retired account types disappear when the
 * IDL is regenerated, instead of being preserved by hand-written lists.
 *
 * The decoder matches accounts by their 8-byte Anchor discriminator
 * (sha256("account:<TypeName>")[0..8]) and deserializes using BorshCoder.
 */

// Use `any` for IDL because the TypeScript type definition in @coral-xyz/anchor
// doesn't perfectly match the JSON schema produced by Anchor 0.29.
// The BorshCoder constructor accepts it at runtime regardless.
let _coder: BorshCoder | null = null;
let _idl: any = null;
let _discriminatorMap: Map<string, string> | null = null;
let _accountSizeMap: Map<string, number | null> | null = null;

/**
 * Load the IDL from disk and initialize the BorshCoder.
 */
export function loadIdl(): any {
  if (_idl) return _idl;
  const raw = fs.readFileSync(config.idlPath, 'utf-8');
  _idl = JSON.parse(raw);
  console.log(`[Decoder] Loaded IDL: ${_idl.name} v${_idl.version}`);
  console.log(`[Decoder] Account types: ${(_idl.accounts || []).map((a: any) => a.name).join(', ')}`);
  console.log(`[Decoder] Event types: ${(_idl.events || []).map((e: any) => e.name).join(', ')}`);
  return _idl;
}

/**
 * Get the BorshCoder (lazy-initialized).
 */
export function getCoder(): BorshCoder {
  if (_coder) return _coder;
  const idl = loadIdl();
  _coder = new BorshCoder(idl);
  return _coder;
}

/**
 * Get the expected encoded size for an account type, including discriminator.
 * Returns null when the size cannot be derived from the IDL.
 */
export function getExpectedAccountSize(accountName: string): number | null {
  if (_accountSizeMap) {
    return _accountSizeMap.get(accountName) ?? null;
  }

  const idl = loadIdl();
  const coder = getCoder();
  _accountSizeMap = new Map();

  for (const accountDef of idl.accounts || []) {
    try {
      _accountSizeMap.set(accountDef.name, coder.accounts.size(accountDef));
    } catch {
      _accountSizeMap.set(accountDef.name, null);
    }
  }

  return _accountSizeMap.get(accountName) ?? null;
}

/**
 * Build a map of discriminator hex -> account type name.
 * The discriminator is sha256("account:<TypeName>")[0..8].
 */
function getDiscriminatorMap(): Map<string, string> {
  if (_discriminatorMap) return _discriminatorMap;

  const idl = loadIdl();
  _discriminatorMap = new Map();

  if (!idl.accounts) return _discriminatorMap;

  for (const accountDef of idl.accounts) {
    const disc = BorshAccountsCoder.accountDiscriminator(accountDef.name);
    const hexKey = Buffer.from(disc).toString('hex');
    _discriminatorMap.set(hexKey, accountDef.name);
  }

  console.log(`[Decoder] Built discriminator map for ${_discriminatorMap.size} account types`);
  return _discriminatorMap;
}

export interface DecodedAccount {
  /** The IDL account type name (e.g., "Vault", "UserState") */
  type: string;
  /** The decoded fields as a JS object */
  fields: Record<string, any>;
}

const LEGACY_LOCAL_LEGEND_ACCOUNT_SIZE = 122;
const CURRENT_LOCAL_LEGEND_ACCOUNT_SIZE = 123;
const LOCAL_LEGEND_IS_ACTIVE_OFFSET = 120;
const LOCAL_LEGEND_IS_BOOTSTRAP_OFFSET = 121;

function isCanonicalBooleanByte(value: number): boolean {
  return value === 0 || value === 1;
}

function decodeLegacyLocalLegendAccount(data: Buffer): DecodedAccount | null {
  if (data.length !== LEGACY_LOCAL_LEGEND_ACCOUNT_SIZE) return null;
  if (!isCanonicalBooleanByte(data[LOCAL_LEGEND_IS_ACTIVE_OFFSET])) return null;

  let offset = 8;
  const vaultId = data.readBigUInt64LE(offset);
  offset += 8;
  const holder = new PublicKey(data.subarray(offset, offset + 32));
  offset += 32;
  const electionPeriod = data.readBigUInt64LE(offset);
  offset += 8;
  const termStartEpoch = data.readBigUInt64LE(offset);
  offset += 8;
  const termEndEpoch = data.readBigUInt64LE(offset);
  offset += 8;
  const completionsAtElection = data.readUInt32LE(offset);
  offset += 4;
  const runnerUp = new PublicKey(data.subarray(offset, offset + 32));
  offset += 32;
  const runnerUpCompletions = data.readUInt32LE(offset);
  offset += 4;
  const totalEarned = data.readBigUInt64LE(offset);
  offset += 8;
  const isActive = data[offset] === 1;
  offset += 1;
  const isBootstrap = isActive && electionPeriod === 0n && completionsAtElection === 0;
  const bump = data[offset];

  return {
    type: 'LocalLegend',
    fields: {
      vaultId,
      holder,
      electionPeriod,
      termStartEpoch,
      termEndEpoch,
      completionsAtElection,
      runnerUp,
      runnerUpCompletions,
      totalEarned,
      isActive,
      isBootstrap,
      bump,
    },
  };
}

/**
 * Decode an account's data buffer using the IDL.
 * Returns the account type and decoded fields, or null if unknown.
 */
export function decodeAccount(data: Buffer): DecodedAccount | null {
  if (data.length < 8) return null;

  const discHex = data.subarray(0, 8).toString('hex');
  const map = getDiscriminatorMap();
  const typeName = map.get(discHex);

  if (!typeName) {
    return null; // Unknown discriminator -- not a boulder_rollers account type
  }

  // Stage 1 bytes are not a public read model before the version advance.
  if (typeName.startsWith('Stage1') && !programVersionWindow.stage1Available) return null;

  if (typeName === 'LocalLegend') {
    if (data.length === LEGACY_LOCAL_LEGEND_ACCOUNT_SIZE) {
      return decodeLegacyLocalLegendAccount(data);
    }
    if (data.length !== CURRENT_LOCAL_LEGEND_ACCOUNT_SIZE) {
      console.error(
        `[Decoder] Failed to decode LocalLegend: unexpected account length ${data.length}`
      );
      return null;
    }
    if (
      !isCanonicalBooleanByte(data[LOCAL_LEGEND_IS_ACTIVE_OFFSET])
      || !isCanonicalBooleanByte(data[LOCAL_LEGEND_IS_BOOTSTRAP_OFFSET])
    ) {
      console.error('[Decoder] Failed to decode LocalLegend: noncanonical boolean byte');
      return null;
    }
  }

  try {
    const coder = getCoder();
    // This fixed layout appends an eight-byte unminted amount. Anchor's BN
    // decoder accepts a missing/partial integer, so reject old or short data.
    if (typeName === 'Stage1DungMint' && data.length !== getExpectedAccountSize(typeName)) return null;
    if (typeName === 'Stage1SettlementCursor') {
      // The sole trailing Vec reserves 26 complete entries on chain. Anchor's
      // size() substitutes one byte for a Vec, and its BN decoder can accept
      // truncated integers; prove the exact allocation/count before decoding.
      const header = getExpectedAccountSize(typeName)! + 3;
      const carry = loadIdl().types.find((type: any) => type.name === 'Stage1CarriedHold');
      const entry = coder.accounts.size(carry) - 8;
      if (data.length !== header + 26 * entry || data.readUInt32LE(header - 4) > 26) return null;
    }
    const decoded = coder.accounts.decode(typeName, data);
    if (typeName === 'Stage1ClaimSet' || typeName === 'Stage1DungClaimSet') {
      // The IDL describes the fixed Borsh header. Version 2 uses only the prepaid
      // index bitmap. Publisher allocation owns person uniqueness.
      const header = getExpectedAccountSize(typeName)!;
      const leaves = decoded.leafCount;
      if (decoded.storageVersion !== 2 || !isCanonicalBooleanByte(data[header - (typeName === 'Stage1ClaimSet' ? 1 : 33)])
          || !Number.isInteger(leaves) || leaves < 0 || leaves > 65536
          || decoded.claimedCount > leaves || decoded.paid.gt(decoded.total)) return null;
      const bytes = header + Math.ceil(leaves / 8);
      if (decoded.sealed) {
        if (data.length !== bytes) return null;
      } else if (data.length < header || data.length > bytes || decoded.claimedCount !== 0
          || !decoded.paid.isZero() || data.subarray(header).some(b => b !== 0)) return null;
    }
    return { type: typeName, fields: decoded as Record<string, any> };
  } catch (err) {
    console.error(`[Decoder] Failed to decode ${typeName}:`, err);
    return null;
  }
}

/**
 * Identify the account type from a data buffer without full decoding.
 */
export function identifyAccountType(data: Buffer): string | null {
  if (data.length < 8) return null;
  const discHex = data.subarray(0, 8).toString('hex');
  return getDiscriminatorMap().get(discHex) || null;
}

/**
 * Decode a program instruction from its data buffer.
 */
export function decodeInstruction(data: Buffer): { name: string; data: Record<string, any> } | null {
  try {
    const coder = getCoder();
    const decoded = coder.instruction.decode(data);
    if (!decoded) return null;
    if (isStage1Instruction(decoded.name) && !programVersionWindow.stage1Available) return null;
    return { name: decoded.name, data: decoded.data as Record<string, any> };
  } catch {
    return null;
  }
}

/**
 * Parse events from transaction log messages.
 * In Anchor 0.29, EventParser.parseLogs returns a generator.
 */
export function decodeEvents(logs: string[]): Array<{ name: string; data: Record<string, any> }> {
  const programId = new PublicKey(config.programId);
  const coder = getCoder();
  const parser = new EventParser(programId, coder);
  const events: Array<{ name: string; data: Record<string, any> }> = [];

  // Anchor 0.29: parseLogs returns a generator
  const generator = parser.parseLogs(logs);
  for (const event of generator) {
    if (event.name.startsWith('Stage1') && !programVersionWindow.stage1Available) continue;
    events.push({ name: event.name, data: event.data as Record<string, any> });
  }

  return events;
}

/**
 * Helper: Convert a PublicKey field to base58 string.
 * Handles both PublicKey objects and raw byte arrays.
 */
export function pubkeyToString(value: any): string {
  if (!value) return '';
  if (value instanceof PublicKey) return value.toBase58();
  if (typeof value === 'string') return value;
  if (Buffer.isBuffer(value) || Array.isArray(value)) {
    return new PublicKey(value).toBase58();
  }
  return String(value);
}

/**
 * Helper: Convert a byte array field to hex string.
 */
export function bytesToHex(value: number[] | Buffer | Uint8Array): string {
  return Buffer.from(value).toString('hex');
}

/**
 * Helper: Check if a PublicKey is the default (all zeros).
 */
export function isDefaultPubkey(value: any): boolean {
  const str = pubkeyToString(value);
  return str === PublicKey.default.toBase58() || str === '11111111111111111111111111111111';
}

/**
 * Safely convert a BN/u64/bigint value to string for Postgres NUMERIC storage.
 * Anchor BorshCoder decodes u64 fields as BN.js objects.
 * Number() loses precision for values > 2^53. toString() is exact.
 */
export function bnToString(value: any): string {
  if (value === null || value === undefined) return '0';
  if (typeof value === 'bigint') return value.toString();
  if (value.toString && typeof value !== 'string' && typeof value !== 'number') return value.toString();
  return String(value);
}

/**
 * Safely convert a decoded small integer field to a finite JS integer.
 * Some partially populated legacy accounts can surface undefined/null here,
 * and raw Number(...) would become NaN and break Postgres integer writes.
 */
export function safeInt(value: any, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
}

/**
 * Get the account metadata for a specific instruction from the IDL.
 * Returns an array of { name, isMut, isSigner } in positional order.
 * Used to label instruction accounts in transaction decoding.
 */
export function getInstructionAccountMeta(
  instructionName: string
): Array<{ name: string; isMut: boolean; isSigner: boolean }> | null {
  const idl = loadIdl();
  const ixDef = (idl.instructions || []).find(
    (ix: any) => ix.name === instructionName
  );
  if (!ixDef) return null;
  return ixDef.accounts;
}

/**
 * List all known account type names from the IDL.
 */
export function getAccountTypeNames(): string[] {
  const idl = loadIdl();
  return (idl.accounts || []).map((a: any) => a.name);
}
