/** The upload deep link keeps its page as the return destination. */
export function readUploadReturnTo(state: unknown): string {
  if (!state || typeof state !== 'object') return '/profile?tab=rides';

  const value = (state as { returnTo?: string }).returnTo;
  if (
    typeof value !== 'string'
    || !value.startsWith('/')
    || value.startsWith('//')
    || value.split(/[?#]/)[0].replace(/\/+$/, '') === '/upload'
  ) {
    return '/profile?tab=rides';
  }
  return value;
}
