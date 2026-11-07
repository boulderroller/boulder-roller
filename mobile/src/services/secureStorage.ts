/**
 * Secure Token Storage Service
 *
 * Wraps expo-secure-store for persisting auth tokens, wallet address,
 * and device ID in the iOS Keychain / Android EncryptedSharedPreferences.
 *
 * Keys use WHEN_UNLOCKED_THIS_DEVICE_ONLY accessibility — tokens are only
 * readable when the device is unlocked and cannot be restored from backups
 * to other devices.
 */

import * as SecureStore from 'expo-secure-store';
import { randomUUID, getRandomBytesAsync } from 'expo-crypto';
import { Buffer } from 'buffer';

const KEYS = {
  ACCESS_TOKEN: 'br_access_token',
  REFRESH_TOKEN: 'br_refresh_token',
  TOKEN_EXPIRES_AT: 'br_token_expires_at',
  DEVICE_ID: 'br_device_id',
  WALLET: 'br_wallet',
  AUTH_METHOD: 'br_auth_method',
  DB_ENCRYPTION_KEY: 'br_db_encryption_key',
} as const;

const SECURE_OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYS.ACCESS_TOKEN, SECURE_OPTIONS);
}

export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYS.REFRESH_TOKEN, SECURE_OPTIONS);
}

export async function getTokenExpiresAt(): Promise<number | null> {
  const raw = await SecureStore.getItemAsync(KEYS.TOKEN_EXPIRES_AT, SECURE_OPTIONS);
  return raw ? parseInt(raw, 10) : null;
}

export async function storeTokens(params: {
  accessToken: string;
  refreshToken: string;
  expiresAtMs: number;
  wallet: string;
  authMethod: 'privy' | 'wallet';
}): Promise<void> {
  await Promise.all([
    SecureStore.setItemAsync(KEYS.ACCESS_TOKEN, params.accessToken, SECURE_OPTIONS),
    SecureStore.setItemAsync(KEYS.REFRESH_TOKEN, params.refreshToken, SECURE_OPTIONS),
    SecureStore.setItemAsync(KEYS.TOKEN_EXPIRES_AT, String(params.expiresAtMs), SECURE_OPTIONS),
    SecureStore.setItemAsync(KEYS.WALLET, params.wallet, SECURE_OPTIONS),
    SecureStore.setItemAsync(KEYS.AUTH_METHOD, params.authMethod, SECURE_OPTIONS),
  ]);
}

export async function clearTokens(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(KEYS.ACCESS_TOKEN),
    SecureStore.deleteItemAsync(KEYS.REFRESH_TOKEN),
    SecureStore.deleteItemAsync(KEYS.TOKEN_EXPIRES_AT),
    SecureStore.deleteItemAsync(KEYS.WALLET),
    SecureStore.deleteItemAsync(KEYS.AUTH_METHOD),
  ]);
  // Note: DEVICE_ID is intentionally NOT cleared on logout.
  // It persists across sessions for refresh token binding.
}

export async function getDeviceId(): Promise<string> {
  let deviceId = await SecureStore.getItemAsync(KEYS.DEVICE_ID);
  if (!deviceId) {
    // Hermes lacks crypto.randomUUID — use expo-crypto's polyfilled version
    deviceId = randomUUID();
    await SecureStore.setItemAsync(KEYS.DEVICE_ID, deviceId);
  }
  return deviceId;
}

export async function getStoredWallet(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYS.WALLET);
}

export async function getStoredAuthMethod(): Promise<'privy' | 'wallet' | null> {
  const method = await SecureStore.getItemAsync(KEYS.AUTH_METHOD);
  if (method === 'privy' || method === 'wallet') return method;
  return null;
}

/**
 * Fetch the SQLCipher passphrase for the local SQLite database. Generates a
 * 256-bit random key on first launch and stores it in the keychain. The key
 * persists across app restarts (and across reinstalls on iOS, since Keychain
 * survives — but the SQLite file is wiped on reinstall, so the next open
 * runs migrations against a fresh schema).
 *
 * Persisted as base64 — SQLCipher accepts arbitrary-length passphrases and
 * derives the actual encryption key via PBKDF2 internally.
 */
export async function getOrCreateDbEncryptionKey(): Promise<string> {
  const existing = await SecureStore.getItemAsync(KEYS.DB_ENCRYPTION_KEY, SECURE_OPTIONS);
  if (existing) return existing;
  const random = await getRandomBytesAsync(32);
  const key = Buffer.from(random).toString('base64');
  await SecureStore.setItemAsync(KEYS.DB_ENCRYPTION_KEY, key, SECURE_OPTIONS);
  return key;
}
