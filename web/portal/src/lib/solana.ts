const DEFAULT_DEVNET_ADDRESSES = {
  programs: {
    boulder_rollers: 'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH',
  },
  mints: {
    cal_mint: {
      address: '4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh',
    },
    dung_mint: {
      address: 'CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk',
    },
  },
} as const;

const DEFAULT_BOULDER_ROLLERS_PROGRAM_ID =
  DEFAULT_DEVNET_ADDRESSES.programs.boulder_rollers;
const DEFAULT_CAL_MINT_ADDRESS = DEFAULT_DEVNET_ADDRESSES.mints.cal_mint.address;
const DEFAULT_DUNG_MINT_ADDRESS = DEFAULT_DEVNET_ADDRESSES.mints.dung_mint.address;
const DEFAULT_SOLANA_RPC = 'https://api.devnet.solana.com';

export const BOULDER_ROLLERS_PROGRAM_ID =
  import.meta.env.VITE_BOULDER_ROLLERS_PROGRAM_ID ||
  DEFAULT_BOULDER_ROLLERS_PROGRAM_ID;

export const SOLANA_RPC_URL =
  import.meta.env.VITE_SOLANA_RPC ||
  import.meta.env.VITE_SOLANA_RPC_URL ||
  DEFAULT_SOLANA_RPC;

export const CAL_MINT_ADDRESS =
  import.meta.env.VITE_CAL_MINT_ADDRESS ||
  DEFAULT_CAL_MINT_ADDRESS;

export const DUNG_MINT_ADDRESS =
  import.meta.env.VITE_DUNG_MINT_ADDRESS ||
  DEFAULT_DUNG_MINT_ADDRESS;

export type SolanaNetwork = 'devnet' | 'testnet' | 'mainnet-beta';

export const SOLANA_NETWORK: SolanaNetwork =
  (import.meta.env.VITE_SOLANA_NETWORK as SolanaNetwork) || 'devnet';

export function solanaExplorerUrl(
  hashOrAddress: string,
  type: 'tx' | 'address' = 'tx',
): string {
  const base = `https://explorer.solana.com/${type}/${hashOrAddress}`;
  return SOLANA_NETWORK === 'mainnet-beta' ? base : `${base}?cluster=${SOLANA_NETWORK}`;
}
