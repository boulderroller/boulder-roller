import { useMemo, ReactNode } from 'react';
import { ConnectionProvider, WalletProvider } from '@solana/wallet-adapter-react';
import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom';
import { SolflareWalletAdapter } from '@solana/wallet-adapter-solflare';
import { SOLANA_RPC_URL } from '../lib/solana';

interface WalletContextProviderProps {
  children: ReactNode;
}

function shouldUseExplicitMobileWalletAdapters(): boolean {
  if (typeof navigator === 'undefined') return false;

  return /\b(android|iphone|ipad|ipod)\b/i.test(navigator.userAgent);
}

export function WalletContextProvider({ children }: WalletContextProviderProps) {
  // Desktop extensions register via Wallet Standard. Keep explicit adapters
  // only for mobile deeplinks, where Wallet Standard is not always present.
  const wallets = useMemo(
    () => (
      shouldUseExplicitMobileWalletAdapters()
        ? [new PhantomWalletAdapter(), new SolflareWalletAdapter()]
        : []
    ),
    [],
  );

  return (
    <ConnectionProvider endpoint={SOLANA_RPC_URL}>
      <WalletProvider wallets={wallets} autoConnect>
        {children}
      </WalletProvider>
    </ConnectionProvider>
  );
}
