import { useCallback, useEffect } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { Buffer } from 'buffer';
import { useAuth } from '../../contexts/AuthContext';
import type { PreparedVaultTransaction } from '../../lib/api';
import {
  validateAndSignPreparedTransaction,
  validateStage1VersionedTransaction,
  type PreparedTransactionIntent,
} from '../../lib/portalTransactionIntent';
import { resolveStage1Lookup, stage1TestPoolFor } from '../../lib/stage1Rpc';
import type { Transaction, VersionedTransaction } from '@solana/web3.js';
import { WalletRuntimeProvider } from './WalletRuntimeProvider';
import type { SignPreparedTransaction } from './WalletTransactionSignerBridge';

interface ExternalWalletTransactionSignerBridgeProps {
  onSignerReady: (signer: SignPreparedTransaction | null) => void;
}

function ExternalWalletTransactionSignerBridgeInner({ onSignerReady }: ExternalWalletTransactionSignerBridgeProps) {
  const { walletAddress } = useAuth();
  const { wallet, connected, connect, publicKey, signTransaction } = useWallet();

  const signPreparedTransaction = useCallback(async (
    prepared: PreparedVaultTransaction,
    intent: PreparedTransactionIntent,
  ): Promise<string> => {
    if (!walletAddress) {
      throw new Error('Authenticated wallet is not ready.');
    }

    const testPool = await stage1TestPoolFor(intent);
    return intent.kind === 'stage1_self_claim' && intent.single
      ? sign(await validateStage1VersionedTransaction(prepared, intent, walletAddress, resolveStage1Lookup, testPool))
      : validateAndSignPreparedTransaction(prepared, intent, walletAddress, sign, testPool);
    async function sign(transaction: Transaction | VersionedTransaction) {
        if (!wallet) {
          throw new Error('Reconnect your Solana wallet to continue.');
        }

        if (!connected) {
          await connect();
        }

        if (!publicKey) {
          throw new Error('Wallet connection is not ready.');
        }

        if (publicKey.toBase58() !== walletAddress) {
          throw new Error('Connected wallet does not match your authenticated wallet.');
        }

        if (!signTransaction) {
          throw new Error('Connected wallet cannot sign transactions.');
        }

        const signedTransaction = await signTransaction(transaction);
        return Buffer.from(signedTransaction.serialize()).toString('base64');
      }

  }, [connect, connected, publicKey, signTransaction, wallet, walletAddress]);

  useEffect(() => {
    onSignerReady(signPreparedTransaction);
    return () => onSignerReady(null);
  }, [onSignerReady, signPreparedTransaction]);

  return null;
}

export default function ExternalWalletTransactionSignerBridge(props: ExternalWalletTransactionSignerBridgeProps) {
  return (
    <WalletRuntimeProvider>
      <ExternalWalletTransactionSignerBridgeInner {...props} />
    </WalletRuntimeProvider>
  );
}
