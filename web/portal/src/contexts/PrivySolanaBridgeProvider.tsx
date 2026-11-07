import { type ReactNode, useMemo } from 'react';
import {
  useSignTransaction as usePrivySolanaSignTransaction,
  useWallets as usePrivySolanaWallets,
} from '@privy-io/react-auth/solana';
import { Buffer } from 'buffer';
import {
  PrivySolanaBridgeContext,
  type PrivySolanaBridgeState,
} from './PrivyContext';

export default function PrivySolanaBridgeProvider({ children }: { children: ReactNode }) {
  const { ready, wallets } = usePrivySolanaWallets();
  const { signTransaction } = usePrivySolanaSignTransaction();

  const value = useMemo<PrivySolanaBridgeState>(() => ({
    enabled: true,
    ready,
    signPreparedTransaction: async (preparedTransaction: string, walletAddress: string, chain: string) => {
      if (!ready) {
        throw new Error('Rider wallet connection is still initializing.');
      }

      const wallet = wallets.find((candidate) => candidate.address === walletAddress);
      if (!wallet) {
        throw new Error('Reconnect your embedded wallet to continue.');
      }

      const { signedTransaction } = await signTransaction({
        transaction: Buffer.from(preparedTransaction, 'base64'),
        wallet,
        chain,
      });

      return Buffer.from(signedTransaction).toString('base64');
    },
  }), [ready, signTransaction, wallets]);

  return (
    <PrivySolanaBridgeContext.Provider value={value}>
      {children}
    </PrivySolanaBridgeContext.Provider>
  );
}
