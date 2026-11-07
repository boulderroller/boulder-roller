export const AUTH_PHASE_VALUES = [
  'invite_gate',
  'choose_access_method',
  'provider_pending',
  'wallet_resolution',
  'session_exchange',
  'profile_completion',
  'authenticated',
  'recoverable_error',
] as const;

export type AuthPhase = typeof AUTH_PHASE_VALUES[number];

export const AUTH_PHASES = {
  inviteGate: 'invite_gate',
  chooseAccessMethod: 'choose_access_method',
  providerPending: 'provider_pending',
  walletResolution: 'wallet_resolution',
  sessionExchange: 'session_exchange',
  profileCompletion: 'profile_completion',
  authenticated: 'authenticated',
  recoverableError: 'recoverable_error',
} as const satisfies Record<string, AuthPhase>;

export const AUTH_ACCESS_METHOD_VALUES = [
  'email_wallet',
  'external_wallet',
] as const;

export type AuthAccessMethod = typeof AUTH_ACCESS_METHOD_VALUES[number];
export type BackendAuthMethod = 'privy' | 'wallet';

export const AUTH_ACCESS_METHODS = {
  emailWallet: 'email_wallet',
  externalWallet: 'external_wallet',
} as const satisfies Record<string, AuthAccessMethod>;

export function authAccessMethodFromBackend(method: BackendAuthMethod | null): AuthAccessMethod | null {
  if (method === 'privy') return AUTH_ACCESS_METHODS.emailWallet;
  if (method === 'wallet') return AUTH_ACCESS_METHODS.externalWallet;
  return null;
}

export function describeAuthAccessMethod(method: AuthAccessMethod | null): string {
  if (method === AUTH_ACCESS_METHODS.emailWallet) return 'Account with rider wallet';
  if (method === AUTH_ACCESS_METHODS.externalWallet) return 'Account with connected wallet';
  return 'Account session';
}
