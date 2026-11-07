import { lazy, Suspense, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import type { PreparedVaultTransaction } from '../../lib/api';
import type { PreparedTransactionIntent } from '../../lib/portalTransactionIntent';

export type SignPreparedTransaction = (
  prepared: PreparedVaultTransaction,
  intent: PreparedTransactionIntent,
) => Promise<string>;

interface WalletTransactionSignerBridgeProps {
  enabled?: boolean;
  onSignerReady: (signer: SignPreparedTransaction | null) => void;
}

const ExternalWalletTransactionSignerBridge = lazy(() => import('./ExternalWalletTransactionSignerBridge'));
const PrivyWalletTransactionSignerBridge = lazy(() => import('./PrivyWalletTransactionSignerBridge'));

export function WalletTransactionSignerBridge({ enabled = true, onSignerReady }: WalletTransactionSignerBridgeProps) {
  const { authMethod, isLoading } = useAuth();

  useEffect(() => {
    if (!enabled || isLoading || authMethod === null) {
      onSignerReady(null);
    }
  }, [authMethod, enabled, isLoading, onSignerReady]);

  if (!enabled || isLoading || authMethod === null) {
    return null;
  }

  if (authMethod === 'wallet') {
    return (
      <Suspense fallback={null}>
        <ExternalWalletTransactionSignerBridge onSignerReady={onSignerReady} />
      </Suspense>
    );
  }

  if (authMethod === 'privy') {
    return (
      <Suspense fallback={null}>
        <PrivyWalletTransactionSignerBridge onSignerReady={onSignerReady} />
      </Suspense>
    );
  }

  return null;
}
