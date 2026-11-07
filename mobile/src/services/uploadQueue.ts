/**
 * Upload Queue Processor
 *
 * SQLite-backed FIFO queue with exponential backoff.
 * Idempotency key = file_hash (SHA-256 of uploaded bytes).
 * Backoff: 1s base, 2x growth, 10 min cap, 10 max attempts.
 * `failed_auth` status triggers re-auth flow (never deletes ride data).
 *
 * Per MOBILE_PHASE0_RESOLUTIONS.md:
 *   - FIX-3: GPX upload via existing presigned flow
 *   - FIX-4: failed_auth status for expired sessions
 *   - FIX-5b: file_hash dedup is sufficient (no X-Idempotency-Key)
 */

import NetInfo from '@react-native-community/netinfo';
import * as Sentry from '@sentry/react-native';
import { API_URL } from '../constants/config';
import {
  getCurrentLocalRideOwnerKey,
  useAuthStore,
} from '../stores/authStore';
import { tokenRefreshManager } from './tokenRefreshManager';
import { queryClient } from '../lib/queryClient';
import {
  getDatabase,
  getNextUploadEntry,
  updateUploadEntry,
  createUploadEntry,
  getRide,
  getUploadEntryForRide,
  updateRide,
  getUploadEntriesByStatus,
} from './database';
import { recordRideValidationEvent } from '../lib/rideValidation';
import { exportRideToGPX, deleteGPXFile } from './gpxExporter';
import {
  isPreEconomyTimestampMs,
  rideCompletedAtMs,
} from '../lib/economyWindow';
import {
  exportRideToFIT,
  deleteFITFile,
} from './fitExporter';
import { bytesToHex } from '../lib/preliminaryHash';

// ---------------------------------------------------------------------------
// Export format dispatcher — native recordings prefer FIT even when the ride
// has no power/HR/cadence. FIT preserves timestamps and richer per-sample
// fields; GPX remains a compatibility fallback if FIT export itself fails.
// ---------------------------------------------------------------------------

export type RideFormat = 'fit' | 'gpx';

interface ExportedRide {
  filePath: string;
  fileHash: string;
  fileSize: number;
  format: RideFormat;
}

export function preferredNativeRideFormat(): RideFormat {
  return 'fit';
}

async function exportRide(rideId: string): Promise<ExportedRide> {
  try {
    const r = await exportRideToFIT(rideId);
    return { ...r, format: 'fit' };
  } catch (err) {
    Sentry.captureMessage('FIT export fallback to GPX', {
      level: 'warning',
      extra: {
        rideId,
        message: err instanceof Error ? err.message : String(err),
      },
    });
  }
  const r = await exportRideToGPX(rideId);
  return { ...r, format: 'gpx' };
}

function contentTypeFor(format: RideFormat): string {
  return format === 'fit' ? 'application/octet-stream' : 'application/gpx+xml';
}

export function signedUploadFilePart(
  filePath: string,
  format: RideFormat,
): { uri: string; name: string; type: string } {
  const fallbackName = `ride.${format}`;
  const fileName = filePath.split('/').pop() || fallbackName;
  return {
    uri: filePath,
    name: fileName.includes('.') ? fileName : fallbackName,
    type: contentTypeFor(format),
  };
}

export function buildSignedUploadFormData(filePath: string, format: RideFormat): FormData {
  const formData = new FormData();
  formData.append('file', {
    ...signedUploadFilePart(filePath, format),
  } as unknown as Blob);
  return formData;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

export function duplicateRideIdFromInitConflict(body: unknown): string | null {
  const root = objectValue(body);
  const detail = objectValue(root.detail);
  for (const value of [
    detail.existing_ride_id,
    detail.existingRideId,
    detail.ride_id,
    detail.rideId,
    root.existing_ride_id,
    root.existingRideId,
    root.ride_id,
    root.rideId,
  ]) {
    if (typeof value === 'string' && value.trim()) {
      return value;
    }
  }
  return null;
}

async function deleteExportedFile(filePath: string, format: RideFormat): Promise<void> {
  return format === 'fit' ? deleteFITFile(filePath) : deleteGPXFile(filePath);
}

async function abortServerUpload(uploadId: string, accessToken: string | null | undefined): Promise<void> {
  if (!accessToken) return;
  try {
    await fetch(`${API_URL}/rides/upload/abort`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ upload_id: uploadId }),
    });
  } catch {
    // Best-effort cleanup only; upload error handling records the user-visible state.
  }
}

function completeServerUpload(uploadId: string, accessToken: string): Promise<Response> {
  return fetch(`${API_URL}/rides/upload/complete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      upload_id: uploadId,
    }),
  });
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 10 * 60 * 1000; // 10 minutes
const MAX_ATTEMPTS = 10;
const PROCESS_INTERVAL_MS = 30_000; // 30 seconds between queue checks

// ---------------------------------------------------------------------------
// Backoff calculation
// ---------------------------------------------------------------------------

function computeNextRetry(attemptCount: number): number {
  const delay = Math.min(
    BACKOFF_BASE_MS * Math.pow(2, attemptCount),
    BACKOFF_MAX_MS,
  );
  // Add jitter: +/- 20%
  const jitter = delay * 0.2 * (Math.random() * 2 - 1);
  return Date.now() + delay + jitter;
}

// ---------------------------------------------------------------------------
// Upload a single ride
// ---------------------------------------------------------------------------

interface UploadInitResponse {
  uploadId: string;
  signedUrl: string;
  expiresIn: number;
}

/**
 * Build the /rides/upload/init request body. Snake_case keys match the
 * backend contract. parser_version and preliminary_ride_hash are mandatory
 * for native uploads; a missing stop-time stamp would bypass the backend's
 * canonical hash compare, so fail locally before opening a server upload.
 */
export function buildUploadInitPayload(args: {
  format: RideFormat;
  fileHash: string;
  fileSize: number;
  parserVersion: number | null;
  preliminaryRideHash: Uint8Array | null;
  clientCompletedAtMs: number | null;
}): Record<string, unknown> {
  if (args.parserVersion == null || args.parserVersion < 1) {
    throw new UploadError('Ride upload requires a valid parser_version stamp.', 400);
  }
  if (args.preliminaryRideHash == null) {
    throw new UploadError('Ride upload requires a preliminary ride hash stamp.', 400);
  }
  const payload: Record<string, unknown> = {
    file_type: args.format,
    file_hash: args.fileHash,
    file_size: args.fileSize,
    parser_version: args.parserVersion,
    preliminary_ride_hash: bytesToHex(args.preliminaryRideHash),
  };
  if (args.clientCompletedAtMs != null && Number.isFinite(args.clientCompletedAtMs)) {
    payload.client_completed_at = new Date(args.clientCompletedAtMs).toISOString();
  }
  return payload;
}

async function uploadRide(rideId: string): Promise<void> {
  const uploadOwnerKey = getCurrentLocalRideOwnerKey();
  if (!uploadOwnerKey) return;
  const db = getDatabase();
  const entry = getUploadEntryForRide(db, rideId);
  if (!entry) return;

  // Mark as uploading
  updateUploadEntry(db, entry.id, { status: 'uploading' });
  recordRideValidationEvent(db, rideId, 'upload_started', {
    attemptCount: entry.attempt_count,
  });

  // Declared before try so the catch handler has the format for Sentry
  // context even when a later step (like /init 500) fails.
  let formatForError: RideFormat | null = null;

  try {
    // Export ride — native recordings prefer FIT; GPX is fallback only.
    const { filePath, fileHash, fileSize, format } = await exportRide(rideId);
    formatForError = format;

    // Hash drift guard. Our exporters are deterministic, so a mismatch
    // between the fresh export and a previously stored hash signals a
    // real regression. Log it loudly AND breadcrumb to Sentry so we hear
    // about it instead of letting it silently orphan a partial upload.
    if (entry.file_hash && entry.file_hash !== fileHash) {
      console.warn(
        `[UploadQueue] Hash drift on retry for ride ${rideId}: ` +
        `stored=${entry.file_hash} fresh=${fileHash}. Using fresh hash.`,
      );
      reportHashDrift({
        rideId,
        format,
        storedHash: entry.file_hash,
        freshHash: fileHash,
      });
    }

    // Store file hash
    updateUploadEntry(db, entry.id, { file_hash: fileHash });

    // Read parser_version + preliminary_ride_hash from the ride row (stamped at stop)
    const ride = getRide(db, rideId);
    const clientCompletedAtMs = ride ? rideCompletedAtMs(ride) : null;

    // Get auth token
    if (getCurrentLocalRideOwnerKey() !== uploadOwnerKey) return;
    const accessToken = useAuthStore.getState().accessToken;
    if (!accessToken) {
      updateUploadEntry(db, entry.id, {
        status: 'failed_auth',
        last_error: 'Session expired. Log in to upload.',
      });
      recordRideValidationEvent(db, rideId, 'upload_failed', {
        status: 'failed_auth',
        phase: 'init_auth',
        message: 'Session expired. Log in to upload.',
      });
      return;
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${accessToken}`,
    };

    // Step 1: POST /rides/upload/init
    // Send parser_version + preliminary_ride_hash as required native fields.
    // Backend re-canonicalizes the uploaded file and compares before economics.
    const initPayload = buildUploadInitPayload({
      format,
      fileHash,
      fileSize,
      parserVersion: ride?.parser_version ?? null,
      preliminaryRideHash: ride?.preliminary_ride_hash ?? null,
      clientCompletedAtMs,
    });
    recordRideValidationEvent(db, rideId, 'upload_init_payload', {
      format,
      fileHash,
      fileSize,
      clientCompletedAt: typeof initPayload.client_completed_at === 'string'
        ? initPayload.client_completed_at
        : null,
      activityBeforeEconomyStart: clientCompletedAtMs == null
        ? null
        : isPreEconomyTimestampMs(clientCompletedAtMs),
      parserVersion: ride?.parser_version ?? null,
      parserVersionPresent: Object.prototype.hasOwnProperty.call(initPayload, 'parser_version'),
      preliminaryRideHashPresent: Object.prototype.hasOwnProperty.call(initPayload, 'preliminary_ride_hash'),
      preliminaryRideHashHex: typeof initPayload.preliminary_ride_hash === 'string'
        ? initPayload.preliminary_ride_hash
        : null,
    });

    const initResponse = await fetch(`${API_URL}/rides/upload/init`, {
      method: 'POST',
      headers,
      body: JSON.stringify(initPayload),
    });

    // Handle 401: attempt refresh
    if (initResponse.status === 401) {
      const refreshed = await tokenRefreshManager.refresh();
      if (refreshed) {
        if (getCurrentLocalRideOwnerKey() !== uploadOwnerKey) return;
        // Retry — don't count as attempt
        updateUploadEntry(db, entry.id, { status: 'pending' });
        return;
      }
      updateUploadEntry(db, entry.id, {
        status: 'failed_auth',
        last_error: 'Session expired. Log in to upload.',
      });
      recordRideValidationEvent(db, rideId, 'upload_failed', {
        status: 'failed_auth',
        phase: 'init_401',
        statusCode: initResponse.status,
        message: 'Session expired. Log in to upload.',
      });
      return;
    }

    // Handle 409: already uploaded (dedup by file_hash)
    if (initResponse.status === 409) {
      const body = await initResponse.json();
      const existingRideId = duplicateRideIdFromInitConflict(body);
      if (!existingRideId) {
        throw new UploadError('Duplicate upload response missing existing ride id', initResponse.status);
      }
      // Atomic: upload_queue and rides must agree on 'uploaded' state.
      // App kill between the two writes was leaving rides stuck in limbo.
      db.withTransactionSync(() => {
        updateUploadEntry(db, entry.id, {
          status: 'uploaded',
          server_ride_id: existingRideId,
        });
        updateRide(db, rideId, { status: 'uploaded' });
      });
      recordRideValidationEvent(db, rideId, 'upload_accepted', {
        source: 'dedupe',
        statusCode: initResponse.status,
        serverRideId: existingRideId,
      });
      await deleteExportedFile(filePath, format);
      invalidateCaches();
      return;
    }

    if (!initResponse.ok) {
      const text = await initResponse.text().catch(() => '');
      throw new UploadError(text, initResponse.status);
    }

    const initData: UploadInitResponse = await initResponse.json();

    // Step 2: PUT exported ride file to signed URL. Supabase signed upload
    // URLs expect multipart "file" uploads; raw bytes may 200 without object.
    const formData = buildSignedUploadFormData(filePath, format);
    const putResponse = await fetch(initData.signedUrl, {
      method: 'PUT',
      headers: { 'x-upsert': 'false' },
      body: formData as BodyInit,
    });

    if (!putResponse.ok) {
      await abortServerUpload(initData.uploadId, useAuthStore.getState().accessToken ?? accessToken);
      throw new UploadError(`PUT failed: ${putResponse.status}`, putResponse.status);
    }

    // Step 3: POST /rides/upload/complete
    // Re-read the auth token — Steps 1 and 2 may have taken long enough
    // that the original token expired (large FIT uploads on slow networks).
    // A stale token at this step orphans the upload server-side.
    if (getCurrentLocalRideOwnerKey() !== uploadOwnerKey) {
      await abortServerUpload(initData.uploadId, accessToken);
      return;
    }
    let freshAccessToken = useAuthStore.getState().accessToken;
    if (!freshAccessToken) {
      const refreshed = await tokenRefreshManager.refresh();
      if (getCurrentLocalRideOwnerKey() !== uploadOwnerKey) {
        await abortServerUpload(initData.uploadId, accessToken);
        return;
      }
      freshAccessToken = refreshed ? useAuthStore.getState().accessToken : null;
      if (!freshAccessToken) {
        await abortServerUpload(initData.uploadId, accessToken);
        updateUploadEntry(db, entry.id, {
          status: 'failed_auth',
          last_error: 'Session expired mid-upload. Log in to complete.',
        });
        recordRideValidationEvent(db, rideId, 'upload_failed', {
          status: 'failed_auth',
          phase: 'complete_auth',
          message: 'Session expired mid-upload. Log in to complete.',
        });
        return;
      }
    }
    let completeResponse = await completeServerUpload(initData.uploadId, freshAccessToken);

    if (completeResponse.status === 401) {
      const refreshed = await tokenRefreshManager.refresh();
      if (getCurrentLocalRideOwnerKey() !== uploadOwnerKey) {
        await abortServerUpload(initData.uploadId, freshAccessToken);
        return;
      }
      const refreshedToken = refreshed ? useAuthStore.getState().accessToken : null;
      if (refreshedToken) {
        completeResponse = await completeServerUpload(initData.uploadId, refreshedToken);
      }
      if (completeResponse.status === 401) {
        await abortServerUpload(initData.uploadId, refreshedToken ?? freshAccessToken);
        updateUploadEntry(db, entry.id, {
          status: 'failed_auth',
          last_error: 'Session expired. Log in to upload.',
        });
        recordRideValidationEvent(db, rideId, 'upload_failed', {
          status: 'failed_auth',
          phase: 'complete_401',
          statusCode: completeResponse.status,
          message: 'Session expired. Log in to upload.',
        });
        return;
      }
    }

    if (!completeResponse.ok) {
      const text = await completeResponse.text().catch(() => '');
      await abortServerUpload(initData.uploadId, useAuthStore.getState().accessToken ?? freshAccessToken);
      throw new UploadError(text, completeResponse.status);
    }

    const completeData = await completeResponse.json();

    // Success — backend returns camelCase (rideId) via Pydantic by_alias=True.
    // Atomic: upload_queue and rides must agree on 'uploaded' state.
    db.withTransactionSync(() => {
      updateUploadEntry(db, entry.id, {
        status: 'uploaded',
        server_ride_id: completeData.rideId ?? null,
      });
      updateRide(db, rideId, {
        status: 'uploaded',
        upload_id: completeData.rideId ?? null,
      });
    });
    recordRideValidationEvent(db, rideId, 'upload_accepted', {
      source: 'complete',
      statusCode: completeResponse.status,
      serverRideId: completeData.rideId ?? null,
    });

    await deleteExportedFile(filePath, format);
    invalidateCaches();
  } catch (err) {
    handleUploadError(entry.id, rideId, formatForError, entry.attempt_count, err);
  }
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

class UploadError extends Error {
  statusCode: number;
  constructor(message: string, statusCode: number) {
    super(message);
    this.name = 'UploadError';
    this.statusCode = statusCode;
  }
}

/**
 * Emit a Sentry event when a ride upload lands in failed_permanent.
 * Exported for tests so they can assert on the telemetry contract
 * without driving the whole upload pipeline.
 */
export function reportPermanentFailure(ctx: {
  rideId: string;
  format: RideFormat | null;
  statusCode: number | null;
  attemptCount: number;
  message: string;
}): void {
  Sentry.captureMessage('Upload permanent failure', {
    level: 'error',
    extra: ctx,
  });
}

/**
 * Emit a Sentry event when a re-export of the same ride produces a
 * different hash than what was stored on the first attempt. Our exporters
 * are deterministic, so this signals a regression we want to hear about
 * before riders lose data to orphaned uploads.
 */
export function reportHashDrift(ctx: {
  rideId: string;
  format: RideFormat;
  storedHash: string;
  freshHash: string;
}): void {
  Sentry.captureMessage('Upload hash drift on retry', {
    level: 'warning',
    extra: ctx,
  });
}

function handleUploadError(
  entryId: string,
  rideId: string,
  format: RideFormat | null,
  currentAttempts: number,
  err: unknown,
): void {
  const db = getDatabase();
  const newAttemptCount = currentAttempts + 1;

  // Client errors (4xx non-401, non-409) are generally permanent.
  // Exception: 403 on the PUT step means the Supabase signed URL expired
  // (large GPX export took longer than the URL TTL). Re-running from step 1
  // will get a fresh signed URL, so this is retryable — not data loss.
  if (err instanceof UploadError && err.statusCode >= 400 && err.statusCode < 500) {
    if (err.statusCode === 403 && err.message.startsWith('PUT failed:')) {
      // Fall through to retryable handling below
    } else {
      updateUploadEntry(db, entryId, {
        status: 'failed_permanent',
        attempt_count: newAttemptCount,
        last_error: err.message,
      });
      recordRideValidationEvent(db, rideId, 'upload_failed', {
        status: 'failed_permanent',
        statusCode: err.statusCode,
        attemptCount: newAttemptCount,
        message: err.message,
      });
      reportPermanentFailure({
        rideId,
        format,
        statusCode: err.statusCode,
        attemptCount: newAttemptCount,
        message: err.message,
      });
      return;
    }
  }

  // Max attempts reached
  if (newAttemptCount >= MAX_ATTEMPTS) {
    const message = err instanceof Error ? err.message : 'Max attempts exceeded';
    updateUploadEntry(db, entryId, {
      status: 'failed_permanent',
      attempt_count: newAttemptCount,
      last_error: message,
    });
    recordRideValidationEvent(db, rideId, 'upload_failed', {
      status: 'failed_permanent',
      statusCode: err instanceof UploadError ? err.statusCode : null,
      attemptCount: newAttemptCount,
      message,
    });
    reportPermanentFailure({
      rideId,
      format,
      statusCode: err instanceof UploadError ? err.statusCode : null,
      attemptCount: newAttemptCount,
      message,
    });
    return;
  }

  // Retryable
  updateUploadEntry(db, entryId, {
    status: 'failed_retryable',
    attempt_count: newAttemptCount,
    next_retry_at: computeNextRetry(newAttemptCount),
    last_error: err instanceof Error ? err.message : 'Unknown error',
  });
  recordRideValidationEvent(db, rideId, 'upload_failed', {
    status: 'failed_retryable',
    statusCode: err instanceof UploadError ? err.statusCode : null,
    attemptCount: newAttemptCount,
    message: err instanceof Error ? err.message : 'Unknown error',
  });
}

// ---------------------------------------------------------------------------
// Cache invalidation
// ---------------------------------------------------------------------------

function invalidateCaches(): void {
  queryClient.invalidateQueries({ queryKey: ['rides'] });
}

// ---------------------------------------------------------------------------
// Queue processor
// ---------------------------------------------------------------------------

let processingTimer: ReturnType<typeof setInterval> | null = null;
let isProcessing = false;

/**
 * Process the next item in the upload queue.
 * Non-re-entrant: only one upload at a time.
 */
export async function processQueue(): Promise<void> {
  if (isProcessing) return;

  // Skip processing when offline — avoids unnecessary errors and battery drain
  const netState = await NetInfo.fetch();
  if (!netState.isConnected) return;

  isProcessing = true;

  try {
    const db = getDatabase();

    // Reset any entries stuck in 'uploading' state (crash recovery)
    const stuckEntries = getUploadEntriesByStatus(db, 'uploading');
    for (const entry of stuckEntries) {
      updateUploadEntry(db, entry.id, {
        status: 'failed_retryable',
        attempt_count: entry.attempt_count + 1,
        next_retry_at: computeNextRetry(entry.attempt_count + 1),
        last_error: 'Upload interrupted (app restart)',
      });
      recordRideValidationEvent(db, entry.ride_id, 'upload_interrupted', {
        attemptCount: entry.attempt_count + 1,
      });
    }

    // Process next ready entry
    const next = getNextUploadEntry(db);
    if (next) {
      await uploadRide(next.ride_id);
    }
  } finally {
    isProcessing = false;
  }
}

/**
 * Start the periodic queue processor.
 * Call on app launch and after ride completion.
 */
export function startQueueProcessor(): void {
  stopQueueProcessor();
  // Process immediately
  processQueue();
  // Then check periodically
  processingTimer = setInterval(() => processQueue(), PROCESS_INTERVAL_MS);
}

/**
 * Stop the periodic queue processor.
 */
export function stopQueueProcessor(): void {
  if (processingTimer) {
    clearInterval(processingTimer);
    processingTimer = null;
  }
}

/**
 * Queue a ride for upload. Call after ride stop.
 */
export function enqueueRide(rideId: string): void {
  const db = getDatabase();
  createUploadEntry(db, rideId);
  recordRideValidationEvent(db, rideId, 'upload_enqueued');
  // Trigger immediate processing
  processQueue();
}

/**
 * Reset failed_auth entries to pending. Call after successful re-login.
 */
export function retryAuthFailedUploads(): void {
  const db = getDatabase();
  const failedAuth = getUploadEntriesByStatus(db, 'failed_auth');
  for (const entry of failedAuth) {
    updateUploadEntry(db, entry.id, {
      status: 'pending',
    });
  }
  if (failedAuth.length > 0) {
    processQueue();
  }
}

/**
 * Manually retry a permanently failed upload.
 */
export function retryFailedUpload(rideId: string): void {
  const db = getDatabase();
  const entry = getUploadEntryForRide(db, rideId);
  if (entry) {
    updateUploadEntry(db, entry.id, {
      status: 'pending',
      attempt_count: 0,
      next_retry_at: null,
      last_error: null,
    });
    processQueue();
  }
}

// Re-export for convenience
export { BACKOFF_BASE_MS, BACKOFF_MAX_MS, MAX_ATTEMPTS, computeNextRetry };
