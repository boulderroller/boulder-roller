export type SolanaExplorerKind = 'account' | 'tx';

export const DEFAULT_SOLANA_NETWORK =
  import.meta.env.VITE_SOLANA_NETWORK || 'devnet';

export function solanaExplorerUrl(
  kind: SolanaExplorerKind,
  value: string,
  network = DEFAULT_SOLANA_NETWORK,
): string {
  const encodedValue = encodeURIComponent(value);
  const path = kind === 'tx' ? `tx/${encodedValue}` : `address/${encodedValue}`;
  const cluster = network === 'mainnet-beta' ? '' : `?cluster=${encodeURIComponent(network)}`;
  return `https://explorer.solana.com/${path}${cluster}`;
}
