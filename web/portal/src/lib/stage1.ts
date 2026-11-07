import { formatBaseUnits } from './tokenAmounts.ts';
import { stage1Copy as copy } from './stage1Copy.ts';

// Composed release contract shared by the gated reads and actions.
export function stage1Live(status: unknown): boolean {
  return !!status && typeof status === 'object' && (status as { stage1?: { live?: unknown } }).stage1?.live === true;
}
export function stage1ActionsLive(status: unknown): boolean {
  return stage1Live(status) && (status as { stage1?: { actions?: unknown } }).stage1?.actions === true;
}
export function exactUnits(value: unknown): value is string {
  return typeof value === 'string' && /^(0|[1-9]\d*)$/.test(value);
}
// Stage 1 devnet test USDC: the devnet city's admitted cash asset (6 decimals, legacy token program).
export const STAGE1_CASH_MINT = '932CwEMTWHDY1BEkV66DKDgngeEypU3JmybWBu4vMh1e';
// Release-pinned provider identities and denominations; no response can rename a token.
export const STAGE1_MINTS: Record<string, { symbol: string; decimals: number }> = {
  J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn: { symbol: 'jitoSOL', decimals: 9 },
  mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So: { symbol: 'mSOL', decimals: 9 },
  jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v: { symbol: 'JupSOL', decimals: 9 },
  DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne: { symbol: 'USDC', decimals: 6 },
  EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v: { symbol: 'USDC', decimals: 6 },
  [STAGE1_CASH_MINT]: { symbol: 'USDC', decimals: 6 },
  CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk: { symbol: 'DUNG', decimals: 9 },
};
export function stage1Amount(row: { amount?: unknown; kind?: string; mint?: string }): string | null {
  if (!exactUnits(row.amount) || BigInt(row.amount) >= 1n << 64n) return null;
  const token = row.mint ? STAGE1_MINTS[row.mint] : row.kind === 'dung' ? { symbol: 'DUNG', decimals: 9 } : null;
  if (token) return `${formatBaseUnits(row.amount, token.decimals, token.decimals)} ${token.symbol}`;
  return row.mint ? `${formatBaseUnits(row.amount, 0, 0)} ${copy.baseUnits} · ${copy.unknownMint}` : null;
}
export function stage1Backing(assets: Array<{ backingLamports?: unknown; backingEligible?: boolean }>): string | null {
  const backing = assets.filter(a => a.backingEligible !== false);
  if (!backing.length || backing.some(a => !exactUnits(a.backingLamports))) return null;
  return backing.reduce((n, a) => n + BigInt(a.backingLamports as string), 0n).toString();
}

export interface Stage1Pay {
  climbName?: string; hill: string; week: string | number; mint: string; amount?: string; kind?: string;
  signature?: string; recipient?: string; chainSlot?: number;
}
export interface Stage1Payments { paid: Stage1Pay[]; pending: Stage1Pay[]; hasMore?: boolean }
export interface Stage1Registration {
  registration: { person: string; recipient: string; registeredAt: string } | null;
  held: Stage1Pay[];
}
export interface Stage1Pledge {
  climbName?: string; address: string; depositId?: string; hill: string; mint: string; units?: string; basisLamports?: string;
  lockWeeks?: number; lockEnd?: string; founding?: boolean; converted?: boolean;
  cancelled?: boolean; exiting?: boolean; returnedUnits?: string;
  eligibility?: Record<string, { refreshRate: boolean }>; eligibilityWeek?: string; pendingRequest?: string; exitRequest?: string; sequence?: string; assetSlot?: number;
  hillState?: Stage1HillState; cityState?: Stage1CityState; assetState?: Stage1Asset; chainTime?: string; chainEpoch?: string;
  withdrawals: Stage1Withdrawal[];
}
export interface Stage1Bonding {
  climb?: string; hillState?: Stage1HillState; cityState?: Stage1CityState; chainTime?: string; chainEpoch?: string; hill: string; bonded?: boolean; foundingCount?: string; lineLamports?: string; week?: number;
  assets: Array<{ config?: Stage1Asset; mint: string; backingLamports?: string; backingEligible?: boolean; weekPool?: { available?: string; pool?: string; published?: boolean } }>;
  split?: { everyRiderByAscents?: number; topTen?: number; localLegend?: number };
}

export function stage1StakingAssets(bonding?: Stage1Bonding) {
  return bonding?.cityState?.intakePaused === false
    ? bonding.assets.filter(a => a.config?.enabled && [2, 3, 4, 5].includes(a.config.adapter) && STAGE1_MINTS[a.mint]) : [];
}

export interface Stage1Withdrawal { address: string; parentDepositId?: string; data: { requestId?: string; lot?: string; exitLot?: string; basisLamports?: string; noticeAt?: string; eligibleAt?: string; status?: number } }
export interface Stage1HillState { bonded: boolean; foundingCutoff: string; foundingFreshSlots: number; assetLots: string[] }
export interface Stage1CityState { seasonAnchor: string; providerSlots: number; assetCount: number; intakePaused?: boolean }
export interface Stage1Asset { mint: string; slot: number; adapter: number; enabled: boolean; admittedEpoch: string; lastFreshUntil: string; admittedNumerator: string; admittedDenominator: string; staleSince?: string }

export function registerStage1TestMint(mint: unknown) {
  if (typeof mint === 'string' && /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(mint) && !STAGE1_MINTS[mint]) STAGE1_MINTS[mint] = { symbol: copy.testPool, decimals: 9 };
}
