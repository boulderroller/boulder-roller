/**
 * Token Refresh Manager
 *
 * Handles proactive token refresh before expiry so that long rides
 * (4+ hours) never encounter an expired access token mid-upload.
 *
 * Strategy: schedule a refresh 5 minutes before the access token expires.
 * After each successful refresh, reschedule for the new token's expiry.
 *
 * AppState handling is done externally (in AuthInitializer) — when the
 * app comes to foreground, it checks if a refresh is due and calls
 * refresh() or schedule() accordingly.
 */

import { useAuthStore } from '../stores/authStore';

/** Refresh 5 minutes before token expiry */
const REFRESH_BUFFER_MS = 5 * 60 * 1000;

// Forward declaration — set by authService to avoid circular imports
let _attemptRefresh: () => Promise<boolean> = async () => false;

export function setRefreshHandler(handler: () => Promise<boolean>): void {
  _attemptRefresh = handler;
}

class TokenRefreshManager {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private refreshPromise: Promise<boolean> | null = null;

  /**
   * Schedule the next proactive refresh based on token expiry.
   * Called after every successful login or refresh.
   */
  schedule(): void {
    this.cancel();

    const expiresAt = useAuthStore.getState().tokenExpiresAt;
    if (!expiresAt) return;

    const msUntilRefresh = expiresAt - Date.now() - REFRESH_BUFFER_MS;

    if (msUntilRefresh <= 0) {
      // Already due — refresh immediately
      this.refresh();
      return;
    }

    this.timer = setTimeout(() => this.refresh(), msUntilRefresh);
  }

  /**
   * Execute refresh. Deduplicates concurrent calls.
   * Returns true if refresh succeeded.
   */
  async refresh(): Promise<boolean> {
    if (this.refreshPromise) return this.refreshPromise;

    this.refreshPromise = _attemptRefresh()
      .then((success) => {
        if (success) this.schedule(); // Schedule next refresh
        return success;
      })
      .finally(() => {
        this.refreshPromise = null;
      });

    return this.refreshPromise;
  }

  /** Cancel any pending refresh timer. */
  cancel(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  /** Check whether a refresh is currently due based on the buffer. */
  isRefreshDue(): boolean {
    const expiresAt = useAuthStore.getState().tokenExpiresAt;
    if (!expiresAt) return false;
    return expiresAt - Date.now() < REFRESH_BUFFER_MS;
  }
}

export const tokenRefreshManager = new TokenRefreshManager();
