/**
 * Post-ride progress derivation.
 *
 * Local upload acceptance and server processing are separate clocks:
 * the rider should see "uploaded" as soon as the local upload queue says
 * the backend accepted the file, even if server processing is still catching up.
 */

export const POST_RIDE_UPLOAD_POLL_MS = 500;
export const POST_RIDE_SERVER_STATUS_POLL_MS = 3000;

export type PostRideUploadState = 'uploading' | 'uploaded' | 'failed';

export interface LocalUploadQueueEntry {
  status: string;
  server_ride_id: string | null;
}

export interface PostRideUploadProgress {
  state: PostRideUploadState;
  serverRideId: string | null;
}

export function derivePostRideUploadProgress(
  entry: LocalUploadQueueEntry | null,
): PostRideUploadProgress {
  if (!entry) {
    return { state: 'uploading', serverRideId: null };
  }

  if (entry.status === 'uploaded') {
    return {
      state: 'uploaded',
      serverRideId: entry.server_ride_id,
    };
  }

  if (
    entry.status === 'failed_retryable' ||
    entry.status === 'failed_permanent' ||
    entry.status === 'failed_auth'
  ) {
    return {
      state: 'failed',
      serverRideId: entry.server_ride_id,
    };
  }

  return {
    state: 'uploading',
    serverRideId: entry.server_ride_id,
  };
}
