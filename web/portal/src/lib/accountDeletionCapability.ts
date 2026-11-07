import { useCallback, useSyncExternalStore } from 'react';

export const ACCOUNT_DELETION_CAPABILITY_STORAGE_PREFIX = 'br_account_deletion_capability_v2:';
export const ACCOUNT_DELETION_ACTIVE_WALLET_STORAGE_KEY = 'br_account_deletion_active_wallet_v2';
export const ACCOUNT_DELETION_STORAGE_PROBE_KEY = 'br_account_deletion_storage_probe_v2';
export const ACCOUNT_DELETION_UNCONFIRMED_STORAGE_PREFIX = 'br_account_deletion_unconfirmed_v1:';
export const ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY = 'br_account_deletion_unconfirmed_active_wallet_v1';
const ACCOUNT_DELETION_CAPABILITY_EVENT = 'br:account-deletion-capability';

export interface AccountDeletionCapability {
  version: 2;
  wallet: string;
  requestId: string;
  statusToken: string;
  createdAt: string;
}

interface AccountDeletionRecoveryEnvelope {
  version: 1;
  state: 'unconfirmed';
  capability: AccountDeletionCapability;
  persistedAt: string;
}

export type AccountDeletionCapabilitySnapshot =
  | { kind: 'none' }
  | { kind: 'unavailable' }
  | { kind: 'invalid' }
  | { kind: 'valid'; capability: AccountDeletionCapability };

const NONE_SNAPSHOT: AccountDeletionCapabilitySnapshot = Object.freeze({ kind: 'none' });
const UNAVAILABLE_SNAPSHOT: AccountDeletionCapabilitySnapshot = Object.freeze({ kind: 'unavailable' });
const INVALID_SNAPSHOT: AccountDeletionCapabilitySnapshot = Object.freeze({ kind: 'invalid' });
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STATUS_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;
const snapshotCache = new Map<string, {
  fingerprint: string;
  snapshot: AccountDeletionCapabilitySnapshot;
}>();

function isWallet(value: unknown): value is string {
  return typeof value === 'string'
    && value.length >= 16
    && value.length <= 128
    && value.trim() === value
    && !/\s/.test(value);
}

function isIsoDate(value: unknown): value is string {
  return typeof value === 'string' && Number.isFinite(Date.parse(value));
}

function decodeStatusToken(value: string): Uint8Array | null {
  if (!STATUS_TOKEN_PATTERN.test(value) || typeof atob !== 'function') return null;
  try {
    const decoded = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '=');
    if (decoded.length !== 32) return null;
    return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

export function getAccountDeletionCapabilityStorageKey(wallet: string): string {
  if (!isWallet(wallet)) throw new Error('A valid wallet is required for account deletion status.');
  return `${ACCOUNT_DELETION_CAPABILITY_STORAGE_PREFIX}${encodeURIComponent(wallet)}`;
}

export function getAccountDeletionRecoveryStorageKey(wallet: string): string {
  if (!isWallet(wallet)) throw new Error('A valid wallet is required for account deletion recovery.');
  return `${ACCOUNT_DELETION_UNCONFIRMED_STORAGE_PREFIX}${encodeURIComponent(wallet)}`;
}

export function parseAccountDeletionCapability(raw: string): AccountDeletionCapability | null {
  try {
    const parsed = JSON.parse(raw) as Partial<AccountDeletionCapability>;
    if (
      parsed.version !== 2
      || !isWallet(parsed.wallet)
      || typeof parsed.requestId !== 'string'
      || !UUID_PATTERN.test(parsed.requestId)
      || typeof parsed.statusToken !== 'string'
      || decodeStatusToken(parsed.statusToken) === null
      || !isIsoDate(parsed.createdAt)
    ) {
      return null;
    }
    return parsed as AccountDeletionCapability;
  } catch {
    return null;
  }
}

function parseAccountDeletionRecoveryEnvelope(raw: string): AccountDeletionRecoveryEnvelope | null {
  try {
    const parsed = JSON.parse(raw) as Partial<AccountDeletionRecoveryEnvelope>;
    const capability = parsed.capability
      ? parseAccountDeletionCapability(JSON.stringify(parsed.capability))
      : null;
    if (
      parsed.version !== 1
      || parsed.state !== 'unconfirmed'
      || !capability
      || !isIsoDate(parsed.persistedAt)
    ) {
      return null;
    }
    return {
      version: 1,
      state: 'unconfirmed',
      capability,
      persistedAt: parsed.persistedAt,
    };
  } catch {
    return null;
  }
}

export function getUnconfirmedAccountDeletionCapability(
  wallet: string,
): AccountDeletionCapability | null {
  const raw = window.localStorage.getItem(getAccountDeletionRecoveryStorageKey(wallet));
  if (raw === null) return null;
  const envelope = parseAccountDeletionRecoveryEnvelope(raw);
  if (!envelope || envelope.capability.wallet !== wallet) {
    throw new Error('The saved account deletion recovery request is invalid.');
  }
  return envelope.capability;
}

export function getActiveUnconfirmedAccountDeletionCapability(): AccountDeletionCapability | null {
  const wallet = window.localStorage.getItem(
    ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY,
  );
  if (wallet === null) return null;
  if (!isWallet(wallet)) {
    throw new Error('The saved account deletion recovery wallet is invalid.');
  }
  return getUnconfirmedAccountDeletionCapability(wallet);
}

export function persistUnconfirmedAccountDeletionCapability(
  capability: AccountDeletionCapability,
): void {
  const storageKey = getAccountDeletionRecoveryStorageKey(capability.wallet);
  const existingRaw = window.localStorage.getItem(storageKey);
  if (existingRaw !== null) {
    const existing = parseAccountDeletionRecoveryEnvelope(existingRaw);
    if (
      !existing
      || existing.capability.wallet !== capability.wallet
      || existing.capability.requestId !== capability.requestId
      || existing.capability.statusToken !== capability.statusToken
    ) {
      throw new Error('Another unconfirmed account deletion request is already saved.');
    }
    window.localStorage.setItem(
      ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY,
      capability.wallet,
    );
    if (window.localStorage.getItem(
      ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY,
    ) !== capability.wallet) {
      throw new Error('Account deletion recovery could not be activated on this device.');
    }
    return;
  }
  const envelope: AccountDeletionRecoveryEnvelope = {
    version: 1,
    state: 'unconfirmed',
    capability,
    persistedAt: new Date().toISOString(),
  };
  const serialized = JSON.stringify(envelope);
  window.localStorage.setItem(storageKey, serialized);
  window.localStorage.setItem(
    ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY,
    capability.wallet,
  );
  const readBack = window.localStorage.getItem(storageKey);
  const parsed = readBack ? parseAccountDeletionRecoveryEnvelope(readBack) : null;
  if (
    readBack !== serialized
    || !parsed
    || parsed.capability.requestId !== capability.requestId
    || parsed.capability.statusToken !== capability.statusToken
    || window.localStorage.getItem(
      ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY,
    ) !== capability.wallet
  ) {
    throw new Error('Account deletion recovery could not be saved on this device.');
  }
}

export function clearUnconfirmedAccountDeletionCapability(wallet: string): void {
  const storageKey = getAccountDeletionRecoveryStorageKey(wallet);
  window.localStorage.removeItem(storageKey);
  if (
    window.localStorage.getItem(
      ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY,
    ) === wallet
  ) {
    window.localStorage.removeItem(
      ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY,
    );
  }
  if (window.localStorage.getItem(storageKey) !== null) {
    throw new Error('Account deletion recovery could not be cleared on this device.');
  }
  if (
    window.localStorage.getItem(
      ACCOUNT_DELETION_UNCONFIRMED_ACTIVE_WALLET_STORAGE_KEY,
    ) === wallet
  ) {
    throw new Error('Account deletion recovery could not be cleared on this device.');
  }
}

function readSnapshot(wallet?: string | null): AccountDeletionCapabilitySnapshot {
  if (typeof window === 'undefined') return NONE_SNAPSHOT;
  const selector = wallet ? `wallet:${wallet}` : 'active';
  try {
    const resolvedWallet = wallet ?? window.localStorage.getItem(ACCOUNT_DELETION_ACTIVE_WALLET_STORAGE_KEY);
    if (resolvedWallet === null) {
      const cached = snapshotCache.get(selector);
      if (cached?.fingerprint === 'none') return cached.snapshot;
      snapshotCache.set(selector, { fingerprint: 'none', snapshot: NONE_SNAPSHOT });
      return NONE_SNAPSHOT;
    }
    if (!isWallet(resolvedWallet)) {
      snapshotCache.set(selector, { fingerprint: `invalid-wallet:${resolvedWallet}`, snapshot: INVALID_SNAPSHOT });
      return INVALID_SNAPSHOT;
    }
    const raw = window.localStorage.getItem(getAccountDeletionCapabilityStorageKey(resolvedWallet));
    const fingerprint = `${resolvedWallet}\u0000${raw ?? ''}`;
    const cached = snapshotCache.get(selector);
    if (cached?.fingerprint === fingerprint) return cached.snapshot;
    if (raw === null) {
      snapshotCache.set(selector, { fingerprint, snapshot: NONE_SNAPSHOT });
      return NONE_SNAPSHOT;
    }
    const capability = parseAccountDeletionCapability(raw);
    const snapshot = capability?.wallet === resolvedWallet
      ? { kind: 'valid' as const, capability }
      : INVALID_SNAPSHOT;
    snapshotCache.set(selector, { fingerprint, snapshot });
    return snapshot;
  } catch {
    return UNAVAILABLE_SNAPSHOT;
  }
}

function invalidateSnapshots() {
  snapshotCache.clear();
}

function emitCapabilityChange() {
  invalidateSnapshots();
  window.dispatchEvent(new Event(ACCOUNT_DELETION_CAPABILITY_EVENT));
}

function subscribe(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const handleChange = () => {
    invalidateSnapshots();
    listener();
  };
  window.addEventListener('storage', handleChange);
  window.addEventListener(ACCOUNT_DELETION_CAPABILITY_EVENT, handleChange);
  return () => {
    window.removeEventListener('storage', handleChange);
    window.removeEventListener(ACCOUNT_DELETION_CAPABILITY_EVENT, handleChange);
  };
}

function encodeStatusToken(bytes: Uint8Array): string {
  const binary = Array.from(bytes, (byte) => String.fromCharCode(byte)).join('');
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function createAccountDeletionCapability(wallet: string): AccountDeletionCapability {
  if (!isWallet(wallet)) throw new Error('A valid wallet is required for account deletion status.');
  const now = new Date().toISOString();
  const randomBytes = new Uint8Array(32);
  crypto.getRandomValues(randomBytes);
  return {
    version: 2,
    wallet,
    requestId: crypto.randomUUID(),
    statusToken: encodeStatusToken(randomBytes),
    createdAt: now,
  };
}

export function assertAccountDeletionStorageAvailable(wallet: string): void {
  const snapshot = readSnapshot(wallet);
  if (snapshot.kind === 'unavailable') {
    throw new Error('This browser cannot save account deletion status.');
  }
  if (snapshot.kind !== 'none') {
    throw new Error('An account deletion request is already saved for this wallet.');
  }
  const probe = crypto.randomUUID();
  try {
    window.localStorage.setItem(ACCOUNT_DELETION_STORAGE_PROBE_KEY, probe);
    if (window.localStorage.getItem(ACCOUNT_DELETION_STORAGE_PROBE_KEY) !== probe) {
      throw new Error('Browser storage verification failed.');
    }
    window.localStorage.removeItem(ACCOUNT_DELETION_STORAGE_PROBE_KEY);
    if (window.localStorage.getItem(ACCOUNT_DELETION_STORAGE_PROBE_KEY) !== null) {
      throw new Error('Browser storage cleanup failed.');
    }
  } catch {
    try {
      window.localStorage.removeItem(ACCOUNT_DELETION_STORAGE_PROBE_KEY);
    } catch {
      // The actionable storage error is reported below.
    }
    throw new Error('This browser cannot save account deletion status.');
  }
}

export function persistAccountDeletionCapability(capability: AccountDeletionCapability): void {
  const serialized = JSON.stringify(capability);
  const storageKey = getAccountDeletionCapabilityStorageKey(capability.wallet);
  const existing = window.localStorage.getItem(storageKey);
  if (existing !== null && existing !== serialized) {
    throw new Error('Another account deletion request is already saved for this wallet.');
  }
  window.localStorage.setItem(storageKey, serialized);
  const readBack = window.localStorage.getItem(storageKey);
  const parsed = readBack ? parseAccountDeletionCapability(readBack) : null;
  if (readBack !== serialized || !parsed || parsed.requestId !== capability.requestId) {
    throw new Error('Account deletion status could not be saved on this device.');
  }
  activateAccountDeletionCapability(capability.wallet);
}

export function activateAccountDeletionCapability(wallet: string): void {
  const snapshot = readSnapshot(wallet);
  if (snapshot.kind === 'none') {
    throw new Error('No account deletion status is saved for this wallet.');
  }
  if (snapshot.kind === 'unavailable') {
    throw new Error('This browser cannot read saved account deletion status.');
  }
  try {
    window.localStorage.setItem(ACCOUNT_DELETION_ACTIVE_WALLET_STORAGE_KEY, wallet);
    if (window.localStorage.getItem(ACCOUNT_DELETION_ACTIVE_WALLET_STORAGE_KEY) !== wallet) {
      throw new Error('Account deletion status could not be activated on this device.');
    }
  } catch {
    throw new Error('This browser cannot open saved account deletion status.');
  }
  emitCapabilityChange();
}

export async function withAccountDeletionCapabilityLock<T>(
  wallet: string,
  action: () => Promise<T>,
): Promise<T> {
  if (typeof navigator === 'undefined' || !navigator.locks) {
    return action();
  }
  return navigator.locks.request(
    `br:account-deletion-capability:${wallet}`,
    { mode: 'exclusive' },
    action,
  );
}

export function clearAccountDeletionCapability(wallet?: string | null): void {
  const resolvedWallet = wallet ?? window.localStorage.getItem(ACCOUNT_DELETION_ACTIVE_WALLET_STORAGE_KEY);
  if (resolvedWallet && isWallet(resolvedWallet)) {
    window.localStorage.removeItem(getAccountDeletionCapabilityStorageKey(resolvedWallet));
  }
  if (
    !wallet
    || window.localStorage.getItem(ACCOUNT_DELETION_ACTIVE_WALLET_STORAGE_KEY) === resolvedWallet
  ) {
    window.localStorage.removeItem(ACCOUNT_DELETION_ACTIVE_WALLET_STORAGE_KEY);
  }
  emitCapabilityChange();
}

export function getAccountDeletionCapabilitySnapshot(
  wallet?: string | null,
): AccountDeletionCapabilitySnapshot {
  return readSnapshot(wallet);
}

export function useAccountDeletionCapability(
  wallet?: string | null,
): AccountDeletionCapabilitySnapshot {
  const getSnapshot = useCallback(() => readSnapshot(wallet), [wallet]);
  return useSyncExternalStore(subscribe, getSnapshot, () => NONE_SNAPSHOT);
}
