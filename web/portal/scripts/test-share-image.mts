import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import { GET as handler } from '../api/og.ts';

for (const kind of ['climbs', 'rides', 'riders', 'brand']) {
  test(`PNG endpoint renders ${kind} at 1200x630`, async () => {
    const original = globalThis.fetch;
    globalThis.fetch = async (url, options) => {
      if (url instanceof URL && url.protocol === 'file:') return new Response(await readFile(url));
      assert.equal(options?.credentials, 'omit');
      return Response.json({contractVersion:'public_preview.v1', objectType:kind.slice(0,-1), title:'Wises Mill Road', seo:{robots:'index,follow'},
        climb:{lengthM:1000,elevGainM:100,avgGradientPct:10,elevationProfile:[{distanceM:0,elevationM:0},{distanceM:1000,elevationM:100}]},
        ride:{distanceM:10000,elevationM:200,durationS:3000}, profile:{totalRides:12},leaderboard:{stats:{top10Count:1,komCount:0}}});
    };
    try {
      const response = await handler(new Request(`https://app.boulderroller.xyz/api/og?kind=${kind}&id=abc`));
      const png = Buffer.from(await response.arrayBuffer());
      assert.equal(response.headers.get('content-type'), 'image/png');
      assert.match(response.headers.get('cache-control')!, /s-maxage=3600/);
      assert.deepEqual([...png.subarray(0,8)], [137,80,78,71,13,10,26,10]);
      assert.equal(png.readUInt32BE(16),1200);
      assert.equal(png.readUInt32BE(20),630);
    } finally {globalThis.fetch = original;}
  });
}

import {renderToStaticMarkup} from 'react-dom/server';
import {cardElement} from '../server/share-card.ts';
test('ride card draws only public runs and cobalt counted spans, with gaps', () => {
  const html = renderToStaticMarkup(cardElement({kind:'rides',id:'abc',path:'/rides/abc'}, {title:'Ride',ride:{
    elevation_profile:[{distance_m:100,elevation_m:0},{distance_m:200,elevation_m:20},{distance_m:400,elevation_m:10,break_before:true},{distance_m:500,elevation_m:30}],
    counted_spans:[{start_distance_m:100,end_distance_m:200,pattern_id:'one'}],calEarned:987654321,
  }}));
  assert.equal((html.match(/stroke="#5592E2"/g) ?? []).length,1);
  assert.equal((html.match(/stroke="#9A9488"/g) ?? []).length,2);
  assert.match(html, />Climbs</);
  assert.doesNotMatch(html,/987654321/);
});
