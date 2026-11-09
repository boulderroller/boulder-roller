import { composeBrowserTitle } from './browser-title.js';

// Server-only consumer: never forward the visitor's session to public previews.
export const APP_ORIGIN = 'https://app.boulderroller.xyz';
const API_ORIGIN = 'https://api.boulderroller.xyz';
export const PAGE_NAMES = { climbs: 'Climb', rides: 'Ride', riders: 'Rider' } as const;
export type Kind = keyof typeof PAGE_NAMES;
export type Preview = Record<string, any>;
export type ShareObject = {kind: Kind; id: string; path: string};

export function shareObject(request: Request): ShareObject | null {
  const url = new URL(request.url, APP_ORIGIN); // the Node runtime passes a relative URL
  // Static function paths (/api/share, /api/og) carry the object as ?kind=&id= so the
  // function is matched in Vercel's filesystem phase, ahead of the /api/:path* proxy rewrite.
  const fromQuery = /^\/api\/(?:share|og)\/?$/.test(url.pathname)
    ? [null, url.searchParams.get('kind') ?? '', url.searchParams.get('id') ?? ''] as const
    : null;
  const match = fromQuery ?? url.pathname.match(/^\/(climbs|rides|riders)\/([^/]+)\/?$/);
  if (!match || !/^(climbs|rides|riders)$/.test(match[1] ?? '')) return null;
  try {
    const id = fromQuery ? match[2] : decodeURIComponent(match[2]);
    if (!id || id.length > 200 || /[\s/\\?#\u0000-\u001f]/u.test(id) || id === '.' || id === '..') return null;
    const kind = match[1] as Kind;
    return {kind, id, path: `/${kind}/${encodeURIComponent(id)}`};
  } catch {return null;}
}

export async function publicPreview(object: ShareObject | null): Promise<Preview | null> {
  if (!object) return null;
  const started = Date.now();
  try {
    const response = await fetch(`${API_ORIGIN}/public/previews${object.path}`, {
      cache: 'no-store', credentials: 'omit', redirect: 'error',
      headers: {accept: 'application/json'}, signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) return null;
    const data = await response.json();
    if (data?.contractVersion !== 'public_preview.v1' || data.objectType !== PAGE_NAMES[object.kind].toLowerCase()) return null;
    if (data.seo?.robots !== 'index,follow' || data.previewPolicy?.privacy?.canView === false || data.previewPolicy?.privacy?.isOwner === true) return null;
    return data;
  } catch (error) {
    console.error('share-preview: fetch failed', Date.now() - started, 'ms', error instanceof Error ? `${error.name}: ${error.message}` : String(error));
    return null;
  }
}

export function objectTitle(object: ShareObject | null, preview: Preview | null): string {
  if (!object || !preview) return 'Boulder Roller';
  const pageName = PAGE_NAMES[object.kind];
  const name = typeof preview.title === 'string' ? preview.title.trim() : '';
  return composeBrowserTitle(name || null, pageName);
}

export function imageUrl(object: ShareObject | null): string {
  if (!object) return `${APP_ORIGIN}/api/og`;
  return `${APP_ORIGIN}/api/og?kind=${object.kind}&id=${encodeURIComponent(object.id)}`;
}

export function canonicalObject(object: ShareObject | null, preview: Preview | null): ShareObject | null {
  const path = preview?.canonicalPath;
  if (!object || typeof path !== 'string' || !path.startsWith(`/${object.kind}/`)) return object;
  const canonical = shareObject(new Request(`${APP_ORIGIN}${path}`));
  return canonical?.kind === object.kind ? canonical : object;
}
