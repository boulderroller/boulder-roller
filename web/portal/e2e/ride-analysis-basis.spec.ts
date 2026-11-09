import { expect, test, type Page } from '@playwright/test';
import { readFileSync, mkdirSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import path from 'node:path';
import { cardElement } from '../server/share-card';
import { instrumentSamples, pathFor } from '../src/components/ride/ridePageModel';
import { fixtures } from '../scripts/share-card-fixtures.mts';

const capture = JSON.parse(gunzipSync(readFileSync(path.resolve('../../history/ride-room-2026-09-05/build/capture-fixture.json.gz'))).toString());
const user = { id: 'user-test-1', wallet: '11111111111111111111111111111111', username: 'lane-b', display_name: 'Lane B', preferred_units: 'metric', is_public: true, theme_id: 'hoo-breddin' };
const presentation = {
  id: 'ride-1', revision: 'offline-revision-1', asOf: '2016-08-28T18:20:00Z',
  metricBasis: { key: 'whole-ride', viewerProjection: 'owner', startOffsetS: 0, endOffsetS: 18727, aggregation: 'whole-ride', coverage: { completeness: 'complete', population: 'whole ride', observedCount: null, expectedCount: null } },
  distanceM: 128730, elevationM: 1013, durationS: 18727, avgPowerW: 188, maxPowerW: 950,
  zoneShareDenominator: null, traceReduction: null,
};
async function setup(page: Page, projection: unknown = presentation) {
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname.replace(/^\/api/, '');
    let body: unknown = {};
    if (p === '/auth/bootstrap' || p === '/auth/onboarding/state') body = { authenticated: true, needs_profile_setup: false, invite_required: false, invite_validated: true, auth_method_hint: 'wallet', user };
    else if (p === '/users/me' || p === '/me') body = user;
    else if (p === '/status') body = { environment: 'test', solana_stub_mode: false, version: 'fixture' };
    else if (p === '/rides/ride-1') body = { ...capture.ride, distance_m: 52600, elevation_m: 1100, duration_s: 7312, presentation: projection };
    else if (p === '/rides/ride-1/gps') body = capture.gps;
    else if (p === '/rides/ride-1/patterns') body = capture.patterns;
    else if (p === '/rides/ride-1/streams') { const kind = url.searchParams.get('type') || 'power'; body = { ...capture.streams[kind], id: kind, ride_id: 'ride-1', stream_type: kind }; }
    else if (p === '/rides') body = [];
    else if (p === '/privacy/settings') body = { contract_version: 'privacy.v2', profile_visibility: 'public', default_ride_visibility: 'public', default_map_visibility: 'hide_start_end', default_map_hide_start_m: 200, default_map_hide_end_m: 200, defaults_apply_to: 'future_rides', provider_privacy_inherited: false, privacy_zone_count: 0, privacy_zones_loaded: true, ride_override_mode: 'optional', protocol_public_fields: [] };
    else if (p === '/users/me/threshold') body = { state: 'established', current_w: 265 };
    else if (p === '/notifications') body = { notifications: [], unread_count: 0, has_more: false };
    else if (p === '/portfolio') body = { staked_positions: [], pending_claims: [] };
    else if (p === '/users/me/leaderboard-positions') body = { stats: {}, positions: [] };
    else if (p === '/climbs/list') body = { climbs: [] };
    else if (p.includes('/social/')) body = { users: [], total: 0, comments: [], kudos_count: 0 };
    else if (p === '/analytics/power-curve') body = { durations_s: [], best_w: [], available: false };
    await route.fulfill({ json: body });
  });
}
const values = ['128.7 km', '1,013 m', '5:12:07'];
test('02 same ride presentation drives page, analysis and public share facts', async ({ page }) => {
  await setup(page);
  await page.goto('/activities/ride-1');
  for (const value of values) await expect(page.locator('.ride-page-card')).toContainText(value);
  await page.goto('/activities/ride-1/analysis');
  for (const value of values) await expect(page.locator('.ride-analysis-stats')).toContainText(value);
  const publicProjection = { ...presentation, metricBasis: { ...presentation.metricBasis, viewerProjection: 'public' } };
  const rendered = JSON.stringify(cardElement({ kind: 'rides', id: 'ride-1', path: '/rides/ride-1' }, { ...fixtures.rides, ride: { ...fixtures.rides.ride, id: 'ride-1', presentation: publicProjection } }));
  for (const value of values) expect(rendered).toContain(value);
  expect(rendered).not.toContain('52.6 km');
  expect(rendered).not.toContain('calEarned');
});

async function trainingSetup(page: Page, withSnapshot: boolean) {
  await setup(page);
  const fitness = { ctl: 48, atl: 54, tsb: -6, form: 'Optimal', thresholdState: 'established', thresholdVersion: 'v1', thresholdTrainingState: null };
  const load = { thresholdState: 'established', thresholdVersion: 'v1', thresholdTrainingState: null, dailyLoads: [{ date: '2026-08-30', totalTss: 70 }, { date: '2026-08-31', totalTss: 90 }] };
  const snapshot = { revision: 'offline-model-1', asOf: '2026-08-31T23:59:59Z', initialization: 'initialized', coverage: { completeness: 'complete', population: '365 days', observedCount: 365, expectedCount: 365 }, fitnessMetrics: fitness, trainingLoad: load };
  await page.route('**/api/analytics/fitness', route => route.fulfill({ json: fitness }));
  await page.route('**/api/analytics/training-load?*', route => route.fulfill({ json: { ...load, snapshot: withSnapshot ? snapshot : null } }));
  await page.route('**/api/analytics/riding-days?*', route => route.fulfill({ json: { start_date: '2026-01-01', end_date: '2026-08-31', days: [] } }));
}
test('03 unsupported current Training values and assessment abstain', async ({ page }) => {
  await trainingSetup(page, false);
  await page.goto('/profile?tab=training');
  await expect(page.locator('.training-trio')).toBeVisible();
  await expect(page.locator('.ledger-slot')).toHaveCount(0);
  await expect(page.locator('.training-trio')).not.toContainText('Optimal');
  await expect(page.locator('.training-trio strong')).toHaveText(['', '', '']);
  await expect(page.locator('.training-load time')).toHaveCount(0);
  await expect(page.locator('.training-load__figure svg')).toBeVisible();
});
test('03 supplied coherent snapshot owns trio, model date and history', async ({ page }) => {
  await trainingSetup(page, true);
  await page.goto('/profile?tab=training');
  await expect(page.locator('.training-trio strong')).toHaveText(['48', '54', '-6']);
  await expect(page.locator('.training-trio')).not.toContainText('Optimal');
  await expect(page.locator('.training-load time')).toHaveAttribute('datetime', '2026-08-31T23:59:59Z');
  await expect(page.locator('.training-load')).toContainText('365 days');
});

for (const width of [1440, 390]) test(`04 readable analysis text and separated primary ticks at ${width}`, async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width, height: 1000 });
  await page.goto('/activities/ride-1/analysis');
  await expect(page.locator('.ride-instrument')).toHaveCount(4);
  await page.evaluate(() => document.fonts.ready);
  const violations = await page.locator('.ride-analysis-page').evaluate(root => {
    return [...root.querySelectorAll('*')].flatMap(el => {
      if (![...el.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.textContent?.trim())) return [];
      if (el.closest('.ride-instrument-table,.ride-analysis-keyboard')) return [];
      const style = getComputedStyle(el), bounds = el.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return [];
      const scale = el instanceof SVGGraphicsElement ? el.getScreenCTM()?.a ?? 1 : 1;
      const size = parseFloat(style.fontSize) * scale;
      return size < 11.99 || parseFloat(style.lineHeight) < 15.99 ? [{ text: el.textContent, size, line: style.lineHeight }] : [];
    });
  });
  expect(violations).toEqual([]);
  const ticks = await page.locator('.ride-instrument-axis text').evaluateAll(nodes => nodes.slice(0, -1).map(n => { const b = n.getBoundingClientRect(); return { left: b.left, right: b.right }; }));
  for (let i = 1; i < ticks.length; i++) expect(ticks[i].left - ticks[i - 1].right).toBeGreaterThanOrEqual(4);
});

const evidenceDir = path.resolve('../../history/portal-audit-2026-09-07/build/lane-b');
for (const mode of ['reflow-320', 'text-200', 'text-spacing', 'font-blocked']) test(`04 analysis ${mode}`, async ({ page }) => {
  await setup(page);
  if (mode === 'font-blocked') {
    await page.route('**/*.{woff,woff2,ttf,otf}', route => route.abort());
    await page.route('https://fonts.googleapis.com/**', route => route.abort());
  }
  await page.setViewportSize({ width: mode === 'reflow-320' ? 320 : mode === 'text-200' ? 720 : 390, height: 1000 });
  await page.goto('/activities/ride-1/analysis');
  await expect(page.locator('.ride-instrument')).toHaveCount(4);
  await expect(page.locator('.ledger-slot')).toHaveCount(0);
  if (mode === 'text-spacing') await page.addStyleTag({ content: '* { letter-spacing: .12em !important; line-height: 1.5 !important; word-spacing: .16em !important; } p { margin-bottom: 2em !important; }' });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  for (const value of values) await expect(page.locator('.ride-analysis-stats')).toContainText(value);
  mkdirSync(evidenceDir, { recursive: true });
  await page.screenshot({ path: path.join(evidenceDir, `analysis-${mode}.png`), fullPage: true });
});

for (const available of [true, false]) test(`06 authoritative average ${available ? 'unifies' : 'abstains in'} both locations`, async ({ page }) => {
  await setup(page, available ? presentation : { ...presentation, avgPowerW: null });
  await page.goto('/activities/ride-1/analysis');
  const summary = page.locator('.ride-analysis-stats > div').filter({ has: page.locator('dt', { hasText: /^Avg power$/ }) });
  const metrics = page.locator('.ride-metrics > div').filter({ has: page.locator('dt', { hasText: /^Avg power$/ }) });
  if (available) {
    await expect(summary.locator('dd')).toHaveText('188 W');
    await expect(metrics.locator('dd')).toHaveText('188 W');
  } else {
    await expect(page.locator('.ride-metrics')).toBeVisible();
    await expect(summary).toHaveCount(0);
    await expect(metrics).toHaveCount(0);
  }
});

for (const known of [true, false]) test(`08 zone shares ${known ? 'use included time' : 'omit unsupported denominator'}`, async ({ page }) => {
  const denominator = { basis: 'classified-power-intervals:max-gap=30s', durationS: 16057, startOffsetS: 0, endOffsetS: 18727, coverage: { completeness: 'partial', population: 'power sample intervals', observedCount: null, expectedCount: null } };
  await setup(page, { ...presentation, zoneShareDenominator: known ? denominator : null });
  await page.goto('/activities/ride-1/analysis');
  await expect(page.locator('.ride-zones')).toBeVisible();
  const share = page.locator('.ride-zones th').filter({ hasText: 'Share' });
  if (known) {
    await expect(share).toContainText('4:27:37');
    await expect(share).not.toContainText('4:27:45');
    await expect(share).not.toContainText('5:12:07');
    await expect(page.locator('.ride-zones tbody tr').first()).toContainText('30%');
  } else {
    await expect(share).toHaveCount(0);
    await expect(page.locator('.ride-zones')).not.toContainText('%');
    await expect(page.locator('.ride-zones tbody tr').first()).toContainText('1:19:07');
  }
});

for (const known of [true, false]) test(`09 trace and maximum ${known ? 'retain distinct supplied bases' : 'omit unknown native claims'}`, async ({ page }) => {
  const traceReduction = { source: 'Native power samples', method: 'native-samples', binDistanceM: null, smoothingWindowSamples: null, preservesExtrema: true };
  await setup(page, { ...presentation, traceReduction: known ? traceReduction : null });
  await page.goto('/activities/ride-1/analysis');
  const trace = page.locator('.ride-instrument-trace--power').first();
  await expect(trace).toHaveAttribute('data-reduction-method', 'distance-bin-mean+moving-mean');
  await expect(trace).toHaveAttribute('data-bin-distance-m', '200');
  await expect(trace).toHaveAttribute('data-window-samples', '5');
  await expect(trace).toHaveAttribute('data-preserves-extrema', 'false');
  const maximum = page.locator('.ride-metrics > div').filter({ has: page.locator('dt', { hasText: /^Max power/ }) });
  if (known) {
    await expect(maximum).toContainText('950 W');
    await expect(maximum).toContainText('Native power samples');
  } else {
    await expect(maximum).toHaveCount(0);
    await expect(page.locator('.ride-analysis-page')).not.toContainText('Native power samples');
  }
});

test('09 local reduction reports the 450 W plotted mean separately from a 950 W sample', async () => {
  const samples = [325, 325, 950, 325, 325].map((power, i) => ({ t: i, d: i, power, elevation: null, cadence: null, speed: null, heartRate: null, gps: {} as never, index: i }));
  const original = structuredClone(samples);
  const reduced = instrumentSamples(samples, false);
  expect(Math.max(...reduced.samples.map(p => p.power!))).toBe(450);
  expect(reduced.descriptor).toEqual({ source: '', method: 'distance-bin-mean+moving-mean', binDistanceM: 200, smoothingWindowSamples: 5, preservesExtrema: false });
  expect(samples).toEqual(original);
  expect(instrumentSamples(samples, true).descriptor.smoothingWindowSamples).toBe(9);
  // pathFor preserves extrema of its input, which is already reduced.
  expect(pathFor(reduced.samples, p => p.power, p => p.d, v => v)).toContain('450');
});

test('02 serial Upload follow-up uses the same permitted presentation distance', async ({ page }) => {
  await setup(page);
  await page.route('**/api/rides/upload/init', route => route.fulfill({ status: 409, json: { detail: { error: 'duplicate_file', existing_ride_id: 'ride-1' } } }));
  await page.goto('/activities/ride-1');
  await page.locator('header').getByRole('button', { name: 'Upload ride', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Who can see this ride?', exact: true })).toBeVisible();
  await page.getByRole('dialog').locator('input[type="file"]').setInputFiles({ name: 'ride.gpx', mimeType: 'application/gpx+xml', buffer: Buffer.from('<gpx version="1.1"><trk><name>Ride</name></trk></gpx>') });
  await page.getByRole('dialog').getByRole('button', { name: 'Upload ride', exact: true }).click();
  await expect(page.locator('.upload-sheet__ride')).toContainText('128.7 km');
  await expect(page.locator('.upload-sheet__ride')).not.toContainText('52.6 km');
});

test('02 public rendering rejects an owner-only presentation without compatibility fallback', () => {
  const rendered = JSON.stringify(cardElement({ kind: 'rides', id: 'ride-1', path: '/rides/ride-1' }, { ...fixtures.rides, ride: { ...fixtures.rides.ride, presentation } }));
  for (const value of values) expect(rendered).not.toContain(value);
});

for (const width of [1440, 390]) test(`lane B local evidence at ${width}`, async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  const save = async (name: string) => {
    await expect(page.locator('.ledger-slot')).toHaveCount(0);
    await page.evaluate(() => document.fonts.ready);
    mkdirSync(evidenceDir, { recursive: true });
    await page.screenshot({ path: path.join(evidenceDir, `${name}-${width}.png`), fullPage: true, animations: 'disabled' });
  };
  await page.goto('/activities/ride-1');
  await expect(page.locator('.ride-page-card')).toContainText('128.7 km');
  await expect(page.locator('.ride-page-climbs a')).toHaveCount(3);
  await save('ride-page');
  await page.goto('/activities/ride-1/analysis');
  await expect(page.locator('.ride-instrument')).toHaveCount(4);
  await save('analysis-whole');
  await page.getByRole('button', { name: 'Wises Mill Road', exact: true }).click();
  await expect(page.locator('.ride-analysis-stats')).toContainText('3:55');
  await save('analysis-scope');
  await trainingSetup(page, false);
  await page.goto('/profile?tab=training');
  await expect(page.locator('.training-trio strong')).toHaveText(['', '', '']);
  await save('training-unsupported');
  await trainingSetup(page, true);
  await page.reload();
  await expect(page.locator('.training-trio strong')).toHaveText(['48', '54', '-6']);
  await save('training-snapshot');
});

test('02 absent comparison populations do not leave empty analysis columns', async ({ page }) => {
  await setup(page);
  await page.goto('/activities/ride-1/analysis');
  await expect(page.locator('.ride-instrument')).toHaveCount(4);
  const table = page.locator('.ride-analysis-figure').first().locator('table');
  await expect(table.getByRole('columnheader', { name: 'Your best', exact: true })).toHaveCount(0);
  await expect(table.getByRole('columnheader', { name: 'Δ W', exact: true })).toHaveCount(0);
  await expect(table.getByRole('columnheader', { name: 'This ride', exact: true })).toHaveCount(1);
});

test('02 mismatched ride identity cannot supply legacy share totals', () => {
  const rendered = JSON.stringify(cardElement({ kind: 'rides', id: 'other-ride', path: '/rides/other-ride' }, fixtures.rides));
  for (const value of values) expect(rendered).not.toContain(value);
});
