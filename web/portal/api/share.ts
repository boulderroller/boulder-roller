import { APP_ORIGIN, shareObject, publicPreview, objectTitle, imageUrl, canonicalObject } from '../server/share-preview.js';
// Node runtime, same as the card function.

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]!));

// Web fetch-style named export: the Node runtime ignores a Response returned from a default export.
export async function GET(request: Request): Promise<Response> {
  const requested = shareObject(request);
  const preview = await publicPreview(requested);
  const object = canonicalObject(requested, preview);
  const title = objectTitle(object, preview);
  const description = typeof preview?.seo?.description === 'string' ? preview.seo.description : '';
  const canonical = `${APP_ORIGIN}${object?.path ?? '/'}`;
  const robots = preview ? 'index,follow' : 'noindex,nofollow';
  const type = object?.kind === 'riders' && preview ? 'profile' : 'website';
  const meta = (attribute: string, name: string, value: string) => `<meta ${attribute}="${name}" content="${escapeHtml(value)}">`;
  const html = '<!doctype html><html><head><meta charset="utf-8">'
    + `<title>${escapeHtml(title)}</title>`
    + meta('name', 'description', description)
    + `<link rel="canonical" href="${escapeHtml(canonical)}">`
    + meta('name', 'robots', robots)
    + meta('property', 'og:title', title)
    + meta('property', 'og:description', description)
    + meta('property', 'og:url', canonical)
    + meta('property', 'og:type', type)
    + meta('property', 'og:image', imageUrl(object))
    + meta('property', 'og:image:width', '1200') + meta('property', 'og:image:height', '630')
    + meta('property', 'og:image:type', 'image/png')
    + meta('name', 'twitter:card', 'summary_large_image')
    + meta('http-equiv', 'refresh', `0;url=${canonical}`)
    + '</head><body></body></html>';
  return new Response(html, {headers: {
    'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'private, no-store, max-age=0',
    'X-Robots-Tag': robots, 'Vary': 'User-Agent',
  }});
}
