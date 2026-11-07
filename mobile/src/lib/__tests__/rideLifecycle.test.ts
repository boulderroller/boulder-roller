import { deriveRideLifecycle, type LocalRideLifecycleInput } from '../rideLifecycle';
import type { RideStatus } from '../api';

function localRide(overrides: Partial<LocalRideLifecycleInput> = {}): LocalRideLifecycleInput {
  return {
    id: 'local-ride-1',
    status: 'stopped',
    sample_count: 120,
    rejected_samples: null,
    had_crash_recovery: 0,
    ...overrides,
  };
}

function serverStatus(overrides: Partial<RideStatus> = {}): RideStatus {
  return {
    contractVersion: 'client.v1',
    truthSource: 'attested',
    rideId: 'server-ride-1',
    status: 'processing',
    processingStage: 'processing',
    errorMessage: null,
    hasGps: false,
    hasPatterns: false,
    hasLeaderboards: false,
    hasAchievements: false,
    inputQuality: {
      status: 'unknown',
      sensorDataState: 'unknown',
      flags: [],
      degradationReasons: [],
    },
    ...overrides,
  };
}

describe('deriveRideLifecycle', () => {
  test('interrupted active rides become recoverable instead of disappearing', () => {
    const view = deriveRideLifecycle({
      localRide: localRide({
        status: 'recording',
        had_crash_recovery: 1,
        rejected_samples: 'GPS:gap',
      }),
      uploadEntry: null,
      serverStatus: null,
    });

    expect(view.phase).toBe('recoverable');
    expect(view.actions).toEqual(['save_interrupted_ride', 'discard_interrupted_ride']);
    expect(view.dataLossRisk).toBe(true);
    expect(view.quality.status).toBe('degraded');
    expect(view.quality.degradationReasons).toEqual([
      'GPS:gap',
      'RECOVERY:interrupted_recording',
    ]);
  });

  test('stopped local rides without a queue entry are ready to upload', () => {
    const view = deriveRideLifecycle({
      localRide: localRide(),
      uploadEntry: null,
      serverStatus: null,
    });

    expect(view.phase).toBe('ready_to_upload');
    expect(view.actions).toEqual(['retry_upload']);
    expect(view.quality.status).toBe('clean');
  });

  test('retryable upload failures preserve the ride and expose retry action', () => {
    const view = deriveRideLifecycle({
      localRide: localRide(),
      uploadEntry: {
        status: 'failed_retryable',
        server_ride_id: null,
        last_error: 'Upload interrupted (app restart)',
        attempt_count: 2,
      },
      serverStatus: null,
    });

    expect(view.phase).toBe('upload_retrying');
    expect(view.actions).toEqual(['retry_upload']);
    expect(view.failure).toEqual({
      phase: 'upload',
      message: 'Upload interrupted (app restart)',
      retryable: true,
    });
    expect(view.dataLossRisk).toBe(false);
  });

  test('auth upload failures route to reauthentication without marking data lost', () => {
    const view = deriveRideLifecycle({
      localRide: localRide(),
      uploadEntry: {
        status: 'failed_auth',
        server_ride_id: null,
        last_error: 'Session expired. Log in to upload.',
      },
      serverStatus: null,
    });

    expect(view.phase).toBe('auth_required');
    expect(view.actions).toEqual(['reauthenticate']);
    expect(view.dataLossRisk).toBe(false);
  });

  test('uploaded local queue defers to later server processing states', () => {
    const view = deriveRideLifecycle({
      localRide: localRide({ status: 'uploaded' }),
      uploadEntry: {
        status: 'uploaded',
        server_ride_id: 'server-ride-1',
      },
      serverStatus: serverStatus({
        processingStage: 'enriched',
        status: 'enriched',
        hasGps: true,
        hasPatterns: true,
      }),
    });

    expect(view.phase).toBe('scored');
    expect(view.serverRideId).toBe('server-ride-1');
    expect(view.actions).toEqual(['open_ride']);
  });

  test('server retryable failures carry readable processing failure', () => {
    const view = deriveRideLifecycle({
      localRide: localRide({ status: 'uploaded' }),
      uploadEntry: {
        status: 'uploaded',
        server_ride_id: 'server-ride-1',
      },
      serverStatus: serverStatus({
        status: 'failed',
        processingStage: 'failed',
        canRetryProcessing: true,
        errorMessage: 'Processing timed out. Please try re-uploading the file.',
        failure: {
          phase: 'processing',
          message: 'Processing timed out. Please try re-uploading the file.',
          retryable: true,
        },
      }),
    });

    expect(view.phase).toBe('failed');
    expect(view.actions).toEqual(['retry_processing']);
    expect(view.failure).toEqual({
      phase: 'processing',
      message: 'Processing timed out. Please try re-uploading the file.',
      retryable: true,
    });
  });

  test('zero-sample stopped rides are invalid even before backend processing', () => {
    const view = deriveRideLifecycle({
      localRide: localRide({ sample_count: 0 }),
      uploadEntry: null,
      serverStatus: null,
    });

    expect(view.quality.status).toBe('invalid');
    expect(view.quality.sampleCount).toBe(0);
  });

  test('backend input quality wins when available and keeps sensor absence explicit', () => {
    const view = deriveRideLifecycle({
      localRide: localRide(),
      uploadEntry: {
        status: 'uploaded',
        server_ride_id: 'server-ride-1',
      },
      serverStatus: serverStatus({
        processingStage: 'completed',
        status: 'completed',
        inputQuality: {
          status: 'degraded',
          sensorDataState: 'absent',
          sampleCount: 6,
          flags: ['SAMPLING:too_few_samples_6'],
          degradationReasons: ['SAMPLING:too_few_samples_6'],
        },
      }),
    });

    expect(view.phase).toBe('complete');
    expect(view.quality.status).toBe('degraded');
    expect(view.quality.sensorDataState).toBe('absent');
    expect(view.quality.degradationReasons).toEqual(['SAMPLING:too_few_samples_6']);
  });
});
