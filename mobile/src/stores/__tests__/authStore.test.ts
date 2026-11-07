import { useAuthStore } from '../authStore';

describe('authStore session exchange gate', () => {
  beforeEach(() => {
    useAuthStore.getState().setUnauthenticated();
  });

  test('authenticated sessions clear transient invite and exchange state', () => {
    useAuthStore.getState().setPendingInviteCode('ALPHA-RIDE');
    useAuthStore.getState().requestSessionExchange();
    useAuthStore.getState().setAuthError('Previous exchange failed');

    useAuthStore.getState().setAuthenticated({
      accessToken: 'backend-access-token',
      tokenExpiresAt: Date.now() + 60_000,
      wallet: 'Wallet1111111111111111111111111111111111',
      authMethod: 'privy',
    });

    expect(useAuthStore.getState()).toMatchObject({
      status: 'authenticated',
      pendingInviteCode: null,
      sessionExchangeRequested: false,
      authError: null,
      authRecovery: null,
    });
  });

  test('loading and unauthenticated resets cannot inherit a pending email exchange', () => {
    useAuthStore.getState().requestSessionExchange();
    useAuthStore.getState().setAuthError('Could not finish sign-in.');

    useAuthStore.getState().setLoading();

    expect(useAuthStore.getState()).toMatchObject({
      status: 'loading',
      sessionExchangeRequested: false,
      authError: null,
      authRecovery: null,
    });

    useAuthStore.getState().requestSessionExchange();
    useAuthStore.getState().setAuthError('Invite required', 'invite_required');
    useAuthStore.getState().setUnauthenticated();

    expect(useAuthStore.getState()).toMatchObject({
      status: 'unauthenticated',
      sessionExchangeRequested: false,
      authError: null,
      authRecovery: null,
      pendingInviteCode: null,
    });
  });

  test('tracks invite recovery separately from general errors', () => {
    useAuthStore.getState().setAuthError('Enter your invite code.', 'invite_required');

    expect(useAuthStore.getState()).toMatchObject({
      authError: 'Enter your invite code.',
      authRecovery: 'invite_required',
    });

    useAuthStore.getState().setPendingInviteCode('ALPHA-RIDE');

    expect(useAuthStore.getState()).toMatchObject({
      pendingInviteCode: 'ALPHA-RIDE',
      authError: null,
      authRecovery: null,
    });
  });
});
