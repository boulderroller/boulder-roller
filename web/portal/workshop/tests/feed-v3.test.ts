import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { mixedFeed } from '../feed/feedModel';
import { withV3Example, parseFeedV3, ridingSummary, personalDays, worldPeriodLabel } from '../feed/feedV3Model';

test('V3 context is explicit and never inherited by an imported familiar ID', () => {
  assert.ok(withV3Example(mixedFeed).workshopV3);
  assert.equal(withV3Example(structuredClone(mixedFeed)).workshopV3, undefined);
  const source = structuredClone(withV3Example(mixedFeed)); delete source.workshopV3;
  assert.equal(parseFeedV3(source).workshopV3, undefined);
});
test('personal history is complete, owned and independently scoped from feed filters', () => {
  const source = structuredClone(withV3Example(mixedFeed));
  const personal = source.workshopV3!.personal!;
  assert.equal(personalDays(personal, 28).length, 28);
  assert.equal(personalDays(personal, 7).length, 7);
  assert.ok(ridingSummary(personalDays(personal, 28)).rides > 3);
  personal.days.pop(); assert.throws(() => parseFeedV3(source), /complete/i);
  const wrong = structuredClone(withV3Example(mixedFeed)); wrong.workshopV3!.personal!.viewer = 'Someone else';
  assert.throws(() => parseFeedV3(wrong), /viewer/i);
});
test('world regions preserve zeros and require consistent counts and geography', () => {
  const source = structuredClone(withV3Example(mixedFeed));
  const world = source.workshopV3!.world!;
  world.regions[0].climbsRidden = 0;
  world.climbsRidden = world.regions.reduce((n,r) => n+r.climbsRidden,0);
  assert.equal(parseFeedV3(source).workshopV3!.world!.regions[0].climbsRidden,0);
  world.regions[0].lon = 300; assert.throws(() => parseFeedV3(source), /region/i);
});
test('the exclusive world period end displays the last included local day', () => {
  assert.equal(worldPeriodLabel('2016-08-22T00:00:00-04:00','2016-08-29T00:00:00-04:00'),'Aug 22–28');
  assert.equal(worldPeriodLabel('2016-08-29T00:00:00-04:00','2016-09-05T00:00:00-04:00'),'Aug 29–Sep 4');
});
test('V3 preserves V2 and V1 presentation and models byte for byte', () => {
  for (const file of ['FeedV1.tsx','feed-v1.css','feedModel.ts','FeedV2.tsx','FeedV2Map.tsx','FeedV2Context.tsx','feed-v2.css','feedV2Model.ts']) {
    assert.equal(readFileSync(new URL(`../feed/${file}`,import.meta.url),'utf8'),execFileSync('git',['show',`ab473c3c0:web/portal/workshop/feed/${file}`],{encoding:'utf8'}));
  }
});
