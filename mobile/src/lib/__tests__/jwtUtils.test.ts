/**
 * JWT Utils Tests
 *
 * Tests parseJwtExpiry for standard JWTs, edge cases,
 * and Base64URL-specific characters.
 */

import { parseJwtExpiry } from '../jwtUtils';

// Helper: create a JWT with a given payload
function makeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  const signature = 'fakesig';
  return `${header}.${body}.${signature}`;
}

describe('parseJwtExpiry', () => {
  test('extracts exp from a valid JWT (seconds to ms conversion)', () => {
    const expSeconds = 1700000000;
    const token = makeJwt({ exp: expSeconds, sub: 'user123' });
    const result = parseJwtExpiry(token);
    expect(result).toBe(expSeconds * 1000);
  });

  test('returns future timestamp for JWT without exp claim', () => {
    const token = makeJwt({ sub: 'user123', iat: 1700000000 });
    const now = Date.now();
    const result = parseJwtExpiry(token);
    // Should be approximately 15 minutes from now
    expect(result).toBeGreaterThan(now);
    expect(result).toBeLessThanOrEqual(now + 16 * 60 * 1000);
  });

  test('returns future timestamp for malformed token (no dots)', () => {
    const now = Date.now();
    const result = parseJwtExpiry('not-a-jwt');
    expect(result).toBeGreaterThan(now);
  });

  test('returns future timestamp for empty string', () => {
    const now = Date.now();
    const result = parseJwtExpiry('');
    expect(result).toBeGreaterThan(now);
  });

  test('returns future timestamp for invalid base64 payload', () => {
    const now = Date.now();
    const result = parseJwtExpiry('header.!!!invalid!!!.signature');
    expect(result).toBeGreaterThan(now);
  });

  test('handles exp=0 (epoch zero)', () => {
    const token = makeJwt({ exp: 0 });
    const result = parseJwtExpiry(token);
    expect(result).toBe(0);
  });
});
