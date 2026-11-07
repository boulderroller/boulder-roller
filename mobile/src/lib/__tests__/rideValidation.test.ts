import {
  buildRideValidationSummary,
  rideHashBytesToHex,
} from '../rideValidation';
import type {
  RideRow,
  RideValidationEventRow,
  UploadQueueRow,
} from '../../services/database';

function ride(overrides: Partial<RideRow> = {}): RideRow {
  return {
    id: 'ride-1',
    status: 'uploaded',
    started_at: 1_000,
    ended_at: 10_000,
    duration_ms: 9_000,
    moving_time_ms: 8_000,
    distance_m: 1_200,
    elevation_gain_m: 90,
    max_speed_mps: 8,
    sport_type: 'ride',
    clock_drift_ms: null,
    sample_count: 12,
    rejected_samples: null,
    upload_id: 'server-1',
    notes: null,
    preliminary_ride_hash: new Uint8Array(32).fill(7),
    parser_version: 1,
    had_crash_recovery: 0,
    ...overrides,
  };
}

function upload(overrides: Partial<UploadQueueRow> = {}): UploadQueueRow {
  return {
    id: 'ride-1',
    ride_id: 'ride-1',
    status: 'uploaded',
    file_hash: 'file-hash',
    attempt_count: 0,
    max_attempts: 10,
    next_retry_at: null,
    last_error: null,
    server_ride_id: 'server-1',
    created_at: 10_100,
    updated_at: 10_750,
    ...overrides,
  };
}

function event(
  eventType: string,
  occurredAt: number,
  metadata: Record<string, unknown> = {},
): RideValidationEventRow {
  return {
    id: occurredAt,
    ride_id: 'ride-1',
    event_type: eventType,
    occurred_at: occurredAt,
    metadata: JSON.stringify(metadata),
  };
}

describe('buildRideValidationSummary', () => {
  test('summarizes decisive stop-to-upload timing and handshake provenance', () => {
    const summary = buildRideValidationSummary({
      ride: ride(),
      uploadEntry: upload(),
      events: [
        event('recording_stopped', 10_000),
        event('upload_enqueued', 10_080),
        event('upload_init_payload', 10_200, {
          parserVersionPresent: true,
          preliminaryRideHashPresent: true,
        }),
        event('upload_accepted', 10_750),
      ],
    });

    expect(summary).toEqual(expect.objectContaining({
      parserVersionPresent: true,
      preliminaryHashPresent: true,
      uploadStatus: 'uploaded',
      serverRideId: 'server-1',
      uploadInitObserved: true,
      uploadInitHadParserVersion: true,
      uploadInitHadPreliminaryHash: true,
      stopToQueuedMs: 80,
      stopToUploadedMs: 750,
      uploadedWithinOneSecond: true,
    }));
    expect(summary.preliminaryHashHex).toMatch(/^(07){32}$/);
  });

  test('keeps missing hash/parser and slow upload visible for M1/M2 validation', () => {
    const summary = buildRideValidationSummary({
      ride: ride({
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 1,
        rejected_samples: JSON.stringify({ low_accuracy: 3, impossible_speed: 1 }),
      }),
      uploadEntry: upload({ status: 'failed_retryable', server_ride_id: null }),
      events: [
        event('recording_stopped', 10_000),
        event('upload_enqueued', 10_300),
        event('upload_accepted', 11_800),
      ],
    });

    expect(summary.parserVersionPresent).toBe(false);
    expect(summary.preliminaryHashPresent).toBe(false);
    expect(summary.hadCrashRecovery).toBe(true);
    expect(summary.rejectedSamples).toEqual({ low_accuracy: 3, impossible_speed: 1 });
    expect(summary.stopToUploadedMs).toBe(1800);
    expect(summary.uploadedWithinOneSecond).toBe(false);
    expect(summary.uploadInitObserved).toBe(false);
  });
});

describe('rideHashBytesToHex', () => {
  test('normalizes blob-like hash values from SQLite and tests', () => {
    expect(rideHashBytesToHex(new Uint8Array([0, 15, 255]))).toBe('000fff');
    expect(rideHashBytesToHex(new ArrayBuffer(0))).toBe('');
    expect(rideHashBytesToHex('abc123')).toBe('abc123');
    expect(rideHashBytesToHex(null)).toBeNull();
  });
});
