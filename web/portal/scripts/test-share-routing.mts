import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

for (const path of ['../vercel.json','../../vercel.json']) {
  test(`${path}: crawlers, humans, API functions, backend proxy and guarded catch-all`, async () => {
    const {rewrites} = JSON.parse(await readFile(new URL(path,import.meta.url),'utf8'));
    const resolve = (path: string, ua: string, accept: string) => rewrites.find((r:any) => {
      const pattern = r.source.replace(':path*','.*').replace(':kind','[^/]+').replace(':id','[^/]+');
      return new RegExp(`^${pattern}$`).test(path) && (r.has ?? []).every((c:any) => new RegExp(c.value).test(c.key==='user-agent' ? ua : accept));
    })?.destination;
    for (const kind of ['climbs','rides','riders']) {
      for (const ua of ['Twitterbot/1.0','facebookexternalhit/1.1','Slackbot-LinkExpanding 1.0','LinkedInBot','Discordbot','WhatsApp','Applebot','iMessage','TelegramBot']) {
        assert.equal(resolve(`/${kind}/abc`,ua,'*/*'),`/api/share?kind=${kind}&id=:id`);
      }
      assert.equal(resolve(`/${kind}/abc`,'Mozilla/5.0','text/html'),'/index.html');
      assert.equal(resolve(`/${kind}/abc`,'Mozilla/5.0','*/*'),'/index.html');
    }
    // Static function paths are served from the filesystem before any rewrite; no rewrite may claim them.
    assert.equal(resolve('/api/og','','*/*'),'https://api.boulderroller.xyz/:path*');
    assert.equal(resolve('/api/share','','*/*'),'https://api.boulderroller.xyz/:path*');
    assert.equal(resolve('/api/rides','','*/*'),'https://api.boulderroller.xyz/:path*');
    assert.equal(resolve('/missing.js','','*/*'),undefined);
    assert.equal(resolve('/feed','','text/html'),'/index.html');
  });
}
