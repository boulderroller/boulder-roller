import { Buffer } from 'buffer';
import { Connection, PublicKey } from '@solana/web3.js';

import { SOLANA_PROGRAM_ID } from '../constants/config';
import { CURRENT_PROGRAM_VERSION } from '../generated/boulderRollersProgramVersion';

const PROGRAM_CONFIG_VERSION_OFFSET = 72;
const PROGRAM_CONFIG_INITIALIZED_OFFSET = 73;
const PROGRAM_CONFIG_STABLE_PREFIX_SIZE = 75;
const PROGRAM_CONFIG_DISCRIMINATOR = Buffer.from('c4d25ae790958c3f', 'hex');

export type ProgramVersionStatus = 'compatible' | 'mismatch' | 'unavailable';

export interface ProgramVersionGate {
  status: ProgramVersionStatus;
  expectedVersion: number;
  observedVersion: number | null;
  verifyEnabled: boolean;
}

export function assessProgramVersion(
  observedVersion: number | null,
  expectedVersion: number = CURRENT_PROGRAM_VERSION,
): ProgramVersionGate {
  if (observedVersion == null) {
    return {
      status: 'unavailable',
      expectedVersion,
      observedVersion: null,
      verifyEnabled: false,
    };
  }
  const compatible = observedVersion === expectedVersion;
  return {
    status: compatible ? 'compatible' : 'mismatch',
    expectedVersion,
    observedVersion,
    verifyEnabled: compatible,
  };
}

export function decodeProgramConfigVersion(data: Uint8Array): number {
  if (data.length < PROGRAM_CONFIG_STABLE_PREFIX_SIZE) {
    throw new Error('ProgramConfig stable prefix is truncated');
  }
  return data[PROGRAM_CONFIG_VERSION_OFFSET];
}

export async function fetchProgramVersionGate(
  connection: Connection,
): Promise<ProgramVersionGate> {
  try {
    const programId = new PublicKey(SOLANA_PROGRAM_ID);
    const [programConfig] = PublicKey.findProgramAddressSync(
      [Buffer.from('program_config')],
      programId,
    );
    const account = await connection.getAccountInfo(programConfig, 'finalized');
    if (!account) return assessProgramVersion(null);
    if (!account.owner.equals(programId)) {
      return assessProgramVersion(null);
    }
    const data = Buffer.from(account.data);
    if (!data.subarray(0, 8).equals(PROGRAM_CONFIG_DISCRIMINATOR)) {
      return assessProgramVersion(null);
    }
    if (data[PROGRAM_CONFIG_INITIALIZED_OFFSET] !== 1) {
      return assessProgramVersion(null);
    }
    return assessProgramVersion(decodeProgramConfigVersion(data));
  } catch {
    return assessProgramVersion(null);
  }
}
