import { lazy, Suspense, useCallback, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { usePrivySolanaBridge } from '../../contexts/PrivyContext';
import type { PreparedVaultTransaction } from '../../lib/api';
import {
  validateAndSignPreparedTransactionBytes,
  validateAndSignStage1VersionedTransactionBytes,
  type PreparedTransactionIntent,
} from '../../lib/portalTransactionIntent';
import { resolveStage1Lookup, stage1TestPoolFor } from '../../lib/stage1Rpc';
import { SOLANA_NETWORK } from '../../lib/solana';
import type { SignPreparedTransaction } from './WalletTransactionSignerBridge';

const PrivySolanaBridgeProvider = lazy(() => import('../../contexts/PrivySolanaBridgeProvider'));

const PRIVY_SOLANA_CHAIN =
  SOLANA_NETWORK === 'mainnet-beta' ? 'solana:mainnet' : `solana:${SOLANA_NETWORK}` as const;

interface PrivyWalletTransactionSignerBridgeProps {
  onSignerReady: (signer: SignPreparedTransaction | null) => void;
}

function PrivyWalletTransactionSignerBridgeInner({ onSignerReady }: PrivyWalletTransactionSignerBridgeProps) {
  const { walletAddress } = useAuth();
  const privySolana = usePrivySolanaBridge();

  const signPreparedTransaction = useCallback(async (
    prepared: PreparedVaultTransaction,
    intent: PreparedTransactionIntent,
  ): Promise<string> => {
    if (!walletAddress) {
      throw new Error('Rider wallet is not ready yet.');
    }

    const ownerWallet = walletAddress;
    const testPool = await stage1TestPoolFor(intent);
    return intent.kind === 'stage1_self_claim' && intent.single
      ? validateAndSignStage1VersionedTransactionBytes(prepared, intent, walletAddress, resolveStage1Lookup, sign, testPool)
      : validateAndSignPreparedTransactionBytes(prepared, intent, walletAddress, sign, testPool);
    async function sign(validatedTransaction: string) {
      if (!privySolana.enabled || !privySolana.ready) throw new Error('Embedded wallet signing is unavailable in this environment.');
      return privySolana.signPreparedTransaction(validatedTransaction, ownerWallet, PRIVY_SOLANA_CHAIN);
    }

  }, [privySolana, walletAddress]);

  useEffect(() => {
    onSignerReady(signPreparedTransaction);
    return () => onSignerReady(null);
  }, [onSignerReady, signPreparedTransaction]);

  return null;
}

export default function PrivyWalletTransactionSignerBridge(props: PrivyWalletTransactionSignerBridgeProps) {
  return (
    <Suspense fallback={null}>
      <PrivySolanaBridgeProvider>
        <PrivyWalletTransactionSignerBridgeInner {...props} />
      </PrivySolanaBridgeProvider>
    </Suspense>
  );
}
