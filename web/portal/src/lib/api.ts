/**
 * Boulder Roller API Client
 * Handles all backend communication with JWT auth
 */

import { getPublicRiderDisplayName } from './riderIdentity';
import { prepareBrowserImageUpload } from './imageUpload';
import type { Stage1Bonding, Stage1Payments, Stage1Pledge, Stage1Registration } from './stage1';

const API_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');

// Events - components can listen to these
export const SESSION_EXPIRED_EVENT = 'br:session-expired';
export const NETWORK_ERROR_EVENT = 'br:network-error';
export const NETWORK_RESTORED_EVENT = 'br:network-restored';

const LOCAL_DOGFOOD_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);

export function isDogfoodAutoLogoutDisabled(): boolean {
  if (!import.meta.env.DEV || typeof window === 'undefined') return false;
  if (!LOCAL_DOGFOOD_HOSTS.has(window.location.hostname)) return false;

  return String(import.meta.env.VITE_DOGFOOD_AUTO_LOGOUT || '').toLowerCase() !== 'true';
}

// Error types for better handling
export type ApiErrorType = 'session_expired' | 'network_error' | 'server_error' | 'unknown';

export class ApiError extends Error {
  type: ApiErrorType;
  statusCode?: number;
  retryable: boolean;
  detail?: Record<string, unknown>;

  constructor(message: string, type: ApiErrorType, statusCode?: number, detail?: Record<string, unknown>) {
    super(message);
    this.name = 'ApiError';
    this.type = type;
    this.statusCode = statusCode;
    this.retryable = type === 'network_error' || (statusCode !== undefined && statusCode >= 500);
    this.detail = detail;
  }
}

export type AccountDeletionStatusName =
  | 'queued'
  | 'processing'
  | 'blocked'
  | 'failed_retryable'
  | 'needs_support'
  | 'completed'
  | 'legacy_unverified';

export interface AccountDeletionBlocker {
  code: string;
  category: string;
  asset?: string | null;
  amountBaseUnits?: string | null;
  count?: number | null;
  source?: string | null;
  action?: string | null;
}

export interface AccountDeletionPreflight {
  contractVersion: 'account-deletion.v1';
  allowed: boolean;
  available: boolean;
  blockers: AccountDeletionBlocker[];
  checkedAt: string;
}

export interface AccountDeletionStatus {
  contractVersion: 'account-deletion.v1';
  requestId: string;
  status: AccountDeletionStatusName;
  requestedAt?: string | null;
  updatedAt?: string | null;
  completedAt?: string | null;
  blockers: AccountDeletionBlocker[];
  failureCode?: string | null;
  retryable: boolean;
  attemptCount: number;
}

export interface AccountDeletionStatusCapability {
  requestId: string;
  statusToken: string;
}

export interface AccountDeletionRequestCapability extends AccountDeletionStatusCapability {
  unuploadedRidesAcknowledged: true;
}

const ACCOUNT_DELETION_STATUSES = new Set<AccountDeletionStatusName>([
  'queued',
  'processing',
  'blocked',
  'failed_retryable',
  'needs_support',
  'completed',
  'legacy_unverified',
]);

function accountDeletionContractError(): ApiError {
  return new ApiError('Account deletion server response was invalid.', 'server_error');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isIsoTimestamp(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && Number.isFinite(Date.parse(value));
}

function isOptionalIsoTimestamp(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || isIsoTimestamp(value);
}

function parseAccountDeletionBlockers(value: unknown): AccountDeletionBlocker[] {
  if (!Array.isArray(value)) throw accountDeletionContractError();
  return value.map((item) => {
    if (
      !isRecord(item)
      || typeof item.code !== 'string'
      || typeof item.category !== 'string'
      || (item.asset !== undefined && item.asset !== null && typeof item.asset !== 'string')
      || (item.amountBaseUnits !== undefined && item.amountBaseUnits !== null && typeof item.amountBaseUnits !== 'string')
      || (item.count !== undefined && item.count !== null
        && (typeof item.count !== 'number' || !Number.isInteger(item.count) || item.count < 0))
      || (item.source !== undefined && item.source !== null && typeof item.source !== 'string')
      || (item.action !== undefined && item.action !== null && typeof item.action !== 'string')
    ) {
      throw accountDeletionContractError();
    }
    return item as unknown as AccountDeletionBlocker;
  });
}

function parseAccountDeletionPreflight(value: unknown): AccountDeletionPreflight {
  if (
    !isRecord(value)
    || value.contractVersion !== 'account-deletion.v1'
    || typeof value.allowed !== 'boolean'
    || typeof value.available !== 'boolean'
    || !isIsoTimestamp(value.checkedAt)
  ) {
    throw accountDeletionContractError();
  }
  const blockers = parseAccountDeletionBlockers(value.blockers);
  if (value.allowed && (!value.available || blockers.length > 0)) {
    throw accountDeletionContractError();
  }
  return { ...value, blockers } as AccountDeletionPreflight;
}

function parseAccountDeletionStatus(
  value: unknown,
  expectedRequestId: string,
): AccountDeletionStatus {
  if (
    !isRecord(value)
    || value.contractVersion !== 'account-deletion.v1'
    || value.requestId !== expectedRequestId
    || typeof value.status !== 'string'
    || !ACCOUNT_DELETION_STATUSES.has(value.status as AccountDeletionStatusName)
    || !isOptionalIsoTimestamp(value.requestedAt)
    || !isOptionalIsoTimestamp(value.updatedAt)
    || !isOptionalIsoTimestamp(value.completedAt)
    || (value.failureCode !== undefined && value.failureCode !== null && typeof value.failureCode !== 'string')
    || typeof value.retryable !== 'boolean'
    || !Number.isInteger(value.attemptCount)
    || (value.attemptCount as number) < 0
  ) {
    throw accountDeletionContractError();
  }
  const blockers = parseAccountDeletionBlockers(value.blockers);
  if (value.status === 'completed' && !isIsoTimestamp(value.completedAt)) {
    throw accountDeletionContractError();
  }
  return { ...value, blockers } as AccountDeletionStatus;
}

function emitSessionExpired(reason?: string) {
  if (isDogfoodAutoLogoutDisabled()) {
    console.info('[BR auth] Suppressed automatic session-expired modal for local dogfood.', { reason });
    return;
  }

  window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: { reason } }));
}

function emitNetworkError() {
  window.dispatchEvent(new CustomEvent(NETWORK_ERROR_EVENT));
}

function emitNetworkRestored() {
  window.dispatchEvent(new CustomEvent(NETWORK_RESTORED_EVENT));
}

// Detect if we're offline
function isOffline(): boolean {
  return typeof navigator !== 'undefined' && !navigator.onLine;
}

// Case conversion utilities
const toSnakeCase = (obj: unknown): unknown => {
  if (Array.isArray(obj)) return obj.map(toSnakeCase);
  if (obj instanceof Date) return obj.toISOString();
  if (obj && typeof obj === 'object' && !(obj instanceof File) && !(obj instanceof Blob)) {
    return Object.entries(obj).reduce<Record<string, unknown>>((acc, [key, val]) => {
      const snakeKey = key.replace(/([A-Z])/g, '_$1').toLowerCase();
      acc[snakeKey] = toSnakeCase(val);
      return acc;
    }, {});
  }
  return obj;
};

const toCamelCase = (obj: unknown): unknown => {
  if (Array.isArray(obj)) return obj.map(toCamelCase);
  if (obj && typeof obj === 'object') {
    return Object.entries(obj).reduce<Record<string, unknown>>((acc, [key, val]) => {
      const camelKey = key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
      acc[camelKey] = toCamelCase(val);
      return acc;
    }, {});
  }
  return obj;
};

// Session event types
type SessionEventType = 'session_warning' | 'session_expired' | 'session_restored';
type SessionEventCallback = (event: SessionEventType, data?: { minutesRemaining?: number }) => void;

class APIClient {
  // Auth state - cookie-first (HttpOnly cookies owned by the backend)
  private _isAuthenticated: boolean = false;
  private _accessToken: string | null = null;
  private _tokenExpiresAt: number | null = null;
  private refreshPromise: Promise<boolean> | null = null;
  private proactiveRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  private sessionWarningTimer: ReturnType<typeof setTimeout> | null = null;
  private _isOnline: boolean = true;
  private _lastNetworkError: number | null = null;
  private sessionEventCallbacks: Set<SessionEventCallback> = new Set();
  private onboardingStatePromise: Promise<OnboardingState> | null = null;
  private onboardingStateCache: { value: OnboardingState; timestamp: number } | null = null;
  private authBootstrapPromise: Promise<AuthBootstrapState> | null = null;
  private authBootstrapCache: { value: AuthBootstrapState; timestamp: number } | null = null;
  private authBootstrapCacheEpoch = 0;
  private authBootstrapRequestId = 0;
  // Retry configuration
  private readonly MAX_RETRIES = 3;
  private readonly RETRY_DELAY_MS = 1000;
  private readonly PROACTIVE_REFRESH_BUFFER_MS = 5 * 60 * 1000; // 5 minutes before expiry
  private readonly NON_RETRYABLE_ENDPOINTS = new Set([
    '/auth/verify',
    '/auth/privy/verify',
    '/auth/invite/validate',
    '/auth/bootstrap',
    '/auth/onboarding/state',
    '/geocoding/search',
  ]);
  private readonly ONBOARDING_CACHE_TTL_MS = 1500;
  private readonly AUTH_BOOTSTRAP_CACHE_TTL_MS = 1500;

  constructor() {
    this._isAuthenticated = this.readStoredAuthenticationHint();
    // Enforce cookie-only sessions by purging any legacy token fallback data.
    this.clearStoredTokenFallback();

    // Listen for online/offline events
    if (typeof window !== 'undefined') {
      window.addEventListener('online', this.handleOnline.bind(this));
      window.addEventListener('offline', this.handleOffline.bind(this));
      this._isOnline = navigator.onLine;
    }

    // Schedule proactive refresh if we have a token
    if (this._isAuthenticated && this._tokenExpiresAt) {
      this.scheduleProactiveRefresh();
    }
  }

  private readStoredAuthenticationHint(): boolean {
    if (typeof window === 'undefined') return false;
    try {
      return window.localStorage.getItem('br_authenticated') === 'true';
    } catch {
      return false;
    }
  }

  private writeStoredAuthenticationHint(authenticated: boolean): void {
    if (typeof window === 'undefined') return;
    try {
      if (authenticated) {
        window.localStorage.setItem('br_authenticated', 'true');
      } else {
        window.localStorage.removeItem('br_authenticated');
      }
    } catch {
      // This hint is optional; the server-owned cookie remains authoritative.
    }
  }

  private handleOnline() {
    const wasOffline = !this._isOnline;
    this._isOnline = true;
    if (wasOffline) {
      emitNetworkRestored();
      // Try to refresh token if we were offline and session might have expired
      if (this._isAuthenticated) {
        this.refreshAccessToken().catch(() => {});
      }
    }
  }

  private handleOffline() {
    this._isOnline = false;
    emitNetworkError();
  }

  isOnline(): boolean {
    return this._isOnline && !isOffline();
  }

  getLastNetworkError(): number | null {
    return this._lastNetworkError;
  }

  /**
   * Subscribe to session events (warning, expired, restored)
   */
  onSessionEvent(callback: SessionEventCallback): () => void {
    this.sessionEventCallbacks.add(callback);
    return () => this.sessionEventCallbacks.delete(callback);
  }

  private emitSessionEvent(event: SessionEventType, data?: { minutesRemaining?: number }) {
    this.sessionEventCallbacks.forEach(cb => cb(event, data));
  }

  // Session warning buffer - warn 5 minutes before expiry
  private readonly SESSION_WARNING_BUFFER_MS = 5 * 60 * 1000; // 5 minutes

  private scheduleSessionWarning() {
    if (this.sessionWarningTimer) {
      clearTimeout(this.sessionWarningTimer);
    }

    if (!this._tokenExpiresAt) return;

    const now = Date.now();
    const timeUntilWarning = this._tokenExpiresAt - now - this.SESSION_WARNING_BUFFER_MS;

    if (timeUntilWarning <= 0) {
      // Already within warning window
      const minutesRemaining = Math.max(0, Math.round((this._tokenExpiresAt - now) / 60000));
      if (minutesRemaining > 0) {
        this.emitSessionEvent('session_warning', { minutesRemaining });
      }
      return;
    }

    this.sessionWarningTimer = setTimeout(() => {
      if (this._tokenExpiresAt) {
        const minutesRemaining = Math.max(0, Math.round((this._tokenExpiresAt - Date.now()) / 60000));
        this.emitSessionEvent('session_warning', { minutesRemaining });
      }
    }, timeUntilWarning);
  }

  private scheduleProactiveRefresh() {
    if (this.proactiveRefreshTimer) {
      clearTimeout(this.proactiveRefreshTimer);
    }

    if (!this._tokenExpiresAt) return;

    const now = Date.now();
    const timeUntilRefresh = this._tokenExpiresAt - now - this.PROACTIVE_REFRESH_BUFFER_MS;

    if (timeUntilRefresh <= 0) {
      // Token is about to expire or already expired, refresh now
      this.refreshAccessToken().catch(() => {});
      return;
    }

    this.proactiveRefreshTimer = setTimeout(() => {
      this.refreshAccessToken().catch(() => {});
    }, timeUntilRefresh);
  }

  private parseTokenExpiry(token: string): number | null {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.exp) {
        return payload.exp * 1000; // Convert to milliseconds
      }
    } catch {
      // Invalid token format
    }
    return null;
  }

  private getAuthErrorCode(error: unknown): string | null {
    if (!(error instanceof ApiError) || !error.detail) return null;
    const nested = error.detail.error;
    if (nested && typeof nested === 'object') {
      const code = (nested as Record<string, unknown>).code;
      return typeof code === 'string' ? code : null;
    }
    const code = error.detail.code;
    return typeof code === 'string' ? code : null;
  }

  /**
   * Mark the client as authenticated after successful login.
   * The actual tokens are stored in HttpOnly cookies by the server.
   */
  setAuthenticated(authenticated: boolean) {
    this._isAuthenticated = authenticated;
    this.writeStoredAuthenticationHint(authenticated);
  }

  /**
   * Cache access token metadata in-memory only.
   * Source of truth for auth is HttpOnly cookies set by backend.
   */
  setTokens(access: string, _refresh?: string) {
    this._accessToken = access;

    // Parse and store token expiry
    const expiresAt = this.parseTokenExpiry(access);
    this._tokenExpiresAt = expiresAt;
    this.clearStoredTokenFallback();

    this.setAuthenticated(true);
    this.clearOnboardingStateCache();

    // Schedule proactive refresh and warning
    this.scheduleProactiveRefresh();
    this.scheduleSessionWarning();
  }

  /**
   * Clear authentication state and notify the server to clear cookies.
   */
  clearTokens() {
    this._isAuthenticated = false;
    this._accessToken = null;
    this._tokenExpiresAt = null;

    if (this.proactiveRefreshTimer) {
      clearTimeout(this.proactiveRefreshTimer);
      this.proactiveRefreshTimer = null;
    }

    if (this.sessionWarningTimer) {
      clearTimeout(this.sessionWarningTimer);
      this.sessionWarningTimer = null;
    }

    this.writeStoredAuthenticationHint(false);
    this.clearStoredTokenFallback();
    this.clearOnboardingStateCache();
  }

  isAuthenticated(): boolean {
    if (!this._isAuthenticated) return false;
    // Don't report authenticated if token is already expired
    if (this._tokenExpiresAt && Date.now() > this._tokenExpiresAt) {
      return false;
    }
    return true;
  }

  /**
   * Get in-memory access token (used for diagnostics/session metadata only).
   */
  getAccessToken(): string | null {
    return this._accessToken;
  }

  private async request<T>(
    path: string,
    options: RequestInit & {
      skipAuth?: boolean;
      retrying?: boolean;
      retryCount?: number;
      disableRetry?: boolean;
      forceNetworkProbe?: boolean;
      suppressNetworkErrorEvent?: boolean;
    } = {}
  ): Promise<T> {
    const {
      skipAuth,
      retrying,
      retryCount = 0,
      disableRetry = false,
      forceNetworkProbe = false,
      suppressNetworkErrorEvent = false,
      ...fetchOptions
    } = options;
    const normalizedPath = path.split('?')[0];
    const canRetry = !disableRetry && !this.NON_RETRYABLE_ENDPOINTS.has(normalizedPath);
    const headers = new Headers(fetchOptions.headers);

    // Check if we're offline before making the request
    if (!forceNetworkProbe && !this.isOnline()) {
      this._lastNetworkError = Date.now();
      throw new ApiError('No internet connection', 'network_error');
    }

    if (!headers.has('Content-Type') && !(fetchOptions.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }

    // Send in-memory access token as Authorization header for cross-domain support.
    // HttpOnly cookies with SameSite=Lax are silently dropped on cross-site fetch().
    if (!skipAuth && this._accessToken && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${this._accessToken}`);
    }

    let response: Response;
    try {
      // Cookies sent as secondary auth (same-site only); header is primary for cross-domain.
      response = await fetch(`${API_URL}${path}`, {
        ...fetchOptions,
        headers,
        credentials: 'include',
      });
    } catch (fetchError) {
      const errorName = fetchError instanceof Error ? fetchError.name : '';
      if (fetchOptions.signal?.aborted || errorName === 'AbortError') {
        throw new ApiError('Request cancelled', 'unknown', 499);
      }

      // Network error (no response received)
      this._lastNetworkError = Date.now();
      if (!suppressNetworkErrorEvent) {
        this._isOnline = false;
        emitNetworkError();
      }

      // Retry on network error
      if (canRetry && retryCount < this.MAX_RETRIES) {
        await new Promise(resolve => setTimeout(resolve, this.RETRY_DELAY_MS * (retryCount + 1)));
        return this.request<T>(path, { ...options, retryCount: retryCount + 1 });
      }

      throw new ApiError(
        'Network error. Please check your connection.',
        'network_error'
      );
    }

    // Network is working if we got a response
    if (!this._isOnline) {
      this._isOnline = true;
      emitNetworkRestored();
    }

    // Handle 401 - try refresh using cookie-based refresh token
    if (response.status === 401 && !skipAuth && !retrying) {
      const refreshed = await this.refreshAccessToken(fetchOptions.signal ?? undefined);
      if (refreshed) {
        if (disableRetry) throw new ApiError('Session refreshed; operation status must be checked.', 'unknown', 401);
        return this.request<T>(path, { ...options, retrying: true });
      }
      // Refresh failed - session has expired
      if (!isDogfoodAutoLogoutDisabled()) {
        this.clearTokens();
      } else {
        console.info('[BR auth] Kept local dogfood auth marker after failed token refresh.', { path });
      }
      emitSessionExpired('token_expired');
      throw new ApiError('Session expired', 'session_expired', 401);
    }

    // Handle server errors with retry
    if (canRetry && response.status >= 500 && retryCount < this.MAX_RETRIES) {
      await new Promise(resolve => setTimeout(resolve, this.RETRY_DELAY_MS * (retryCount + 1)));
      return this.request<T>(path, { ...options, retryCount: retryCount + 1 });
    }

    const text = await response.text();
    if (!response.ok) {
      const errorType: ApiErrorType = response.status >= 500 ? 'server_error' : 'unknown';

      // Try to parse JSON error response for additional details
      let message = text || response.statusText;
      let detail: Record<string, unknown> | undefined;

      try {
        const errorJson = JSON.parse(text);
        // FastAPI returns errors in {detail: ...} format
        if (typeof errorJson.detail === 'object') {
          detail = errorJson.detail;
          const detailRecord = errorJson.detail as Record<string, unknown>;
          const nestedError = detailRecord.error;
          if (nestedError && typeof nestedError === 'object') {
            const nestedRecord = nestedError as Record<string, unknown>;
            if (typeof nestedRecord.message === 'string' && nestedRecord.message.trim()) {
              message = nestedRecord.message;
            } else if (typeof nestedRecord.error === 'string' && nestedRecord.error.trim()) {
              message = nestedRecord.error;
            }
          } else if (typeof detailRecord.message === 'string' && detailRecord.message.trim()) {
            message = detailRecord.message;
          } else if (typeof detailRecord.error === 'string' && detailRecord.error.trim()) {
            message = detailRecord.error;
          }
        } else if (typeof errorJson.detail === 'string') {
          message = errorJson.detail;
        } else if (errorJson.message) {
          message = errorJson.message;
        }
      } catch {
        // Not JSON, use raw text as message
      }

      throw new ApiError(message, errorType, response.status, detail);
    }

    if (!text) return undefined as T;
    return toCamelCase(JSON.parse(text)) as T;
  }

  private async awaitWithSignal<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
    if (!signal) return promise;
    if (signal.aborted) {
      throw new ApiError('Request cancelled', 'unknown', 499);
    }

    return new Promise<T>((resolve, reject) => {
      const handleAbort = () => {
        reject(new ApiError('Request cancelled', 'unknown', 499));
      };
      const cleanup = () => signal.removeEventListener('abort', handleAbort);

      signal.addEventListener('abort', handleAbort, { once: true });
      promise.then(
        (value) => {
          cleanup();
          resolve(value);
        },
        (error) => {
          cleanup();
          reject(error);
        },
      );
    });
  }

  private async waitForRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
    if (!signal) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
      return;
    }

    if (signal.aborted) {
      throw new ApiError('Request cancelled', 'unknown', 499);
    }

    await new Promise<void>((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        signal.removeEventListener('abort', handleAbort);
        resolve();
      }, delayMs);
      const handleAbort = () => {
        clearTimeout(timeoutId);
        reject(new ApiError('Request cancelled', 'unknown', 499));
      };

      signal.addEventListener('abort', handleAbort, { once: true });
    });
  }

  private async performRefreshAccessToken(retryCount: number, signal?: AbortSignal): Promise<boolean> {
    try {
      const result = await this.post<{ accessToken: string; refreshToken?: string }>(
        '/auth/refresh',
        { deviceId: this.getDeviceId() },
        { skipAuth: true, signal },
      );

      if (signal?.aborted) {
        throw new ApiError('Request cancelled', 'unknown', 499);
      }

      if (result.accessToken) {
        // Cache latest token metadata in-memory (cookies are updated by server)
        this.setTokens(result.accessToken, result.refreshToken);
        return true;
      }
      return false;
    } catch (error) {
      if (signal?.aborted || (error instanceof ApiError && error.statusCode === 499)) {
        throw error instanceof ApiError
          ? error
          : new ApiError('Request cancelled', 'unknown', 499);
      }

      const authCode = this.getAuthErrorCode(error);
      const canRetryRotated = authCode === 'refresh_rotated' && retryCount < this.MAX_RETRIES;
      const canRetryNetwork = error instanceof ApiError
        && error.type === 'network_error'
        && retryCount < this.MAX_RETRIES;
      if (canRetryRotated || canRetryNetwork) {
        await this.waitForRetry(this.RETRY_DELAY_MS * (retryCount + 1), signal);
        return this.performRefreshAccessToken(retryCount + 1, signal);
      }

      // Refresh failed - clear auth state unless localhost dogfood is keeping the surface open.
      if (!isDogfoodAutoLogoutDisabled()) {
        this.clearTokens();
      } else {
        console.info('[BR auth] Ignoring failed refresh during local dogfood session.');
      }
      return false;
    }
  }

  private async refreshAccessToken(signal?: AbortSignal): Promise<boolean> {
    // Only try refresh if we think we're authenticated
    if (!this._isAuthenticated) return false;
    if (this.refreshPromise) {
      return this.awaitWithSignal(this.refreshPromise, signal);
    }

    const refreshWork = this.performRefreshAccessToken(0, signal);
    this.refreshPromise = refreshWork;
    const clearRefreshWork = () => {
      if (this.refreshPromise === refreshWork) {
        this.refreshPromise = null;
      }
    };
    void refreshWork.then(clearRefreshWork, clearRefreshWork);
    return this.awaitWithSignal(refreshWork, signal);
  }

  // HTTP methods
  async get<T>(path: string, options?: RequestInit & { skipAuth?: boolean; disableRetry?: boolean; forceNetworkProbe?: boolean; suppressNetworkErrorEvent?: boolean }): Promise<T> {
    return this.request<T>(path, { ...options, method: 'GET' });
  }

  async post<T>(path: string, body?: unknown, options?: RequestInit & { skipAuth?: boolean; disableRetry?: boolean; forceNetworkProbe?: boolean; suppressNetworkErrorEvent?: boolean }): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: 'POST',
      body: body ? JSON.stringify(toSnakeCase(body)) : undefined,
    });
  }

  async put<T>(path: string, body?: unknown, options?: RequestInit & { skipAuth?: boolean; disableRetry?: boolean; forceNetworkProbe?: boolean; suppressNetworkErrorEvent?: boolean }): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: 'PUT',
      body: body ? JSON.stringify(toSnakeCase(body)) : undefined,
    });
  }

  async delete<T>(path: string, options?: RequestInit & { skipAuth?: boolean; disableRetry?: boolean; forceNetworkProbe?: boolean; suppressNetworkErrorEvent?: boolean }): Promise<T> {
    return this.request<T>(path, { ...options, method: 'DELETE' });
  }

  // ==================== AUTH ====================

  private getDeviceId(): string {
    let deviceId = localStorage.getItem('br_device_id');
    if (!deviceId) {
      deviceId = crypto.randomUUID();
      localStorage.setItem('br_device_id', deviceId);
    }
    return deviceId;
  }

  async getNonce(wallet: string): Promise<{ nonce: string; message: string; expiresAt: string }> {
    return this.post('/auth/nonce', { wallet, deviceId: this.getDeviceId() }, { skipAuth: true });
  }

  async verifySignature(
    wallet: string,
    signature: string,
    nonce: string,
    inviteCode?: string
  ): Promise<AuthTokenResponse> {
    const result = await this.post<AuthTokenResponse>(
      '/auth/verify',
      { wallet, signature, nonce, deviceId: this.getDeviceId(), inviteCode },
      { skipAuth: true }
    );
    this.clearOnboardingStateCache();
    this.setTokens(result.accessToken, result.refreshToken);
    return result;
  }

  async verifyPrivyToken(
    wallet: string,
    privyToken: string,
    inviteCode?: string
  ): Promise<AuthTokenResponse> {
    const result = await this.post<AuthTokenResponse>(
      '/auth/privy/verify',
      { wallet, privyToken, deviceId: this.getDeviceId(), inviteCode },
      { skipAuth: true }
    );
    this.clearOnboardingStateCache();
    this.setTokens(result.accessToken, result.refreshToken);
    return result;
  }

  async getMe(options?: RequestInit): Promise<User> {
    return this.get('/users/me', options);
  }

  async getThreshold(options?: RequestInit): Promise<ThresholdResponse> {
    return this.get('/users/me/threshold', options);
  }

  async getAuthBootstrap(options: {
    forceRemote?: boolean;
    signal?: AbortSignal;
    useAuthHeader?: boolean;
  } = {}): Promise<AuthBootstrapState> {
    const now = Date.now();
    const canUsePublicCache = !options.useAuthHeader && !options.forceRemote && !options.signal;
    if (
      canUsePublicCache
      && this.authBootstrapCache
      && now - this.authBootstrapCache.timestamp < this.AUTH_BOOTSTRAP_CACHE_TTL_MS
    ) {
      return this.authBootstrapCache.value;
    }

    if (canUsePublicCache && this.authBootstrapPromise) {
      return this.authBootstrapPromise;
    }

    const requestEpoch = this.authBootstrapCacheEpoch;
    const requestId = ++this.authBootstrapRequestId;
    let bootstrapPromise: Promise<AuthBootstrapState>;
    bootstrapPromise = this.get<AuthBootstrapState>('/auth/bootstrap', {
      signal: options.signal,
      skipAuth: !options.useAuthHeader,
    })
      .then((bootstrap) => {
        if (
          requestEpoch === this.authBootstrapCacheEpoch
          && requestId === this.authBootstrapRequestId
        ) {
          this.authBootstrapCache = {
            value: bootstrap,
            timestamp: Date.now(),
          };

          const onboarding: OnboardingState = {
            authenticated: bootstrap.authenticated,
            inviteRequired: bootstrap.inviteRequired,
            inviteValidated: bootstrap.inviteValidated,
            needsProfileSetup: bootstrap.needsProfileSetup,
            authMethodHint: bootstrap.authMethodHint,
          };

          this.onboardingStateCache = {
            value: onboarding,
            timestamp: Date.now(),
          };
        }

        return bootstrap;
      })
      .finally(() => {
        if (this.authBootstrapPromise === bootstrapPromise) {
          this.authBootstrapPromise = null;
        }
      });

    if (canUsePublicCache) {
      this.authBootstrapPromise = bootstrapPromise;
    }

    return bootstrapPromise;
  }

  async getOnboardingState(): Promise<OnboardingState> {
    const now = Date.now();
    if (this.onboardingStateCache && now - this.onboardingStateCache.timestamp < this.ONBOARDING_CACHE_TTL_MS) {
      return this.onboardingStateCache.value;
    }

    if (this.onboardingStatePromise) {
      return this.onboardingStatePromise;
    }

    const requestEpoch = this.authBootstrapCacheEpoch;
    const bootstrapPromise = this.getAuthBootstrap();
    const requestId = this.authBootstrapRequestId;
    this.onboardingStatePromise = bootstrapPromise
      .then((state) => {
        const onboarding: OnboardingState = {
          authenticated: state.authenticated,
          inviteRequired: state.inviteRequired,
          inviteValidated: state.inviteValidated,
          needsProfileSetup: state.needsProfileSetup,
          authMethodHint: state.authMethodHint,
        };

        if (
          requestEpoch === this.authBootstrapCacheEpoch
          && requestId === this.authBootstrapRequestId
        ) {
          this.onboardingStateCache = {
            value: onboarding,
            timestamp: Date.now(),
          };
        }
        return onboarding;
      })
      .finally(() => {
        this.onboardingStatePromise = null;
      });

    return this.onboardingStatePromise;
  }

  async validateInviteCode(code: string, wallet?: string): Promise<InviteValidationResult> {
    const result = await this.post<InviteValidationResult>('/auth/invite/validate', { code, wallet }, { skipAuth: true });
    this.clearOnboardingStateCache();
    return result;
  }

  async joinWaitlist(email: string, source = 'portal_access'): Promise<WaitlistResult> {
    return this.post<WaitlistResult>('/waitlist', { email, source }, { skipAuth: true });
  }

  async clearInviteState(): Promise<{ status: string }> {
    const result = await this.post<{ status: string }>('/auth/invite/clear', undefined, { skipAuth: true });
    this.clearOnboardingStateCache();
    return result;
  }

  async logout(): Promise<void> {
    try {
      await this.post('/auth/logout', { deviceId: this.getDeviceId() }, { skipAuth: true });
    } finally {
      this.clearOnboardingStateCache();
      this.clearTokens();
    }
  }

  private clearOnboardingStateCache() {
    this.authBootstrapCacheEpoch += 1;
    this.onboardingStatePromise = null;
    this.onboardingStateCache = null;
    this.authBootstrapPromise = null;
    this.authBootstrapCache = null;
  }

  private clearStoredTokenFallback() {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.removeItem('br_access_token');
      window.localStorage.removeItem('br_refresh_token');
      window.localStorage.removeItem('br_token_expires_at');
    } catch {
      // Legacy cleanup is best-effort and must not prevent cookie authentication.
    }
  }

  /**
   * Check if a username is available
   */
  async checkUsernameAvailability(username: string): Promise<{ available: boolean; message?: string }> {
    return this.post('/users/check-username', { username });
  }

  /**
   * Export user data (GDPR compliant)
   */
  async exportUserData(): Promise<ExportUserDataResponse> {
    return this.get('/compliance/export');
  }

  // ==================== RIDES ====================

  async getRides(options?: { limit?: number; offset?: number }): Promise<Ride[]> {
    const params = new URLSearchParams();
    if (options?.limit != null) params.set('limit', String(options.limit));
    if (options?.offset != null) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.get(`/rides${query ? `?${query}` : ''}`);
  }

  async getRide(id: string): Promise<Ride> {
    return this.get(`/rides/${id}`);
  }

  async getRideDetail(id: string, options?: { commentsLimit?: number }): Promise<RideDetailResponse> {
    const params = new URLSearchParams();
    if (options?.commentsLimit != null) params.set('comments_limit', String(options.commentsLimit));
    const query = params.toString();
    return this.get(`/rides/${id}/detail${query ? `?${query}` : ''}`);
  }

  async uploadRide(
    file: File,
    options: { signal?: AbortSignal; privacy?: RidePrivacyChoice } = {},
  ): Promise<{ rideId: string; status: string }> {
    // Direct upload is the canonical browser path. The inline/base64 route is
    // kept only as an explicit rollback switch during cutover.
    if (import.meta.env.VITE_LEGACY_INLINE_UPLOAD === 'true') {
      const base64 = await this.fileToBase64(file);
      const ext = file.name.split('.').pop()?.toLowerCase();
      const fileType = ext && ['fit', 'gpx', 'tcx'].includes(ext) ? ext : 'fit';
      return this.post('/rides/upload', {
        fileDataB64: base64,
        fileType,
        ...options.privacy,
      }, options);
    }
    return this.uploadRideDirect(file, options);
  }

  /**
   * Upload a ride file using presigned URL (direct-to-storage).
   *
   * Flow:
   *   1. Compute SHA-256 hash of file
   *   2. POST /rides/upload/init -> get signed URL
   *   3. PUT multipart form data directly to Supabase Storage via signed URL
   *   4. POST /rides/upload/complete -> trigger processing
   *
   * Falls back to abort on upload failure.
   */
  async uploadRideDirect(
    file: File,
    options: { signal?: AbortSignal; privacy?: RidePrivacyChoice } = {},
  ): Promise<{ rideId: string; status: string }> {
    const ext = file.name.split('.').pop()?.toLowerCase();
    const fileType = ext && ['fit', 'gpx', 'tcx'].includes(ext) ? ext : 'fit';

    // 1. Compute SHA-256 hash
    const fileHash = await this.computeFileHash(file);

    // 2. Init - get presigned URL
    const initResult = await this.post<{ uploadId: string; signedUrl: string; expiresIn: number }>(
      '/rides/upload/init',
      { fileType, fileHash, fileSize: file.size, ...options.privacy },
      options,
    );

    // 3. PUT directly to storage
    let uploadOk = false;
    try {
      // Supabase signed upload URLs expect the file in a multipart "file"
      // field. Raw bytes can return a successful response without creating the
      // object that /upload/complete later verifies.
      const formData = new FormData();
      formData.append('file', file, file.name);

      const uploadResp = await fetch(initResult.signedUrl, {
        method: 'PUT',
        body: formData,
        headers: { 'x-upsert': 'false' },
        signal: options.signal,
      });
      uploadOk = uploadResp.ok;
      if (!uploadOk) {
        throw new Error(`Storage upload failed: ${uploadResp.status} ${uploadResp.statusText}`);
      }
    } catch (err) {
      // Abort on failure so the ride row is cleaned up
      try {
        await this.post('/rides/upload/abort', { uploadId: initResult.uploadId });
      } catch {
        // Best-effort abort
      }
      throw err instanceof ApiError ? err : new ApiError(
        options.signal?.aborted ? 'Upload cancelled' : err instanceof Error ? err.message : 'Direct upload failed',
        'unknown',
        options.signal?.aborted ? 499 : undefined,
      );
    }

    // 4. Complete - trigger processing
    let result: { rideId: string; status: string };
    try {
      result = await this.post<{ rideId: string; status: string }>(
        '/rides/upload/complete',
        { uploadId: initResult.uploadId },
        options,
      );
    } catch (err) {
      try {
        await this.post('/rides/upload/abort', { uploadId: initResult.uploadId });
      } catch {
        // Best-effort abort
      }
      throw err;
    }

    return result;
  }

  private async computeFileHash(file: File): Promise<string> {
    const buffer = await file.arrayBuffer();
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async getRideStatus(rideId: string, options?: RequestInit & { skipAuth?: boolean }): Promise<RideStatus> {
    return this.get(`/rides/${rideId}/status`, options);
  }

  async updateRide(rideId: string, updates: {
    title?: string;
    description?: string;
    activityType?: string;
    visibility?: RideVisibility;
    mapVisibility?: RideMapVisibility;
    mapHideStartM?: MapHideDistanceM;
    mapHideEndM?: MapHideDistanceM;
    commentsEnabled?: boolean;
    hideFromLeaderboards?: boolean;
  }): Promise<{ status: string }> {
    return this.patch(`/rides/${rideId}`, updates);
  }

  async initRideMediaUpload(
    rideId: string,
    file: File,
    sortOrder: number,
  ): Promise<{ mediaId: string; signedUrl: string; expiresIn: number }> {
    return this.post(`/rides/${rideId}/media/init`, {
      fileName: file.name,
      mimeType: file.type || 'image/jpeg',
      fileSize: file.size,
      sortOrder,
      role: sortOrder === 0 ? 'cover' : 'photo',
    });
  }

  async completeRideMediaUpload(rideId: string, mediaId: string): Promise<RideMedia> {
    return this.post(`/rides/${rideId}/media/complete`, { mediaId });
  }

  async uploadRideMedia(rideId: string, file: File, sortOrder = 0): Promise<RideMedia> {
    const uploadFile = await prepareBrowserImageUpload(file, {
      fileNamePrefix: `ride-${rideId}-photo-${sortOrder + 1}`,
      maxDimension: 2048,
      maxBytes: 4 * 1024 * 1024,
    });
    const initResult = await this.initRideMediaUpload(rideId, uploadFile, sortOrder);
    const formData = new FormData();
    formData.append('file', uploadFile, uploadFile.name);

    const uploadResp = await fetch(initResult.signedUrl, {
      method: 'PUT',
      body: formData,
      headers: { 'x-upsert': 'false' },
    });
    if (!uploadResp.ok) {
      throw new ApiError(
        `Photo upload failed: ${uploadResp.status} ${uploadResp.statusText}`,
        'unknown',
        uploadResp.status,
      );
    }

    return this.completeRideMediaUpload(rideId, initResult.mediaId);
  }

  async uploadRideMediaBatch(rideId: string, files: File[]): Promise<RideMedia[]> {
    const cappedFiles = files.slice(0, 6);
    const uploaded: RideMedia[] = [];
    for (const [index, file] of cappedFiles.entries()) {
      uploaded.push(await this.uploadRideMedia(rideId, file, index));
    }
    return uploaded;
  }

  async updateRideMedia(
    rideId: string,
    mediaId: string,
    updates: { role?: 'photo' | 'cover'; sortOrder?: number },
  ): Promise<RideMedia> {
    return this.patch(`/rides/${rideId}/media/${mediaId}`, updates);
  }

  async reorderRideMedia(
    rideId: string,
    items: Array<{ mediaId: string; sortOrder: number }>,
  ): Promise<RideMedia[]> {
    return this.patch(`/rides/${rideId}/media/reorder`, { items });
  }

  async initAvatarUpload(file: File): Promise<{ uploadId: string; signedUrl: string; expiresIn: number }> {
    return this.post('/users/me/avatar/init', {
      fileName: file.name,
      mimeType: file.type || 'image/jpeg',
      fileSize: file.size,
    });
  }

  async completeAvatarUpload(uploadId: string): Promise<User> {
    return this.post('/users/me/avatar/complete', { uploadId });
  }

  async uploadAvatar(file: File): Promise<User> {
    const uploadFile = await prepareBrowserImageUpload(file, {
      fileNamePrefix: 'rider-avatar',
      maxDimension: 1024,
      maxBytes: 2 * 1024 * 1024,
    });
    const initResult = await this.initAvatarUpload(uploadFile);
    const formData = new FormData();
    formData.append('file', uploadFile, uploadFile.name);

    const uploadResp = await fetch(initResult.signedUrl, {
      method: 'PUT',
      body: formData,
      headers: { 'x-upsert': 'false' },
    });
    if (!uploadResp.ok) {
      throw new ApiError(
        `Avatar upload failed: ${uploadResp.status} ${uploadResp.statusText}`,
        'unknown',
        uploadResp.status,
      );
    }

    return this.completeAvatarUpload(initResult.uploadId);
  }

  async deleteAvatar(): Promise<User> {
    return this.delete('/users/me/avatar');
  }

  async deleteRideMedia(rideId: string, mediaId: string): Promise<{ status: string; mediaId: string }> {
    return this.delete(`/rides/${rideId}/media/${mediaId}`);
  }

  async deleteRide(rideId: string): Promise<{ status: string; rideId: string }> {
    return this.delete(`/rides/${rideId}`);
  }

  async getRideGps(rideId: string): Promise<GpsResponse> {
    return this.get(`/rides/${rideId}/gps`);
  }

  async getRideStream(rideId: string, type: 'power' | 'heart_rate' | 'cadence' | 'speed' | 'temperature'): Promise<StreamResponse> {
    return this.get(`/rides/${rideId}/streams?type=${type}`);
  }

  async getRideTelemetry(rideId: string, options: { includeGps?: boolean } = {}): Promise<TelemetryData> {
    const includeGps = options.includeGps ?? true;
    // Fetch streams in parallel. GPS can be omitted when the caller already has
    // the route polyline and only needs the expensive analysis streams.
    const [gps, power, hr, cadence, speed, temperature] = await Promise.allSettled([
      includeGps ? this.getRideGps(rideId) : Promise.resolve(null),
      this.getRideStream(rideId, 'power'),
      this.getRideStream(rideId, 'heart_rate'),
      this.getRideStream(rideId, 'cadence'),
      this.getRideStream(rideId, 'speed'),
      this.getRideStream(rideId, 'temperature'),
    ]);

    return {
      gps: gps.status === 'fulfilled' ? gps.value : null,
      power: power.status === 'fulfilled' ? power.value : null,
      heartRate: hr.status === 'fulfilled' ? hr.value : null,
      cadence: cadence.status === 'fulfilled' ? cadence.value : null,
      speed: speed.status === 'fulfilled' ? speed.value : null,
      temperature: temperature.status === 'fulfilled' ? temperature.value : null,
    };
  }

  async getRideTiles(rideId: string): Promise<TilesResponse> {
    return this.get(`/rides/${rideId}/tiles`);
  }

  async getRidePatterns(rideId: string): Promise<PatternsResponse> {
    return this.get(`/rides/${rideId}/patterns`);
  }

  // Comments
  async getRideComments(rideId: string): Promise<{ comments: Comment[] }> {
    return this.get(`/rides/${rideId}/comments`);
  }

  async getRideInteractions(rideId: string): Promise<RideInteractions> {
    return this.get(`/rides/${rideId}/interactions`);
  }

  async addRideComment(rideId: string, content: string, parentId?: string): Promise<Comment> {
    return this.post(`/rides/${rideId}/comments`, { content, parentId });
  }

  async updateRideComment(rideId: string, commentId: string, content: string): Promise<Comment> {
    return this.patch(`/rides/${rideId}/comments/${commentId}`, { content });
  }

  async deleteRideComment(rideId: string, commentId: string): Promise<{ status: string; commentId: string }> {
    return this.delete(`/rides/${rideId}/comments/${commentId}`);
  }

  async reportSocialContent(
    targetType: 'ride' | 'comment' | 'user' | 'ride_media',
    targetId: string,
    reason: string,
    details?: string
  ): Promise<SocialReport> {
    return this.post('/social/reports', { targetType, targetId, reason, details });
  }

  async getModerationReports(options?: {
    status?: string;
    limit?: number;
    offset?: number;
  }): Promise<ModerationReportsResponse> {
    const params = new URLSearchParams();
    if (options?.status) params.set('report_status', options.status);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.get(`/admin/moderation/reports${query ? `?${query}` : ''}`);
  }

  async resolveModerationReport(
    reportId: string,
    status: 'open' | 'reviewing' | 'resolved' | 'dismissed',
    resolutionNote?: string,
    action?: 'review_started' | 'leave_visible' | 'hide' | 'remove' | 'unsupported',
    reporterMessage?: string,
  ): Promise<SocialReport> {
    return this.patch(`/admin/moderation/reports/${reportId}`, { status, action, resolutionNote, reporterMessage });
  }

  // Kudos
  async giveKudos(rideId: string): Promise<{ status: string }> {
    return this.post(`/rides/${rideId}/kudos`, {});
  }

  async removeKudos(rideId: string): Promise<{ status: string }> {
    return this.delete(`/rides/${rideId}/kudos`);
  }

  private async fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        resolve(result.split(',')[1]);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }

  // ==================== CLIMBS ====================
  // Canonical API targets `/climbs/*`. Backend keeps `/segments/*` as a
  // back-compat alias (mfab.5 Phase A) so in-flight sessions never break.
  // The alias is scheduled for retirement in wdvr.8 tail cleanup.

  async getClimbs(options?: { q?: string; bbox?: string; limit?: number }): Promise<{ climbs: Climb[] }> {
    const params = new URLSearchParams();
    if (options?.q) params.set('q', options.q);
    if (options?.bbox) params.set('bbox', options.bbox);
    if (options?.limit) params.set('limit', String(options.limit));
    const query = params.toString();
    const response = await this.get(`/climbs/list${query ? `?${query}` : ''}`);
    const payload = toCamelCase(response) as { climbs?: Climb[]; segments?: Climb[] };
    return { climbs: payload.climbs ?? payload.segments ?? [] };
  }

  async searchLocations(query: string): Promise<GeocodingSearchResponse> {
    const response = await this.post('/geocoding/search', { query });
    return toCamelCase(response) as GeocodingSearchResponse;
  }

  async getClimb(climbId: string): Promise<Climb> {
    const response = await this.get(`/climbs/${climbId}`);
    return toCamelCase(response) as Climb;
  }

  async getClimbEffort(effortId: string): Promise<ClimbEffort> {
    return this.get(`/climbs/efforts/${encodeURIComponent(effortId)}`, { disableRetry: true });
  }

  async getPopularClimbs(limit = 6): Promise<{ climbs: PopularClimb[] }> {
    const response = await this.get(`/climbs/popular?limit=${limit}`, { skipAuth: true });
    const payload = toCamelCase(response) as { climbs?: PopularClimb[]; segments?: PopularClimb[] };
    return { climbs: payload.climbs ?? payload.segments ?? [] };
  }

  async getLeaderboard(climbId: string, epochNumber = 1, limit = 100): Promise<LeaderboardResponse> {
    const response = await this.get(`/climbs/${climbId}/leaderboard`);
    const payload = toCamelCase(response) as {
      contractVersion?: 'client.v1';
      truthSource?: TruthSource;
      source?: 'onchain' | 'rides';
      earlierVersionId?: string | null;
      climbId?: string;
      climbName?: string;
      segmentId?: string;
      segmentName?: string;
      vaultId?: number | string;
      entries?: VaultLeaderboardEntry[];
      leaderboard?: VaultLeaderboardEntry[];
      viewerEntry?: VaultLeaderboardEntry | null;
      komHolder?: string | null;
      komTimeS?: number | null;
    };

    const rawEntries = payload.entries ?? payload.leaderboard ?? [];
    const entries = rawEntries.slice(0, limit).map((entry) => ({
      ...entry,
      rank: entry.rank,
      userId: entry.userId ?? entry.wallet,
      displayName: entry.displayName,
      avatarUrl: entry.avatarUrl,
      timeS: entry.bestTimeSeconds,
      avgPowerW: entry.avgPowerW,
    }));

    return {
      contractVersion: payload.contractVersion,
      truthSource: payload.truthSource,
      source: payload.source,
      earlierVersionId: payload.earlierVersionId,
      entries,
      leaderboard: entries,
      climbId: String(payload.climbId ?? payload.segmentId ?? payload.vaultId ?? climbId),
      climbName: payload.climbName ?? payload.segmentName ?? null,
      vaultId: payload.vaultId != null ? Number(payload.vaultId) : null,
      komHolder: payload.komHolder ?? null,
      komTimeS: payload.komTimeS ?? null,
      epochNumber,
      total: entries.length,
      viewerEntry: payload.viewerEntry,
    };
  }

  async getGlobalLeaderboard(
    type: 'climb' | 'steady' | 'exploration',
    period: 'today' | 'week' | 'month' | 'all_time' = 'week'
  ): Promise<GlobalLeaderboardResponse> {
    return this.get(`/leaderboard/${type}?period=${period}`, { skipAuth: true });
  }

  // ==================== SOCIAL ====================

  async getFeed(options?: { limit?: number; before?: string | Date }): Promise<FeedResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.before) {
      params.set('before', options.before instanceof Date ? options.before.toISOString() : options.before);
    }
    const query = params.toString();
    return this.get(`/feed${query ? `?${query}` : ''}`);
  }

  async getGlobalFeed(options?: { limit?: number; before?: string | Date }): Promise<FeedResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.before) {
      params.set('before', options.before instanceof Date ? options.before.toISOString() : options.before);
    }
    const query = params.toString();
    return this.get(`/feed/global${query ? `?${query}` : ''}`, { skipAuth: true });
  }

  async getHomeFeed(options?: {
    scope?: 'following' | 'global';
    limit?: number;
    before?: string | Date;
    sidecarLimit?: number;
  }): Promise<HomeFeedResponse> {
    const params = new URLSearchParams();
    params.set('scope', options?.scope ?? 'global');
    params.set('limit', String(options?.limit ?? 20));
    if (options?.sidecarLimit) params.set('sidecar_limit', String(options.sidecarLimit));
    if (options?.before) {
      params.set('before', options.before instanceof Date ? options.before.toISOString() : options.before);
    }
    return this.get(`/feed/home?${params.toString()}`, { skipAuth: options?.scope === 'global' });
  }

  async getSuggestedRiders(limit = 10): Promise<{ suggestions: SuggestedRider[] }> {
    return this.get(`/social/suggested?limit=${limit}`);
  }

  async followUser(userId: string): Promise<{ status: string }> {
    return this.post(`/social/follow/${userId}`);
  }

  async unfollowUser(userId: string): Promise<{ status: string }> {
    return this.delete(`/social/follow/${userId}`);
  }

  async checkIsFollowing(userId: string): Promise<{ isFollowing: boolean }> {
    return this.get(`/social/is-following/${userId}`);
  }

  async getFollowers(userId: string): Promise<UserProfilePublic[]> {
    return this.get(`/social/followers/${userId}`);
  }

  async getFollowing(userId: string): Promise<UserProfilePublic[]> {
    return this.get(`/social/following/${userId}`);
  }

  // ==================== SYSTEM STATUS ====================

  /**
   * Get system status including feature flags like stub mode.
   * This endpoint is public and doesn't require auth.
   */
  async getStatus(): Promise<SystemStatus> {
    return this.get('/status', { skipAuth: true });
  }

  async getStage1Hill(climbId: string): Promise<{ hill: string | null }> {
    return this.get(`/stage1/climbs/${encodeURIComponent(climbId)}/hill`, { skipAuth: true });
  }

  async getStage1Bonding(hill: string): Promise<Stage1Bonding> {
    return this.get(`/stage1/hills/${encodeURIComponent(hill)}/bonding`, { skipAuth: true });
  }

  async getStage1Registration(hill?: string): Promise<Stage1Registration> {
    return this.get(`/stage1/me/registration${hill ? `?hill=${encodeURIComponent(hill)}` : ''}`);
  }

  async getStage1Pay(kind: 'pay' | 'dung', hill?: string, offset = 0): Promise<Stage1Payments> {
    const params = new URLSearchParams({ limit: '50', offset: String(offset) });
    if (hill) params.set('hill', hill);
    return this.get(`/stage1/me/${kind}?${params}`);
  }

  async getStage1Pledges(hill?: string, offset = 0): Promise<{ pledges: Stage1Pledge[] }> {
    const params = new URLSearchParams({ limit: '50', offset: String(offset) });
    if (hill) params.set('hill', hill);
    return this.get(`/stage1/me/pledges?${params}`);
  }

  async getStage1Eligibility(lot: string): Promise<{ actions: Record<string, { refreshRate: boolean }>; chainTime: string; week: string; withdrawalsPausedUntil?: string }> {
    return this.post('/stage1/me/eligibility', { lot }, { disableRetry: true });
  }
  async getStage1Lookups(offset = 0): Promise<{ tables: Array<{ address: string; state: 'active' | 'cooling' | 'closeable' | 'missing' }>; nextOffset: number | null }> {
    return this.get(`/stage1/me/lookups?offset=${offset}`, { disableRetry: true });
  }
  async getStage1Claims(offset = 0): Promise<{ claims: import('./stage1Actions').Stage1Claim[]; nextOffset: number | null }> {
    return this.get(`/stage1/me/claims?limit=10&offset=${offset}`);
  }
  async prepareStage1(plan: import('./stage1Actions').Stage1Plan): Promise<PreparedBalanceAction> {
    return this.post(`/stage1/me/${plan.action}/prepare`, plan.request, { disableRetry: true });
  }
  async submitStage1(plan: import('./stage1Actions').Stage1Plan, signedTransaction: string, lastValidBlockHeight: number, clientRequestId: string): Promise<PreparedBalanceAction> {
    return this.post(`/stage1/me/${plan.action}`, { ...plan.request, signedTransaction, lastValidBlockHeight, clientRequestId }, { disableRetry: true });
  }
  async stage1Operation(action: string, reference: string, clientRequestId: string, operationId?: string): Promise<RiderBalanceOperationStatus> {
    const params = new URLSearchParams({ reference_type: 'stage1', reference_id: reference, action_type: `stage1_${action.replace(/-/g, '_')}`, client_request_id: clientRequestId });
    return this.get(operationId ? `/balance/operations/${encodeURIComponent(operationId)}` : `/balance/operations/lookup?${params}`, { disableRetry: true });
  }

  // ==================== CAL/TOKENS ====================

  async getCALBalance(): Promise<{ calBalance: string; calBalanceBaseUnits: string; canMintToday: boolean }> {
    // Use on-chain CAL balance from Solana UserState PDA
    const result = await this.get<CalOnchainResponse>('/cal/onchain');
    return {
      calBalance: result.calBalance ?? '0',
      calBalanceBaseUnits: result.calBalanceBaseUnits ?? '0',
      canMintToday: false, // No manual minting - CAL comes from admin crediting
    };
  }

  async getMyDistributions(options?: { limit?: number; offset?: number }): Promise<MyDistributionsResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.get(`/distributions/my${query ? `?${query}` : ''}`);
  }

  async getVaultDistributionHistory(vaultId: number, limit = 20): Promise<VaultDistributionHistoryResponse> {
    return this.get(`/distributions/vault/${vaultId}?limit=${limit}`);
  }

  async getCurrentEpoch(): Promise<CurrentEpochResponse> {
    return this.get('/distributions/epoch/current');
  }

  // ==================== PORTFOLIO ====================

  async getPortfolio(): Promise<Portfolio> {
    return this.get('/portfolio');
  }

  async getPortfolioSnapshot(options?: { limit?: number; offset?: number }): Promise<PortfolioSnapshot> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    const query = params.toString();
    return this.get(`/portfolio/snapshot${query ? `?${query}` : ''}`);
  }

  async prepareBalanceAddFunds(data: {
    asset: 'CAL' | 'USDC';
    amountBaseUnits: string;
  }): Promise<PreparedBalanceAction> {
    return this.post('/portfolio/balance/add-funds/prepare', data);
  }

  async submitBalanceAddFunds(data: {
    asset: 'CAL' | 'USDC';
    amountBaseUnits: string;
    signedTransaction: string;
    lastValidBlockHeight: number;
    clientRequestId?: string;
  }): Promise<PreparedBalanceAction> {
    return this.post('/portfolio/balance/add-funds', data);
  }

  async prepareBalanceWithdrawToWallet(data: {
    asset: 'CAL' | 'USDC' | 'DUNG';
    amountBaseUnits: string;
  }): Promise<PreparedBalanceAction> {
    return this.post('/portfolio/balance/withdraw-to-wallet/prepare', data);
  }

  async submitBalanceWithdrawToWallet(data: {
    asset: 'CAL' | 'USDC' | 'DUNG';
    amountBaseUnits: string;
    signedTransaction: string;
    lastValidBlockHeight: number;
    clientRequestId?: string;
  }): Promise<PreparedBalanceAction> {
    return this.post('/portfolio/balance/withdraw-to-wallet', data);
  }

  // ==================== ANALYTICS ====================

  async getRideTraining(rideId: string, start?: number, end?: number): Promise<RideTrainingMetrics | null> {
    const span = start !== undefined && end !== undefined ? `?start_s=${Math.floor(start)}&end_s=${Math.ceil(end)}` : '';
    return this.get(`/rides/${rideId}/training${span}`);
  }

  async getRidingDays(days = 182): Promise<RidingDays> {
    const zone = encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone);
    return this.get(`/analytics/riding-days?days=${days}&timezone=${zone}`);
  }

  async getPowerCurve(): Promise<PowerCurve> {
    return this.get('/analytics/power-curve');
  }

  async getFitnessMetrics(): Promise<FitnessMetrics> {
    const zone = encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone);
    return this.get(`/analytics/fitness?timezone=${zone}`);
  }

  async getTrainingLoad(days = 28): Promise<TrainingLoad> {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    // Atomic on the server: keep a configured preference, initialize only absence.
    // A failed preference write must not hide the available training read.
    await this.post('/analytics/timezone', { timezone }).catch(() => undefined);
    return this.get(`/analytics/training-load?days=${days}&timezone=${encodeURIComponent(timezone)}`);
  }

  // ==================== PROFILE ====================

  async updateProfile(data: Partial<UserProfile>): Promise<User> {
    const user = await this.put<User>('/users/me', data);
    this.clearOnboardingStateCache();
    return user;
  }

  async getPrivacySettings(): Promise<PrivacySettings> {
    return this.get('/privacy/settings');
  }

  async updatePrivacySettings(data: {
    shareWkg?: boolean;
    isPublic?: boolean;
    defaultRideVisibility?: RideVisibility;
    defaultMapVisibility?: RideMapVisibility;
    defaultMapHideStartM?: MapHideDistanceM;
    defaultMapHideEndM?: MapHideDistanceM;
  }): Promise<PrivacySettings> {
    return this.put('/privacy/settings', data);
  }

  // ==================== LEADERBOARD POSITIONS ====================

  async getMyLeaderboardPositions(): Promise<UserLeaderboardSummaryResponse> {
    return this.get('/users/me/leaderboard-positions');
  }

  async getUserLeaderboardPositions(wallet: string): Promise<UserLeaderboardSummaryResponse> {
    return this.get(`/users/${wallet}/leaderboard-positions`);
  }

  // ==================== ACHIEVEMENTS ====================

  async getMyAchievements(): Promise<AchievementsResponse> {
    return this.get('/users/me/achievements');
  }

  // ==================== ACCOUNT MANAGEMENT ====================

  async getAccountDeletionPreflight(): Promise<AccountDeletionPreflight> {
    const response = await this.get<unknown>('/compliance/account/preflight', {
      disableRetry: true,
      forceNetworkProbe: true,
      suppressNetworkErrorEvent: true,
      cache: 'no-store',
    });
    return parseAccountDeletionPreflight(response);
  }

  async requestAccountDeletion(
    capability: AccountDeletionRequestCapability,
  ): Promise<AccountDeletionStatus> {
    const response = await this.request<unknown>('/compliance/account', {
      method: 'DELETE',
      body: JSON.stringify(toSnakeCase({
        requestId: capability.requestId,
        statusToken: capability.statusToken,
        unuploadedRidesAcknowledged: capability.unuploadedRidesAcknowledged,
      })),
      disableRetry: true,
      forceNetworkProbe: true,
      suppressNetworkErrorEvent: true,
      cache: 'no-store',
    });
    return parseAccountDeletionStatus(response, capability.requestId);
  }

  async getAccountDeletionStatus(
    capability: AccountDeletionStatusCapability,
  ): Promise<AccountDeletionStatus> {
    const response = await this.get<unknown>(`/compliance/deletion-status/${encodeURIComponent(capability.requestId)}`, {
      skipAuth: true,
      disableRetry: true,
      forceNetworkProbe: true,
      suppressNetworkErrorEvent: true,
      cache: 'no-store',
      headers: { 'X-Account-Deletion-Token': capability.statusToken },
    });
    return parseAccountDeletionStatus(response, capability.requestId);
  }

  async retryAccountDeletion(
    capability: AccountDeletionStatusCapability,
  ): Promise<AccountDeletionStatus> {
    const response = await this.post<unknown>(
      `/compliance/deletion-status/${encodeURIComponent(capability.requestId)}/retry`,
      {},
      {
        skipAuth: true,
        disableRetry: true,
        forceNetworkProbe: true,
        suppressNetworkErrorEvent: true,
        cache: 'no-store',
        headers: { 'X-Account-Deletion-Token': capability.statusToken },
      },
    );
    return parseAccountDeletionStatus(response, capability.requestId);
  }

  // ==================== SESSION MANAGEMENT ====================

  async listSessions(): Promise<SessionsListResponse> {
    return this.get('/users/me/sessions');
  }

  async revokeSession(sessionId: string): Promise<{ status: string; count: number }> {
    return this.delete(`/users/me/sessions/${sessionId}`);
  }

  async revokeAllOtherSessions(): Promise<{ status: string; count: number }> {
    return this.delete('/users/me/sessions');
  }

  // ==================== PUBLIC PROFILES ====================

  async getPublicProfile(identifier: string): Promise<PublicProfile> {
    return this.get(`/users/${encodeURIComponent(identifier)}`);
  }

  async getRidePublicPreview(
    rideId: string,
    endpoint: 'rides' | 'activities' = 'rides'
  ): Promise<RidePublicPreview> {
    const response = await this.get(`/public/previews/${endpoint}/${encodeURIComponent(rideId)}`, { skipAuth: true });
    return toCamelCase(response) as RidePublicPreview;
  }

  async getClimbPublicPreview(climbId: string): Promise<ClimbPublicPreview> {
    const response = await this.get(`/public/previews/climbs/${encodeURIComponent(climbId)}`, { skipAuth: true });
    return toCamelCase(response) as ClimbPublicPreview;
  }

  async getRiderPublicPreview(identifier: string, limit = 5): Promise<RiderPublicPreview> {
    const params = new URLSearchParams({ limit: String(limit) });
    const response = await this.get(
      `/public/previews/riders/${encodeURIComponent(identifier)}?${params.toString()}`,
      { skipAuth: true }
    );
    return toCamelCase(response) as RiderPublicPreview;
  }

  async getPublicRiderProfile(identifier: string, limit = 10): Promise<PublicRiderProfileResponse> {
    return this.get(`/users/${encodeURIComponent(identifier)}/profile?limit=${limit}`);
  }

  async getPublicRiderRecentRides(identifier: string, limit = 10): Promise<PublicRiderRecentRidesResponse> {
    return this.get(`/users/${encodeURIComponent(identifier)}/recent-rides?limit=${limit}`);
  }

  async getPublicRiderBeetleCards(identifier: string): Promise<PublicRiderBeetleCardsResponse> {
    return this.get(`/users/${encodeURIComponent(identifier)}/beetle-cards`);
  }

  // ==================== LINKS / SHARE ====================

  async getLinkSchema(): Promise<LinkSchemaResponse> {
    return this.get('/links/schema');
  }

  async resolveLink(targetType: LinkTargetType, targetId: string): Promise<ResolvedLink> {
    const params = new URLSearchParams({
      target_type: targetType,
      target_id: targetId,
    });
    return this.get(`/links/resolve?${params.toString()}`);
  }

  async resolveLinkUrl(url: string): Promise<ResolvedLink> {
    const params = new URLSearchParams({ url });
    return this.get(`/links/resolve?${params.toString()}`);
  }

  // ==================== SEARCH ====================

  async search(options: { q: string; type?: SearchType; limit?: number }): Promise<SearchResponse> {
    const params = new URLSearchParams();
    params.set('q', options.q);
    if (options.type) params.set('type', options.type);
    if (options.limit) params.set('limit', String(options.limit));
    return this.get(`/search?${params.toString()}`);
  }

  async getSearchSuggestions(options?: { limit?: number }): Promise<SearchSuggestionsResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    const query = params.toString();
    return this.get(`/search/suggestions${query ? `?${query}` : ''}`);
  }

  async getSearchSchema(): Promise<SearchSchemaResponse> {
    return this.get('/search/schema');
  }

  // ==================== VAULTS ====================

  async getVaults(options?: { limit?: number; offset?: number; search?: string }): Promise<VaultsListResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    if (options?.search) params.set('search', options.search);
    const query = params.toString();
    return this.get(`/vaults${query ? `?${query}` : ''}`);
  }

  async getVault(id: number): Promise<VaultDetail> {
    return this.get(`/vaults/${id}`);
  }

  async getVaultLeaderboard(vaultId: number): Promise<VaultLeaderboardResponse> {
    return this.get(`/vaults/${vaultId}/leaderboard`, { disableRetry: true });
  }

  async matchVaultSignatures(signatures: string[]): Promise<VaultMatchResponse> {
    return this.post('/vaults/match', { signatures });
  }

  async recordVaultCompletion(
    vaultId: number,
    data: { activityId: string; timeSeconds: number; avgPowerW?: number }
  ): Promise<VaultCompletionResponse> {
    return this.post(`/vaults/${vaultId}/complete`, data);
  }

  async prepareStakeInVault(vaultId: number, calAmount: number): Promise<PreparedVaultTransaction> {
    return this.post(`/vaults/${vaultId}/stake/prepare`, { cal_amount: calAmount });
  }

  async stakeInVault(
    vaultId: number,
    calAmount: number,
    signedTransaction?: string,
    lastValidBlockHeight?: number,
    clientRequestId?: string,
  ): Promise<VaultStakeResponse> {
    return this.post(`/vaults/${vaultId}/stake`, {
      cal_amount: calAmount,
      signed_transaction: signedTransaction,
      last_valid_block_height: lastValidBlockHeight,
      client_request_id: clientRequestId,
    }, { disableRetry: true });
  }

  async prepareUnstakeFromVault(
    vaultId: number,
    input: VaultUnstakeInput,
  ): Promise<PreparedVaultTransaction> {
    return this.post(`/vaults/${vaultId}/unstake/prepare`, input.withdrawAll
      ? { withdraw_all: true }
      : { lp_amount_base_units: input.lpAmountBaseUnits });
  }

  async unstakeFromVault(
    vaultId: number,
    input: VaultUnstakeInput,
    signedTransaction?: string,
    lastValidBlockHeight?: number,
    clientRequestId?: string,
  ): Promise<VaultUnstakeResponse> {
    return this.post(`/vaults/${vaultId}/unstake`, {
      ...(input.withdrawAll
        ? { withdraw_all: true }
        : { lp_amount_base_units: input.lpAmountBaseUnits }),
      signed_transaction: signedTransaction,
      last_valid_block_height: lastValidBlockHeight,
      client_request_id: clientRequestId,
    }, { disableRetry: true });
  }

  async getVaultPendingRewards(vaultId: number): Promise<VaultPendingRewardsResponse> {
    return this.request<VaultPendingRewardsResponse>(`/vaults/${vaultId}/pending-rewards`);
  }

  async harvestVaultRewards(
    vaultId: number,
    submission?: {
      signedTransaction?: string;
      lastValidBlockHeight?: number;
      clientRequestId?: string;
    },
  ): Promise<VaultHarvestResponse> {
    return this.request<VaultHarvestResponse>(`/vaults/${vaultId}/harvest`, {
      method: 'POST',
      disableRetry: true,
      body: submission ? JSON.stringify(toSnakeCase(submission)) : undefined,
    });
  }

  async lookupVaultOperation(vaultId: number, actionType: string, clientRequestId: string, operationId?: string): Promise<RiderBalanceOperationStatus> {
    const params = new URLSearchParams({ reference_type: 'vault', reference_id: String(vaultId), action_type: actionType, client_request_id: clientRequestId });
    return this.get(operationId ? `/balance/operations/${encodeURIComponent(operationId)}` : `/balance/operations/lookup?${params}`, { disableRetry: true });
  }

  async getMyVaultStakes(): Promise<{ stakes: VaultStake[] }> {
    return this.get('/vaults/my/stakes');
  }

  async getMyVaultCompletions(): Promise<{ completions: VaultCompletion[] }> {
    return this.get('/vaults/my/completions');
  }

  async getMyVaultEffortHistory(vaultId: number, limit = 50): Promise<UserEffortHistoryResponse> {
    return this.get(`/vaults/${vaultId}/my-completions?limit=${limit}`);
  }

  async prepareCreateVault(data: {
    climbId: string;
    paymentMethod: VaultCreationPaymentMethod;
    clientRequestId: string;
  }): Promise<PreparedVaultCreation> {
    return this.post('/vaults/create/canon/prepare', {
      climb_id: data.climbId,
      payment_method: data.paymentMethod,
      client_request_id: data.clientRequestId,
    });
  }

  async createVault(data: {
    preparationId: string;
    signedTransaction: string;
  }): Promise<CreateVaultResponse> {
    return this.post('/vaults/create/canon/submit', {
      preparation_id: data.preparationId,
      signed_transaction: data.signedTransaction,
    });
  }

  // PATCH method needed for ride updates
  async patch<T>(path: string, body?: unknown, options?: RequestInit & { skipAuth?: boolean }): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: 'PATCH',
      body: body ? JSON.stringify(toSnakeCase(body)) : undefined,
    });
  }

  // ==================== BEETLE CARDS ====================

  async getMyBeetleCards(): Promise<BeetleCard[]> {
    return this.get('/beetles/my-cards');
  }

  async getBeetleCard(cardType: BeetleCardType, scopeId?: string): Promise<BeetleCard> {
    const params = scopeId ? `?scope_id=${scopeId}` : '';
    return this.get(`/beetles/my-cards/${cardType.toLowerCase()}${params}`);
  }

  async getBeetleLevelInfo(): Promise<BeetleLevelInfo> {
    return this.get('/beetles/levels');
  }

  async getBeetleLeaderboard(
    cardType: BeetleCardType,
    scopeId?: string,
    limit = 50,
    offset = 0
  ): Promise<BeetleLeaderboardResponse> {
    const params = new URLSearchParams({
      ...(scopeId && { scope_id: scopeId }),
      limit: limit.toString(),
      offset: offset.toString(),
    });
    return this.get(`/beetles/leaderboard/${cardType.toLowerCase()}?${params}`);
  }

  // ==================== STRAVA INTEGRATION ====================

  async getStravaAuthUrl(): Promise<StravaAuthUrlResponse> {
    return this.get('/strava/auth/url');
  }

  async exchangeStravaCode(code: string, state: string): Promise<StravaConnectionResponse> {
    return this.get(`/strava/auth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`);
  }

  async getStravaConnection(): Promise<StravaConnectionResponse> {
    return this.get('/strava/connection');
  }

  async disconnectStrava(): Promise<{ success: boolean; message: string }> {
    return this.delete('/strava/connection');
  }

  async getStravaActivities(page = 1, perPage = 30): Promise<StravaActivitiesResponse> {
    return this.get(`/strava/activities?page=${page}&per_page=${perPage}`);
  }

  async importStravaActivities(
    activityIds: number[],
    privacy: RidePrivacyChoice,
  ): Promise<StravaImportResponse> {
    return this.post('/strava/import', { activityIds, ...privacy });
  }

  // ==================== TERRITORY ====================

  async getTerritoryTiles(limit = 10000): Promise<TerritoryTilesResponse> {
    return this.get(`/territory/tiles?limit=${limit}`);
  }

  async getTerritoryStats(): Promise<TerritoryStats> {
    return this.get('/territory/stats');
  }

  async getTerritoryHeatmap(resolution = 7): Promise<TerritoryHeatmapResponse> {
    return this.get(`/territory/heatmap?resolution=${resolution}`);
  }

  // ==================== NOTIFICATIONS ====================

  async getNotifications(options?: {
    limit?: number;
    unreadOnly?: boolean;
  }): Promise<NotificationsResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.unreadOnly) params.set('unread_only', 'true');
    const query = params.toString();
    return this.get(`/notifications${query ? `?${query}` : ''}`);
  }

  async markNotificationRead(notificationId: string): Promise<{ status: string }> {
    return this.post(`/notifications/${notificationId}/read`);
  }

  async markAllNotificationsRead(): Promise<{ status: string; count: number }> {
    return this.post('/notifications/read-all');
  }

  async getNotificationPreferences(): Promise<NotificationPreferences> {
    return this.get('/notifications/preferences');
  }

  async updateNotificationPreferences(prefs: NotificationPreferences): Promise<NotificationPreferences> {
    return this.put('/notifications/preferences', prefs);
  }

  // ==================== ADMIN: SIGNIFICANCE DASHBOARD ====================

  async checkAdmin(): Promise<{ isAdmin: boolean; role: string | null }> {
    return this.get('/admin/check');
  }

  async getSignificanceOverview(): Promise<SignificanceOverview> {
    return this.get('/admin/significance/overview');
  }

  async getSignificanceClimbs(params?: {
    limit?: number;
    offset?: number;
    minG?: number;
    confidenceTier?: number;
    sort?: string;
  }): Promise<SignificanceClimbsResponse> {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    if (params?.minG !== undefined) qs.set('min_g', String(params.minG));
    if (params?.confidenceTier !== undefined) qs.set('confidence_tier', String(params.confidenceTier));
    if (params?.sort) qs.set('sort', params.sort);
    const q = qs.toString();
    return this.get(`/admin/significance/climbs${q ? `?${q}` : ''}`);
  }

  async getSignificanceCells(params?: {
    limit?: number;
    confidenceTier?: number;
    resolution?: number;
    diversityTier?: number;
    minUniqueRiders?: number;
  }): Promise<SignificanceCellsResponse> {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.confidenceTier !== undefined) qs.set('confidence_tier', String(params.confidenceTier));
    if (params?.resolution) qs.set('resolution', String(params.resolution));
    if (params?.diversityTier !== undefined) qs.set('diversity_tier', String(params.diversityTier));
    if (params?.minUniqueRiders !== undefined) qs.set('min_unique_riders', String(params.minUniqueRiders));
    const q = qs.toString();
    return this.get(`/admin/significance/cells${q ? `?${q}` : ''}`);
  }

  async getSignificanceCellDetail(h3Index: string): Promise<SignificanceCellDetail> {
    return this.get(`/admin/significance/cells/${h3Index}`);
  }

  async triggerTerrainBootstrap(minRidesPerCell?: number): Promise<{ cellsFitted: number; message: string }> {
    const qs = minRidesPerCell ? `?min_rides_per_cell=${minRidesPerCell}` : '';
    return this.post(`/admin/significance/bootstrap${qs}`);
  }

  async getBackfillCandidates(limit?: number): Promise<BackfillCandidatesResponse> {
    return this.get(`/admin/significance/backfill-candidates${limit ? `?limit=${limit}` : ''}`);
  }

  async backfillScores(params?: { limit?: number; dryRun?: boolean; staleOnly?: boolean }): Promise<BackfillScoresResponse> {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.dryRun) qs.set('dry_run', 'true');
    if (params?.staleOnly) qs.set('stale_only', 'true');
    const q = qs.toString();
    return this.post(`/admin/significance/backfill-scores${q ? `?${q}` : ''}`);
  }

  async getClimbScoringTrace(climbId: string): Promise<ScoringTrace> {
    return this.get(`/admin/significance/climb/${climbId}/trace`);
  }

  async getClimbElevationProfile(climbId: string): Promise<ElevationProfileData> {
    return this.get(`/admin/significance/climb/${climbId}/profile`);
  }

  async getPipelineStats(): Promise<PipelineStats> {
    return this.get('/admin/significance/pipeline-stats');
  }

  async getCellFitData(h3Index: string): Promise<CellFitData> {
    return this.get(`/admin/significance/cells/${h3Index}/fit`);
  }

  async getCellHistory(h3Index: string, limit?: number): Promise<CellHistory> {
    const qs = limit ? `?limit=${limit}` : '';
    return this.get(`/admin/significance/cells/${h3Index}/history${qs}`);
  }

  async getDriftSummary(): Promise<DriftSummary> {
    return this.get('/admin/significance/drift-summary');
  }

  // ==================== ADMIN: CLIMB REVIEWS ====================

  async reviewClimb(climbId: string, body: ClimbReviewRequest): Promise<{ climbId: string; verdict: string; previousStatus: string | null }> {
    return this.post(`/admin/significance/climbs/${climbId}/review`, body);
  }

  async bulkReviewClimbs(body: BulkReviewRequest): Promise<{ batchId: string; reviewed: number; total: number; verdict: string }> {
    return this.post('/admin/significance/climbs/bulk-review', { climbIds: body.climbIds, verdict: body.verdict, reason: body.reason, category: body.category });
  }

  async revertClimbReview(climbId: string): Promise<{ climbId: string; previousStatus: string | null; verdict: string }> {
    return this.post(`/admin/significance/climbs/${climbId}/revert`);
  }

  async autoConfirmClimbs(params?: { minG?: number; minPersistence?: number; minConfidenceTier?: number; dryRun?: boolean }): Promise<{ candidates: number; confirmed: number; dryRun: boolean; thresholds: Record<string, number> }> {
    const qs = new URLSearchParams();
    if (params?.minG !== undefined) qs.set('min_g', String(params.minG));
    if (params?.minPersistence !== undefined) qs.set('min_persistence', String(params.minPersistence));
    if (params?.minConfidenceTier !== undefined) qs.set('min_confidence_tier', String(params.minConfidenceTier));
    if (params?.dryRun) qs.set('dry_run', 'true');
    const q = qs.toString();
    return this.post(`/admin/significance/auto-confirm${q ? `?${q}` : ''}`);
  }

  async getReviewQueue(params?: { limit?: number; offset?: number; status?: string; cellH3?: string }): Promise<SignificanceClimbsResponse> {
    const qs = new URLSearchParams();
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    if (params?.status) qs.set('status', params.status);
    if (params?.cellH3) qs.set('cell_h3', params.cellH3);
    const q = qs.toString();
    return this.get(`/admin/significance/review-queue${q ? `?${q}` : ''}`);
  }

  async getCellsNeedingRefit(): Promise<{ cells: Record<string, unknown>[]; total: number }> {
    return this.get('/admin/significance/cells-needing-refit');
  }

  async getClimbReviewHistory(climbId: string): Promise<{ climbId: string; reviews: Record<string, unknown>[] }> {
    return this.get(`/admin/significance/climbs/${climbId}/reviews`);
  }

  // ==================== ADMIN: PLATFORM DASHBOARD ====================

  async getPlatformOverview(): Promise<PlatformOverview> {
    return this.get('/admin/platform/overview');
  }

  async getAdminActivityFeed(limit?: number): Promise<AdminActivityFeedResponse> {
    return this.get(`/admin/platform/activity-feed${limit ? `?limit=${limit}` : ''}`);
  }

  async getAuditLog(limit?: number): Promise<AuditLogResponse> {
    return this.get(`/admin/platform/audit-log${limit ? `?limit=${limit}` : ''}`);
  }

  async getAdminStravaHealth(): Promise<StravaAdminHealth> {
    return this.get('/admin/strava/health');
  }

  async createAdminStravaSubscription(): Promise<{ subscriptionId: number; status: string }> {
    return this.post('/admin/strava/subscribe');
  }

  async deleteAdminStravaSubscription(): Promise<{ subscriptionId: number; status: string }> {
    return this.delete('/admin/strava/subscribe');
  }

  async getAdminControls(): Promise<AdminControlsResponse> {
    return this.get('/admin/controls');
  }

  async updateAdminControl(key: string, enabled: boolean, reason?: string): Promise<{ success: boolean; message: string }> {
    return this.put(`/admin/controls/${key}`, { enabled, reason });
  }

  async emergencyPauseAll(reason: string): Promise<{ success: boolean; message: string }> {
    return this.post(`/admin/emergency/pause-all?reason=${encodeURIComponent(reason)}`);
  }

  async emergencyResumeAll(): Promise<{ success: boolean; message: string }> {
    return this.post('/admin/emergency/resume-all');
  }

  async getEpochStatus(): Promise<EpochStatusResponse> {
    return this.get('/admin/epoch/status');
  }

  async processEpoch(): Promise<{ transitioned: boolean; processed: number }> {
    return this.post('/admin/epoch/process');
  }
}

// Types
export type Units = 'metric' | 'imperial';
export type ThemeId = 'hoo-breddin' | 'water' | 'sunny' | 'safari' | 'moss' | 'foundries';
export type RiderType = 'climber' | 'sprinter' | 'tt' | 'rouleur' | 'allrounder' | 'diesel';
export type RideVisibility = 'public' | 'followers' | 'private';
export type RideMapVisibility = 'show_all' | 'hide_start_end' | 'hide_entire';
export type MapHideDistanceM = 0 | 200 | 400 | 800 | 1600;

export interface RidePrivacyChoice {
  visibility: RideVisibility;
  mapVisibility: RideMapVisibility;
  mapHideStartM: MapHideDistanceM;
  mapHideEndM: MapHideDistanceM;
}

export interface PrivacyState {
  visibility: RideVisibility;
  canView: boolean;
  isOwner: boolean;
  isFollower: boolean;
  redactGps: boolean;
  mapVisibility: RideMapVisibility;
  mapHideStartM: number;
  mapHideEndM: number;
  protocolPublic: boolean;
  protocolPublicFields: string[];
  reason: string;
}

export interface PrivacySettings {
  contractVersion: 'privacy.v2';
  shareWkg: boolean;
  profileVisibility: 'public' | 'private';
  defaultRideVisibility: RideVisibility;
  defaultMapVisibility: RideMapVisibility;
  defaultMapHideStartM: MapHideDistanceM;
  defaultMapHideEndM: MapHideDistanceM;
  defaultsApplyTo: 'future_rides';
  providerPrivacyInherited: false;
  privacyZoneCount: number;
  privacyZonesLoaded: true;
  rideOverrideMode: 'optional';
  protocolPublicFields: string[];
}

export interface AuthTokenResponse {
  userId: string;
  wallet: string;
  accessToken: string;
  accessExpiresAt: string;
  refreshToken: string;
  refreshExpiresAt: string;
}

export interface OnboardingState {
  authenticated: boolean;
  inviteRequired: boolean;
  inviteValidated: boolean;
  needsProfileSetup: boolean;
  authMethodHint?: 'wallet' | 'privy' | string | null;
}

export interface AuthBootstrapState extends OnboardingState {
  user?: User | null;
}

export interface InviteValidationResult {
  valid: boolean;
  message: string;
  codeId?: string | null;
}

export interface WaitlistResult {
  contractVersion?: 'waitlist.v1';
  status: string;
  state?: 'accepted';
  message: string;
  email?: string;
  source?: string;
  submittedAt?: string | null;
}

export interface User {
  id: string;
  wallet: string;
  username?: string;
  displayName?: string;
  beetleId?: string | number;
  beetleNumber?: number;
  rank?: string;
  avatarUrl?: string;
  bio?: string;
  email?: string;
  location?: string;
  // Physical stats
  weightKg?: number;
  // Preferences
  preferredUnits?: Units;
  themeId?: ThemeId;
  isDarkMode?: boolean;
  riderType?: RiderType;
  isPublic?: boolean;
  privacy?: PrivacyState | null;
  defaultRideVisibility?: RideVisibility;
  createdAt?: string;
  // Aggregated stats from rides
  totalRides?: number;
  totalDistanceKm?: number;
  totalElevationM?: number;
  totalKcals?: number;
  totalDurationSec?: number;
  totalDungEarned?: number;
  // Streaks
  currentStreak?: number;
  longestStreak?: number;
  lastActivityDate?: string;
  // Accessories
  accessories?: string[];
  equippedAccessories?: string[];
  // Daily earnings (from today's rides)
  calEarnedToday?: number;
  dungEarnedToday?: number;
}

export interface UserProfile {
  username?: string;
  displayName?: string;
  bio?: string;
  location?: string;
  weightKg?: number;
  riderType?: RiderType;
  units?: Units;
  themeId?: ThemeId;
  isDarkMode?: boolean;
  isPublic?: boolean;
  defaultRideVisibility?: RideVisibility;
}

export interface UserProfilePublic {
  id: string;
  wallet: string;
  username?: string;
  displayName?: string;
  bio?: string;
  avatarUrl?: string;
  isPublic?: boolean;
  privacy?: PrivacyState | null;
  createdAt?: string;
  totalRides?: number;
  totalDistanceKm?: number;
  totalElevationM?: number;
  currentStreak?: number;
}

// User leaderboard summary types
export interface VaultPositionSummary {
  vaultId: number;
  vaultName: string;
  vaultSignature: string;
  rank: number;
  bestTimeSeconds: number;
  isKom: boolean;
  totalRiders: number;
  percentile?: number;
  achievedAt?: string;
}

export interface UserLeaderboardStats {
  totalPositions: number;
  komCount: number;
  podiumCount: number;
  top10Count: number;
  totalVaultsCompleted: number;
  bestPercentile?: number;
}

export interface UserLeaderboardSummaryResponse {
  wallet: string;
  stats: UserLeaderboardStats;
  positions: VaultPositionSummary[];
}

export type TruthSource = 'onchain' | 'attested' | 'projected' | 'compatibility';

export interface CarryBuckets {
  recordRoyalty: string;
  recordRoyaltyBaseUnits: string;
  stakers: string;
  stakersBaseUnits: string;
  localLegend: string;
  localLegendBaseUnits: string;
  pol: string;
  polBaseUnits: string;
  treasury: string;
  treasuryBaseUnits: string;
  total: string;
  totalBaseUnits: string;
}

export interface VaultEconomy {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  hasVault: boolean;
  vaultId: number | null;
  vaultSignature: string | null;
  totalStaked: string;
  totalStakedBaseUnits: string;
  totalCalStaked: string;
  totalCalStakedBaseUnits: string;
  totalCompletions: number;
  currentCarry?: CarryBuckets | null;
}

export interface RecordBoardEntry extends ClimbPowerFields {
  placeSource?: 'onchain' | 'offchain_completions' | 'rides' | null;
  position?: number | null;
  rank: number;
  competitionRank?: number | null;
  tieSize?: number | null;
  isTied?: boolean;
  wallet: string;
  bestTimeSeconds?: number | null;
  avgPowerW?: number | null;
  completionId?: string | null;
  effortId?: string | null;
  rideId?: string | null;
  achievedAt?: string | null;
  vaultSignature?: string | null;
  userId?: string | null;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
}

export interface RecordBoard {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  source?: 'onchain' | 'rides';
  earlierVersionId?: string | null;
  climbId: string;
  climbName?: string | null;
  vaultId?: number | null;
  entries: RecordBoardEntry[];
  leaderboard: RecordBoardEntry[];
  komHolder?: string | null;
  komTimeS: number | null;
}

export interface LocalLegendStatus {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  climbId: string;
  vaultId?: number | null;
  wallet?: string | null;
  attemptsInWindow: number;
  electedAt?: string | null;
  founderWallet?: string | null;
  founderResidualRecipient?: string | null;
}

export interface SettlementStatus {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  settlementWeek: number;
  epoch?: number | null;
  finalizedAt?: string | null;
  distributedAt?: string | null;
  vaultId?: number | null;
  vaultSignature?: string | null;
  totalAmount: string;
  totalAmountBaseUnits: string;
  recordRoyaltyAmount: string;
  recordRoyaltyAmountBaseUnits: string;
  stakerAmount: string;
  stakerAmountBaseUnits: string;
  localLegendAmount: string;
  localLegendAmountBaseUnits: string;
  polAmount: string;
  polAmountBaseUnits: string;
  treasuryAmount: string;
  treasuryAmountBaseUnits: string;
  currentCarry: CarryBuckets;
}

export interface RideStatusMetrics {
  tss?: number | null;
  thresholdTrainingState?: 'pending' | null;
  kcals?: number | null;
  distanceM?: number | null;
  elevationGainM?: number | null;
  durationSec?: number | null;
  avgPowerW?: number | null;
  normalizedPowerW?: number | null;
}

export interface RideInputQuality {
  status?: 'unknown' | 'clean' | 'degraded' | 'invalid';
  sensorDataState?: 'unknown' | 'absent' | 'partial' | 'present';
  integrityScore?: number | null;
  sampleCount?: number | null;
  flags?: string[];
  degradationReasons?: string[];
  gpsCoverage?: number | null;
  elevationCoverage?: number | null;
  samplingRegularity?: number | null;
  maxGapS?: number | null;
  powerCoverage?: number | null;
  heartRateCoverage?: number | null;
  speedCoverage?: number | null;
  importQualityTier?: string | null;
}

export interface RideImportDiagnostics {
  importSource?: string;
  sourceActivityId?: string;
  qualityTier?: string;
  trackpointCount?: number;
  streamCounts?: Record<string, number>;
  medianIntervalS?: number | null;
  maxGapS?: number | null;
  gapCountOver10s?: number;
  gapCountOver30s?: number;
  altitudeCoverage?: number;
  powerCoverage?: number;
  heartrateCoverage?: number;
  cadenceCoverage?: number;
  flags?: string[];
}

export interface RideEffortPolicy {
  contractVersion?: 'client.v1';
  truthSource?: TruthSource;
  effortEvidenceTier?: 'route_only' | 'sensor_supported' | 'power_verified' | 'manual_review' | null;
  rewardPolicy?: 'rewardable' | 'estimated_only' | 'manual_review' | 'not_counted' | 'threshold_provisional_hold_v1' | null;
  thresholdEconomyState?: 'held' | 'counted' | 'lapsed' | 'review' | 'not_counted' | null;
  estimatedCal?: number | null;
  rewardableCal?: number | null;
  tributableCal?: number | null;
}

export interface RideStatus {
  contractVersion?: 'client.v1';
  truthSource?: TruthSource;
  rideId: string;
  status: string;
  attestationStatus?: string;
  rideHashHex?: string | null;
  attestationCommitmentHex?: string | null;
  parserVersion?: number | null;
  preliminaryRideHashHex?: string | null;
  preliminaryParserVersion?: number | null;
  canonicalMatch?: boolean | null;
  reviewReason?: string | null;
  effortSeconds?: number | null;
  coveredEffortSeconds?: number | null;
  paidEffortSeconds?: number | null;
  rideAttestationPda?: string | null;
  rideAttestationTxSignature?: string | null;
  rideAttestedAt?: string | null;
  finalizedAt?: string | null;
  importSource?: string | null;
  importSourceId?: string | null;
  importDiagnostics?: RideImportDiagnostics | null;
  errorMessage?: string | null;
  phase1Error?: string | null;
  phase2Error?: string | null;
  phase3Error?: string | null;
  phase1CompletedAt?: string | null;
  phase2CompletedAt?: string | null;
  phase3CompletedAt?: string | null;
  phase1DurationMs?: number | null;
  phase2DurationMs?: number | null;
  phase3DurationMs?: number | null;
  metrics?: RideStatusMetrics | null;
  inputQuality?: RideInputQuality | null;
  hasGps?: boolean;
  hasPatterns?: boolean;
  hasLeaderboards?: boolean;
  hasAchievements?: boolean;
  calEarned?: number | null;
  dungMinted?: number | null;
  txSignature?: string | null;
  earnings?: {
    contractVersion: 'client.v1';
    truthSource: TruthSource;
    rideId: string;
    calEarned?: number | null;
    dungEarned?: number | null;
    finalizedAt?: string | null;
    settlementStatus?: SettlementStatus | null;
  } | null;
  effortPolicy?: RideEffortPolicy | null;
}

export interface RideCalItemizationClimb {
  patternId: string;
  vaultId: number;
  vaultSignature: string;
  climbName?: string | null;
  /** Exact CAL base units (9 decimals) attributed to this climb. */
  calTributeBaseUnits: string;
  completionTimeS?: number | null;
  intensityBps?: number | null;
}

/**
 * The truthful per-climb CAL decomposition the protocol already computes:
 * the frozen vault-tribute flow. Per PROTOCOL_TRUTHS the rider's credited CAL
 * is never reduced by tribute — climbs are attributed their exact frozen
 * share and everythingBetweenBaseUnits is the remainder, so the parts sum
 * exactly to rideCalBaseUnits.
 */
export interface RideCalItemization {
  contractVersion: 'client.v1';
  basis: 'vault_tribute_flow';
  tributePolicyVersion: string;
  calDecimals: number;
  rideCalBaseUnits: string;
  tributeBudgetBaseUnits: string;
  climbs: RideCalItemizationClimb[];
  everythingBetweenBaseUnits: string;
}

export interface TrainingEstimate {
  value: number;
  estimate: boolean;
  basis: string;
  range?: [number, number];
}
export interface RideTrainingMetrics {
  engineVersion: number;
  elapsedS: number | null;
  recordingS: number | null;
  movingS: number | null;
  load: number | null;
  loadEstimate: boolean;
  threshold: TrainingEstimate | null;
  estimates: Record<string, TrainingEstimate | null>;
  avgPowerW: number | null;
  avgHrBpm: number | null;
  avgCadenceRpm: number | null;
  maxCadenceRpm: number | null;
  avgSpeedMps: number | null;
  maxSpeedMps: number | null;
  maxPowerW: number | null;
  npW: number | null;
  distanceM: number | null;
  elevationGainM: number | null;
  workJ: number | null;
  caloriesKcal: number | null;
  caloriesEstimate: boolean;
  powerCurveS: number[];
  powerCurveW: Array<number | null> | null;
  powerZoneS: number[] | null;
  powerZoneRangesW: Array<[number, number | null]> | null;
  powerZoneTotalS: number | null;
  powerZonePct: number[] | null;
  hrZoneS: number[] | null;
}

export interface Ride {
  trainingMetrics?: RideTrainingMetrics | null;
  movingTimeS?: number | null;
  recordingTimeS?: number | null;
  presentation?: RidePresentation | null;
  contractVersion?: 'client.v1';
  truthSource?: TruthSource;
  id: string;
  riderId?: string;
  title?: string;
  description?: string | null;
  startedAt: string;
  /** Owner-list-only stored upload time; never substitute startedAt when absent. */
  uploadedAt?: string | null;
  status?: string;
  distanceM?: number;
  elevationM?: number;
  durationS?: number;
  avgPowerW?: number;
  normalizedPowerW?: number;
  /** Average heart rate in bpm. Absent = the ride carried no HR data. */
  avgHrBpm?: number | null;
  tss?: number;
  thresholdTrainingState?: 'pending' | null;
  calories?: number;
  /**
   * Per-climb CAL itemization from the frozen economic plan (vault tribute
   * flow decomposition). Null until a ride has a complete frozen plan.
   * Base units are decimal strings — never parse through Number for math.
   */
  calItemization?: RideCalItemization | null;
  // Token earnings
  dungEarned?: number;
  calEarned?: number;
  effortEvidenceTier?: RideEffortPolicy['effortEvidenceTier'];
  rewardPolicy?: RideEffortPolicy['rewardPolicy'];
  thresholdEconomyState?: RideEffortPolicy['thresholdEconomyState'];
  estimatedCal?: number | null;
  rewardableCal?: number | null;
  tributableCal?: number | null;
  attestationStatus?: string;
  rideHashHex?: string | null;
  attestationCommitmentHex?: string | null;
  parserVersion?: number | null;
  preliminaryRideHashHex?: string | null;
  preliminaryParserVersion?: number | null;
  canonicalMatch?: boolean | null;
  reviewReason?: string | null;
  effortSeconds?: number | null;
  coveredEffortSeconds?: number | null;
  paidEffortSeconds?: number | null;
  rideAttestationPda?: string | null;
  rideAttestationTxSignature?: string | null;
  rideAttestedAt?: string | null;
  finalizedAt?: string | null;
  importSource?: string | null;
  importSourceId?: string | null;
  importDiagnostics?: RideImportDiagnostics | null;
  earnings?: {
    contractVersion: 'client.v1';
    truthSource: TruthSource;
    rideId: string;
    calEarned?: number | null;
    dungEarned?: number | null;
    finalizedAt?: string | null;
    settlementStatus?: SettlementStatus | null;
  };
  patterns?: Pattern[];
  media?: RideMedia[];
  primaryMedia?: RideMedia | null;
  routePreview?: RoutePreview | null;
  /**
   * Compact elevation cross-section for the ride log's spine (rides list
   * contract, bead 24xry.19): evenly spaced points along the ride.
   */
  elevationProfile?: Array<{ distanceM: number; elevationM: number }> | null;
  /** Climb spans that counted CAL, in ride distance, for the spine's cobalt strokes. */
  countedSpans?: Array<{ startDistanceM: number; endDistanceM: number }> | null;
  isOwner?: boolean;
  visibility?: RideVisibility;
  privacy?: PrivacyState | null;
}

export interface ThresholdPendingMondayResponse {
  watts: number;
  effectiveAt: string;
}

export interface ThresholdResponse {
  contractVersion: 'threshold.v1';
  state: 'establishing' | 'established';
  currentW?: number | null;
  establishedAt?: string | null;
  lastRaisedAt?: string | null;
  pendingMonday?: ThresholdPendingMondayResponse | null;
  sealingInProgress: boolean;
}

export interface RideDetailResponse {
  contractVersion: 'ride_detail.v1';
  ride: Ride;
  status: RideStatus;
  interactions: RideInteractions;
  comments: {
    comments: Comment[];
    count: number;
    hasMore: boolean;
  };
  link: ResolvedLink;
  freshness?: {
    source: string;
    loadedAt: string;
    status?: string;
  };
}

export interface RoutePreviewPoint {
  x: number;
  y: number;
}

export interface RoutePreviewBounds {
  minLat: number;
  minLon: number;
  maxLat: number;
  maxLon: number;
}

export interface RoutePreview {
  contractVersion?: 'route_preview.v1';
  source?: string;
  points?: RoutePreviewPoint[];
  segments?: RoutePreviewPoint[][];
  pointCount?: number;
  bounds?: RoutePreviewBounds | null;
  placeLabel?: string | null;
  fallbackReason?: string | null;
  privacy?: Record<string, unknown>;
}

export interface RideMedia {
  id: string;
  rideId: string;
  url?: string | null;
  fileName?: string | null;
  mimeType: string;
  sizeBytes: number;
  width?: number | null;
  height?: number | null;
  sortOrder: number;
  role: 'photo' | 'cover';
  moderationState: string;
  createdAt?: string | null;
}

export interface Pattern {
  type: 'climb' | 'steady' | 'exploration';
  durationS: number;
  elevationM?: number;
  powerW?: number;
  newTilesWallet?: number;
  status: 'pending' | 'verified' | 'failed';
}

export interface GeographicData {
  releaseId: string;
  canonId: string;
  canonVersion: number;
  geographicRevisionId: string;
  sourceOffer: string;
  manifestUrl: string;
  noticesUrl: string;
  sources: Array<{ assetId: string; licenseId: string; licenseUrl: string; notices: Array<{id: string; text: string}> }>;
}

export interface Climb {
  geographicData?: GeographicData | null;
  contractVersion?: 'client.v1';
  truthSource?: TruthSource;
  id: string;
  canonId?: string;
  version?: number;
  revisionState?: 'current' | 'retired';
  vaultCreation?: VaultCreationAvailability;
  name?: string;
  lengthM?: number;
  elevGainM?: number;
  avgGradientPct?: number;
  category?: string;
  region?: string;
  startLat?: number;
  startLon?: number;
  endLat?: number;
  endLon?: number;
  vaultId?: number | null;
  vaultSignature?: string | null;
  hasVault?: boolean;
  totalStaked?: string;
  totalStakedBaseUnits?: string;
  totalCalStaked?: string;
  totalCalStakedBaseUnits?: string;
  totalCompletions?: number;
  vaultEconomy?: VaultEconomy;
  recordBoard?: RecordBoard | null;
  localLegend?: LocalLegendStatus | null;
  settlementStatus?: SettlementStatus | null;
  routePreview?: RoutePreview | null;
  elevationProfile?: Array<{
    distanceM: number;
    elevationM: number;
  }>;
}

export interface GeocodingResult {
  displayName: string;
  latitude: number;
  longitude: number;
}

export interface GeocodingAttribution {
  text: string;
  url: string;
}

export interface GeocodingSearchResponse {
  contractVersion: 'geocoding.v1';
  state: 'available';
  results: GeocodingResult[];
  attribution: GeocodingAttribution;
  provider: string;
  cached: boolean;
}

export interface PopularClimb {
  id: string;
  name: string;
  region?: string;
  elevGainM: number;
  completions: number;
  staked: string;
  stakedBaseUnits: string;
}

export interface LeaderboardResponse {
  source?: 'onchain' | 'rides';
  earlierVersionId?: string | null;
  viewerEntry?: VaultLeaderboardEntry | null;
  contractVersion?: 'client.v1';
  truthSource?: TruthSource;
  entries: LeaderboardEntry[];
  leaderboard?: LeaderboardEntry[];
  climbId: string;
  climbName?: string | null;
  vaultId?: number | null;
  komHolder?: string | null;
  komTimeS?: number | null;
  epochNumber: number;
  total: number;
}

export interface LeaderboardEntry extends ClimbPowerFields {
  placeSource?: 'onchain' | 'offchain_completions' | 'rides' | null;
  rank: number;
  wallet?: string;
  username?: string | null;
  position?: number | null;
  competitionRank?: number | null;
  isTied?: boolean;
  identityHidden?: boolean;
  effortId?: string | null;
  rideId?: string | null;
  completionId?: string | null;
  achievedAt?: string | null;
  userId: string;
  displayName?: string | null;
  avatarUrl?: string | null;
  timeS?: number;
  vam?: number;
}

export interface GlobalLeaderboardResponse {
  leaderboardType: 'climb' | 'steady' | 'exploration';
  metric: string;
  period: string;
  arenaId: string | null;
  arenaName: string;
  entries: GlobalLeaderboardEntry[];
  totalCount: number;
  updatedAt: string;
}

export interface GlobalLeaderboardEntry {
  rank: number;
  wallet: string;
  username: string | null;
  avatarUrl: string | null;
  activityId: string;
  patternId: string;
  value: number | null;
  secondaryValue: number | null;
  createdAt: string;
}

export type FeedEventType =
  | 'ride_completed'
  | 'ride_under_review'
  | 'climb_completed'
  | 'record_rank_moved'
  | 'local_legend_moved'
  | 'achievement_unlocked'
  | 'comment_created'
  | 'follow_created'
  | 'report_resolved'
  | 'social';

export interface FeedActor {
  id?: string | null;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
}

export interface FeedTarget {
  type: string;
  id?: string | null;
}

export interface Activity {
  resultSummary?: FeedItemResultSummary | null;
  contractVersion?: 'feed.v1';
  id: string;
  type: string;
  eventType?: FeedEventType;
  title: string;
  createdAt: string;
  occurredAt?: string;
  status?: string;
  actor?: FeedActor;
  user?: FeedActor;
  target?: FeedTarget;
  privacy?: PrivacyState | null;
  metadata?: {
    distanceM?: number;
    elevationM?: number;
    durationS?: number;
    status?: string;
    dungEarned?: number;
    calEarned?: number;
    kudosCount?: number;
    commentCount?: number;
    viewerHasKudos?: boolean;
    viewerReported?: boolean;
    reportStatus?: string | null;
    visibility?: RideVisibility;
    privacy?: PrivacyState | null;
    media?: RideMedia[];
    primaryMedia?: RideMedia | null;
    routePreview?: RoutePreview | null;
  };
}

export interface FeedResponse {
  contractVersion?: 'feed.v1';
  activities: Activity[];
  hasMore?: boolean;
  has_more?: boolean;
  nextCursor?: string | null;
  next_cursor?: string | null;
  message?: string;
}

export interface HomeFeedResponse {
  contractVersion: 'feed_home.v1';
  scope: 'following' | 'global';
  viewer: {
    authenticated: boolean;
    userId?: string | null;
    wallet?: string | null;
  };
  feed: FeedResponse;
  suggestedRiders: SuggestedRider[];
  popularClimbs: PopularClimb[];
  achievements: Achievement[];
  socialCounts: {
    followerCount: number;
    followingCount: number;
  };
  notifications: {
    unreadCount: number;
  };
}

export interface SuggestedRider {
  id: string;
  username?: string;
  displayName?: string;
  avatarUrl?: string;
  wallet: string;
}

export interface DistributionReceipt {
  id: string;
  receiptType: string;
  amount: string;
  amountBaseUnits: string;
  rank?: number | null;
  createdAt: string;
}

export interface DistributionGroup {
  distributionId: string;
  vaultSignature: string;
  vaultId?: string | number | null;
  vaultName?: string | null;
  climbId?: string | null;
  climbName?: string | null;
  epoch: number;
  totalAmount: string;
  totalAmountBaseUnits: string;
  leaderboardAmount: string;
  leaderboardAmountBaseUnits: string;
  stakerAmount: string;
  stakerAmountBaseUnits: string;
  localLegendAmount: string;
  localLegendAmountBaseUnits: string;
  polAmount: string;
  polAmountBaseUnits: string;
  protocolAmount: string;
  protocolAmountBaseUnits: string;
  distributedAt: string;
  finalizedAt?: string;
  currentCarry?: CarryBuckets;
  settlementStatus?: SettlementStatus | null;
  receipts: DistributionReceipt[];
}

export interface MyDistributionsResponse {
  distributions: DistributionGroup[];
  receiptCount: number;
  distributionCount: number;
  limit: number;
  offset: number;
}

export interface VaultDistributionSummary {
  distributionId: string;
  epoch: number;
  totalAmount: string;
  totalAmountBaseUnits: string;
  leaderboardAmount: string;
  leaderboardAmountBaseUnits: string;
  stakerAmount: string;
  stakerAmountBaseUnits: string;
  localLegendAmount: string;
  localLegendAmountBaseUnits: string;
  polAmount: string;
  polAmountBaseUnits: string;
  protocolAmount: string;
  protocolAmountBaseUnits: string;
  distributedAt: string;
  leaderboardDetails?: { rank: number; wallet: string; amount: number }[];
  settlementStatus?: SettlementStatus | null;
}

export interface VaultDistributionHistoryResponse {
  vaultId: number;
  vaultSignature: string;
  vaultName: string;
  currentCarry: CarryBuckets;
  distributions: VaultDistributionSummary[];
  totalDistributed: string;
  totalDistributedBaseUnits: string;
  distributionCount: number;
}

export interface CurrentEpochResponse {
  settlementWeek: number;
  currentEpoch: number;
  startsAt: string;
  endsAt: string;
  finalizesAt: string;
  durationSeconds: number;
  epochDurationSeconds: number;
  clockVersion: number;
  cutoverAt: string;
  transitionWeek?: number | null;
  isTransitionWeek: boolean;
}

export interface Portfolio {
  collectionSnapshot?: CollectionSnapshot | null;
  contractVersion?: 'portfolio.v5';
  dungBalance: string | null;
  dungBalanceBaseUnits: string | null;
  walletDung: DungBalanceSource;
  balanceDung: DungBalanceSource;
  calBalance: string;
  calBalanceBaseUnits: string;
  balanceLifecycle?: BalanceLifecyclePlan;
  stakedPositions: unknown[];
  pendingClaims: unknown[];
  totalClaims?: number;
  totalStaked?: string;
  totalStakedBaseUnits?: string;
  weeklyYield?: string;
  weeklyYieldBaseUnits?: string;
  harvestFeeBps: string;
  exitFeeBps: string;
  totalYield?: string;
  totalYieldBaseUnits?: string;
  claims?: unknown[];
  freshness?: {
    source?: string;
    chainStatus?: string;
    calStatus?: string;
    calAccountExists?: boolean | null;
    walletDungStatus?: DungBalanceSourceStatus;
    balanceDungStatus?: DungBalanceSourceStatus;
    balanceHeaderStatus?: TokenAccountSourceStatus;
    balanceCalStatus?: TokenAccountSourceStatus;
    balanceUsdcStatus?: TokenAccountSourceStatus;
    balanceLifecycleSource?: string;
    balanceLifecycleSlot?: number | null;
    loadedAt?: string;
  };
}

export type TokenAccountSourceStatus = 'live' | 'not_initialized' | 'unavailable';
export type DungBalanceSourceStatus = TokenAccountSourceStatus;

export interface DungBalanceSource {
  amount: string | null;
  amountBaseUnits: string | null;
  source: 'spl_wallet_ata' | 'rider_balance_token_pda';
  status: DungBalanceSourceStatus;
  tokenAccount: string | null;
  slot: number | null;
}

export interface BalanceLifecycleStep {
  actionType: string;
  riderLabel: string;
  asset?: string | null;
  stepUpRequired: boolean;
}

export interface BalanceAssetView {
  asset: string;
  exists: boolean;
  balanceBaseUnits: string | null;
  riderState: string;
  mint?: string | null;
  tokenAccount?: string | null;
  source?: string | null;
  sourceStatus: TokenAccountSourceStatus;
  slot?: number | null;
}

export interface BalanceLifecyclePlan {
  riderAccountId: string;
  protocolWallet: string;
  status: string;
  initialized: boolean;
  riderHeadline: string;
  riderDetail: string;
  noPromptExecutionAllowed: boolean;
  canAddFunds: boolean;
  canWithdrawToWallet: boolean;
  setupSteps: BalanceLifecycleStep[];
  assets: BalanceAssetView[];
  blockers: string[];
  source?: string;
  sourceStatus?: TokenAccountSourceStatus;
  account?: string | null;
  slot?: number | null;
  authorityModel?: string | null;
  policyHash?: string | null;
  delegateAuthority?: string | null;
  lastAuthorityRotationAt?: number | null;
  revokedAt?: number | null;
  programConfigAccount?: string | null;
  programConfigSlot?: number | null;
  projectionStatus?: string;
}

export interface PortfolioSnapshot {
  collectionSnapshot?: CollectionSnapshot | null;
  contractVersion: 'portfolio_snapshot.v4';
  portfolio: Portfolio;
  distributions: MyDistributionsResponse;
  freshness?: {
    source?: string;
    chainStatus?: string;
    calStatus?: string;
    calAccountExists?: boolean | null;
    walletDungStatus?: DungBalanceSourceStatus;
    balanceDungStatus?: DungBalanceSourceStatus;
    balanceHeaderStatus?: TokenAccountSourceStatus;
    balanceCalStatus?: TokenAccountSourceStatus;
    balanceUsdcStatus?: TokenAccountSourceStatus;
    balanceLifecycleSource?: string;
    balanceLifecycleSlot?: number | null;
    loadedAt?: string;
    distributionCount?: number;
    receiptCount?: number;
  };
}

export interface RiderBalanceOperationStatus {
  stage1TerminalFailure?: boolean;
  operationId: string;
  actionType: string;
  referenceType: string | null;
  referenceId: string | null;
  riderState: string | null;
  readState: string;
  pending: boolean;
  delayed: boolean;
  needsReview: boolean;
  recorded: boolean;
}

export interface BalanceOperationView {
  operationId: string;
  riderAccountId: string;
  protocolWallet: string;
  actionType: string;
  authorityModel: string;
  asset: string;
  amount: string;
  source: string;
  destination: string;
  idempotencyKey: string;
  preparedMessageHash?: string | null;
  feePayer?: string | null;
  policyOrDelegateId?: string | null;
  txSignature?: string | null;
  confirmationStatus: string;
  projectionStatus: string;
  retryCount: number;
  failureReason?: string | null;
  referenceType?: string | null;
  referenceId?: string | null;
  riderState?: string | null;
  metadata?: Record<string, string>;
}

export interface PreparedBalanceAction {
  contractVersion: 'portfolio_balance_action.v2';
  actionType: string;
  riderLabel: string;
  asset: string;
  amountBaseUnits: string;
  riderState: string;
  riderDetail: string;
  nextStep: string;
  blockers: string[];
  preparedTransaction?: PreparedVaultTransaction | null;
  operation?: BalanceOperationView | null;
  withdrawalsPausedUntil?: string;
}

interface ThresholdAnalyticsAuthority {
  thresholdTrainingState: 'pending' | null;
  thresholdVersion: string;
  trainingAvailable?: boolean;
  trainingThreshold?: TrainingEstimate | null;
  estimate?: boolean;
}

export interface PowerCurve {
  contractVersion?: 'power_curve.v1';
  durationsS: number[];
  bestW: Array<number | null>;
  sampledRides: number;
  rideCount: number;
  available: boolean;
  threshold: {
    sealedW: number | null;
    candidateW: number | null;
    anchorsW: Record<string, number | null>;
  };
  thresholdState?: string;
  thresholdVersion?: string;
}

export interface RidingDays {
  contractVersion?: 'riding_days.v1';
  startDate: string;
  endDate: string;
  undatedCount?: number;
  days: Array<{ date: string; movingS: number | null; distanceM?: number | null; elevationGainM?: number | null; rideCount: number }>;
}

export interface FitnessMetrics extends ThresholdAnalyticsAuthority {
  thresholdState: 'establishing' | 'established' | 'estimated';
  ctl: number | null;
  atl: number | null;
  tsb: number | null;
  form: string | null;
  date: string;
}

export interface CalOnchainResponse {
  wallet: string;
  calBalance: string;
  calBalanceBaseUnits: string;
  onChainTotal?: number;
  totalStaked: number;
  calEarnedToday: number;
  totalRides: number;
  totalTss: number;
  accountExists: boolean;
}

export interface TrainingLoad extends ThresholdAnalyticsAuthority {
  thresholdState: 'establishing' | 'established' | 'estimated';
  dailyLoads: { date: string; totalTss: number }[];
  totalTss: number | null;
  avgDailyTss: number | null;
}

// Telemetry types for ride analysis
export interface GpsPoint {
  sequenceNum: number;
  timestamp: string | number;
  latitude: number;
  longitude: number;
  elevationM?: number;
  distanceM?: number;
  redacted?: boolean;
}

export interface GpsResponse {
  gpsPoints: GpsPoint[];
}

export interface StreamResponse {
  id: string | null;
  rideId: string;
  streamType: string;
  timestamps: string[];
  values: number[];
  sampleCount: number;
  minValue: number | null;
  maxValue: number | null;
  avgValue: number | null;
}

export interface TelemetryData {
  gps: GpsResponse | null;
  power: StreamResponse | null;
  heartRate: StreamResponse | null;
  cadence: StreamResponse | null;
  speed: StreamResponse | null;
  temperature: StreamResponse | null;
}

// Tile types for H3 visualization
export interface TileSample {
  tileId: string;
  t: number;
  elevationM?: number;
  powerW?: number;
  hrBpm?: number;
  speedMps?: number;
}

export interface TilesResponse {
  rideId: string;
  tileSamples: TileSample[];
  totalSamples: number;
  uniqueTiles: number;
}

// Pattern types for ride analysis
export interface ClimbPattern extends ClimbPowerFields {
  category?: string | null;
  id?: string;
  climbId?: string;
  segmentId?: string;
  name?: string;
  roadName?: string;
  tileIds?: string[];
  startOffsetS?: number;
  endOffsetS?: number;
  startTimeOffsetS?: number;  // alias for backwards compat
  endTimeOffsetS?: number;    // alias for backwards compat
  startIdx?: number;
  endIdx?: number;
  vertM: number;
  distanceM?: number;
  avgGradientPct?: number;
  durationS?: number;
  avgSpeedMps?: number;
  vam?: number;
  signatureHex?: string;
  matchTrace?: {
    detection?: {
      effortBounds?: number[];
    };
  };
  // Real completion-backed facts, present only when this ride produced an
  // authoritative vault completion for this climb pattern. Every field is a
  // backend projection — the API never sends invented values.
  vaultMatch?: {
    id: string;
    vaultId: number;
    vaultClimbId?: string | null;  // Canon registry climb UUID (climb-sheet key)
    name?: string | null;
    yourTime?: number | null;      // This ride's completion time on the vault
    isPR?: boolean | null;         // vault_completions.is_pr for this ride
    yourBestTime?: number | null;  // All-time best (chain-indexed)
    yourRank?: number | null;      // All-time Record Board rank (top 10)
    komTime?: number | null;       // Current KOM time
    komHolder?: string | null;     // Current KOM holder wallet
  };
}

export interface SteadyPattern {
  durationS: number;
  avgPowerW?: number;
  avgHrBpm?: number;
  startTimeOffsetS: number;
  endTimeOffsetS: number;
}

export interface ExplorationPattern {
  newTilesWallet: number;
  totalTiles: number;
  discoveryPct: number;
}

export interface PatternsResponse {
  rideId: string;
  patterns: {
    climbPatterns?: ClimbPattern[];
    steadyPattern?: SteadyPattern;
    explorationPattern?: ExplorationPattern;
  };
  summary: string;
  totalCount: number;
}

// Achievement types
export interface Achievement {
  id: string;
  achievementType: string;
  title: string;
  description?: string;
  value?: number;
  rank?: number;
  rideId?: string;
  climbId?: string;
  metadata?: Record<string, unknown>;
  isPublic?: boolean;
  createdAt: string;
}

export interface AchievementsResponse {
  achievements: Achievement[];
}

// ==================== VAULT TYPES ====================

export interface Vault {
  id: number;
  signatureHex: string;
  signatureHashHex?: string;
  name: string;
  vertM: number;
  distanceM: number;
  avgGradientPct: number;
  totalCompletions: number;
  totalStaked: string;
  totalStakedBaseUnits: string;
  totalCalStaked: string;
  totalCalStakedBaseUnits: string;
  komHolder: string | null;
  komTimeS: number | null;
  minter: string;
  pda?: string;
  startLat?: number | null;
  startLon?: number | null;
  endLat?: number | null;
  endLon?: number | null;
  onChainActive?: boolean;
  onChainSeedingStatus?: 'pending' | 'seeding' | 'seeded' | 'activating' | 'active' | 'failed';
}

export interface VaultDetail extends Vault {
  leaderboard: VaultLeaderboardEntry[];
  totalLpTokens: string;
  totalLpTokensBaseUnits: string;
  localLegend: {
    wallet: string;
    electedEpoch: number;
    termEndEpoch: number;
    completionsCount: number;
    isActive?: boolean;
    isBootstrap?: boolean;
    seatStatus?: string;
  } | null;
}

/** Display provenance comes from the API, never from the presence of watts. */
export interface ClimbPowerFields {
  powerKind?: 'measured' | 'estimated' | null;
  avgPowerW?: number | null;
  estimatedPowerW?: number | null;
  estimatedPowerRangeW?: [number, number] | null;
  wPerKg?: number | null;
}

export interface ClimbEffort {
  effortId: string;
  climbId: string;
  rideId: string;
  metrics: ClimbPowerFields;
}

export interface VaultLeaderboardEntry extends ClimbPowerFields {
  placeSource?: 'onchain' | 'offchain_completions' | 'rides' | null;
  identityHidden?: boolean;
  vaultSignature?: string | null;
  position?: number | null;
  rank: number;
  competitionRank?: number | null;
  tieSize?: number | null;
  isTied?: boolean;
  wallet: string;
  userId?: string | null;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
  bestTimeSeconds: number;
  avgPowerW: number | null;
  effortId?: string | null;
  rideId?: string | null;
  completionId?: string | null;
  achievedAt?: string | null;
}

export interface VaultCompletion {
  id: string;
  vaultId: number;
  vaultName?: string;
  wallet: string;
  timeSeconds: number;
  avgPowerW: number | null;
  activityId: string;
  achievedAt: string;
  isKom?: boolean;
  leaderboardRank?: number;
}

export interface VaultStake {
  vaultSignature: string;
  vaultId?: number | null;
  vaultName?: string | null;
  /** Canon registry climb UUID where the vault is canon-bound. */
  climbId?: string | null;
  wallet: string;
  calStaked: string;
  calStakedBaseUnits: string;
  lpTokens: string;
  lpTokensBaseUnits: string;
  stakedAt: string;
}

export interface VaultsListResponse {
  vaults: Vault[];
  total: number;
  offset: number;
  limit: number;
}

export interface VaultLeaderboardResponse {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  climbId: string;
  climbName?: string | null;
  segmentId?: string | null;
  segmentName?: string | null;
  vaultId: number | null;
  leaderboard: VaultLeaderboardEntry[];
  entries: VaultLeaderboardEntry[];
  komHolder: string | null;
  komTimeS: number | null;
  viewerEntry?: VaultLeaderboardEntry | null;
}

export interface VaultMatchResponse {
  matched: Array<{
    signatureHex: string;
    vault: Vault;
    similarity: number;
  }>;
  unmatched: string[];
}

export interface VaultCompletionResponse {
  completion: VaultCompletion;
  newLeaderboardRank: number | null;
  calEarned: number;
}

export interface VaultStakeResponse {
  vaultSignature: string;
  calStaked: string;
  calStakedBaseUnits: string;
  lpTokensReceived: string | null;
  lpTokensReceivedBaseUnits: string | null;
  totalPosition: string | null;
  totalPositionBaseUnits: string | null;
  stake: VaultStake | null;
  newTotalStaked: string | null;
  newTotalStakedBaseUnits: string | null;
  txSignature?: string | null;
  projectionStatus?: string;
  confirmationStatus?: string | null;
  riderState?: string | null;
  operationId?: string | null;
  message?: string | null;
}

export type VaultUnstakeInput =
  | { withdrawAll: true; lpAmountBaseUnits?: never }
  | { withdrawAll?: false; lpAmountBaseUnits: string };

export interface VaultUnstakeResponse {
  vaultSignature: string;
  lpBurned: string;
  lpBurnedBaseUnits: string;
  calReturned: string | null;
  calReturnedBaseUnits: string | null;
  txSignature?: string | null;
  projectionStatus?: string;
  confirmationStatus?: string | null;
  riderState?: string | null;
  operationId?: string | null;
  message?: string | null;
}

export interface PreparedVaultTransaction {
  transaction: string;
  blockhash: string;
  lastValidBlockHeight: number;
  message: string;
  vaultId?: number | null;
  pda?: string | null;
}

export type VaultCreationPaymentMethod = 'dung' | 'cal_usdc';

export interface VaultCreationAvailability {
  state: 'available' | 'reserved' | 'active' | 'unavailable';
  paymentMethods: VaultCreationPaymentMethod[];
}

export interface PreparedVaultCreation extends PreparedVaultTransaction {
  preparationId: string;
  climbId: string;
  canonCommitmentHex: string;
}

export interface PendingRewardEntry {
  epoch: number;
  receiptType: string;
  amount: string;
  amountBaseUnits: string;
  rank: number | null;
}

export interface VaultPendingRewardsResponse {
  vaultSignature: string;
  vaultName: string;
  pendingRewards: PendingRewardEntry[];
  totalPending: string;
  totalPendingBaseUnits: string;
  feeEstimate: string;
  feeEstimateBaseUnits: string;
  netEstimate: string;
  netEstimateBaseUnits: string;
  harvestFeeBps: string;
  exitFeeBps: string;
  lpTokensBaseUnits: string | null;
  withdrawalAmountBaseUnits: string | null;
  withdrawalFeeBaseUnits: string | null;
  withdrawalNetBaseUnits: string | null;
}

export interface VaultHarvestResponse {
  vaultSignature: string;
  vaultName: string;
  totalHarvested: string;
  totalHarvestedBaseUnits: string;
  feeAmount: string;
  feeAmountBaseUnits: string;
  netReceived: string;
  netReceivedBaseUnits: string;
  destinationTokenAccount: string;
  destinationType: 'spl_wallet_ata';
  receiptsCount: number;
  txSignature: string | null;
  projectionStatus?: string | null;
  confirmationStatus?: string | null;
  riderState?: string | null;
  operationId?: string | null;
  message?: string | null;
}

export interface UserEffortHistoryEntry {
  id: string;
  rideId?: string | null;
  timeSeconds: number;
  avgPowerW: number | null;
  achievedAt: string | null;
  isPR: boolean;
  improvement: number | null; // seconds faster than previous PR
}

export interface UserEffortHistoryResponse {
  vaultId: number;
  vaultName: string;
  efforts: UserEffortHistoryEntry[];
  totalCount: number;
  bestTimeSeconds: number | null;
  totalPrs: number;
}

export interface CreateVaultResponse {
  preparationId: string;
  vaultId: number;
  climbId: string;
  pda: string;
  txSignature: string;
  activationState: 'active' | 'pending';
  projectionStatus: 'active' | 'pending';
  confirmationStatus: 'finalized' | 'confirmed' | 'pending';
  message: string;
}

// Public profile (limited view for other users)
export interface PublicProfile {
  id: string;
  wallet: string;
  username?: string;
  displayName?: string;
  bio?: string;
  avatarUrl?: string;
  isPublic: boolean;
  privacy?: PrivacyState | null;
  createdAt?: string;
  totalRides?: number;
  totalDistanceKm?: number;
  totalElevationM?: number;
  followerCount?: number;
  followingCount?: number;
  currentStreak?: number;
  longestStreak?: number;
  lastActivityDate?: string;
}

export interface PublicRiderRideSummary {
  id: string;
  title: string;
  status?: string;
  startedAt?: string;
  createdAt?: string;
  distanceM?: number;
  elevationGainM?: number;
  durationSec?: number;
  visibility?: RideVisibility;
  privacy?: PrivacyState | null;
  media?: RideMedia[];
  primaryMedia?: RideMedia | null;
  routePreview?: RoutePreview | null;
}

export interface PublicRiderRecentRidesResponse {
  isPublic: boolean;
  rides: PublicRiderRideSummary[];
  count: number;
  privacy?: PrivacyState;
}

export interface PublicRiderProfileModule {
  id: string;
  key?: string;
  state: 'present' | 'hidden' | 'empty' | 'unavailable' | string;
  title?: string;
  reason?: string | null;
  count?: number;
}

export interface PublicRiderProfileResponse {
  contractVersion?: 'public_rider_profile.v1';
  rider?: unknown;
  profile: PublicProfile;
  privacy?: PrivacyState | null;
  viewerCapabilities?: Record<string, unknown>;
  modules?: PublicRiderProfileModule[];
  followState?: {
    isFollowing?: boolean;
    isFollowedBy?: boolean;
    isMutualFollow?: boolean;
  } | null;
  recentRides: PublicRiderRecentRidesResponse;
  beetleCards: PublicRiderBeetleCardsResponse;
  leaderboard?: unknown;
}

export interface PublicPreviewPolicy {
  mode: 'public_preview';
  objectType: 'ride' | 'climb' | 'rider';
  rawGpsAvailable: boolean;
  streamsAvailable: boolean;
  tilesAvailable: boolean;
  privateRideHistoryAvailable: boolean;
  unreviewedProjectionsAvailable: boolean;
  walletRequired: boolean;
  loginRequiredFor: string[];
  blockedSurfaces: string[];
  privacy?: PrivacyState | Record<string, unknown> | null;
}

export interface PublicPreviewSeo {
  title: string;
  description: string;
  canonicalPath: string;
  robots: string;
  openGraph?: {
    type?: string;
    image?: {
      kind?: string;
      url?: string | null;
      alt?: string | null;
    };
  };
}

export interface PublicPreviewRiderRef {
  contractVersion?: 'public_rider_ref.v1';
  id?: string | null;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
  isPublic?: boolean | null;
  viewerRelationship?: string;
  displayLabel?: string;
  identityHidden?: boolean;
}

export interface PublicRecordBoardPreviewEntry extends ClimbPowerFields {
  rank: number;
  position?: number;
  competitionRank?: number;
  tieSize?: number;
  isTied?: boolean;
  bestTimeSeconds?: number | null;
  avgPowerW?: number | null;
  effortId?: string | null;
  rideId?: string | null;
  completionId?: string | null;
  achievedAt?: string | null;
  rider: PublicPreviewRiderRef;
}

export interface PublicRecordBoardPreview {
  contractVersion: 'record_board_preview.v1';
  climbId?: string | null;
  climbName?: string | null;
  vaultId?: number | string | null;
  entries: PublicRecordBoardPreviewEntry[];
  rowLimit: number;
  visibleRows: number;
  hiddenRows: number;
  identityPolicy: {
    wallets: 'redacted' | string;
    profileFields: 'public_profile_only' | string;
  };
  truthSource?: TruthSource | string;
}

export interface PublicPreviewAssets {
  contractVersion: 'public_preview.v1';
  objectType: 'ride' | 'climb' | 'rider';
  openGraphImage?: {
    kind?: string;
    status?: string;
    alt?: string | null;
  };
  routePreview?: {
    kind: string;
    preview: RoutePreview;
  };
  recordBoard?: {
    kind: 'record_board_preview' | string;
    preview: PublicRecordBoardPreview;
  };
  media?: {
    kind: 'ride_media_preview' | string;
    items: RideMedia[];
  };
}

export interface PublicPreviewFreshness {
  source: string;
  loadedAt: string;
  cacheTtlSeconds: number;
}

interface PublicPreviewBase {
  contractVersion: 'public_preview.v1';
  objectType: 'ride' | 'climb' | 'rider';
  id?: string | null;
  canonicalPath: string;
  title: string;
  previewPolicy: PublicPreviewPolicy;
  seo: PublicPreviewSeo;
  assets: PublicPreviewAssets;
  freshness: PublicPreviewFreshness;
}

export interface RidePublicPreview extends PublicPreviewBase {
  objectType: 'ride';
  id: string;
  compatPaths?: string[];
  ride: Ride & {
    createdAt?: string | null;
    status?: string | null;
    rider?: PublicPreviewRiderRef | null;
    // Public projection gaps must remain disconnected in every consumer.
    elevationProfile?: Array<{ distanceM: number; elevationM: number; breakBefore?: boolean }> | null;
    countedSpans?: Array<{ startDistanceM: number; endDistanceM: number; patternId: string }> | null;
  };
}

export interface ClimbPublicPreview extends PublicPreviewBase {
  objectType: 'climb';
  id: string;
  climb: Climb & {
    routePreview?: RoutePreview | null;
    recordBoard?: PublicRecordBoardPreview | null;
  };
}

export interface RiderPublicPreview extends PublicPreviewBase {
  objectType: 'rider';
  rider?: PublicPreviewRiderRef | null;
  profile?: Partial<PublicProfile> | null;
  modules?: PublicRiderProfileModule[];
  recentRides?: PublicRiderRecentRidesResponse | null;
  beetleCards?: PublicRiderBeetleCardsResponse | null;
  leaderboard?: unknown;
  viewerCapabilities?: Record<string, unknown> | null;
}

export type PublicPreview = RidePublicPreview | ClimbPublicPreview | RiderPublicPreview;

// Comments
export interface Comment {
  id: string;
  userId: string;
  targetType?: string;
  targetId?: string;
  username?: string;
  displayName?: string;
  content: string;
  createdAt: string;
  updatedAt?: string;
  parentId?: string;
  viewerReported?: boolean;
  reportStatus?: string | null;
}

export interface RideInteractions {
  rideId: string;
  kudosCount: number;
  commentCount: number;
  viewerHasKudos: boolean;
  viewerReported?: boolean;
  reportStatus?: string | null;
  commentsEnabled: boolean;
  canComment: boolean;
}

export interface SocialReport {
  contractVersion?: 'moderation.v1';
  id: string;
  reporterId: string;
  targetType: 'ride' | 'comment' | 'user' | 'ride_media';
  targetId: string;
  reason: string;
  details?: string | null;
  status: 'open' | 'reviewing' | 'resolved' | 'dismissed';
  createdAt: string;
  updatedAt?: string;
  reviewedAt?: string | null;
  reviewedBy?: string | null;
  resolutionNote?: string | null;
  resolutionAction?: 'review_started' | 'leave_visible' | 'hide' | 'remove' | 'unsupported' | null;
  reporterOutcome?: string | null;
  reporterMessage?: string | null;
  moderationMetadata?: Record<string, unknown>;
  actionHistory?: ModerationAction[];
  reporter?: {
    id?: string | null;
    username?: string | null;
    displayName?: string | null;
    avatarUrl?: string | null;
  } | null;
  reviewer?: {
    id?: string | null;
    username?: string | null;
    displayName?: string | null;
    avatarUrl?: string | null;
  } | null;
}

export interface ModerationAction {
  id: string;
  reportId?: string | null;
  actorId?: string | null;
  actionType: 'review_started' | 'leave_visible' | 'hide' | 'remove' | 'unsupported' | string;
  actionStatus: 'applied' | 'deferred' | 'unsupported' | 'failed' | string;
  targetType: string;
  targetId: string;
  note?: string | null;
  metadata?: Record<string, unknown>;
  createdAt?: string | null;
}

export interface ModerationReportsResponse {
  reports: SocialReport[];
  count: number;
}

// ==================== BEETLE CARD TYPES ====================

export type BeetleCardType = 'CLIMB' | 'STEADY' | 'EXPLORATION';

export interface BeetleCard {
  id: string;
  wallet: string;
  cardType: BeetleCardType;
  scopeId: string;
  scopeName?: string;
  score: number;
  level: number;
  patternsScored: number;
  nextLevelThreshold?: number;
  progressToNext?: number;
  upgradeCostDung?: number;
  createdAt: string;
  updatedAt: string;
}

export interface PublicRiderBeetleCardsResponse {
  isPublic: boolean;
  cards: BeetleCard[];
  count: number;
  privacy?: PrivacyState;
}

export interface BeetleLevelInfo {
  maxLevel: number;
  upgradeCosts: {
    fromLevel: number;
    toLevel: number;
    dungCost: number;
    formula: string;
  }[];
  levelNames: string[];
}

export interface BeetleLeaderboardEntry {
  rank: number;
  wallet: string;
  score: number;
  level: number;
  patternsScored: number;
  scopeName?: string;
}

export interface BeetleLeaderboardResponse {
  cardType: BeetleCardType;
  scopeId: string;
  scopeName: string;
  entries: BeetleLeaderboardEntry[];
  count: number;
  offset: number;
}

// ==================== SESSION TYPES ====================

export interface SessionInfo {
  id: string;
  deviceId: string;
  userAgent?: string;
  ipAddress?: string;
  locationHint?: string;
  createdAt: string;
  lastUsedAt?: string;
  isCurrent: boolean;
}

export interface SessionsListResponse {
  sessions: SessionInfo[];
}

// ==================== LINK TYPES ====================

export type LinkTargetType =
  | 'rider'
  | 'ride'
  | 'ride_media'
  | 'climb'
  | 'record_board'
  | 'local_legend'
  | 'proof'
  | 'scan_tx'
  | 'scan_account';

export interface LinkTarget {
  type: LinkTargetType;
  id: string;
}

export interface LinkAccess {
  canView: boolean;
  reason: string;
  protocolPublic: boolean;
  requiresAuth: boolean;
}

export interface LinkSharePayload {
  title: string;
  text: string;
  url: string;
}

export interface LinkOpenGraphPayload extends LinkSharePayload {
  type: string;
}

export interface ResolvedLink {
  contractVersion: 'link.v1';
  status: 'resolved' | 'forbidden' | 'missing';
  target: LinkTarget;
  webPath: string;
  canonicalUrl: string;
  appUrl: string;
  externalUrl?: string | null;
  title: string;
  description: string;
  access: LinkAccess;
  metadata: Record<string, unknown>;
  scanState?: 'pending' | 'recorded' | 'finalized' | 'missing' | 'failed' | 'off_chain_only' | 'private' | null;
  scanTargets?: ScanTarget[];
  share: LinkSharePayload;
  openGraph: LinkOpenGraphPayload;
}

export interface ScanTarget {
  contractVersion?: 'scan.v1';
  type: 'transaction' | 'account' | 'vault' | 'proof' | 'wallet' | string;
  id: string;
  state: 'pending' | 'recorded' | 'finalized' | 'missing' | 'failed' | 'off_chain_only' | 'private' | string;
  label: string;
  url: string;
  source: string;
  metadata?: Record<string, unknown>;
}

export interface LinkSchemaTarget {
  type: LinkTargetType;
  webPathTemplate: string;
  aliases: string[];
}

export interface LinkSchemaResponse {
  contractVersion: 'link.v1';
  webOrigin: string;
  scanOrigin: string;
  scanContractVersion?: 'scan.v1';
  targets: LinkSchemaTarget[];
}

// ==================== SEARCH TYPES ====================

export type SearchType = 'all' | 'riders' | 'rides' | 'climbs' | 'proofs';
export type SearchResultType = 'rider' | 'ride' | 'climb' | 'proof';

export interface SearchStat {
  label: string;
  value: string;
}

export interface SearchImage {
  kind: 'avatar' | 'route' | 'climb' | string;
  url?: string | null;
}

export interface SearchResult {
  contractVersion: 'search.v1';
  id: string;
  type: SearchResultType;
  title: string;
  subtitle: string;
  summary?: string | null;
  target: LinkTarget;
  webPath: string;
  source: 'backend' | 'indexer' | string;
  privacy?: PrivacyState | null;
  stats: SearchStat[];
  image?: SearchImage | null;
  score: number;
  matchedFields: string[];
  scanState?: ResolvedLink['scanState'];
  scanTargets?: ScanTarget[];
  metadata: Record<string, unknown>;
}

export interface SearchResponse {
  contractVersion: 'search.v1';
  query: string;
  normalizedQuery: string;
  type: SearchType;
  results: SearchResult[];
  hasMore: boolean;
}

export interface SearchSuggestionSection {
  id: string;
  title: string;
  results: SearchResult[];
}

export interface SearchSuggestionsResponse {
  contractVersion: 'search.v1';
  sections: SearchSuggestionSection[];
}

export interface SearchSchemaResponse {
  contractVersion: 'search.v1';
  types: SearchType[];
  resultTypes: SearchResultType[];
  targetContractVersion: 'link.v1';
  targets: LinkTargetType[];
  capabilities?: string[];
}

// ==================== NOTIFICATION TYPES ====================

export type NotificationEventType =
  | 'comment_created'
  | 'follow_created'
  | 'kudos_created'
  | 'ride_completed'
  | 'ride_finalized'
  | 'ride_failed'
  | 'leaderboard_entered'
  | 'leaderboard_bumped'
  | 'record_rank_moved'
  | 'rank_changed'
  | 'kom_achieved'
  | 'local_legend_moved'
  | 'achievement_unlocked'
  | 'payout_received'
  | 'stake_payout'
  | 'legend_payout'
  | 'report_resolved'
  | 'proof_updated'
  | 'settlement_finalized'
  | 'tier_unlocked'
  | 'login_new_device'
  | 'session_revoked'
  | 'strava_revoked'
  | 'system';

export interface NotificationActor {
  id?: string | null;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
  wallet?: string | null;
}

export interface NotificationTarget {
  type: string;
  id?: string | null;
  /** The noun the push is about, when the backend names it (climb, ride, rider). */
  label?: string | null;
}

export interface Notification {
  transition?: NotificationTransition | null;
  contractVersion?: 'notification.v1';
  id: string;
  notificationType: NotificationEventType;
  legacyType?: string | null;
  eventType?: NotificationEventType;
  title: string;
  message: string;
  actor?: NotificationActor | null;
  target?: NotificationTarget | null;
  metadata?: {
    vaultName?: string;
    vaultSignature?: string;
    rank?: number;
    oldRank?: number;
    bumpedBy?: string;
    payoutAmount?: number;
    timeSeconds?: number;
    time?: number;
    rideId?: string;
    commentId?: string;
    followerId?: string;
    isPR?: boolean;
    [key: string]: unknown;
  };
  deliveryStatus?: 'pending' | 'in_app_delivered' | 'suppressed' | 'failed' | string;
  deliveryChannels?: string[];
  dedupeKey?: string | null;
  vaultSignature?: string;
  read: boolean;
  readAt?: string;
  createdAt: string;
  occurredAt?: string;
  actionUrl?: string | null;
}

export interface NotificationsResponse {
  contractVersion?: 'notification.v1';
  notifications: Notification[];
  unreadCount: number;
}

export interface NotificationPreferences {
  emailEnabled?: boolean;
  pushEnabled?: boolean;
  inAppEnabled?: boolean;
  newFollower?: boolean;
  rideCompleted?: boolean;
  achievementUnlocked?: boolean;
  komBeaten?: boolean;
  stakingReward?: boolean;
  leaderboardUpdates?: boolean;
  payoutAlerts?: boolean;
  socialActivity?: boolean;
  systemAnnouncements?: boolean;
  securityAlerts?: boolean;
  connectedAppAlerts?: boolean;
  rideUpdates?: boolean;
  followCreated?: boolean;
  commentCreated?: boolean;
  kudosCreated?: boolean;
  rideFinalized?: boolean;
  rideFailed?: boolean;
  leaderboardEntered?: boolean;
  leaderboardBumped?: boolean;
  rankChanged?: boolean;
  recordRankMoved?: boolean;
  komAchieved?: boolean;
  localLegendMoved?: boolean;
  payoutReceived?: boolean;
  stakePayout?: boolean;
  legendPayout?: boolean;
  reportResolved?: boolean;
  proofUpdated?: boolean;
  settlementFinalized?: boolean;
  tierUnlocked?: boolean;
  loginNewDevice?: boolean;
  sessionRevoked?: boolean;
  stravaRevoked?: boolean;
}

// ==================== STRAVA TYPES ====================

export interface StravaAuthUrlResponse {
  url: string;
  state: string;
}

export interface ExportUserDataResponse {
  status: string;
  message: string;
  downloadUrl?: string | null;
}

export interface StravaConnectionResponse {
  connected: boolean;
  athleteId?: number;
  athleteUsername?: string;
  athleteFirstname?: string;
  athleteLastname?: string;
  connectedAt?: string;
  lastSyncAt?: string;
}

export interface StravaActivitySummary {
  id: number;
  name: string;
  type: string;
  sportType: string;
  startDate: string;
  distanceKm: number;
  movingTimeMinutes: number;
  elevationGainM: number;
  hasPower: boolean;
  alreadyImported: boolean;
}

export interface StravaActivitiesResponse {
  activities: StravaActivitySummary[];
  page: number;
  hasMore: boolean;
}

export interface StravaImportResult {
  stravaActivityId: number;
  success: boolean;
  activityId?: string;
  error?: string;
}

export interface StravaImportResponse {
  results: StravaImportResult[];
  importedCount: number;
  failedCount: number;
}

// System status for feature flags
export interface BalanceRolloutActionStatus {
  key: string;
  label: string;
  enabled: boolean;
  order: number;
  boundaryAction: boolean;
}

export interface BalanceRolloutStatus {
  stage: string;
  cohort: string;
  enabledActions: string[];
  actionOrder: string[];
  actions: BalanceRolloutActionStatus[];
  owner?: string | null;
  rollbackOwner?: string | null;
  rollbackContact?: string | null;
  startedAt?: string | null;
  enforced: boolean;
  orderValid: boolean;
  blockers: string[];
}

export interface SystemStatus {
  stage1?: { live: boolean; actions: boolean };
  environment: string;  // "development", "staging", "production"
  solanaStubMode: boolean;  // True if using stubbed Solana transactions
  version?: string;
  authSignatureBypassRequested?: boolean;
  authSignatureBypassEffective?: boolean;
  authCookieSecure?: boolean;
  devRoutesEnabled?: boolean;
  balanceRollout: BalanceRolloutStatus;
}

// ==================== ADMIN: SIGNIFICANCE TYPES ====================

export interface HistogramBin {
  bin: number;
  count: number;
}

export interface SignificanceOverview {
  terrainCells: {
    total: number;
    byConfidenceTier: Record<string, number>;
    byResolution: Record<string, number>;
    diagPassCount: number;
    diagFailCount: number;
    oldestBootstrap: string | null;
    newestBootstrap: string | null;
    byDiversityTier: Record<string, number>;
    singleRiderCells: number;
    effectiveNStats: { min: number; max: number; median: number };
  };
  gpdParams: {
    xiHistogram: HistogramBin[];
    sigmaHistogram: HistogramBin[];
    xiStats: { min: number; max: number; mean: number; median: number };
    sigmaStats: { min: number; max: number; mean: number; median: number };
  };
  climbScores: {
    total: number;
    scored: number;
    unscored: number;
    gHistogram: HistogramBin[];
    percentileHistogram: HistogramBin[];
  };
}

export type ReviewStatus = 'confirmed' | 'false_positive' | 'disputed' | 'auto_confirmed' | null;
export type ReviewCategory = 'noise' | 'too_short' | 'duplicate' | 'sensor_error' | 'misattributed' | 'borderline' | 'other';

export interface ClimbReviewRequest {
  verdict: 'confirmed' | 'false_positive' | 'disputed';
  reason?: string;
  category?: ReviewCategory;
}

export interface BulkReviewRequest {
  climbIds: string[];
  verdict: 'confirmed' | 'false_positive' | 'disputed';
  reason?: string;
  category?: ReviewCategory;
}

export interface SignificanceClimb {
  id: string;
  activityId: string;
  roadName: string | null;
  vertM: number;
  distanceM: number | null;
  avgGradientPct: number | null;
  persistenceM: number;
  significanceG: number;
  significancePercentile: number;
  significanceReturnPeriod: number;
  significanceConfidenceTier: number;
  significanceBootstrapped: boolean;
  significanceCellH3: string | null;
  signatureHex: string | null;
  reviewStatus: ReviewStatus;
  reviewedAt: string | null;
  createdAt: string;
}

export interface SignificanceClimbsResponse {
  climbs: SignificanceClimb[];
  total: number;
  limit: number;
  offset: number;
}

export interface TerrainCell {
  h3Index: string;
  h3Resolution: number;
  nFeatures: number;
  kExceedances: number;
  thresholdM: number;
  thresholdQuantile: number;
  gpdXi: number;
  gpdSigma: number;
  xiCiHi: number;
  gCap: number;
  confidenceTier: number;
  tailDiagPass: boolean;
  bootstrappedAt: string | null;
  osmRoadKm: number | null;
  parentH3Index: string | null;
  // Rider diversity fields
  nUniqueRiders: number;
  effectiveN: number | null;
  topRiderPct: number | null;
  diversityTier: number;
  nUniqueRoutes: number | null;
}

export interface SignificanceCellsResponse {
  cells: TerrainCell[];
  total: number;
}

export interface SignificanceCellDetail {
  cell: TerrainCell;
  climbsInCell: {
    id: string;
    activityId: string;
    roadName: string | null;
    vertM: number;
    persistenceM: number;
    significanceG: number;
    significancePercentile: number;
    significanceReturnPeriod: number;
  }[];
  diversityMetrics?: {
    nUniqueRiders: number;
    effectiveN: number | null;
    topRiderPct: number | null;
    diversityTier: number;
    diversityTierName: string;
    nUniqueRoutes: number | null;
  };
}

export interface BackfillCandidatesResponse {
  candidates: {
    id: string;
    activityId: string;
    roadName: string | null;
    vertM: number;
    persistenceM: number;
    createdAt: string;
  }[];
  totalMissing: number;
}

export interface BackfillScoresResponse {
  processed: number;
  scored: number;
  noTerrainData: number;
  dryRun: boolean;
  staleOnly?: boolean;
}

// ==================== ADMIN: CELL HISTORY / DRIFT TYPES ====================

export interface CellHistoryEntry {
  id: number;
  runId: string;
  h3Index: string;
  h3Resolution: number;
  nFeatures: number | null;
  kExceedances: number | null;
  thresholdM: number | null;
  thresholdQuantile: number | null;
  gpdXi: number | null;
  gpdSigma: number | null;
  xiCiHi: number | null;
  gCap: number | null;
  confidenceTier: number;
  tailDiagPass: boolean;
  nUniqueRiders: number | null;
  effectiveN: number | null;
  diversityTier: number | null;
  // Deltas
  prevGpdXi: number | null;
  prevGpdSigma: number | null;
  deltaXi: number | null;
  deltaSigma: number | null;
  deltaNFeatures: number | null;
  deltaKExceedances: number | null;
  tierChanged: boolean;
  diagChanged: boolean;
  // Drift
  maxScoreImpact: number | null;
  driftFlagged: boolean;
  triggerReason: string;
  createdAt: string;
}

export type ConvergenceStatus = 'stable' | 'converging' | 'diverging' | 'insufficient_history';

export interface CellHistory {
  h3Index: string;
  history: CellHistoryEntry[];
  convergenceStatus: ConvergenceStatus;
  snapshotCount: number;
}

export interface DriftSummary {
  runId: string | null;
  totalCells: number;
  driftedCells: number;
  staleClimbs: number;
  driftedCellDetails: Array<{
    h3Index: string;
    deltaXi: number | null;
    deltaSigma: number | null;
    maxScoreImpact: number | null;
    tierChanged: boolean;
    diagChanged: boolean;
    confidenceTier: number | null;
    nFeatures: number | null;
  }>;
  triggerReason: string | null;
}

// ==================== ADMIN: SCORING TRACE / PIPELINE / FIT TYPES ====================

export interface ScoringTrace {
  climb: SignificanceClimb;
  cell: TerrainCell | null;
  trace: {
    persistenceM: number;
    noiseGateM: number;
    passedNoiseGate: boolean;
    midpointTile: string | null;
    cellLookup: {
      res5Parent: string | null;
      res5Found: boolean;
      res4Fallback: boolean;
      cellH3: string | null;
    };
    thresholdM: number | null;
    thresholdQuantile: number | null;
    exceedanceM: number | null;
    gpdXi: number | null;
    gpdSigma: number | null;
    xiCiHi: number | null;
    survivalPoint: number | null;
    survivalConservative: number | null;
    gPoint: number | null;
    gConservative: number | null;
    gCap: number | null;
    gFinal: number;
    diagPass: boolean | null;
    confidenceTier: number;
    percentile: number;
    returnPeriod: number;
  };
}

export interface PipelineStats {
  climbsDetected: number;
  climbsWithPersistence: number;
  climbsInTerrainCell: number;
  climbsScored: number;
  climbsUnscored: number;
  dropoffs: Array<{ stage: string; from: number; to: number; reason: string }>;
}

export interface ElevationProfileSample {
  t: number;
  elevationM: number;
  powerW: number | null;
  speedMps: number | null;
}

export interface PersistencePairData {
  birthIdx: number;
  deathIdx: number;
  birthElev: number;
  deathElev: number;
  persistenceM: number;
  aboveNoiseGate: boolean;
}

export interface ElevationProfileData {
  climb: {
    id: string;
    roadName: string | null;
    vertM: number | null;
    distanceM: number | null;
    persistenceM: number | null;
    significanceG: number | null;
    startOffsetS: number;
    endOffsetS: number;
  };
  profile: {
    contextBeforeS: number;
    contextAfterS: number;
    samples: ElevationProfileSample[];
    smoothed: number[];
    smoothingWindow: number;
  };
  persistence: {
    noiseGateM: number;
    pairs: PersistencePairData[];
  };
}

export interface CellFitData {
  cell: TerrainCell;
  persistenceValues: number[];
  thresholdM: number;
  fittedCurve: Array<{ x: number; empiricalCdf: number; gpdCdf: number }>;
  climbPositions: Array<{ id: string; persistenceM: number; gScore: number; roadName: string | null }>;
}

// ==================== ADMIN: PLATFORM DASHBOARD TYPES ====================

export interface PlatformOverview {
  users: { total: number; new7d: number };
  rides: { total: number; thisWeek: number; totalTss: number; totalDistanceM: number; totalElevationM: number; byStatus: Record<string, number> };
  vaults: { total: number; totalCompletions: number; totalStakedCal: number; uniqueStakers: number };
  climbs: { total: number; scored: number; pctScored: number };
  epoch: { currentEpoch: number; storedEpoch: number; epochNeedsTransition: boolean; pendingDistributions: number };
  supply: {
    maxSupplyBaseUnits: string;
    totalMintedBaseUnits: string;
    protocolBurnedBaseUnits: string;
    circulatingSupplyBaseUnits: string | null;
    circulatingSource: 'spl_mint_supply' | 'unavailable';
    communityMintedBaseUnits: string;
    communityCapBaseUnits: string;
    treasuryMintedBaseUnits: string;
    treasuryCapBaseUnits: string;
    teamMintedBaseUnits: string;
    teamCapBaseUnits: string;
    investorMintedBaseUnits: string;
    investorCapBaseUnits: string;
    polMintedBaseUnits: string;
    polCapBaseUnits: string;
  };
  emission: { currentEpoch: number; currentEmissionRateBps: number; totalHalvings: number; nextHalvingAt: string | null };
  controls: { stakingEnabled: boolean; mintingEnabled: boolean; uploadsEnabled: boolean; withdrawalsEnabled: boolean; maintenanceMode: boolean };
  healthStatus: string;
  generatedAt: string;
}

export interface AdminActivityFeedItem {
  id: string;
  source: string;
  eventType: string;
  detail: string | null;
  wallet?: string | null;
  metadata?: Record<string, unknown> | null;
  createdAt: string;
}

export interface AdminActivityFeedResponse {
  items: AdminActivityFeedItem[];
  count: number;
}

export interface AuditLogEntry {
  id: string;
  action: string;
  userId?: string | null;
  targetType?: string | null;
  metadata?: Record<string, unknown> | null;
  ipAddress?: string | null;
  createdAt: string;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
  count: number;
}

export interface StravaAdminHealth {
  healthStatus: string;
  enabled: boolean;
  syncEnabled: boolean;
  integrationMode: 'strava_sync' | 'file_import_only';
  stateVerified: boolean;
  redirectUri?: string | null;
  webhookCallbackUrl?: string | null;
  subscription: {
    active: boolean;
    subscriptionId?: number | null;
    callbackUrl?: string | null;
    createdAt?: string | null;
  };
  connections: {
    activeCount: number;
    recentSync24h: number;
    staleSync7d: number;
    lastWebhookAt?: string | null;
  };
  backfill: Record<string, number>;
  rateLimits: {
    storage: string;
    redisAvailable: boolean;
    usage15min: number;
    limit15min: number;
    remaining15min: number;
    usageDaily: number;
    limitDaily: number;
    remainingDaily: number;
    resetInSeconds15min: number;
  };
  alerts: string[];
  generatedAt: string;
}

export interface AdminControl {
  key: string;
  value: unknown;
  updatedAt?: string | null;
  updatedBy?: string | null;
}

export interface AdminControlsResponse {
  controls: AdminControl[];
}

export interface EpochStatusResponse {
  currentEpoch: number;
  storedEpoch: number;
  epochNeedsTransition: boolean;
  pendingDistributions: number;
  pendingDungTotal: number;
  recentlyCompleted: number;
}

// ==================== TERRITORY TYPES ====================

export interface TerritoryTile {
  tileId: string;
  visitCount: number;
  firstVisitedAt: string;
  lastVisitedAt: string | null;
}

export interface TerritoryTilesResponse {
  tiles: TerritoryTile[];
  count: number;
}

export interface TerritoryStats {
  totalTiles: number;
  totalVisits: number;
  tilesThisWeek: number;
  tilesThisMonth: number;
}

export interface TerritoryHeatmapResponse {
  tiles: { tileId: string; visitCount: number }[];
  resolution: number;
  count: number;
}

// Singleton export
export const api = new APIClient();

// Audit-lane read models. These types do not assert that a producer supplies
// these facts. Missing projections remain absent; no adapter synthesizes them.
export interface ReadModelCoverage {
  completeness: 'complete' | 'partial' | 'unknown';
  population: string;
  observedCount: number | null;
  expectedCount: number | null;
}

export interface CollectionSnapshot {
  revision: string;
  asOf: string;
  coverage: ReadModelCoverage;
  positions: Array<{
    vaultId: number;
    dungReadyBaseUnits: string | null;
  }>;
  uncollectedDungBaseUnits: string | null;
}

export interface RideMetricBasis {
  /** Producer identity for the included span, aggregation and viewer projection. */
  key: string;
  viewerProjection: string;
  startOffsetS: number | null;
  endOffsetS: number | null;
  aggregation: string;
  coverage: ReadModelCoverage;
}

export interface ZoneShareDenominator {
  basis: string;
  durationS: number | null;
  startOffsetS: number | null;
  endOffsetS: number | null;
  coverage: ReadModelCoverage;
}

export interface TraceReductionDescriptor {
  source: string;
  method: string;
  binDistanceM: number | null;
  smoothingWindowSamples: number | null;
  preservesExtrema: boolean | null;
}

export interface RidePresentation {
  id: string;
  revision: string;
  asOf: string;
  metricBasis: RideMetricBasis;
  distanceM: number | null;
  elevationM: number | null;
  durationS: number | null;
  avgPowerW: number | null;
  maxPowerW: number | null;
  zoneShareDenominator: ZoneShareDenominator | null;
  traceReduction: TraceReductionDescriptor | null;
}

export interface TrainingModelSnapshot {
  estimate?: boolean;
  basis?: string;
  revision: string;
  asOf: string;
  initialization: 'initialized' | 'initializing' | 'unknown';
  coverage: ReadModelCoverage;
  fitnessMetrics: FitnessMetrics;
  trainingLoad: TrainingLoad;
}

export interface FeedItemResultSummary {
  rideId: string;
  climbId: string;
  revision: string;
  asOf: string;
  timeSeconds: number | null;
  place: number | null;
  isPersonalBest: boolean | null;
}

export interface NotificationTransition {
  climbId: string;
  revision: string;
  occurredAt: string;
  beforePlace: number | null;
  afterPlace: number | null;
}
