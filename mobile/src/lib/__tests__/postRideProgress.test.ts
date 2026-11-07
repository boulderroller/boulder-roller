import {
  POST_RIDE_UPLOAD_POLL_MS,
  derivePostRideUploadProgress,
} from '../postRideProgress';

describe('derivePostRideUploadProgress', () => {
  test('missing queue entry means upload is still pending locally', () => {
    expect(derivePostRideUploadProgress(null)).toEqual({
      state: 'uploading',
      serverRideId: null,
    });
  });

  test('uploaded queue state is decisive even before server status polling has an id', () => {
    expect(
      derivePostRideUploadProgress({
        status: 'uploaded',
        server_ride_id: null,
      }),
    ).toEqual({
      state: 'uploaded',
      serverRideId: null,
    });
  });

  test('preserves server ride id when upload has one', () => {
    expect(
      derivePostRideUploadProgress({
        status: 'uploaded',
        server_ride_id: 'srv-ride-1',
      }),
    ).toEqual({
      state: 'uploaded',
      serverRideId: 'srv-ride-1',
    });
  });

  test('retryable, auth, and permanent failures are rider-visible failures', () => {
    expect(
      derivePostRideUploadProgress({
        status: 'failed_retryable',
        server_ride_id: null,
      }).state,
    ).toBe('failed');
    expect(
      derivePostRideUploadProgress({
        status: 'failed_auth',
        server_ride_id: null,
      }).state,
    ).toBe('failed');
    expect(
      derivePostRideUploadProgress({
        status: 'failed_permanent',
        server_ride_id: null,
      }).state,
    ).toBe('failed');
  });

  test('local upload polling is fast enough for the one-second stop gate', () => {
    expect(POST_RIDE_UPLOAD_POLL_MS).toBeLessThanOrEqual(1000);
  });
});
