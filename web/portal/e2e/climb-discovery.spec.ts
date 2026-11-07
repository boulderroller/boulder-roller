import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import path from 'node:path';

const evidence = path.resolve('../../history/portal-audit-2026-09-07/build/lane-c');
const user = { id: 'user-test-1', wallet: '11111111111111111111111111111111', username: 'lane-c', display_name: 'Lane C', weight_kg: 74, preferred_units: 'metric', is_public: true, theme_id: 'hoo-breddin' };
const climbs = [
  { id: 'hill-west', name: 'West Hill', hasVault: true, lengthM: 800, elevGainM: 69, avgGradientPct: 8.2, routePreview: { source: 'canon_centerline', bounds: { minLat: 40.03, maxLat: 40.035, minLon: -75.3, maxLon: -75.29 }, points: [{ x: 0, y: 1 }, { x: .4, y: .6 }, { x: 1, y: 0 }] } },
  { id: 'hill-east', name: 'East Hill', hasVault: false, lengthM: 1200, elevGainM: 90, avgGradientPct: 7.5, routePreview: { source: 'canon_centerline', bounds: { minLat: 40.07, maxLat: 40.075, minLon: -75.2, maxLon: -75.19 }, points: [{ x: 0, y: 1 }, { x: .6, y: .5 }, { x: 1, y: 0 }] } },
  { id: 'hill-small', name: 'Small Hill', hasVault: true, lengthM: 100, elevGainM: 8, avgGradientPct: 8, routePreview: { source: 'canon_centerline', bounds: { minLat: 40.05, maxLat: 40.050001, minLon: -75.24, maxLon: -75.239999 }, points: [{ x: 0, y: 1 }, { x: 1, y: 0 }] } },
];
async function setup(page: Page) {
  await page.clock.setFixedTime(new Date('2026-09-07T15:00:00Z'));
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname.replace(/^\/api/, '');
    let body: unknown = {};
    if (p === '/auth/bootstrap' || p === '/auth/onboarding/state') body = { authenticated: true, needs_profile_setup: false, invite_required: false, invite_validated: true, auth_method_hint: 'wallet', user };
    else if (p === '/users/me' || p === '/me') body = user;
    else if (p === '/status') body = { environment: 'test', solana_stub_mode: true, version: 'fixture' };
    else if (p === '/notifications') body = { notifications: [], unread_count: 0, has_more: false };
    else if (p === '/climbs/list') body = { climbs: climbs.filter(c => c.name.toLowerCase().includes((url.searchParams.get('q') || '').toLowerCase())) };
    else if (p === '/rides') body = [];
    else if (p === '/portfolio') body = { staked_positions: [], pending_claims: [] };
    else if (p === '/users/me/leaderboard-positions') body = { stats: {}, positions: [] };
    else if (p.includes('/social/')) body = { users: [], total: 0, comments: [], kudos_count: 0 };
    await route.fulfill({ json: body });
  });
}
async function capture(page: Page, name: string) {
  if (!process.env.BR_LANE_C_CAPTURE) return;
  mkdirSync(evidence, { recursive: true });
  await page.evaluate(() => document.fonts.ready);
  if (process.env.BR_LANE_C_MAP_READY && await page.locator('.climb-discovery__map-canvas[data-ground-ready], .feed-card [data-ground-ready]').count()) await expect(page.locator('.climb-discovery__map-canvas[data-ground-ready], .feed-card [data-ground-ready]').first()).toHaveAttribute('data-ground-ready', 'true', { timeout: 30000 });
  if (await page.locator('.profile-ground__map').count()) await page.waitForTimeout(1500);
  if (await page.locator('.ride-room-map').count()) {
    await expect(page.locator('.ride-room-map').first()).toHaveAttribute('data-route-ready', 'true');
    await page.waitForTimeout(1500);
  }
  await page.screenshot({ path: path.join(evidence, `${name}.png`), fullPage: true, animations: 'disabled' });
}
async function visibleRepresentations(page: Page, ids: string[]) {
  await expect.poll(() => page.locator('.climb-discovery-canon').evaluate((svg, expected) => {
    const obstacles = Array.from(document.querySelectorAll('.climbs-room__column, .climbs-room__controls, .climbs-room__card-layer, .maplibregl-ctrl-group')).filter(el => el.getClientRects().length).map(el => el.getBoundingClientRect());
    const map = svg.getBoundingClientRect();
    return expected.filter(id => Array.from(svg.querySelectorAll<SVGGraphicsElement>(`[data-climb-id="${id}"]`)).some(el => {
      if (getComputedStyle(el).display === 'none') return false;
      const r = el.getBoundingClientRect();
      return Math.max(r.width, r.height) >= 6 && r.left >= map.left && r.right <= map.right && r.top >= map.top && r.bottom <= map.bottom
        && obstacles.every(o => r.right < o.left || r.left > o.right || r.bottom < o.top || r.top > o.bottom);
    })).sort();
  }, ids)).toEqual([...ids].sort());
}
for (const width of [1440, 390]) {
  test(`05 one discovery set remains visible through filters and overlays at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await setup(page);
    await page.goto('/climbs');
    await expect(page.locator('.climbs-room__count')).toHaveText('3 in view');
    await expect(page.locator('.climbs-room__row')).toHaveCount(3);
    await visibleRepresentations(page, climbs.map(c => c.id));
    await expect(page.locator('.climb-discovery-marker[data-climb-id="hill-small"]')).toBeVisible();
    await capture(page, `climbs-${width}`);
    if (width === 390) await page.getByRole('button', { name: 'Expand climb results' }).click();
    await visibleRepresentations(page, climbs.map(c => c.id));
    await capture(page, `climbs-list-${width}`);
    await page.getByRole('button', { name: 'With vaults', exact: true }).click();
    await expect(page.locator('.climbs-room__count')).toHaveText('2 in view');
    await expect(page.locator('.climbs-room__row')).toHaveCount(2);
    await expect(page.locator('.climb-discovery-canon [data-climb-id="hill-east"]')).toHaveCount(0);
    await visibleRepresentations(page, ['hill-west', 'hill-small']);
    await page.getByRole('link', { name: 'Open West Hill', exact: true }).click();
    await expect(page.locator('.climbs-room__card')).toHaveAttribute('data-climb-id', 'hill-west');
    await expect(page.locator('.climb-discovery-route--selected')).toHaveAttribute('data-climb-id', 'hill-west');
    await visibleRepresentations(page, ['hill-west']);
  });
}
test('05 missing geometry uses only a permitted anchor, never a straight line', async ({ page }) => {
  await setup(page);
  await page.route('**/api/climbs/list?*', route => route.fulfill({ json: { climbs: [
    { ...climbs[0], routePreview: null, startLat: 40.03, startLon: -75.3, endLat: 40.035, endLon: -75.29 },
    { ...climbs[1], routePreview: null },
  ] } }));
  await page.goto('/climbs');
  await expect(page.locator('.climbs-room__count')).toHaveText('1 in view');
  await expect(page.locator('.climb-discovery-route')).toHaveCount(0);
  await expect(page.locator('.climb-discovery-marker')).toHaveCount(1);
  await expect(page.locator('.climbs-room__row')).toHaveAttribute('data-climb-id', 'hill-west');
});

const rideFixture = JSON.parse(gunzipSync(readFileSync(path.resolve('../../history/ride-room-2026-09-05/build/capture-fixture.json.gz'))).toString());
async function rideSetup(page: Page, permitted: boolean) {
  await setup(page);
  await page.route('**/api/rides/ride-1**', async route => {
    const url = new URL(route.request().url()), p = url.pathname.replace(/^\/api/, '');
    let body: unknown;
    if (p === '/rides/ride-1') body = rideFixture.ride;
    else if (p === '/rides/ride-1/gps') body = rideFixture.gps;
    else if (p === '/rides/ride-1/patterns') body = { patterns: { climb_patterns: permitted ? [rideFixture.patterns.patterns.climb_patterns[0]] : [] } };
    else if (p === '/rides/ride-1/streams') { const kind = url.searchParams.get('type') || 'power'; body = { ...rideFixture.streams[kind], id: kind, ride_id: 'ride-1', stream_type: kind }; }
    else { await route.fallback(); return; }
    await route.fulfill({ json: body });
  });
}
for (const width of [1440, 390]) {
  test(`07 matched results precede CAL and social at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await rideSetup(page, true);
    await page.goto('/activities/ride-1');
    await expect(page.locator('.ride-room-climbs .ride-room-row')).toHaveCount(1);
    await expect(page.locator('.ride-room-climbs .ride-room-row')).toContainText('Wises Mill Road');
    await expect(page.locator('.ride-room-cal')).toBeVisible();
    await expect.poll(() => page.locator('.ride-room-climbs').evaluate(climbs => {
      const social = document.querySelector('.ride-room-social')!;
      const cal = document.querySelector('.ride-room-ledger-right')!;
      return {
        beforeSocial: !!(climbs.compareDocumentPosition(social) & Node.DOCUMENT_POSITION_FOLLOWING),
        beforeCal: !!(climbs.compareDocumentPosition(cal) & Node.DOCUMENT_POSITION_FOLLOWING),
        visualSocial: climbs.getBoundingClientRect().top < social.getBoundingClientRect().top,
        visualCal: climbs.getBoundingClientRect().top <= cal.getBoundingClientRect().top,
      };
    })).toEqual({ beforeSocial: true, beforeCal: true, visualSocial: true, visualCal: true });
    await capture(page, `ride-${width}`);
    await page.locator('.ride-room-ledger').scrollIntoViewIfNeeded();
    await capture(page, `ride-results-${width}`);
  });
  test(`07 a ride without a permitted result invents none at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await rideSetup(page, false);
    await page.goto('/activities/ride-1');
    await expect(page.locator('.ride-room-ledger')).toBeVisible();
    await expect(page.locator('.ride-room-climbs .ride-room-row')).toHaveCount(0);
    await expect(page.locator('.ride-room-climbs')).not.toContainText('Wises Mill Road');
    await expect(page.locator('.ride-room-cal')).toBeVisible();
  });
}

async function profileSetup(page: Page) {
  await setup(page);
  await page.route('**/api/users/me/leaderboard-positions*', route => route.fulfill({ json: { stats: { total_positions: 0, kom_count: 0, top10_count: 0 }, positions: [] } }));
  await page.route('**/api/analytics/fitness*', route => route.fulfill({ json: { threshold_state: 'established', threshold_version: 'v1' } }));
  await page.route('**/api/analytics/training-load*', route => route.fulfill({ json: { threshold_state: 'established', threshold_version: 'v1', daily_loads: [] } }));
  await page.route('**/api/analytics/riding-days*', route => route.fulfill({ json: { days: [] } }));
}
for (const width of [1440, 390]) {
  test(`14 Profile navigation precedes expanded overview and keeps compact working tabs at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await profileSetup(page);
    await page.goto('/profile');
    const tabs = page.getByRole('tablist', { name: 'Profile sections' });
    await expect(tabs.getByRole('tab')).toHaveCount(4);
    await expect(page.locator('.profile-ledger')).toBeVisible();
    expect(await tabs.evaluate(el => !!(el.compareDocumentPosition(document.querySelector('.profile-ledger')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
    if (width === 390) expect((await tabs.boundingBox())!.y + (await tabs.boundingBox())!.height).toBeLessThanOrEqual(360);
    await expect(page.locator('.profile-ground__map')).toBeVisible();
    await capture(page, `profile-overview-${width}`);
    for (const name of ['Training', 'Portfolio']) {
      await tabs.getByRole('tab', { name, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`tab=${name.toLowerCase()}`));
      await expect(page.locator('.profile-masthead')).toContainText('Lane C');
      await expect(page.locator('.profile-ledger')).toHaveCount(0);
      await expect(page.locator('.profile-ground__map')).toBeVisible();
      if (width === 390) expect((await tabs.boundingBox())!.y + (await tabs.boundingBox())!.height).toBeLessThanOrEqual(360);
      await expect(page.locator('.ledger-slot')).toHaveCount(0);
      await capture(page, `profile-${name.toLowerCase()}-${width}`);
    }
    await tabs.getByRole('tab', { name: 'Overview', exact: true }).click();
    await expect(page.locator('.profile-ledger')).toBeVisible();
  });
}
for (const mode of ['reflow-320', 'text-200', 'text-only-200', 'text-spacing', 'font-blocked']) {
  test(`14 Profile tabs and identity survive ${mode}`, async ({ page }) => {
    await profileSetup(page);
    if (mode === 'font-blocked') {
      await page.route('**/*.{woff,woff2,ttf,otf}', route => route.abort());
      await page.route('https://fonts.googleapis.com/**', route => route.abort());
    }
    await page.setViewportSize({ width: mode === 'reflow-320' ? 320 : mode === 'text-200' ? 720 : 390, height: 844 });
    await page.goto('/profile?tab=training');
    await expect(page.locator('.profile-masthead')).toBeVisible();
    if (mode === 'text-only-200') await page.locator('.profile-masthead__name, .profile-masthead__meta, .profile-tabs__tab').evaluateAll(elements => {
      const sizes = elements.map(el => ({ size: parseFloat(getComputedStyle(el).fontSize), line: parseFloat(getComputedStyle(el).lineHeight) }));
      elements.forEach((el, i) => { (el as HTMLElement).style.fontSize = `${sizes[i].size * 2}px`; (el as HTMLElement).style.lineHeight = `${sizes[i].line * 2}px`; });
    });
    if (mode === 'text-spacing') await page.addStyleTag({ content: '* { letter-spacing: .12em !important; line-height: 1.5 !important; word-spacing: .16em !important; } p { margin-bottom: 2em !important; }' });
    await expect(page.getByRole('tablist').getByRole('tab')).toHaveCount(4);
    for (const name of ['Overview', 'Rides', 'Training', 'Portfolio']) await expect(page.getByRole('tab', { name, exact: true })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.locator('.profile-masthead__copy').evaluate(el => el.scrollHeight <= el.clientHeight && el.scrollWidth <= el.clientWidth)).toBe(true);
    await capture(page, `profile-${mode}`);
  });
}

const resultSummary = { rideId: 'ride-1', climbId: 'hill-west', revision: 'result-revision-1', asOf: '2026-09-06T15:00:00Z', timeSeconds: 235, place: null, isPersonalBest: null };
async function feedSetup(page: Page, summary: unknown, count = 1) {
  await setup(page);
  await page.route('**/api/feed/home?*', route => route.fulfill({ json: {
    contractVersion: 'feed_home.v1', scope: 'global', viewer: { authenticated: true, userId: user.id },
    feed: { activities: Array.from({ length: count }, (_, i) => ({
      id: `feed-event-${i}`, type: 'ride', title: 'Morning Ride', createdAt: '2026-09-06T15:00:00Z',
      target: { type: 'ride', id: 'ride-1' }, actor: { id: user.id, username: 'lane-c', displayName: 'Lane C' },
      resultSummary: summary,
      metadata: { distanceM: 31800, elevationM: 456, durationS: 5400, calEarned: 84, kudosCount: 2, commentCount: 1 },
    })), hasMore: false },
    suggestedRiders: [], popularClimbs: [], achievements: [], socialCounts: { followerCount: 0, followingCount: 0 }, notifications: { unreadCount: 0 },
  } }));
}
for (const width of [1440, 390]) {
  test(`15 a supplied climb result precedes CAL and retains social at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await feedSetup(page, resultSummary);
    await page.goto('/');
    const card = page.locator('.feed-card').first(), result = card.locator('.feed-card__result'), cal = card.locator('.feed-card__cal');
    await expect(card).toContainText('Morning Ride');
    await expect(result).toHaveCount(1);
    await expect(result).toContainText('3:55');
    await expect(result.getByRole('link')).toHaveAttribute('href', '/climbs/hill-west');
    await expect(cal).toContainText('84');
    await expect(card.locator('.feed-card__footer')).toBeVisible();
    expect(await result.evaluate(el => !!(el.compareDocumentPosition(el.closest('.feed-card')!.querySelector('.feed-card__cal')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
    expect((await result.boundingBox())!.y + (await result.boundingBox())!.height).toBeLessThanOrEqual((await cal.boundingBox())!.y);
    await expect(result).not.toContainText(/Best|Place|—/);
    await capture(page, `feed-${width}`);
  });
}
for (const [label, summary] of [
  ['missing', undefined], ['withheld', null], ['time absent', { ...resultSummary, timeSeconds: null }],
  ['wrong ride', { ...resultSummary, rideId: 'other-ride' }], ['revision absent', { ...resultSummary, revision: '' }],
  ['climb absent', { ...resultSummary, climbId: '' }], ['negative time', { ...resultSummary, timeSeconds: -5 }],
] as const) test(`15 ${label} result produces no fabricated row`, async ({ page }) => {
  await feedSetup(page, summary);
  await page.goto('/');
  await expect(page.locator('.feed-card').first()).toContainText('Morning Ride');
  await expect(page.locator('.feed-card__result')).toHaveCount(0);
  await expect(page.locator('.feed-card__cal')).toContainText('84');
  await expect(page.locator('.feed-card__footer')).toBeVisible();
});
test('15 zero and subsecond results retain their supplied value without a missing glyph', async ({ page }) => {
  for (const time of [0, 0.25, 1e-25]) {
    await feedSetup(page, { ...resultSummary, timeSeconds: time });
    await page.goto('/');
    await expect(page.locator('.feed-card__result strong')).toHaveText(String(time));
    await expect(page.locator('.feed-card__result')).toContainText('Time · s');
    await expect(page.locator('.feed-card__result')).not.toContainText('—');
  }
});
test('15 growing the feed creates no per-card result or detail requests', async ({ page }) => {
  const details: string[] = [];
  page.on('request', request => {
    const p = new URL(request.url()).pathname;
    if (/\/api\/(rides|climbs)\/[^/]+/.test(p)) details.push(p);
  });
  await feedSetup(page, { ...resultSummary, place: 4, isPersonalBest: true }, 24);
  await page.goto('/');
  await expect(page.locator('.feed-card__result').first()).toContainText('3:55');
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await expect(page.locator('.feed-card').last()).toBeVisible();
  await expect(page.locator('.feed-card__result').last()).not.toContainText(/Best|Place|4th/);
  expect(details).toEqual([]);
});

for (const surface of ['climbs', 'ride', 'feed']) for (const mode of ['reflow-320', 'text-200', 'text-spacing', 'font-blocked']) {
  test(`Lane C ${surface} remains usable under ${mode}`, async ({ page }) => {
    await page.setViewportSize({ width: mode === 'reflow-320' ? 320 : mode === 'text-200' ? 720 : 390, height: 844 });
    if (surface === 'ride') await rideSetup(page, true);
    else if (surface === 'feed') await feedSetup(page, resultSummary);
    else await setup(page);
    if (mode === 'font-blocked') {
      await page.route('**/*.{woff,woff2,ttf,otf}', route => route.abort());
      await page.route('https://fonts.googleapis.com/**', route => route.abort());
    }
    await page.goto(surface === 'climbs' ? '/climbs' : surface === 'ride' ? '/activities/ride-1' : '/');
    if (mode === 'text-spacing') await page.addStyleTag({ content: '* { letter-spacing: .12em !important; line-height: 1.5 !important; word-spacing: .16em !important; } p { margin-bottom: 2em !important; }' });
    if (surface === 'climbs') {
      await expect(page.locator('.climbs-room__count')).toHaveText('3 in view');
      await page.getByRole('button', { name: 'Expand climb results' }).click();
      await expect(page.getByRole('link', { name: 'Open West Hill' })).toBeVisible();
      await visibleRepresentations(page, climbs.map(c => c.id));
    } else if (surface === 'ride') {
      await expect(page.locator('.ride-room-climbs .ride-room-row')).toHaveCount(1);
      const results = await page.locator('.ride-room-climbs').boundingBox(), social = await page.locator('.ride-room-social').boundingBox();
      expect(results!.y).toBeLessThan(social!.y);
    } else {
      await expect(page.locator('.feed-card__result')).toContainText('3:55');
      await expect(page.locator('.feed-card__cal')).toContainText('84');
      await expect(page.locator('.feed-card__footer')).toBeVisible();
    }
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await capture(page, `${surface}-${mode}`);
  });
}

test('15 fractional Time uses the RideRoomLedger duration policy', async ({ page }) => {
  await feedSetup(page, { ...resultSummary, timeSeconds: 235.9 });
  await page.goto('/');
  await expect(page.locator('.feed-card__result strong')).toHaveText('3:55');
});
