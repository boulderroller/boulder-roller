/**
 * Verification state primitives.
 *
 * Projected values are useful for UX speed, but identity/claim surfaces need
 * explicit state when a value is checked against chain truth.
 */

export type VerificationState =
  | 'unchecked'
  | 'checking'
  | 'verified'
  | 'diverged'
  | 'unavailable';

export interface VerificationResult<T> {
  state: VerificationState;
  projected: T | null;
  onchain: T | null;
  error?: string | null;
}

export function verifyExact<T>(
  projected: T | null | undefined,
  onchain: T | null | undefined,
): VerificationResult<T> {
  if (onchain == null) {
    return {
      state: projected == null ? 'unchecked' : 'unavailable',
      projected: projected ?? null,
      onchain: null,
    };
  }

  if (projected == null) {
    return {
      state: 'verified',
      projected: null,
      onchain,
    };
  }

  return {
    state: Object.is(projected, onchain) ? 'verified' : 'diverged',
    projected,
    onchain,
  };
}

export function verifyNumber(params: {
  projected: number | null | undefined;
  onchain: number | null | undefined;
  tolerance?: number;
}): VerificationResult<number> {
  const projected = params.projected ?? null;
  const onchain = params.onchain ?? null;

  if (onchain == null) {
    return {
      state: projected == null ? 'unchecked' : 'unavailable',
      projected,
      onchain,
    };
  }

  if (projected == null) {
    return {
      state: 'verified',
      projected,
      onchain,
    };
  }

  const tolerance = params.tolerance ?? 0;
  return {
    state: Math.abs(projected - onchain) <= tolerance ? 'verified' : 'diverged',
    projected,
    onchain,
  };
}

export function unavailableVerification<T>(
  projected: T | null,
  error: unknown,
): VerificationResult<T> {
  return {
    state: 'unavailable',
    projected,
    onchain: null,
    error: error instanceof Error ? error.message : 'Unable to verify',
  };
}
