const CHUNK_RELOAD_GUARD_KEY = 'br_chunk_reload_guard';
const CHUNK_RELOAD_EVENT = 'br:stale-chunk-recovery';
const GUARD_CLEAR_DELAY_MS = 5_000;

function readGuard(): boolean {
  try {
    return sessionStorage.getItem(CHUNK_RELOAD_GUARD_KEY) === '1';
  } catch {
    return false;
  }
}

function writeGuard(): void {
  try {
    sessionStorage.setItem(CHUNK_RELOAD_GUARD_KEY, '1');
  } catch {
    // If sessionStorage is blocked, still try the reload once.
  }
}

function clearGuard(): void {
  try {
    sessionStorage.removeItem(CHUNK_RELOAD_GUARD_KEY);
  } catch {
    // Storage access can be denied in hardened browser contexts.
  }
}

function extractErrorMessage(error: unknown): string {
  if (typeof error === 'string') {
    return error;
  }
  if (error && typeof error === 'object' && 'message' in error) {
    const message = (error as { message?: unknown }).message;
    return typeof message === 'string' ? message : '';
  }
  return '';
}

export function isDynamicImportFetchError(error: unknown): boolean {
  const message = extractErrorMessage(error);
  if (!message) return false;
  return (
    message.includes('Failed to fetch dynamically imported module') ||
    message.includes('Importing a module script failed') ||
    message.includes('Loading chunk') ||
    message.includes('ChunkLoadError')
  );
}

export function hasAttemptedStaleChunkRecovery(): boolean {
  return readGuard();
}

export function recoverFromStaleChunk(): boolean {
  if (readGuard()) return false;

  writeGuard();
  window.dispatchEvent(new CustomEvent(CHUNK_RELOAD_EVENT));
  window.location.reload();
  return true;
}

export function recoverFromDynamicImportError(error: unknown): boolean {
  if (!isDynamicImportFetchError(error)) return false;
  return recoverFromStaleChunk();
}

export function installStaleChunkRecoveryHandlers(): void {
  if (readGuard()) return;

  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault();
    recoverFromStaleChunk();
  });

  window.addEventListener('error', (event) => {
    if (isDynamicImportFetchError(event.error) || isDynamicImportFetchError(event.message)) {
      recoverFromStaleChunk();
    }
  });

  window.addEventListener('unhandledrejection', (event) => {
    if (isDynamicImportFetchError(event.reason)) {
      event.preventDefault();
      recoverFromStaleChunk();
    }
  });
}

export function clearStaleChunkRecoveryGuardAfterBoot(): void {
  window.setTimeout(() => {
    clearGuard();
  }, GUARD_CLEAR_DELAY_MS);
}
