import test from 'node:test';
import assert from 'node:assert/strict';
import { GET as handler } from '../api/share.ts';

for (const [kind, pageName] of [['climbs', 'Climb'], ['rides', 'Ride'], ['riders', 'Rider']]) {
  test(`crawler head: ${kind}, existing description, no money or credentials`, async () => {
    const original = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      assert.equal(String(url), `https://api.boulderroller.xyz/public/previews/${kind}/abc`);
      assert.equal(options?.cache, 'no-store');
      assert.equal(options?.credentials, 'omit');
      assert.equal(new Headers(options?.headers).has('authorization'), false);
      return Response.json({ contractVersion: 'public_preview.v1', objectType: pageName.toLowerCase(), title: 'A <hill> & "name"', seo: {description: 'Philadelphia', robots: 'index,follow'}, previewPolicy: {privacy: {canView: true}}, calEarned: 999 });
    };
    try {
      const response = await handler(new Request(`https://app.boulderroller.xyz/api/share?kind=${kind}&id=abc`, {headers: {cookie: 'private=secret', authorization: 'Bearer secret'}}));
      const html = await response.text();
      assert.match(html, new RegExp(`A &lt;hill&gt; &amp; &quot;name&quot; · ${pageName} · Boulder Roller`));
      assert.match(html, /content="Philadelphia"/);
      assert.match(html, new RegExp(`https://app.boulderroller.xyz/api/og\\?kind=${kind}&(?:amp;)?id=abc`));
      assert.match(html, /summary_large_image/);
      assert.match(html, /http-equiv="refresh"/);
      assert.doesNotMatch(html, /999|calEarned|private=secret/);
      assert.equal(response.headers.get('cache-control'), 'private, no-store, max-age=0');
    } finally { globalThis.fetch = original; }
  });
}

test('private and unavailable objects reveal only the brand and noindex', async () => {
  const original = globalThis.fetch;
  try {
    for (const result of [Response.json({title: 'Secret name', seo: {robots: 'noindex,nofollow', description: 'Secret place'}}), new Response(null, {status:404})]) {
      globalThis.fetch = async () => result;
      const response = await handler(new Request('https://app.boulderroller.xyz/riders/private'));
      const html = await response.text();
      assert.match(html, /<title>Boulder Roller<\/title>/);
      assert.match(html, /noindex,nofollow/);
      assert.doesNotMatch(html, /Secret/);
    }
  } finally {globalThis.fetch = original;}
});

test('unknown kind, invalid id, failures and upstream redirects fail closed', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => {throw new Error('unavailable');};
    for (const path of ['/api/share?kind=unknown&id=id', '/api/share?kind=rides&id=a%2Fb', '/api/share?kind=rides&id=abc']) {
      const response = await handler(new Request(`https://app.boulderroller.xyz${path}`));
      assert.match(await response.text(), /noindex,nofollow/);
    }
  } finally {globalThis.fetch = original;}
});

test('head and image use the public projection canonical rider identifier', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({contractVersion:'public_preview.v1',objectType:'rider',title:'Tim',canonicalPath:'/riders/tim',seo:{robots:'index,follow',description:'Rider profile on Boulder Roller.'}});
  try {
    const html = await (await handler(new Request('https://app.boulderroller.xyz/riders/@tim'))).text();
    assert.match(html, /rel="canonical" href="https:\/\/app.boulderroller.xyz\/riders\/tim"/);
    assert.match(html, /content="https:\/\/app.boulderroller.xyz\/api\/og\?kind=riders&(?:amp;)?id=tim"/);
    assert.match(html, /property="og:url" content="https:\/\/app.boulderroller.xyz\/riders\/tim"/);
  } finally {globalThis.fetch=original;}
});
