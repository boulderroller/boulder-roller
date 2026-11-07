import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';

const overallNote = "Each rider's fastest ascent. Power with ⚡ was measured by a power meter. Power with ≈ is an estimate from the time and the climb, at a standard rider weight.";
const reportDir = path.resolve('../../history/codex-reports-2026-10-20/legacy-power');
const ownerWallet = '11111111111111111111111111111111';
const rows = [
  { rank: 1, wallet: ownerWallet, display_name: 'Measured Rider', username: 'measured', best_time_seconds: 180, avg_power_w: 324, power_kind: 'measured', w_per_kg: 4.32, effort_id: 'effort-measured', ride_id: 'ride-for-effort' },
  { rank: 2, wallet: 'estimated', display_name: 'Estimated Rider', username: 'estimated', best_time_seconds: 195, avg_power_w: 999, power_kind: 'estimated', estimated_power_w: 278, estimated_power_range_w: [250, 310], effort_id: 'effort-estimated', ride_id: 'ride-for-effort' },
  { rank: 3, wallet: 'unshared', display_name: 'Unshared Rider', username: 'unshared', best_time_seconds: 210, avg_power_w: 301, power_kind: 'measured' },
  { rank: 4, wallet: 'absent', display_name: 'No Power', username: 'absent', best_time_seconds: 220 },
  { rank: 5, wallet: 'legacy', display_name: 'Unknown Kind', username: 'legacy', best_time_seconds: 230, avg_power_w: 450, estimated_power_w: 400, w_per_kg: 6 },
].map(row => ({ ...row, position: row.rank, competition_rank: row.rank, achieved_at: '2026-10-20T12:00:00Z' }));

async function fixture(page: Page, signedIn = true, vault = false) {
  const effortRequests: string[] = [];
  page.on('request', request => { if (new URL(request.url()).pathname.includes('/climbs/efforts/')) effortRequests.push(request.url()); });
  const user = { id: 'owner', wallet: ownerWallet, username: 'measured', display_name: 'Measured Rider', weight_kg: 75, preferred_units: 'metric', is_public: true };
  const auth = { authenticated: signedIn, invite_required: false, invite_validated: true, needs_profile_setup: false, user: signedIn ? user : null };
  const climb = {
    id: 'power-climb', name: 'Shawmont Rise', region: 'Philadelphia, PA', length_m: 620, elev_gain_m: 58, avg_gradient_pct: 9.4,
    has_vault: vault, vault_id: vault ? 1 : null,
    elevation_profile: [{ distance_m: 0, elevation_m: 40 }, { distance_m: 180, elevation_m: 47 }, { distance_m: 380, elevation_m: 79 }, { distance_m: 620, elevation_m: 98 }],
  };
  const board = { contract_version: 'client.v1', truth_source: 'onchain', climb_id: climb.id, vault_id: vault ? 1 : null, entries: rows, leaderboard: rows };
  await page.addInitScript((authenticated) => { if (authenticated) localStorage.setItem('br_authenticated', 'true'); }, signedIn);
  await page.route('**/*', async route => {
    if (!['fetch', 'xhr'].includes(route.request().resourceType())) return route.continue();
    const url = new URL(route.request().url());
    const pathname = url.pathname.replace(/^\/api/, '');
    const json = (body: unknown, status = 200) => route.fulfill({ json: body, status });
    if (pathname === '/auth/bootstrap' || pathname === '/auth/onboarding/state') return json(auth);
    if (pathname === '/users/me') return json(user);
    if (pathname === '/climbs/power-climb') return json(climb);
    if (pathname === '/climbs/power-climb/leaderboard' || pathname === '/vaults/1/leaderboard') return json(board);
    if (pathname.startsWith('/climbs/efforts/')) return json({ effort_id: pathname.split('/').at(-1), ride_id: 'ride-for-effort', climb_id: climb.id, metrics: {} });
    if (pathname === '/public/previews/climbs/power-climb') return json({
      contract_version: 'public_preview.v1', object_type: 'climb', id: climb.id, title: climb.name, canonical_path: '/climbs/power-climb',
      preview_policy: { mode: 'public_preview' }, seo: {}, assets: {}, freshness: { source: 'fixture' },
      climb: { ...climb, record_board: { entries: rows.map(row => ({ ...row, rider: { username: row.username, display_name: row.display_name } })), row_limit: 10, hidden_rows: 0 } },
    });
    if (pathname === '/admin/check') return json({ is_admin: false });
    if (pathname === '/status') return json({ solana_stub: false });
    if (pathname === '/notifications') return json({ notifications: [], unread_count: 0 });
    if (pathname === '/vaults/1/my-history') return json({ efforts: [], total_count: 0 });
    if (/\/vaults\/1\//.test(pathname) || pathname === '/vaults/1') return json({}, 404);
    return route.continue();
  });
  return effortRequests;
}

for (const surface of ['climb', 'vault', 'public'] as const) {
  for (const width of [1440, 390]) {
    test(`${surface} power marks, privacy and effort links at ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      const effortRequests = await fixture(page, surface !== 'public', surface === 'vault');
      await page.goto('/climbs/power-climb');
      const board = page.getByRole('region', { name: 'Climb leaderboard', exact: true });
      await expect(board.locator('.climb-result-row')).toHaveCount(5);
      const measured = board.locator('[data-rank="1"]');
      await expect(measured.getByRole('link', { name: /3:00/ })).toHaveAttribute('href', '/activities/ride-for-effort/analysis');
      await expect(measured.getByRole('link', { name: 'Measured Rider', exact: true })).toHaveAttribute('href', surface === 'public' ? '/riders/measured' : '/rider/measured');
      await expect(board.locator('[data-rank="3"] .climb-result-effort')).toHaveCount(0);
      await board.getByRole('radio', { name: 'Power', exact: true }).check();
      await expect(measured).toContainText('⚡');
      await expect(measured).toContainText('324 W');
      await expect(measured).toContainText('4.32 W/kg');
      const estimated = board.locator('[data-rank="2"]');
      await expect(estimated).toContainText('≈278 W');
      await expect(estimated).not.toContainText('⚡');
      await expect(estimated).not.toContainText('999');
      await expect(board.locator('[data-rank="3"]')).not.toContainText('W/kg');
      for (const rank of [4, 5]) await expect(board.locator(`[data-rank="${rank}"] .climb-power`)).toHaveCount(0);
      await expect(board).not.toContainText(/\bweight\b|\d+(?:\.\d+)? kg\b/i);
      const estimate = estimated.getByRole('button', { name: 'Estimated 278 watts', exact: true });
      await estimate.focus();
      await expect(page.getByRole('dialog', { name: 'Estimated 278 watts' })).toContainText('250–310 W');
      await page.keyboard.press('Escape');
      await estimate.hover();
      await expect(page.getByRole('dialog', { name: 'Estimated 278 watts' })).toBeVisible();
      await page.mouse.move(0, 0);
      await board.getByRole('button', { name: 'About this leaderboard' }).click();
      await expect(page.getByRole('dialog', { name: 'About this leaderboard' })).toHaveText(overallNote);
      await page.keyboard.press('Escape');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(effortRequests).toEqual([]);
      if (surface !== 'vault') {
        await page.evaluate(() => {
          (document.activeElement as HTMLElement | null)?.blur();
          document.querySelectorAll<HTMLElement>('*').forEach(element => { if (element.scrollTop) element.scrollTop = 0; });
          window.scrollTo(0, 0);
        });
        await page.screenshot({ path: path.join(reportDir, `${surface}-${width}.png`), fullPage: true });
        if (width === 390) {
          await page.getByRole('slider', { name: 'Climb route and elevation', exact: true }).press('End');
          await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
        }
        await board.screenshot({ path: path.join(reportDir, `${surface}-leaderboard-${width}.png`) });
      }
    });
  }
}

for (const seated of [false, true]) test(`own row ${seated ? 'seated beyond five' : 'outside Top 10 without profile metadata'} stays visible`, async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page);
  const own = { rank: seated ? 6 : 12, position: seated ? 6 : null, wallet: ownerWallet,
    best_time_seconds: 240, power_kind: 'measured', avg_power_w: 300, w_per_kg: 4, effort_id: 'effort-own', ride_id: 'ride-for-effort' };
  await page.route('**/climbs/power-climb/leaderboard', route => route.fulfill({ json: {
    entries: [...rows.map(row => ({ ...row, wallet: `${row.wallet}-other` })), ...(seated ? [own] : [])], viewer_entry: own,
  } }));
  await page.goto('/climbs/power-climb');
  const row = page.locator('.climb-result-row[data-viewer="true"]');
  await expect(row).toHaveCount(1);
  await expect(row).toBeVisible();
  await expect(row.getByRole('link', { name: /4:00/ })).toHaveAttribute('href', '/activities/ride-for-effort/analysis');
  await expect(row).not.toContainText('Rider profile private');
  await page.getByRole('radio', { name: 'Power', exact: true }).check();
  await expect(row).toContainText('4.00 W/kg');
});

test('a withheld server ride id never manufactures a destination or requests an effort', async ({ page }) => {
  const effortRequests = await fixture(page);
  await page.route('**/climbs/power-climb/leaderboard', route => route.fulfill({ json: { entries: rows.map(({ ride_id, ...row }) => row) } }));
  await page.goto('/climbs/power-climb');
  await expect(page.locator('.climb-result-row')).toHaveCount(5);
  await expect(page.locator('.climb-result-effort')).toHaveCount(0);
  expect(effortRequests).toEqual([]);
  await expect(page.getByRole('link', { name: 'Measured Rider', exact: true })).toBeVisible();
});

test('missing profile metadata never manufactures a public rider identity', async ({ page }) => {
  await fixture(page);
  await page.route('**/climbs/power-climb/leaderboard', route => route.fulfill({ json: { entries: [{
    rank: 1, wallet: '99999999999999999999999999999999', best_time_seconds: 180,
    power_kind: 'measured', avg_power_w: 300, effort_id: 'effort-anonymous', ride_id: 'ride-for-effort', achieved_at: '2026-10-20T12:00:00Z',
  }] } }));
  await page.goto('/climbs/power-climb');
  const row = page.locator('.climb-result-row');
  await expect(row.locator('.climb-result-rider strong')).toHaveText('Rider');
  await expect(row.locator('.climb-result-rider a, .climb-result-rider small')).toHaveCount(0);
  // An explicit server-authorized ride can open without naming its rider.
  await expect(row.getByRole('link', { name: /3:00/ })).toHaveAttribute('href', '/activities/ride-for-effort/analysis');
});

test('ride patterns consume server power without calling the effort endpoint', async ({ page }) => {
  const effortRequests = await fixture(page);
  const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222', '33333333-3333-4333-8333-333333333333'];
  const power = [
    { power_kind: 'measured', avg_power_w: 324, w_per_kg: 4.32 },
    { power_kind: 'estimated', estimated_power_w: 278, estimated_power_range_w: [250, 310] },
    {},
  ];
  await page.route('**/rides/power-ride/patterns', route => route.fulfill({ json: {
    ride_id: 'power-ride', patterns: { climb_patterns: ids.map((id, index) => ({ id, climb_id: 'power-climb', ...power[index] })) },
  } }));
  await page.goto('/climbs/power-climb');
  await expect(page.locator('.climb-result-row')).toHaveCount(5);
  const powers = await page.evaluate(async () => {
    const source = '/src/lib/api.ts';
    const { api } = await import(source);
    const response = await api.getRidePatterns('power-ride');
    return response.patterns.climbPatterns;
  });
  expect(powers[0]).toMatchObject({ powerKind: 'measured', avgPowerW: 324, wPerKg: 4.32 });
  expect(powers[1]).toMatchObject({ powerKind: 'estimated', estimatedPowerW: 278, estimatedPowerRangeW: [250, 310] });
  expect(powers[1].wPerKg).toBeUndefined();
  expect(powers[2].powerKind).toBeUndefined();
  expect(powers[2].wPerKg).toBeUndefined();
  expect(effortRequests).toEqual([]);
});
