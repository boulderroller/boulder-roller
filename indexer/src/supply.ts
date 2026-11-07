import { BorshAccountsCoder } from '@coral-xyz/anchor';
import { Connection, PublicKey } from '@solana/web3.js';
import { config } from './config';
import { ProgramVersionWindow, programVersionWindow } from './program-version-window';
import { observeFinalizedProgramVersion } from './program-version-state';
import { writeDungMintSupply } from './writers/legend';

const PROGRAM_CONFIG_SEED = Buffer.from('program_config');
const U64_MAX = (1n << 64n) - 1n;
const PROGRAM_CONFIG_DISCRIMINATOR = Buffer.from(
  BorshAccountsCoder.accountDiscriminator('ProgramConfig')
);
const PROGRAM_CONFIG_INITIALIZED_OFFSET = 8 + 32 + 32 + 1;
const PROGRAM_CONFIG_VERSION_OFFSET = 8 + 32 + 32;
const PROGRAM_CONFIG_DUNG_MINT_OFFSET = 8 + 32 + 32 + 1 + 1 + 1 + 32;
const PROGRAM_CONFIG_AUTHORITY_PREFIX_SIZE = PROGRAM_CONFIG_DUNG_MINT_OFFSET + 32;

export interface DungMintSupplyObservation {
  amount: string;
  slot: number;
  written: boolean;
}

export interface CanonicalDungMint {
  address: PublicKey;
  programConfigSlot: number;
  programVersion: number;
  stage1Available: boolean;
}

function decodeProgramConfigAuthorityPrefix(data: Buffer): {
  initialized: boolean;
  programVersion: number;
  dungMint: PublicKey;
} {
  if (data.length < PROGRAM_CONFIG_AUTHORITY_PREFIX_SIZE) {
    throw new Error(
      `stable authority prefix requires ${PROGRAM_CONFIG_AUTHORITY_PREFIX_SIZE} bytes, got ${data.length}`
    );
  }
  if (!data.subarray(0, 8).equals(PROGRAM_CONFIG_DISCRIMINATOR)) {
    throw new Error('account discriminator does not identify ProgramConfig');
  }

  const initialized = data[PROGRAM_CONFIG_INITIALIZED_OFFSET];
  if (initialized !== 0 && initialized !== 1) {
    throw new Error(`initialized flag must be 0 or 1, got ${initialized}`);
  }

  return {
    initialized: initialized === 1,
    programVersion: data[PROGRAM_CONFIG_VERSION_OFFSET],
    dungMint: new PublicKey(
      data.subarray(
        PROGRAM_CONFIG_DUNG_MINT_OFFSET,
        PROGRAM_CONFIG_DUNG_MINT_OFFSET + 32
      )
    ),
  };
}

/** Resolve the configured DUNG mint only after checking on-chain ProgramConfig. */
export async function resolveCanonicalDungMint(
  connection: Connection,
  window: ProgramVersionWindow = programVersionWindow
): Promise<CanonicalDungMint> {
  try {
    return await resolveVerifiedCanonicalDungMint(connection, window);
  } catch (error) {
    window.invalidate(error);
    throw error;
  }
}

async function resolveVerifiedCanonicalDungMint(
  connection: Connection,
  window: ProgramVersionWindow
): Promise<CanonicalDungMint> {
  const programId = new PublicKey(config.programId);
  const configuredAddress = new PublicKey(config.dungMintAddress);
  const [programConfigPda] = PublicKey.findProgramAddressSync(
    [PROGRAM_CONFIG_SEED],
    programId
  );
  const response = await connection.getAccountInfoAndContext(
    programConfigPda,
    'finalized'
  );
  const accountInfo = response.value;

  if (!accountInfo) {
    throw new Error('[Supply] ProgramConfig is missing; DUNG mint authority cannot be verified');
  }
  if (!accountInfo.owner.equals(programId)) {
    throw new Error('[Supply] ProgramConfig PDA is not owned by the configured program');
  }

  let authority: ReturnType<typeof decodeProgramConfigAuthorityPrefix>;
  try {
    // Mint authority is in ProgramConfig's original stable prefix. Decode only
    // that prefix so append-only account upgrades do not require unrelated
    // trailing fields to exist before the configured mint can be verified.
    authority = decodeProgramConfigAuthorityPrefix(Buffer.from(accountInfo.data));
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    throw new Error(`[Supply] ProgramConfig could not be decoded: ${reason}`);
  }

  if (!authority.initialized) {
    throw new Error('[Supply] ProgramConfig is not initialized');
  }
  const canonicalAddress = authority.dungMint;
  if (canonicalAddress.equals(PublicKey.default)) {
    throw new Error('[Supply] ProgramConfig DUNG mint is not configured');
  }
  if (!canonicalAddress.equals(configuredAddress)) {
    throw new Error(
      `[Supply] DUNG_MINT_ADDRESS ${configuredAddress.toBase58()} does not match ProgramConfig DUNG mint ${canonicalAddress.toBase58()}`
    );
  }
  if (!Number.isSafeInteger(response.context.slot) || response.context.slot < 0) {
    throw new Error('[Supply] ProgramConfig requires a valid finalized slot');
  }
  const programVersion = await observeFinalizedProgramVersion(connection, authority.programVersion, window);

  return {
    address: canonicalAddress,
    programConfigSlot: response.context.slot,
    programVersion,
    stage1Available: window.stage1Available,
  };
}

export async function readDungMintSupply(
  connection: Connection,
  canonicalMint?: CanonicalDungMint
): Promise<Omit<DungMintSupplyObservation, 'written'>> {
  const mint = canonicalMint ?? await resolveCanonicalDungMint(connection);
  const response = await connection.getTokenSupply(
    mint.address,
    'finalized'
  );
  if (response.value.decimals !== 9) {
    throw new Error(`[Supply] Canonical DUNG mint has ${response.value.decimals} decimals, expected 9`);
  }
  if (!/^\d+$/.test(response.value.amount) || BigInt(response.value.amount) > U64_MAX) {
    throw new Error('[Supply] Canonical DUNG mint returned a non-u64 supply');
  }
  if (!Number.isSafeInteger(response.context.slot) || response.context.slot < 0) {
    throw new Error('[Supply] Canonical DUNG mint requires a valid finalized slot');
  }
  return {
    amount: response.value.amount,
    slot: response.context.slot,
  };
}

export async function refreshDungMintSupply(
  connection: Connection,
  canonicalMint?: CanonicalDungMint
): Promise<DungMintSupplyObservation> {
  const observation = await readDungMintSupply(connection, canonicalMint);
  return {
    ...observation,
    written: await writeDungMintSupply(observation.amount, observation.slot),
  };
}
