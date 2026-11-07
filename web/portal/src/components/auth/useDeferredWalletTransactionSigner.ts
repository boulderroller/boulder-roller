import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuthRuntime } from '../../contexts/AuthRuntimeContext';
import type { SignPreparedTransaction } from './WalletTransactionSignerBridge';

const SIGNER_READY_TIMEOUT_MS = 8000;

interface SignerWaiter {
  reject: (error: Error) => void;
  resolve: (signer: SignPreparedTransaction) => void;
  timeoutId: ReturnType<typeof setTimeout>;
}

export function useDeferredWalletTransactionSigner() {
  const { status: authRuntimeStatus, error: authRuntimeError } = useAuthRuntime();
  const [signerEnabled, setSignerEnabled] = useState(false);
  const signerRef = useRef<SignPreparedTransaction | null>(null);
  const waitersRef = useRef<SignerWaiter[]>([]);

  const rejectWaiters = useCallback((error: Error) => {
    const waiters = waitersRef.current;
    waitersRef.current = [];
    for (const waiter of waiters) {
      clearTimeout(waiter.timeoutId);
      waiter.reject(error);
    }
  }, []);

  const setSignerRef = useCallback((signer: SignPreparedTransaction | null) => {
    signerRef.current = signer;

    if (!signer) return;

    const waiters = waitersRef.current;
    waitersRef.current = [];
    for (const waiter of waiters) {
      clearTimeout(waiter.timeoutId);
      waiter.resolve(signer);
    }
  }, []);

  const getSigner = useCallback(async () => {
    if (signerRef.current) {
      return signerRef.current;
    }

    setSignerEnabled(true);

    return new Promise<SignPreparedTransaction>((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        waitersRef.current = waitersRef.current.filter((waiter) => waiter.timeoutId !== timeoutId);
        reject(new Error('Wallet signing is still initializing. Please try again.'));
      }, SIGNER_READY_TIMEOUT_MS);

      waitersRef.current.push({ reject, resolve, timeoutId });
    });
  }, []);

  const signPreparedTransaction: SignPreparedTransaction = useCallback(
    async (...request) => (await getSigner())(...request),
    [getSigner],
  );

  useEffect(() => {
    if (!signerEnabled || authRuntimeStatus !== 'failed') return;
    rejectWaiters(new Error(authRuntimeError ?? 'Wallet signing failed to load.'));
  }, [authRuntimeError, authRuntimeStatus, rejectWaiters, signerEnabled]);

  useEffect(() => () => {
    rejectWaiters(new Error('Wallet signing was cancelled.'));
    signerRef.current = null;
  }, [rejectWaiters]);

  return {
    setSignerRef,
    signPreparedTransaction,
    signerEnabled,
  };
}
