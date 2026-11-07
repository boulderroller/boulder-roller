import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';

const reportDir = path.resolve('../../history/codex-reports-2026-10-20/rides-leaderboard');
const ownerWallet = '11111111111111111111111111111111';
const overallNote = "Each rider's fastest ascent. Power with ⚡ was measured by a power meter. Power with ≈ is an estimate from the time and the climb, at a standard rider weight.";
const entries = Array.from({ length: 10 }, (_, i) => ({
  rank: i + 1, position: i + 1, competition_rank: i === 1 ? 1 : i + 1, is_tied: i < 2,
  wallet: `wallet-${i}`, user_id: `rider-${i}`, username: `rider-${i}`, display_name: `Rider ${i + 1}`,
  best_time_seconds: i < 2 ? 100 : 100 + i * 10, achieved_at: '2026-10-21T12:00:00Z',
  ride_id: `ride-${i}`, place_source: 'rides',
  ...(i === 1 ? { power_kind: 'estimated', estimated_power_w: 280, estimated_power_range_w: [250, 310] }
    : { power_kind: 'measured', avg_power_w: 300, ...(i === 0 ? { w_per_kg: 4 } : {}) }),
}));
const own = { ...entries[0], user_id: 'owner', wallet: ownerWallet, username: 'owner', display_name: 'Your Rider',
  rank: 12, position: 12, competition_rank: 12, is_tied: false, best_time_seconds: 240, ride_id: 'own-ride' };

async function fixture(page: Page, { empty = false, earlier = false, vault = false } = {}) {
  const user = { id: 'owner', wallet: ownerWallet, username: 'owner', display_name: 'Your Rider', is_public: true, weight_kg: 75 };
  const auth = { authenticated: true, invite_required: false, invite_validated: true, needs_profile_setup: false, user };
  const climb = { id: 'rides-climb', name: 'Test Hill', region: 'Philadelphia, PA', version: earlier ? 2 : 1,
    length_m: 620, elev_gain_m: 58, avg_gradient_pct: 9.4, has_vault: vault, vault_id: vault ? 1 : null,
    elevation_profile: [{ distance_m: 0, elevation_m: 40 }, { distance_m: 180, elevation_m: 47 },
      { distance_m: 380, elevation_m: 79 }, { distance_m: 620, elevation_m: 98 }] };
  const board = { contract_version: 'client.v1', truth_source: 'projected', source: vault ? 'onchain' : 'rides',
    climb_id: climb.id, vault_id: vault ? 1 : null, entries: empty ? [] : entries,
    leaderboard: empty ? [] : entries, viewer_entry: empty ? null : own, earlier_version_id: earlier ? 'version-one' : null };
  await page.addInitScript(() => localStorage.setItem('br_authenticated', 'true'));
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (!['fetch', 'xhr'].includes(request.resourceType())) {
      return ['localhost', '127.0.0.1'].includes(url.hostname) ? route.continue() : route.abort();
    }
    const pathname = url.pathname.replace(/^\/api/, '');
    const json = (body: unknown, status = 200) => route.fulfill({ json: body, status });
    if (pathname === '/auth/bootstrap' || pathname === '/auth/onboarding/state') return json(auth);
    if (pathname === '/users/me') return json(user);
    if (pathname === '/climbs/rides-climb') return json(climb);
    if (pathname === '/climbs/rides-climb/leaderboard' || pathname === '/vaults/1/leaderboard') return json(board);
    if (pathname === '/admin/check') return json({ is_admin: false });
    if (pathname === '/status') return json({ solana_stub: true });
    if (pathname === '/notifications') return json({ notifications: [], unread_count: 0 });
    if (pathname === '/vaults/1/my-history') return json({ efforts: [], total_count: 0 });
    return json({}, 404); // All external state stays mocked; never connect to production.
  });
}

for (const width of [1440, 390]) {
  test(`rides source, ties, own pin, power and row destinations at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await fixture(page);
    await page.goto('/climbs/rides-climb');
    const board = page.getByRole('region', { name: 'Climb leaderboard', exact: true });
    await expect(board.getByText('From rides', { exact: true })).toBeVisible();
    await expect(board.getByText('Leaderboard from rides · this version only', { exact: true })).toBeVisible();
    await expect(board.locator('.climb-result-row')).toHaveCount(11);
    const first = board.locator('.climb-result-row').first();
    await expect(first).toContainText('T-1');
    await expect(first.getByRole('link', { name: 'Rider 1', exact: true })).toHaveAttribute('href', '/rider/rider-0');
    await expect(first.getByRole('link', { name: /Open ride analysis/ })).toHaveAttribute('href', '/activities/ride-0/analysis');
    const pinned = board.locator('[data-viewer="true"]');
    await expect(pinned).toBeVisible();
    await expect(pinned).toContainText('12');
    await board.getByRole('button', { name: 'About this leaderboard' }).click();
    await expect(page.getByRole('dialog', { name: 'About this leaderboard' })).toHaveText(overallNote);
    await page.keyboard.press('Escape');
    await board.getByRole('radio', { name: 'Power', exact: true }).check();
    await expect(first).toContainText('⚡');
    await expect(first).toContainText('4.00 W/kg');
    await expect(board.locator('.climb-result-row').nth(1)).toContainText('≈280 W');
    await expect(board.locator('.climb-result-row').nth(1)).not.toContainText('W/kg');
    await board.getByRole('radio', { name: 'Time', exact: true }).check();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.mouse.move(0, 0);
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    if (width === 1440) await board.scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(reportDir, `rides-${width}.png`) });
    if (width === 390) {
      await page.getByRole('slider', { name: 'Climb route and elevation', exact: true }).press('End');
      await board.getByText('Leaderboard from rides · this version only', { exact: true }).scrollIntoViewIfNeeded();
      await expect(pinned).toBeInViewport();
      await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
      await page.screenshot({ path: path.join(reportDir, 'pinned-390.png') });
      await board.locator('h2').scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(reportDir, 'leaderboard-390.png') });
    } else {
      await board.screenshot({ path: path.join(reportDir, `leaderboard-${width}.png`) });
    }
    // Activate both hit areas, including the row's stretched link, on each viewport.
    await first.getByRole('link', { name: 'Rider 1', exact: true }).click();
    await expect(page).toHaveURL(/\/rider\/rider-0$/);
    await page.goBack();
    await expect(board).toBeVisible();
    const rankBox = await first.locator('.climb-result-rank').boundingBox();
    expect(rankBox).not.toBeNull();
    await page.mouse.click(rankBox!.x + rankBox!.width / 2, rankBox!.y + rankBox!.height / 2);
    await expect(page).toHaveURL(/\/activities\/ride-0\/analysis$/);
  });

  test(`honest empty version at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await fixture(page, { empty: true, earlier: true });
    await page.goto('/climbs/rides-climb');
    const board = page.getByRole('region', { name: 'Climb leaderboard', exact: true });
    await expect(board.getByText('No times on this version yet.', { exact: true })).toBeVisible();
    await expect(board.getByText('Earlier times remain on version 1.', { exact: true })).toBeVisible();
    await expect(board).not.toContainText('Ride it to set the first time.');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width === 390) await page.getByRole('slider', { name: 'Climb route and elevation', exact: true }).press('End');
    await board.locator('h2').scrollIntoViewIfNeeded();
    await page.mouse.move(0, 0);
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.screenshot({ path: path.join(reportDir, `empty-${width}.png`) });
  });
}

test('empty first version makes no earlier-version claim', async ({ page }) => {
  await fixture(page, { empty: true });
  await page.goto('/climbs/rides-climb');
  const board = page.getByRole('region', { name: 'Climb leaderboard', exact: true });
  await expect(board).toContainText('No times on this version yet.');
  await expect(board).not.toContainText('Earlier times');
});

test('vault board retains its presentation', async ({ page }) => {
  await fixture(page, { vault: true });
  await page.goto('/climbs/rides-climb');
  const board = page.getByRole('region', { name: 'Climb leaderboard', exact: true });
  await expect(board.locator('.climb-result-row')).toHaveCount(11);
  await expect(board).not.toContainText('From rides');
  await expect(board).not.toContainText('this version only');
});
