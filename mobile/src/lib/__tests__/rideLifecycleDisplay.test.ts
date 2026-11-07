import { deriveRideLifecycle } from '../rideLifecycle';
import { buildRideLifecycleDisplayModel } from '../rideLifecycleDisplay';
import type { RideStatus } from '../api';

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

describe('buildRideLifecycleDisplayModel', () => {
  test('turns retryable upload failures into a rider repair action', () => {
    const view = deriveRideLifecycle({
      localRide: {
        id: 'ride-1',
        status: 'stopped',
        sample_count: 42,
        rejected_samples: null,
        had_crash_recovery: 0,
      },
      uploadEntry: {
        status: 'failed_retryable',
        server_ride_id: null,
        last_error: 'Network dropped during upload',
        attempt_count: 2,
      },
      serverStatus: null,
    });

    const display = buildRideLifecycleDisplayModel(view);

    expect(display.title).toBe('Upload paused');
    expect(display.stateLabel).toBe('Retry upload');
    expect(display.failureMessage).toBe('Network dropped during upload');
    expect(display.primaryAction).toBe('retry_upload');
    expect(display.primaryActionLabel).toBe('Retry upload');
  });

  test('surfaces auth-required uploads without saying data is gone', () => {
    const view = deriveRideLifecycle({
      localRide: {
        id: 'ride-1',
        status: 'stopped',
        sample_count: 42,
        rejected_samples: null,
        had_crash_recovery: 0,
      },
      uploadEntry: {
        status: 'failed_auth',
        server_ride_id: null,
        last_error: 'Session expired',
      },
      serverStatus: null,
    });

    const display = buildRideLifecycleDisplayModel(view);

    expect(display.title).toBe('Sign in needed');
    expect(display.subtitle).toContain('safe on this device');
    expect(display.primaryAction).toBe('reauthenticate');
  });

  test('maps retryable ride check failures to retry processing', () => {
    const view = deriveRideLifecycle({
      localRide: null,
      uploadEntry: null,
      serverStatus: serverStatus({
        status: 'failed',
        processingStage: 'failed',
        canRetryProcessing: true,
        failure: {
          phase: 'processing',
          message: 'Processing queue timed out',
          retryable: true,
        },
      }),
    });

    const display = buildRideLifecycleDisplayModel(view);

    expect(display.title).toBe('Ride check failed');
    expect(display.failureMessage).toBe('Processing queue timed out');
    expect(display.primaryAction).toBe('retry_processing');
  });

  test('keeps review and complete states distinct', () => {
    const review = buildRideLifecycleDisplayModel(deriveRideLifecycle({
      localRide: null,
      uploadEntry: null,
      serverStatus: serverStatus({ status: 'under_review', processingStage: 'under_review' }),
    }));
    const complete = buildRideLifecycleDisplayModel(deriveRideLifecycle({
      localRide: null,
      uploadEntry: null,
      serverStatus: serverStatus({ status: 'completed', processingStage: 'completed' }),
    }));

    expect(review.stateLabel).toBe('Review');
    expect(review.tone).toBe('warning');
    expect(complete.stateLabel).toBe('Complete');
    expect(complete.tone).toBe('success');
  });
});
