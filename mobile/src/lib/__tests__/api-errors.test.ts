/**
 * API Error Classification Tests
 *
 * Tests the error classification system: every error must be classified
 * as TRANSIENT, RECOVERABLE, AUTH, or FATAL. This classification drives
 * what the user sees and what the system does.
 */

import { ApiError } from '../api';
import { classifyError, getUserMessage, isRetryable } from '../errors';

describe('ApiError', () => {
  test('network_error is retryable', () => {
    const err = new ApiError('Network error', 'network_error');
    expect(err.retryable).toBe(true);
    expect(err.type).toBe('network_error');
    expect(err.statusCode).toBeUndefined();
  });

  test('session_expired is not retryable', () => {
    const err = new ApiError('Session expired', 'session_expired', 401);
    expect(err.retryable).toBe(false);
    expect(err.type).toBe('session_expired');
    expect(err.statusCode).toBe(401);
  });

  test('server_error (500) is retryable', () => {
    const err = new ApiError('Server error', 'server_error', 500);
    expect(err.retryable).toBe(true);
    expect(err.type).toBe('server_error');
    expect(err.statusCode).toBe(500);
  });

  test('unknown (400) is not retryable', () => {
    const err = new ApiError('Bad request', 'unknown', 400);
    expect(err.retryable).toBe(false);
    expect(err.type).toBe('unknown');
    expect(err.statusCode).toBe(400);
  });

  test('server_error (502) is retryable', () => {
    const err = new ApiError('Bad gateway', 'server_error', 502);
    expect(err.retryable).toBe(true);
  });

  test('server_error (503) is retryable', () => {
    const err = new ApiError('Service unavailable', 'server_error', 503);
    expect(err.retryable).toBe(true);
  });

  test('is instanceof Error', () => {
    const err = new ApiError('Test', 'unknown');
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('ApiError');
  });
});

describe('classifyError', () => {
  test('classifies session_expired as AUTH', () => {
    const err = new ApiError('Session expired', 'session_expired', 401);
    const classified = classifyError(err);
    expect(classified.classification).toBe('AUTH');
    expect(classified.retryable).toBe(false);
  });

  test('classifies network_error as TRANSIENT', () => {
    const err = new ApiError('Network error', 'network_error');
    const classified = classifyError(err);
    expect(classified.classification).toBe('TRANSIENT');
    expect(classified.retryable).toBe(true);
  });

  test('classifies server_error as TRANSIENT', () => {
    const err = new ApiError('Server error', 'server_error', 500);
    const classified = classifyError(err);
    expect(classified.classification).toBe('TRANSIENT');
    expect(classified.retryable).toBe(true);
  });

  test('classifies unknown ApiError as RECOVERABLE', () => {
    const err = new ApiError('Bad request', 'unknown', 400);
    const classified = classifyError(err);
    expect(classified.classification).toBe('RECOVERABLE');
    expect(classified.retryable).toBe(true);
  });

  test('classifies TypeError as FATAL', () => {
    const err = new TypeError('Cannot read property of undefined');
    const classified = classifyError(err);
    expect(classified.classification).toBe('FATAL');
    expect(classified.retryable).toBe(false);
  });

  test('classifies RangeError as FATAL', () => {
    const err = new RangeError('Invalid array length');
    const classified = classifyError(err);
    expect(classified.classification).toBe('FATAL');
    expect(classified.retryable).toBe(false);
  });

  test('classifies network-related Error as TRANSIENT', () => {
    const err = new Error('Network request failed');
    const classified = classifyError(err);
    expect(classified.classification).toBe('TRANSIENT');
    expect(classified.retryable).toBe(true);
  });

  test('classifies timeout Error as TRANSIENT', () => {
    const err = new Error('Request timeout exceeded');
    const classified = classifyError(err);
    expect(classified.classification).toBe('TRANSIENT');
    expect(classified.retryable).toBe(true);
  });

  test('classifies generic Error as RECOVERABLE', () => {
    const err = new Error('Something broke');
    const classified = classifyError(err);
    expect(classified.classification).toBe('RECOVERABLE');
    expect(classified.retryable).toBe(true);
  });

  test('classifies null/undefined as FATAL', () => {
    const classified = classifyError(null);
    expect(classified.classification).toBe('FATAL');
    expect(classified.retryable).toBe(false);
  });

  test('classifies string as FATAL', () => {
    const classified = classifyError('something went wrong');
    expect(classified.classification).toBe('FATAL');
    expect(classified.retryable).toBe(false);
  });
});

describe('getUserMessage', () => {
  test('returns user-friendly message for network error', () => {
    const err = new ApiError('fetch failed', 'network_error');
    const msg = getUserMessage(err);
    expect(msg).toContain('Connection');
  });

  test('returns user-friendly message for session expired', () => {
    const err = new ApiError('401', 'session_expired', 401);
    const msg = getUserMessage(err);
    expect(msg).toContain('session');
  });

  test('returns generic message for unknown error shape', () => {
    const msg = getUserMessage(42);
    expect(msg.length).toBeGreaterThan(0);
  });
});

describe('isRetryable', () => {
  test('network errors are retryable', () => {
    expect(isRetryable(new ApiError('net', 'network_error'))).toBe(true);
  });

  test('server errors are retryable', () => {
    expect(isRetryable(new ApiError('srv', 'server_error', 500))).toBe(true);
  });

  test('auth errors are not retryable', () => {
    expect(isRetryable(new ApiError('auth', 'session_expired', 401))).toBe(false);
  });

  test('fatal errors are not retryable', () => {
    expect(isRetryable(new TypeError('fatal'))).toBe(false);
  });
});
