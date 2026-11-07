import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { mixedFeed, parseFeed } from '../feed/feedModel';
import { withV2Example, parseFeedV2, personalTrend, climbBand, formatFeedCal } from '../feed/feedV2Model';

test('V2 economics require their own supplied context, preserving true zero', () => {
  const source = structuredClone(withV2Example(mixedFeed));
  source.workshopV2!.world!.rideCal = 0;
  assert.equal(parseFeedV2(source).workshopV2!.world!.rideCal, 0);
  delete source.workshopV2;
  assert.equal(parseFeedV2(source).workshopV2, undefined);
  assert.equal(withV2Example(parseFeed(source)).workshopV2, undefined);
});
test('V2 rejects misbound or non-owner economics and inverted periods', () => {
  const source = structuredClone(withV2Example(mixedFeed));
  source.workshopV2!.rideEconomics[0].rideId = 'another-ride';
  assert.throws(() => parseFeedV2(source), /ride/i);
  const visitor = structuredClone(withV2Example(mixedFeed));
  visitor.entries[0].owned = false;
  assert.throws(() => parseFeedV2(visitor), /owner/i);
  const period = structuredClone(withV2Example(mixedFeed));
  period.workshopV2!.world!.periodEnd = '2016-01-01T00:00:00Z';
  assert.throws(() => parseFeedV2(period), /period/i);
});
test('personal history uses own climb and band uses exact ride distance bounds', () => {
  const trend = personalTrend(mixedFeed)!;
  assert.equal(trend.entry.owned, true);
  assert.ok(trend.points.length > 1);
  assert.ok(trend.points.every((p, i, all) => i === 0 || p.date >= all[i - 1].date));
  const band = climbBand(trend.entry.ride, trend.climb)!;
  const samples = trend.entry.ride.ride.samples;
  assert.equal(band.from, (samples.find(p => p.t === trend.climb.start)!.d - samples[0].d) / (samples.at(-1)!.d - samples[0].d));
  assert.equal(personalTrend({...mixedFeed, entries: mixedFeed.entries.filter(e => !e.owned)}), null);
});
test('personal progress starts from the newest eligible owned ride', () => {
  const latest = structuredClone(mixedFeed.entries[0]);
  latest.id = 'latest'; latest.ride.id = 'latest-ride'; latest.ride.ride.startedAt = '2017-01-01T12:00:00Z';
  assert.equal(personalTrend({...mixedFeed, entries:[...mixedFeed.entries, latest]})!.entry.id, 'latest');
});
test('a positive fractional CAL amount never displays as zero', () => {
  assert.equal(formatFeedCal(0.001), '0.001');
  assert.notEqual(formatFeedCal(1e-24), '0');
  assert.equal(formatFeedCal(0), '0');
});
test('Feed V1 presentation and its data source remain exactly preserved', () => {
  for (const file of ['FeedV1.tsx', 'feed-v1.css', 'feedModel.ts']) {
    const path = `web/portal/workshop/feed/${file}`;
    assert.equal(readFileSync(new URL(`../feed/${file}`, import.meta.url), 'utf8'), execFileSync('git', ['show', `8a4125b0c:${path}`], {encoding:'utf8'}));
  }
});
