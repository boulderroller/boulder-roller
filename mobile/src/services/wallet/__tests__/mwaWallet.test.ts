/**
 * mwaWallet tests — mocks the MWA + web3js native dependencies to verify
 * our wrapper logic (Platform gating, base58 pubkey decoding, error
 * classification). Real end-to-end signing is verified manually on a
 * Seeker / Android emulator with the Seed Vault Simulator APK; jest can
 * only check our glue.
 */

import { Buffer } from 'buffer';

// Minimal scoped react-native mock — only Platform is used by mwaWallet.
jest.mock('react-native', () => ({
  Platform: {
    OS: 'android',
    Version: 33,
    select: (obj: Record<string, unknown>) => obj.android ?? obj.default,
  },
}));

jest.mock('@solana-mobile/mobile-wallet-adapter-protocol-web3js', () => ({
  transact: jest.fn(),
}));

// Mock the protocol error classes with real constructors so `instanceof`
// works inside classifyMwaError. The shape matches the production d.ts.
jest.mock('@solana-mobile/mobile-wallet-adapter-protocol', () => {
  class SolanaMobileWalletAdapterError extends Error {
    code: string;
    data: unknown;
    constructor(code: string, message: string, data?: unknown) {
      super(message);
      this.name = 'SolanaMobileWalletAdapterError';
      this.code = code;
      this.data = data;
    }
  }
  class SolanaMobileWalletAdapterProtocolError extends Error {
    code: number | string;
    data: unknown;
    constructor(_id: number, code: number | string, message: string, data?: unknown) {
      super(message);
      this.name = 'SolanaMobileWalletAdapterProtocolError';
      this.code = code;
      this.data = data;
    }
  }
  return {
    SolanaMobileWalletAdapterError,
    SolanaMobileWalletAdapterErrorCode: {
      ERROR_WALLET_NOT_FOUND: 'ERROR_WALLET_NOT_FOUND',
      ERROR_ASSOCIATION_CANCELLED: 'ERROR_ASSOCIATION_CANCELLED',
      ERROR_SESSION_CLOSED: 'ERROR_SESSION_CLOSED',
      ERROR_SESSION_TIMEOUT: 'ERROR_SESSION_TIMEOUT',
    },
    SolanaMobileWalletAdapterProtocolError,
    SolanaMobileWalletAdapterProtocolErrorCode: {
      ERROR_AUTHORIZATION_FAILED: -1,
      ERROR_INVALID_PAYLOADS: -2,
      ERROR_NOT_SIGNED: -3,
    },
  };
});

import { Platform } from 'react-native';
import { transact } from '@solana-mobile/mobile-wallet-adapter-protocol-web3js';
import {
  SolanaMobileWalletAdapterError,
  SolanaMobileWalletAdapterErrorCode,
  SolanaMobileWalletAdapterProtocolError,
  SolanaMobileWalletAdapterProtocolErrorCode,
} from '@solana-mobile/mobile-wallet-adapter-protocol';

import {
  classifyMwaError,
  connectWallet,
  isMwaSupported,
  MwaUnsupportedError,
  signWalletAuthMessage,
} from '../mwaWallet';

const mockTransact = transact as jest.Mock;

describe('isMwaSupported', () => {
  let originalOS: string;
  beforeEach(() => {
    originalOS = Platform.OS;
  });
  afterEach(() => {
    Object.defineProperty(Platform, 'OS', { value: originalOS, configurable: true });
  });

  test('returns true on android', () => {
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
    expect(isMwaSupported()).toBe(true);
  });

  test('returns false on ios', () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    expect(isMwaSupported()).toBe(false);
  });
});

describe('connectWallet', () => {
  let originalOS: string;
  beforeEach(() => {
    originalOS = Platform.OS;
    mockTransact.mockClear();
  });
  afterEach(() => {
    Object.defineProperty(Platform, 'OS', { value: originalOS, configurable: true });
  });

  test('throws MwaUnsupportedError on iOS', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    await expect(connectWallet()).rejects.toBeInstanceOf(MwaUnsupportedError);
    expect(mockTransact).not.toHaveBeenCalled();
  });

  test('runs authorize and decodes the base64 address into a base58 pubkey', async () => {
    // Synthetic 32-byte pubkey, base64-encoded as MWA wire format
    const pubkeyBytes = new Uint8Array(32);
    for (let i = 0; i < 32; i++) pubkeyBytes[i] = i + 1;
    const addressBase64 = Buffer.from(pubkeyBytes).toString('base64');

    const authorizeMock = jest.fn().mockResolvedValue({
      accounts: [{ address: addressBase64, label: 'Test Wallet' }],
    });
    mockTransact.mockImplementationOnce(async (callback: (w: unknown) => unknown) =>
      callback({ authorize: authorizeMock }),
    );

    const result = await connectWallet();

    // Authorize was called with cluster + identity
    expect(authorizeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        cluster: 'devnet',
        identity: expect.objectContaining({ name: 'Boulder Roller' }),
      }),
    );
    // Returned pubkey is base58 (no I/O/0/l characters; alphanumeric only)
    expect(result.publicKey).toMatch(/^[1-9A-HJ-NP-Za-km-z]{32,44}$/);
    expect(result.walletLabel).toBe('Test Wallet');
  });
});

describe('signWalletAuthMessage', () => {
  let originalOS: string;
  beforeEach(() => {
    originalOS = Platform.OS;
    mockTransact.mockClear();
  });
  afterEach(() => {
    Object.defineProperty(Platform, 'OS', { value: originalOS, configurable: true });
  });

  test('authorizes, loads a backend challenge for the signer, and signs the SIWS message', async () => {
    const pubkeyBytes = new Uint8Array(32);
    for (let i = 0; i < 32; i++) pubkeyBytes[i] = i + 1;
    const addressBase64 = Buffer.from(pubkeyBytes).toString('base64');
    const signatureBytes = new Uint8Array(64);
    for (let i = 0; i < 64; i++) signatureBytes[i] = i + 2;

    const authorizeMock = jest.fn().mockResolvedValue({
      accounts: [{ address: addressBase64, label: 'Auth Wallet' }],
    });
    const signMessagesMock = jest.fn().mockResolvedValue([signatureBytes]);
    const loadChallenge = jest.fn(async (walletAddress: string) => ({
      nonce: 'nonce-123',
      message: `Sign in to Boulder Roller as ${walletAddress}`,
    }));
    mockTransact.mockImplementationOnce(async (callback: (w: unknown) => unknown) =>
      callback({ authorize: authorizeMock, signMessages: signMessagesMock }),
    );

    const result = await signWalletAuthMessage(loadChallenge);

    expect(loadChallenge).toHaveBeenCalledWith(result.signer);
    expect(signMessagesMock).toHaveBeenCalledWith({
      addresses: [addressBase64],
      payloads: [expect.any(Uint8Array)],
    });
    const payload = signMessagesMock.mock.calls[0][0].payloads[0] as Uint8Array;
    expect(Buffer.from(payload).toString('utf8')).toBe(`Sign in to Boulder Roller as ${result.signer}`);
    expect(result).toEqual({
      nonce: 'nonce-123',
      signature: expect.stringMatching(/^[1-9A-HJ-NP-Za-km-z]+$/),
      signer: expect.stringMatching(/^[1-9A-HJ-NP-Za-km-z]{32,44}$/),
      walletLabel: 'Auth Wallet',
    });
  });

  test('encodes an all-zero signature without adding an extra Base58 leading one', async () => {
    const pubkeyBytes = new Uint8Array(32);
    pubkeyBytes[31] = 1;
    const addressBase64 = Buffer.from(pubkeyBytes).toString('base64');
    const signatureBytes = new Uint8Array(64);

    mockTransact.mockImplementationOnce(async (callback: (w: unknown) => unknown) =>
      callback({
        authorize: jest.fn().mockResolvedValue({
          accounts: [{ address: addressBase64 }],
        }),
        signMessages: jest.fn().mockResolvedValue([signatureBytes]),
      }),
    );

    const result = await signWalletAuthMessage(async () => ({
      nonce: 'nonce-zero',
      message: 'Sign in to Boulder Roller',
    }));

    expect(result.signature).toBe('1'.repeat(64));
  });

  test('fails closed when the wallet returns no signing account', async () => {
    mockTransact.mockImplementationOnce(async (callback: (w: unknown) => unknown) =>
      callback({
        authorize: jest.fn().mockResolvedValue({ accounts: [] }),
        signMessages: jest.fn(),
      }),
    );

    await expect(signWalletAuthMessage(async () => ({
      nonce: 'nonce',
      message: 'Sign in to Boulder Roller',
    }))).rejects.toThrow('Wallet did not return a Solana account.');
  });
});

describe('classifyMwaError', () => {
  test('maps MwaUnsupportedError to unsupported_platform', () => {
    const result = classifyMwaError(new MwaUnsupportedError('iOS not wired'));
    expect(result.kind).toBe('unsupported_platform');
    expect(result.message).toContain('iOS');
  });

  test('maps ERROR_WALLET_NOT_FOUND to no_wallet with install guidance', () => {
    const err = new SolanaMobileWalletAdapterError(
      SolanaMobileWalletAdapterErrorCode.ERROR_WALLET_NOT_FOUND,
      'no wallet',
    );
    const result = classifyMwaError(err);
    expect(result.kind).toBe('no_wallet');
    expect(result.message).toMatch(/Phantom|Solflare|Backpack/);
    expect(result.message).toMatch(/Seeker|Seed Vault/);
  });

  test('maps ERROR_ASSOCIATION_CANCELLED to user_cancelled', () => {
    const err = new SolanaMobileWalletAdapterError(
      SolanaMobileWalletAdapterErrorCode.ERROR_ASSOCIATION_CANCELLED,
      'user cancelled',
      { event: undefined },
    );
    const result = classifyMwaError(err);
    expect(result.kind).toBe('user_cancelled');
  });

  test('maps ERROR_SESSION_CLOSED to user_cancelled (soft close)', () => {
    const err = new SolanaMobileWalletAdapterError(
      SolanaMobileWalletAdapterErrorCode.ERROR_SESSION_CLOSED,
      'closed',
      { closeEvent: {} as CloseEvent },
    );
    const result = classifyMwaError(err);
    expect(result.kind).toBe('user_cancelled');
  });

  test('maps ERROR_SESSION_TIMEOUT to session with retry hint', () => {
    const err = new SolanaMobileWalletAdapterError(
      SolanaMobileWalletAdapterErrorCode.ERROR_SESSION_TIMEOUT,
      'timeout',
    );
    const result = classifyMwaError(err);
    expect(result.kind).toBe('session');
    expect(result.message).toMatch(/foreground|retry|again/i);
  });

  test('maps ERROR_AUTHORIZATION_FAILED to authorization', () => {
    const err = new SolanaMobileWalletAdapterProtocolError(
      1,
      SolanaMobileWalletAdapterProtocolErrorCode.ERROR_AUTHORIZATION_FAILED,
      'decline',
    );
    const result = classifyMwaError(err);
    expect(result.kind).toBe('authorization');
  });

  test('maps ERROR_NOT_SIGNED to user_cancelled', () => {
    const err = new SolanaMobileWalletAdapterProtocolError(
      1,
      SolanaMobileWalletAdapterProtocolErrorCode.ERROR_NOT_SIGNED,
      'declined signing',
    );
    const result = classifyMwaError(err);
    expect(result.kind).toBe('user_cancelled');
  });

  test('falls back to string match when plain Error carries cancel wording', () => {
    const result = classifyMwaError(new Error('User rejected the request'));
    expect(result.kind).toBe('user_cancelled');
  });

  test('falls back to string match when plain Error says no wallet', () => {
    const result = classifyMwaError(new Error('No wallet installed'));
    expect(result.kind).toBe('no_wallet');
  });

  test('returns unknown + preserves cause for unexpected errors', () => {
    const err = new Error('Something exploded');
    const result = classifyMwaError(err);
    expect(result.kind).toBe('unknown');
    expect(result.message).toBe('Something exploded');
    expect(result.cause).toBe(err);
  });

  test('handles non-Error throws gracefully', () => {
    const result = classifyMwaError('some string');
    expect(result.kind).toBe('unknown');
    expect(result.message).toBeTruthy();
  });
});
