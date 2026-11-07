/**
 * Solana read helpers for mobile identity surfaces.
 *
 * These helpers are intentionally read-only. Transaction construction stays
 * in dedicated wallet modules; UI surfaces use this file to fetch on-chain
 * truth directly instead of trusting backend projections for balances.
 */

import { Connection, PublicKey } from '@solana/web3.js';

import { CAL_MINT, SOLANA_RPC_URL } from '../constants/config';
import { fetchProgramVersionGate } from './programVersion';

export interface TokenBalance {
  rawAmount: string;
  decimals: number;
  uiAmountString: string;
  accountCount: number;
}

interface ParsedTokenAccountLike {
  account: {
    data: {
      parsed?: {
        info?: {
          tokenAmount?: {
            amount?: string;
            decimals?: number;
          };
        };
      };
    };
  };
}

export function createSolanaConnection(): Connection {
  return new Connection(SOLANA_RPC_URL, 'confirmed');
}

export async function requireCompatibleProgram(connection: Connection): Promise<void> {
  const gate = await fetchProgramVersionGate(connection);
  if (gate.verifyEnabled) return;

  const expected = `0x${gate.expectedVersion.toString(16).padStart(2, '0')}`;
  if (gate.status === 'mismatch' && gate.observedVersion != null) {
    const observed = `0x${gate.observedVersion.toString(16).padStart(2, '0')}`;
    throw new Error(
      `ProgramConfig version mismatch: expected ${expected}, got ${observed}`,
    );
  }
  throw new Error(`ProgramConfig ${expected} compatibility is unavailable`);
}

function scaleForDecimals(decimals: number): bigint {
  let scale = 1n;
  for (let i = 0; i < decimals; i += 1) {
    scale *= 10n;
  }
  return scale;
}

export function formatTokenAmount(rawAmount: string | bigint, decimals: number): string {
  const raw = typeof rawAmount === 'bigint' ? rawAmount : BigInt(rawAmount);
  const scale = scaleForDecimals(decimals);
  const whole = raw / scale;
  const fraction = raw % scale;

  if (fraction === 0n) return whole.toString();

  const fractionPadded = fraction.toString().padStart(decimals, '0');
  const fractionTrimmed = fractionPadded.replace(/0+$/, '');
  return `${whole.toString()}.${fractionTrimmed}`;
}

export function sumParsedTokenAccounts(accounts: ParsedTokenAccountLike[]): TokenBalance {
  let rawTotal = 0n;
  let decimals: number | null = null;
  let accountCount = 0;

  for (const item of accounts) {
    const tokenAmount = item.account.data.parsed?.info?.tokenAmount;
    if (!tokenAmount?.amount || tokenAmount.decimals == null) continue;

    if (decimals == null) {
      decimals = tokenAmount.decimals;
    } else if (decimals !== tokenAmount.decimals) {
      throw new Error('Token accounts for one mint reported mixed decimals');
    }

    rawTotal += BigInt(tokenAmount.amount);
    accountCount += 1;
  }

  const resolvedDecimals = decimals ?? 0;
  return {
    rawAmount: rawTotal.toString(),
    decimals: resolvedDecimals,
    uiAmountString: formatTokenAmount(rawTotal, resolvedDecimals),
    accountCount,
  };
}

export async function getTokenBalanceForOwner(params: {
  owner: string;
  mint: string;
  connection?: Connection;
}): Promise<TokenBalance> {
  const connection = params.connection ?? createSolanaConnection();
  const owner = new PublicKey(params.owner);
  const mint = new PublicKey(params.mint);
  const accounts = await connection.getParsedTokenAccountsByOwner(owner, { mint });
  return sumParsedTokenAccounts(accounts.value as ParsedTokenAccountLike[]);
}

export async function getCalBalance(
  owner: string,
  connection?: Connection,
): Promise<TokenBalance> {
  const resolvedConnection = connection ?? createSolanaConnection();
  await requireCompatibleProgram(resolvedConnection);
  return getTokenBalanceForOwner({
    owner,
    mint: CAL_MINT,
    connection: resolvedConnection,
  });
}
