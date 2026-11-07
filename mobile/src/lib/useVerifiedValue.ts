import { useEffect } from 'react';
import { create } from 'zustand';

import {
  unavailableVerification,
  verifyExact,
  type VerificationResult,
} from './verify';

export interface VerifiedValueSnapshot<T> extends VerificationResult<T> {
  key: string;
  updatedAt: number | null;
}

interface VerifyStore {
  values: Record<string, VerifiedValueSnapshot<unknown>>;
  setValue: <T>(value: VerifiedValueSnapshot<T>) => void;
}

export const useVerifyStore = create<VerifyStore>((set) => ({
  values: {},
  setValue: (value) =>
    set((state) => ({
      values: {
        ...state.values,
        [value.key]: value as VerifiedValueSnapshot<unknown>,
      },
    })),
}));

export function useVerifiedValue<T>(params: {
  key: string;
  enabled: boolean;
  projected?: T | null;
  fetchOnchain: () => Promise<T | null>;
  verify?: (projected: T | null, onchain: T | null) => VerificationResult<T>;
}): VerifiedValueSnapshot<T> {
  const projected = params.projected ?? null;
  const verify = params.verify ?? verifyExact<T>;
  const setValue = useVerifyStore((s) => s.setValue);
  const snapshot = useVerifyStore(
    (s) => s.values[params.key] as VerifiedValueSnapshot<T> | undefined,
  );

  useEffect(() => {
    let cancelled = false;

    if (!params.enabled) {
      setValue<T>({
        key: params.key,
        state: 'unchecked',
        projected,
        onchain: null,
        updatedAt: Date.now(),
      });
      return () => {
        cancelled = true;
      };
    }

    setValue<T>({
      key: params.key,
      state: 'checking',
      projected,
      onchain: snapshot?.onchain ?? null,
      updatedAt: snapshot?.updatedAt ?? null,
    });

    params.fetchOnchain()
      .then((onchain) => {
        if (cancelled) return;
        setValue<T>({
          key: params.key,
          ...verify(projected, onchain),
          updatedAt: Date.now(),
        });
      })
      .catch((error) => {
        if (cancelled) return;
        setValue<T>({
          key: params.key,
          ...unavailableVerification(projected, error),
          updatedAt: Date.now(),
        });
      });

    return () => {
      cancelled = true;
    };
  }, [params.enabled, params.key, params.fetchOnchain, projected, setValue, verify]);

  return snapshot ?? {
    key: params.key,
    state: params.enabled ? 'checking' : 'unchecked',
    projected,
    onchain: null,
    updatedAt: null,
  };
}
