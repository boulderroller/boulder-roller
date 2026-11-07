import { Connection } from '@solana/web3.js';
import { COMPATIBILITY_RPC_RETRY_MS, retryTransientRpc } from './rpc-retry';
import {
  resolveCanonicalDungMint,
  type CanonicalDungMint,
} from './supply';

export interface IndexerProgramCompatibility {
  programVersion: number;
  stage1Available: boolean;
  canonicalDungMint: CanonicalDungMint;
}

/** Reread finalized config; upgrades become visible without a redeploy. */
export async function requireIndexerProgramCompatibility(
  connection: Connection
): Promise<IndexerProgramCompatibility> {
  const canonicalDungMint = await retryTransientRpc(
    () => resolveCanonicalDungMint(connection),
    { label: 'startup compatibility', deadline: Date.now() + COMPATIBILITY_RPC_RETRY_MS }
  );
  return {
    programVersion: canonicalDungMint.programVersion,
    stage1Available: canonicalDungMint.stage1Available,
    canonicalDungMint,
  };
}
