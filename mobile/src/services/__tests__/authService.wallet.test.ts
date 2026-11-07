import { Buffer } from 'buffer';

jest.mock('../../lib/api', () => ({
  api: {
    getNonce: jest.fn(),
    verifySignature: jest.fn(),
    refreshTokens: jest.fn(),
    logout: jest.fn(),
    getMe: jest.fn(),
  },
  setApiRefreshHandler: jest.fn(),
}));

jest.mock('../secureStorage', () => ({
  getAccessToken: jest.fn(),
  getRefreshToken: jest.fn(),
  getTokenExpiresAt: jest.fn(),
  getStoredWallet: jest.fn(),
  getStoredAuthMethod: jest.fn(),
  getDeviceId: jest.fn(),
  storeTokens: jest.fn(),
  clearTokens: jest.fn(),
}));

jest.mock('../tokenRefreshManager', () => ({
  tokenRefreshManager: {
    schedule: jest.fn(),
    cancel: jest.fn(),
    refresh: jest.fn(),
  },
  setRefreshHandler: jest.fn(),
}));

jest.mock('../wallet/mwaWallet', () => ({
  signWalletAuthMessage: jest.fn(),
}));

jest.mock('../gpsRecording', () => ({
  suspendRecordingForAccountBoundary: jest.fn().mockResolvedValue(undefined),
}));

import { api } from '../../lib/api';
import { useAuthStore } from '../../stores/authStore';
import { initializeAuth, loginWithExternalWallet, logout } from '../authService';
import { suspendRecordingForAccountBoundary } from '../gpsRecording';
import {
  clearTokens,
  getAccessToken,
  getDeviceId,
  getRefreshToken,
  getStoredAuthMethod,
  getStoredWallet,
  getTokenExpiresAt,
  storeTokens,
} from '../secureStorage';
import { tokenRefreshManager } from '../tokenRefreshManager';
import { signWalletAuthMessage } from '../wallet/mwaWallet';

const mockApi = api as jest.Mocked<typeof api>;
const mockClearTokens = clearTokens as jest.Mock;
const mockGetAccessToken = getAccessToken as jest.Mock;
const mockGetDeviceId = getDeviceId as jest.Mock;
const mockGetRefreshToken = getRefreshToken as jest.Mock;
const mockGetStoredAuthMethod = getStoredAuthMethod as jest.Mock;
const mockGetStoredWallet = getStoredWallet as jest.Mock;
const mockGetTokenExpiresAt = getTokenExpiresAt as jest.Mock;
const mockStoreTokens = storeTokens as jest.Mock;
const mockSignWalletAuthMessage = signWalletAuthMessage as jest.Mock;
const mockSuspendRecording = suspendRecordingForAccountBoundary as jest.Mock;

function jwtWithExp(exp: number): string {
  const payload = Buffer.from(JSON.stringify({ exp })).toString('base64url');
  return `header.${payload}.sig`;
}

describe('loginWithExternalWallet', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuthStore.getState().setUnauthenticated();
  });

  test('signs backend SIWS challenge and persists a wallet-authenticated session', async () => {
    const accessToken = jwtWithExp(1_900_000_000);
    mockGetDeviceId.mockResolvedValue('device-123');
    mockApi.getNonce.mockResolvedValue({
      nonce: 'nonce-123',
      message: 'Sign in to Boulder Roller',
      expiresAt: '2026-04-22T12:00:00Z',
    });
    mockSignWalletAuthMessage.mockImplementation(async (loadChallenge) => {
      const challenge = await loadChallenge('Wallet1111111111111111111111111111111111');
      return {
        nonce: challenge.nonce,
        signature: 'wallet-signature-base58',
        signer: 'Wallet1111111111111111111111111111111111',
      };
    });
    mockApi.verifySignature.mockResolvedValue({
      accessToken,
      refreshToken: 'refresh-token',
      wallet: 'Wallet1111111111111111111111111111111111',
      expiresIn: 3600,
    });

    await loginWithExternalWallet('ALPHA-RIDE');

    expect(mockApi.getNonce).toHaveBeenCalledWith(
      'Wallet1111111111111111111111111111111111',
      'device-123',
    );
    expect(mockApi.verifySignature).toHaveBeenCalledWith(
      'Wallet1111111111111111111111111111111111',
      'wallet-signature-base58',
      'nonce-123',
      'device-123',
      'ALPHA-RIDE',
    );
    expect(mockStoreTokens).toHaveBeenCalledWith({
      accessToken,
      refreshToken: 'refresh-token',
      expiresAtMs: 1_900_000_000_000,
      wallet: 'Wallet1111111111111111111111111111111111',
      authMethod: 'wallet',
    });
    expect(useAuthStore.getState()).toMatchObject({
      status: 'authenticated',
      wallet: 'Wallet1111111111111111111111111111111111',
      authMethod: 'wallet',
      accessMethod: 'external_wallet',
    });
    expect(tokenRefreshManager.schedule).toHaveBeenCalledTimes(1);
  });

  test('returns to unauthenticated state when wallet sign-in fails', async () => {
    mockGetDeviceId.mockResolvedValue('device-123');
    mockSignWalletAuthMessage.mockRejectedValue(new Error('Wallet connection cancelled.'));

    await expect(loginWithExternalWallet()).rejects.toThrow('Wallet connection cancelled.');

    expect(mockApi.verifySignature).not.toHaveBeenCalled();
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });
});

describe('logout recorder boundary', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuthStore.getState().setAuthenticated({
      accessToken: 'access-a',
      tokenExpiresAt: Date.now() + 60_000,
      wallet: 'WalletAAAA111111111111111111111111111111',
      authMethod: 'wallet',
    });
    mockGetRefreshToken.mockResolvedValue('refresh-a');
    mockGetDeviceId.mockResolvedValue('device-a');
    mockApi.logout.mockResolvedValue(undefined);
  });

  test('suspends the live recorder while the departing owner is still active', async () => {
    mockSuspendRecording.mockImplementation(async () => {
      expect(useAuthStore.getState().wallet).toBe(
        'WalletAAAA111111111111111111111111111111',
      );
    });

    await logout();

    expect(mockSuspendRecording).toHaveBeenCalledTimes(1);
    expect(useAuthStore.getState().status).toBe('unauthenticated');
  });
});

describe('initializeAuth', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuthStore.getState().setUnauthenticated();
  });

  test('hydrates a valid stored backend session without requiring a Privy exchange', async () => {
    const expiresAt = Date.now() + 10 * 60_000;
    mockGetAccessToken.mockResolvedValue('stored-access-token');
    mockGetRefreshToken.mockResolvedValue('stored-refresh-token');
    mockGetTokenExpiresAt.mockResolvedValue(expiresAt);
    mockGetStoredWallet.mockResolvedValue('PrivyWallet11111111111111111111111111111');
    mockGetStoredAuthMethod.mockResolvedValue('privy');
    mockApi.getMe.mockResolvedValue({
      wallet: 'PrivyWallet11111111111111111111111111111',
      displayName: null,
      bio: null,
      avatarUrl: null,
      createdAt: '2026-05-01T00:00:00Z',
      totalRides: 0,
    });
    useAuthStore.getState().requestSessionExchange();

    await initializeAuth();

    expect(useAuthStore.getState()).toMatchObject({
      status: 'authenticated',
      wallet: 'PrivyWallet11111111111111111111111111111',
      authMethod: 'privy',
      accessMethod: 'email_wallet',
      accessToken: 'stored-access-token',
      tokenExpiresAt: expiresAt,
      sessionExchangeRequested: false,
    });
    expect(mockApi.getMe).toHaveBeenCalledTimes(1);
    expect(tokenRefreshManager.schedule).toHaveBeenCalledTimes(1);
    expect(mockClearTokens).not.toHaveBeenCalled();
  });

  test('does not block startup on slow stored-session validation', async () => {
    const expiresAt = Date.now() + 10 * 60_000;
    let resolveGetMe: () => void = () => {};
    mockGetAccessToken.mockResolvedValue('stored-access-token');
    mockGetRefreshToken.mockResolvedValue('stored-refresh-token');
    mockGetTokenExpiresAt.mockResolvedValue(expiresAt);
    mockGetStoredWallet.mockResolvedValue('PrivyWallet11111111111111111111111111111');
    mockGetStoredAuthMethod.mockResolvedValue('privy');
    mockApi.getMe.mockReturnValue(
      new Promise<Awaited<ReturnType<typeof api.getMe>>>((resolve) => {
        resolveGetMe = () =>
          resolve({
            wallet: 'PrivyWallet11111111111111111111111111111',
            displayName: null,
            bio: null,
            avatarUrl: null,
            createdAt: '2026-05-01T00:00:00Z',
            totalRides: 0,
          });
      }),
    );

    await initializeAuth();

    expect(useAuthStore.getState()).toMatchObject({
      status: 'authenticated',
      wallet: 'PrivyWallet11111111111111111111111111111',
      authMethod: 'privy',
      accessToken: 'stored-access-token',
      tokenExpiresAt: expiresAt,
    });
    expect(mockApi.getMe).toHaveBeenCalledTimes(1);

    resolveGetMe();
    await Promise.resolve();
  });
});
