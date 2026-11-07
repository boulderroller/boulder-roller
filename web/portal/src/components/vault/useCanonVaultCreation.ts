import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  api,
  type CreateVaultResponse,
  type VaultCreationPaymentMethod,
} from '../../lib/api';
import type { SignPreparedTransaction } from '../auth/WalletTransactionSignerBridge';
import { createClientRequestId } from '../../lib/clientRequestId';
import { queryKeys } from '../../lib/queryKeys';

export type CanonVaultCreationPhase =
  | 'idle'
  | 'preparing'
  | 'wallet_confirmation'
  | 'submitting'
  | 'pending'
  | 'success'
  | 'error';

interface UseCanonVaultCreationOptions {
  climbId: string | undefined;
  canonId: string | undefined;
  canonVersion: number | undefined;
  enabled: boolean;
  signPreparedTransaction: SignPreparedTransaction;
}

export function useCanonVaultCreation({
  climbId,
  canonId,
  canonVersion,
  enabled,
  signPreparedTransaction,
}: UseCanonVaultCreationOptions) {
  const queryClient = useQueryClient();
  const requestIdRef = useRef<string | null>(null);
  const paymentMethodRef = useRef<VaultCreationPaymentMethod | null>(null);
  const [phase, setPhase] = useState<CanonVaultCreationPhase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CreateVaultResponse | null>(null);

  const isBusy = phase === 'preparing'
    || phase === 'wallet_confirmation'
    || phase === 'submitting';

  const createVault = useCallback(async (paymentMethod: VaultCreationPaymentMethod) => {
    if (!climbId || !enabled || isBusy) return;

    if (!canonId || !Number.isInteger(canonVersion) || canonVersion === undefined || canonVersion <= 0) {
      setError('This climb is missing its canonical identity. Refresh and try again.');
      setPhase('error');
      return;
    }

    if (!requestIdRef.current || paymentMethodRef.current !== paymentMethod) {
      requestIdRef.current = createClientRequestId('create-vault');
      paymentMethodRef.current = paymentMethod;
    }

    setError(null);
    setResult(null);
    setPhase('preparing');
    try {
      const prepared = await api.prepareCreateVault({
        climbId,
        paymentMethod,
        clientRequestId: requestIdRef.current,
      });
      setPhase('wallet_confirmation');
      const signedTransaction = await signPreparedTransaction(prepared, {
        kind: 'create_vault',
        paymentMethod,
        climbId,
        canonId,
        canonVersion,
      });
      setPhase('submitting');
      const submitted = await api.createVault({
        preparationId: prepared.preparationId,
        signedTransaction,
      });

      setResult(submitted);
      setPhase(submitted.activationState === 'active' ? 'success' : 'pending');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.climbs.all }),
        queryClient.invalidateQueries({ queryKey: queryKeys.vaults.all }),
      ]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Please try again.');
      setPhase('error');
    }
  }, [canonId, canonVersion, climbId, enabled, isBusy, queryClient, signPreparedTransaction]);

  const reset = useCallback(() => {
    requestIdRef.current = null;
    paymentMethodRef.current = null;
    setError(null);
    setResult(null);
    setPhase('idle');
  }, []);

  return {
    createVault,
    error,
    isBusy,
    phase,
    reset,
    result,
  };
}
