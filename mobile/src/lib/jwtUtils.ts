/**
 * JWT Utility Functions
 *
 * Parses JWT expiry from the token payload without validating the signature.
 * Uses proper Base64URL decoding per RFC 7515.
 */

function base64UrlDecode(str: string): string {
  const padded = str + '=='.slice(0, (4 - (str.length % 4)) % 4);
  return atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
}

/**
 * Extract the `exp` claim from a JWT and return it as epoch milliseconds.
 * Falls back to 15 minutes from now if the token cannot be parsed.
 */
export function parseJwtExpiry(token: string): number {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) throw new Error('Invalid JWT format');
    const payload = JSON.parse(base64UrlDecode(parts[1]));
    if (typeof payload.exp === 'number') {
      return payload.exp * 1000; // Convert seconds to milliseconds
    }
  } catch {
    // Invalid JWT format — fall through to default
  }
  // Fallback: assume 15 minutes from now (matches server default)
  return Date.now() + 15 * 60 * 1000;
}
