/**
 * Error Classification Unit Tests
 *
 * Verifies that every error type is correctly classified into
 * TRANSIENT / RECOVERABLE / AUTH / FATAL categories.
 */

import { classifyError, type ClassifiedError, type ErrorClassification } from '../errors';

describe('classifyError - comprehensive', () => {
  function expectClassification(
    error: unknown,
    expected: ErrorClassification,
    expectRetryable: boolean,
  ) {
    const result = classifyError(error);
    expect(result.classification).toBe(expected);
    expect(result.retryable).toBe(expectRetryable);
    expect(result.originalError).toBe(error);
    expect(typeof result.message).toBe('string');
    expect(result.message.length).toBeGreaterThan(0);
  }

  describe('ApiError-shaped objects', () => {
    test('session_expired -> AUTH, not retryable', () => {
      expectClassification(
        { type: 'session_expired', retryable: false, statusCode: 401, message: 'Expired' },
        'AUTH',
        false,
      );
    });

    test('network_error -> TRANSIENT, retryable', () => {
      expectClassification(
        { type: 'network_error', retryable: true, message: 'Network' },
        'TRANSIENT',
        true,
      );
    });

    test('server_error -> TRANSIENT, retryable', () => {
      expectClassification(
        { type: 'server_error', retryable: true, statusCode: 502, message: 'Bad gateway' },
        'TRANSIENT',
        true,
      );
    });

    test('unknown type -> RECOVERABLE, retryable', () => {
      expectClassification(
        { type: 'unknown', retryable: false, statusCode: 422, message: 'Validation' },
        'RECOVERABLE',
        true,
      );
    });
  });

  describe('native Error types', () => {
    test('TypeError -> FATAL', () => {
      expectClassification(new TypeError('oops'), 'FATAL', false);
    });

    test('RangeError -> FATAL', () => {
      expectClassification(new RangeError('out of bounds'), 'FATAL', false);
    });

    test('Error with network message -> TRANSIENT', () => {
      expectClassification(new Error('Failed to fetch'), 'TRANSIENT', true);
    });

    test('Error with timeout message -> TRANSIENT', () => {
      expectClassification(new Error('timeout'), 'TRANSIENT', true);
    });

    test('Error with generic message -> RECOVERABLE', () => {
      expectClassification(new Error('Something else'), 'RECOVERABLE', true);
    });
  });

  describe('non-error values', () => {
    test('null -> FATAL', () => {
      expectClassification(null, 'FATAL', false);
    });

    test('undefined -> FATAL', () => {
      expectClassification(undefined, 'FATAL', false);
    });

    test('string -> FATAL', () => {
      expectClassification('error string', 'FATAL', false);
    });

    test('number -> FATAL', () => {
      expectClassification(42, 'FATAL', false);
    });

    test('empty object -> FATAL', () => {
      expectClassification({}, 'FATAL', false);
    });
  });

  describe('classified error shape', () => {
    test('always returns a ClassifiedError with all fields', () => {
      const result: ClassifiedError = classifyError(new Error('test'));
      expect(result).toHaveProperty('classification');
      expect(result).toHaveProperty('message');
      expect(result).toHaveProperty('retryable');
      expect(result).toHaveProperty('originalError');
    });
  });
});
