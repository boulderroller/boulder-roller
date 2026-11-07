import {
  AUTH_ACCESS_METHODS,
  AUTH_ACCESS_METHOD_VALUES,
  AUTH_PHASES,
  AUTH_PHASE_VALUES,
  authAccessMethodFromBackend,
  describeAuthAccessMethod,
} from '../authState';

describe('authState contract', () => {
  test('keeps the canonical auth phases in order', () => {
    expect(AUTH_PHASE_VALUES).toEqual([
      AUTH_PHASES.inviteGate,
      AUTH_PHASES.chooseAccessMethod,
      AUTH_PHASES.providerPending,
      AUTH_PHASES.walletResolution,
      AUTH_PHASES.sessionExchange,
      AUTH_PHASES.profileCompletion,
      AUTH_PHASES.authenticated,
      AUTH_PHASES.recoverableError,
    ]);
  });

  test('maps backend auth methods to product access methods', () => {
    expect(AUTH_ACCESS_METHOD_VALUES).toEqual([
      AUTH_ACCESS_METHODS.emailWallet,
      AUTH_ACCESS_METHODS.externalWallet,
    ]);
    expect(authAccessMethodFromBackend('privy')).toBe(AUTH_ACCESS_METHODS.emailWallet);
    expect(authAccessMethodFromBackend('wallet')).toBe(AUTH_ACCESS_METHODS.externalWallet);
    expect(authAccessMethodFromBackend(null)).toBeNull();
    expect(describeAuthAccessMethod(AUTH_ACCESS_METHODS.emailWallet)).toBe('Email-created rider wallet');
    expect(describeAuthAccessMethod(AUTH_ACCESS_METHODS.externalWallet)).toBe('Connected rider wallet');
  });
});
