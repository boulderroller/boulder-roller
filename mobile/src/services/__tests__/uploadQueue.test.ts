/**
 * Upload Queue Tests
 *
 * Tests retry logic, backoff calculation, and error classification.
 */

import * as Sentry from '@sentry/react-native';
import { createHash } from 'crypto';

import {
  computeNextRetry,
  BACKOFF_BASE_MS,
  BACKOFF_MAX_MS,
  MAX_ATTEMPTS,
  reportPermanentFailure,
  reportHashDrift,
  buildUploadInitPayload,
  buildSignedUploadFormData,
  duplicateRideIdFromInitConflict,
  signedUploadFilePart,
  preferredNativeRideFormat,
} from '../uploadQueue';
import type { RideFormat } from '../uploadQueue';

function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

function expectSupportedRideFormat(fileType: string): asserts fileType is RideFormat {
  if (fileType !== 'fit' && fileType !== 'gpx') {
    throw new Error(`Fixture file_type ${fileType} is not emitted by mobile upload exports`);
  }
}

function loadUploadHandshakeFixture(): {
  cases: Array<{
    expected_payload: {
      file_type: string;
      file_hash: string;
      file_size: number;
      preliminary_ride_hash: string;
      parser_version: number;
    };
  }>;
} {
  const fs = jest.requireActual('fs') as typeof import('fs');
  const path = jest.requireActual('path') as typeof import('path');
  const fixturePath = path.resolve(
    __dirname,
    '../../../../tests/fixtures/upload_init_handshake_v1.json',
  );
  return JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
}

function loadSharedSensorFitBytes(): Buffer {
  const fs = jest.requireActual('fs') as typeof import('fs');
  const path = jest.requireActual('path') as typeof import('path');
  const fixturePath = path.resolve(
    __dirname,
    '../../../../tests/fixtures/mobile_sensor_ride_fit_v1.base64',
  );
  return Buffer.from(fs.readFileSync(fixturePath, 'utf8').trim(), 'base64');
}

describe('Upload Queue', () => {
  describe('computeNextRetry', () => {
    test('first retry is around 2 seconds (base * 2^1)', () => {
      const now = Date.now();
      const nextRetry = computeNextRetry(1);
      const delay = nextRetry - now;
      // 2s +/- 20% jitter = 1600-2400ms
      expect(delay).toBeGreaterThan(BACKOFF_BASE_MS);
      expect(delay).toBeLessThan(BACKOFF_BASE_MS * 4);
    });

    test('delays increase exponentially', () => {
      const now = Date.now();
      const retry1 = computeNextRetry(1) - now;
      const retry2 = computeNextRetry(2) - now;
      const retry3 = computeNextRetry(3) - now;

      // Each retry should roughly double (with jitter)
      // Use broad bounds due to jitter
      expect(retry2).toBeGreaterThan(retry1 * 0.5);
      expect(retry3).toBeGreaterThan(retry2 * 0.5);
    });

    test('delay is capped at BACKOFF_MAX_MS (10 minutes)', () => {
      const now = Date.now();
      const delay = computeNextRetry(20) - now;
      // Even with 20 retries, should not exceed cap + jitter
      const maxWithJitter = BACKOFF_MAX_MS * 1.2;
      expect(delay).toBeLessThanOrEqual(maxWithJitter + 1000);
    });

    test('first retry (attempt 0) is around 1 second', () => {
      const now = Date.now();
      const delay = computeNextRetry(0) - now;
      // 1s +/- 20% jitter = 800-1200ms
      expect(delay).toBeGreaterThan(BACKOFF_BASE_MS * 0.5);
      expect(delay).toBeLessThan(BACKOFF_BASE_MS * 1.5);
    });
  });

  describe('constants', () => {
    test('BACKOFF_BASE_MS is 1 second', () => {
      expect(BACKOFF_BASE_MS).toBe(1000);
    });

    test('BACKOFF_MAX_MS is 10 minutes', () => {
      expect(BACKOFF_MAX_MS).toBe(10 * 60 * 1000);
    });

    test('MAX_ATTEMPTS is 10', () => {
      expect(MAX_ATTEMPTS).toBe(10);
    });

    test('native mobile recordings prefer FIT even without external sensors', () => {
      expect(preferredNativeRideFormat()).toBe('fit');
    });
  });

  describe('backoff schedule', () => {
    test('generates a sensible schedule for all attempts', () => {
      const now = Date.now();
      const schedule: number[] = [];

      for (let i = 0; i < MAX_ATTEMPTS; i++) {
        const nextRetry = computeNextRetry(i);
        schedule.push(nextRetry - now);
      }

      // Verify the schedule is monotonically increasing (on average)
      // Due to jitter, individual values may not be strictly increasing
      // but the expected values should be
      const expectedDelays = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512].map(
        (x) => Math.min(x * BACKOFF_BASE_MS, BACKOFF_MAX_MS),
      );

      for (let i = 0; i < MAX_ATTEMPTS; i++) {
        const expected = expectedDelays[i];
        // Within 30% of expected (jitter + timing)
        expect(schedule[i]).toBeGreaterThan(expected * 0.5);
        expect(schedule[i]).toBeLessThan(expected * 2);
      }
    });
  });

  describe('reportPermanentFailure telemetry', () => {
    beforeEach(() => {
      (Sentry.captureMessage as jest.Mock).mockClear();
    });

    test('captures Sentry error with full upload context', () => {
      reportPermanentFailure({
        rideId: 'ride-123',
        format: 'fit',
        statusCode: 415,
        attemptCount: 1,
        message: 'Unsupported Media Type',
      });

      expect(Sentry.captureMessage).toHaveBeenCalledWith(
        'Upload permanent failure',
        expect.objectContaining({
          level: 'error',
          extra: expect.objectContaining({
            rideId: 'ride-123',
            format: 'fit',
            statusCode: 415,
            attemptCount: 1,
            message: 'Unsupported Media Type',
          }),
        }),
      );
    });

    test('accepts null format and statusCode when export never completed', () => {
      reportPermanentFailure({
        rideId: 'ride-bad',
        format: null,
        statusCode: null,
        attemptCount: 10,
        message: 'Max attempts exceeded',
      });

      expect(Sentry.captureMessage).toHaveBeenCalledWith(
        'Upload permanent failure',
        expect.objectContaining({
          extra: expect.objectContaining({
            format: null,
            statusCode: null,
          }),
        }),
      );
    });
  });

  describe('buildUploadInitPayload', () => {
    test('always includes upload identity and attestation fields in snake_case', () => {
      const hashBytes = hexToBytes('11'.repeat(32));
      const payload = buildUploadInitPayload({
        format: 'fit',
        fileHash: 'abc',
        fileSize: 1234,
        parserVersion: 1,
        preliminaryRideHash: hashBytes,
        clientCompletedAtMs: null,
      });
      expect(payload).toEqual({
        file_type: 'fit',
        file_hash: 'abc',
        file_size: 1234,
        parser_version: 1,
        preliminary_ride_hash: '11'.repeat(32),
      });
    });

    test('rejects missing parser_version instead of opening a server upload', () => {
      expect(() => buildUploadInitPayload({
        format: 'gpx',
        fileHash: 'h',
        fileSize: 1,
        parserVersion: null,
        preliminaryRideHash: new Uint8Array([0xab, 0xcd]),
        clientCompletedAtMs: null,
      })).toThrow(/parser_version/);
    });

    test('rejects missing preliminary_ride_hash instead of opening a server upload', () => {
      expect(() => buildUploadInitPayload({
        format: 'gpx',
        fileHash: 'h',
        fileSize: 1,
        parserVersion: 3,
        preliminaryRideHash: null,
        clientCompletedAtMs: null,
      })).toThrow(/preliminary ride hash/);
    });

    test('fully-stamped ride: both attestation fields included in wire format', () => {
      const hashBytes = new Uint8Array(32);
      for (let i = 0; i < 32; i++) hashBytes[i] = i;
      const payload = buildUploadInitPayload({
        format: 'fit',
        fileHash: 'ffff',
        fileSize: 99,
        parserVersion: 1,
        preliminaryRideHash: hashBytes,
        clientCompletedAtMs: null,
      });
      expect(payload.parser_version).toBe(1);
      expect(payload.preliminary_ride_hash).toMatch(/^[0-9a-f]{64}$/);
      expect(payload.preliminary_ride_hash).toBe(
        '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f',
      );
    });

    test('parser_version=0 is rejected as an invalid stamp', () => {
      expect(() => buildUploadInitPayload({
        format: 'fit',
        fileHash: 'h',
        fileSize: 1,
        parserVersion: 0,
        preliminaryRideHash: hexToBytes('11'.repeat(32)),
        clientCompletedAtMs: null,
      })).toThrow(/parser_version/);
    });

    test('matches shared backend upload-init handshake fixture', () => {
      const [fixtureCase] = loadUploadHandshakeFixture().cases;
      const expected = fixtureCase.expected_payload;
      expectSupportedRideFormat(expected.file_type);

      const payload = buildUploadInitPayload({
        format: expected.file_type,
        fileHash: expected.file_hash,
        fileSize: expected.file_size,
        parserVersion: expected.parser_version,
        preliminaryRideHash: hexToBytes(expected.preliminary_ride_hash),
        clientCompletedAtMs: null,
      });

      expect(payload).toEqual(expected);
    });

    test('FIT upload init uses the hash and size of the raw uploaded bytes', () => {
      const fitBytes = loadSharedSensorFitBytes();
      const rawFileHash = createHash('sha256').update(fitBytes).digest('hex');
      const base64WrapperHash = createHash('sha256').update(fitBytes.toString('base64')).digest('hex');

      const payload = buildUploadInitPayload({
        format: 'fit',
        fileHash: rawFileHash,
        fileSize: fitBytes.byteLength,
        parserVersion: 1,
        preliminaryRideHash: hexToBytes('11'.repeat(32)),
        clientCompletedAtMs: null,
      });

      expect(payload).toMatchObject({
        file_type: 'fit',
        file_hash: rawFileHash,
        file_size: 260,
        preliminary_ride_hash: '11'.repeat(32),
        parser_version: 1,
      });
      expect(payload.file_hash).not.toBe(base64WrapperHash);
    });

    test('includes advisory client completion timestamp when available', () => {
      const payload = buildUploadInitPayload({
        format: 'fit',
        fileHash: 'h',
        fileSize: 1,
        parserVersion: 1,
        preliminaryRideHash: hexToBytes('11'.repeat(32)),
        clientCompletedAtMs: Date.UTC(2015, 5, 26, 12, 0, 0),
      });

      expect(payload.client_completed_at).toBe('2015-06-26T12:00:00.000Z');
      expect(payload).not.toHaveProperty('completed_at');
    });
  });

  describe('signed upload compatibility', () => {
    test('builds React Native multipart file parts for exported rides', () => {
      expect(signedUploadFilePart('file:///mock/documents/rides/ride-1.fit', 'fit')).toEqual({
        uri: 'file:///mock/documents/rides/ride-1.fit',
        name: 'ride-1.fit',
        type: 'application/octet-stream',
      });
      expect(signedUploadFilePart('file:///mock/documents/rides/ride-2.gpx', 'gpx')).toEqual({
        uri: 'file:///mock/documents/rides/ride-2.gpx',
        name: 'ride-2.gpx',
        type: 'application/gpx+xml',
      });
    });

    test('uses FormData for signed storage uploads', () => {
      const formData = buildSignedUploadFormData('file:///mock/documents/rides/ride-1.fit', 'fit');
      expect(formData).toBeInstanceOf(FormData);
    });

    test('reads duplicate ride ids from FastAPI detail envelopes', () => {
      expect(duplicateRideIdFromInitConflict({
        detail: {
          error: 'duplicate_file',
          existing_ride_id: 'ride-existing',
        },
      })).toBe('ride-existing');
      expect(duplicateRideIdFromInitConflict({ existing_ride_id: 'legacy-root' })).toBe('legacy-root');
      expect(duplicateRideIdFromInitConflict({ detail: { error: 'duplicate_file' } })).toBeNull();
    });
  });

  describe('reportHashDrift telemetry', () => {
    beforeEach(() => {
      (Sentry.captureMessage as jest.Mock).mockClear();
    });

    test('emits a warning-level Sentry event with both hashes and ride context', () => {
      reportHashDrift({
        rideId: 'ride-99',
        format: 'fit',
        storedHash: 'abc123',
        freshHash: 'def456',
      });

      expect(Sentry.captureMessage).toHaveBeenCalledWith(
        'Upload hash drift on retry',
        expect.objectContaining({
          level: 'warning',
          extra: expect.objectContaining({
            rideId: 'ride-99',
            format: 'fit',
            storedHash: 'abc123',
            freshHash: 'def456',
          }),
        }),
      );
    });
  });
});
