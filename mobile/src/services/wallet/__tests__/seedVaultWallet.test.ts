jest.mock('react-native', () => ({
  Platform: {
    OS: 'android',
    Version: 33,
    select: (obj: Record<string, unknown>) => obj.android ?? obj.default,
  },
}));

jest.mock('@solana-mobile/seed-vault-lib', () => ({
  SeedVault: {
    isSeedVaultAvailable: jest.fn(),
  },
}));

import { Platform } from 'react-native';
import { SeedVault } from '@solana-mobile/seed-vault-lib';

import { isSeedVaultAvailable } from '../seedVaultWallet';

const mockIsAvailable = SeedVault.isSeedVaultAvailable as jest.Mock;

describe('isSeedVaultAvailable', () => {
  let originalOS: string;
  beforeEach(() => {
    originalOS = Platform.OS;
    mockIsAvailable.mockClear();
  });
  afterEach(() => {
    Object.defineProperty(Platform, 'OS', { value: originalOS, configurable: true });
  });

  test('returns false on iOS without touching the native bridge', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
    await expect(isSeedVaultAvailable()).resolves.toBe(false);
    expect(mockIsAvailable).not.toHaveBeenCalled();
  });

  test('passes allowSimulated=true so Simulator APK counts as available', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
    mockIsAvailable.mockResolvedValueOnce(true);
    await expect(isSeedVaultAvailable()).resolves.toBe(true);
    expect(mockIsAvailable).toHaveBeenCalledWith(true);
  });

  test('returns false when the native bridge throws (no Seed Vault app installed)', async () => {
    Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
    mockIsAvailable.mockRejectedValueOnce(new Error('Native module not found'));
    await expect(isSeedVaultAvailable()).resolves.toBe(false);
  });
});
