import React from 'react';
import { Text } from 'react-native';
import { render, waitFor } from '@testing-library/react-native';
import { usePrivy, useEmbeddedSolanaWallet } from '@privy-io/expo';

import PrivyAuthBridge, { getPrivySyncFailureState } from '../PrivyAuthBridge';
import { syncPrivyAuth } from '../../services/privyBridge';
import { useAuthStore } from '../../stores/authStore';

jest.mock('../../services/privyBridge', () => ({
  syncPrivyAuth: jest.fn(),
}));

const mockUsePrivy = usePrivy as jest.Mock;
const mockUseEmbeddedSolanaWallet = useEmbeddedSolanaWallet as jest.Mock;
const mockSyncPrivyAuth = syncPrivyAuth as jest.Mock;

function setAuthenticatedPrivy(logout = jest.fn()) {
  const getAccessToken = jest.fn(async () => 'privy-access-token');
  const user = { id: 'privy-user', linked_accounts: [] };
  mockUsePrivy.mockReturnValue({
    user,
    isReady: true,
    getAccessToken,
    logout,
  });
  return { user, getAccessToken, logout };
}

function setConnectedWallet(address = 'So11111111111111111111111111111111111111112') {
  mockUseEmbeddedSolanaWallet.mockReturnValue({
    status: 'connected',
    wallets: [{ address }],
    create: jest.fn(),
  });
}

function setUncreatedWallet(create = jest.fn()) {
  mockUseEmbeddedSolanaWallet.mockReturnValue({
    status: 'not-created',
    wallets: [],
    create,
  });
  return create;
}

function renderBridge() {
  return render(
    <PrivyAuthBridge>
      <Text>child</Text>
    </PrivyAuthBridge>,
  );
}

describe('PrivyAuthBridge', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuthStore.getState().setUnauthenticated();
    setAuthenticatedPrivy();
    setConnectedWallet();
  });

  test('passes the checked invite code through backend Privy exchange', async () => {
    const { user, getAccessToken } = setAuthenticatedPrivy();
    setConnectedWallet('InviteWallet111111111111111111111111111111');
    useAuthStore.getState().setPendingInviteCode('ALPHA-RIDE');
    useAuthStore.getState().requestSessionExchange();
    mockSyncPrivyAuth.mockImplementation(async () => {
      useAuthStore.getState().setAuthenticated({
        accessToken: 'backend-access-token',
        tokenExpiresAt: Date.now() + 60_000,
        wallet: 'InviteWallet111111111111111111111111111111',
        authMethod: 'privy',
      });
    });

    renderBridge();

    await waitFor(() => {
      expect(mockSyncPrivyAuth).toHaveBeenCalledWith(
        user,
        getAccessToken,
        'ALPHA-RIDE',
        'InviteWallet111111111111111111111111111111',
      );
    });
    expect(useAuthStore.getState().pendingInviteCode).toBeNull();
    expect(useAuthStore.getState().sessionExchangeRequested).toBe(false);
    expect(useAuthStore.getState().authError).toBeNull();
  });

  test('omits invite code for returning-user Privy exchange', async () => {
    const { user, getAccessToken } = setAuthenticatedPrivy();
    setConnectedWallet('ReturnWallet11111111111111111111111111111');
    useAuthStore.getState().requestSessionExchange();
    mockSyncPrivyAuth.mockImplementation(async () => {
      useAuthStore.getState().setAuthenticated({
        accessToken: 'backend-access-token',
        tokenExpiresAt: Date.now() + 60_000,
        wallet: 'ReturnWallet11111111111111111111111111111',
        authMethod: 'privy',
      });
    });

    renderBridge();

    await waitFor(() => {
      expect(mockSyncPrivyAuth).toHaveBeenCalledWith(
        user,
        getAccessToken,
        undefined,
        'ReturnWallet11111111111111111111111111111',
      );
    });
  });

  test('surfaces invalid invite failures without logging out so the rider can retry', async () => {
    const logout = jest.fn();
    setAuthenticatedPrivy(logout);
    useAuthStore.getState().setPendingInviteCode('STALE-CODE');
    useAuthStore.getState().requestSessionExchange();
    mockSyncPrivyAuth.mockRejectedValue(
      new Error('API error 401: {"code":"invite_invalid"}'),
    );

    renderBridge();

    await waitFor(() => {
      expect(mockSyncPrivyAuth).toHaveBeenCalledTimes(1);
    });
    expect(logout).not.toHaveBeenCalled();
    expect(useAuthStore.getState().pendingInviteCode).toBeNull();
    expect(useAuthStore.getState().sessionExchangeRequested).toBe(false);
    expect(useAuthStore.getState().authError).toBe('That invite is not active.');
    expect(useAuthStore.getState().authRecovery).toBe('invite_invalid');
  });

  test('allows invite recovery to retry the same Privy session', async () => {
    const { user, getAccessToken } = setAuthenticatedPrivy();
    setConnectedWallet('RecoveryWallet11111111111111111111111111');
    useAuthStore.getState().requestSessionExchange();
    mockSyncPrivyAuth
      .mockRejectedValueOnce(new Error('API error 401: {"code":"invite_required"}'))
      .mockImplementationOnce(async () => {
        useAuthStore.getState().setAuthenticated({
          accessToken: 'backend-access-token',
          tokenExpiresAt: Date.now() + 60_000,
          wallet: 'RecoveryWallet11111111111111111111111111',
          authMethod: 'privy',
        });
      });

    const view = renderBridge();

    await waitFor(() => {
      expect(useAuthStore.getState().authRecovery).toBe('invite_required');
    });

    useAuthStore.getState().setPendingInviteCode('ALPHA-RIDE');
    useAuthStore.getState().requestSessionExchange();
    view.rerender(
      <PrivyAuthBridge>
        <Text>child</Text>
      </PrivyAuthBridge>,
    );

    await waitFor(() => {
      expect(mockSyncPrivyAuth).toHaveBeenCalledTimes(2);
    });
    expect(mockSyncPrivyAuth).toHaveBeenLastCalledWith(
      user,
      getAccessToken,
      'ALPHA-RIDE',
      'RecoveryWallet11111111111111111111111111',
    );
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  test('does not auto-sync a stale Privy session without an explicit exchange request', async () => {
    const { user, getAccessToken } = setAuthenticatedPrivy();
    setConnectedWallet('StalePrivyWallet1111111111111111111111111');

    renderBridge();

    await waitFor(() => {
      expect(mockSyncPrivyAuth).not.toHaveBeenCalled();
    });
    expect(useAuthStore.getState().status).toBe('unauthenticated');
    expect(user).toBeDefined();
    expect(getAccessToken).toBeDefined();
  });

  test('does not create an embedded wallet for a stale Privy session without an explicit exchange request', async () => {
    const create = setUncreatedWallet();

    renderBridge();

    await waitFor(() => {
      expect(mockUseEmbeddedSolanaWallet).toHaveBeenCalled();
    });
    expect(create).not.toHaveBeenCalled();
    expect(mockSyncPrivyAuth).not.toHaveBeenCalled();
  });

  test('keeps the backend session when Privy drops after a successful exchange', async () => {
    const { user, getAccessToken } = setAuthenticatedPrivy();
    const logout = jest.fn();
    useAuthStore.getState().requestSessionExchange();
    mockSyncPrivyAuth.mockImplementation(async () => {
      useAuthStore.getState().setAuthenticated({
        accessToken: 'backend-access-token',
        tokenExpiresAt: Date.now() + 60_000,
        wallet: 'StableWallet111111111111111111111111111111',
        authMethod: 'privy',
      });
    });

    const view = renderBridge();

    await waitFor(() => {
      expect(mockSyncPrivyAuth).toHaveBeenCalledWith(
        user,
        getAccessToken,
        undefined,
        'So11111111111111111111111111111111111111112',
      );
    });

    mockUsePrivy.mockReturnValue({
      user: null,
      isReady: true,
      getAccessToken: jest.fn(async () => null),
      logout,
    });
    view.rerender(
      <PrivyAuthBridge>
        <Text>child</Text>
      </PrivyAuthBridge>,
    );

    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe('authenticated');
    });
  });
});

describe('getPrivySyncFailureState', () => {
  test('classifies invite-required failures as invite-clearing recovery', () => {
    expect(getPrivySyncFailureState(new Error('{"code":"invite_required"}'))).toEqual({
      message: 'Invite required.',
      clearInvite: true,
      recovery: 'invite_required',
      shouldLogout: false,
    });
  });

  test('classifies transient failures without clearing the checked invite', () => {
    expect(getPrivySyncFailureState(new Error('Network error: timeout'))).toEqual({
      message: 'Connection issue.',
      clearInvite: false,
      shouldLogout: true,
    });
  });
});
