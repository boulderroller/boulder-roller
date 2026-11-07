import { Connection } from '@solana/web3.js';
import { config } from './config';
import { persistProgramVersion } from './program-version-store';
import { ProgramVersionWindow, programVersionWindow, requireCompatibleProgramVersion } from './program-version-window';

/** Validate the window before persistence; expose capability only after it. */
export async function observeFinalizedProgramVersion(
  connection: Connection,
  observed: unknown,
  window: ProgramVersionWindow = programVersionWindow
): Promise<number> {
  try {
    const version = requireCompatibleProgramVersion(observed);
    const genesis = await connection.getGenesisHash();
    if (typeof genesis !== 'string' || !genesis) throw new Error('RPC genesis hash is missing');
    const highest = await persistProgramVersion(genesis, config.programId, version);
    window.observe(highest);
    return window.observe(version);
  } catch (error) {
    window.invalidate(error);
    throw error;
  }
}
