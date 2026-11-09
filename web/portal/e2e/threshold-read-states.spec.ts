import { expect, test, type Page } from '@playwright/test';

// Exercise the real Training page and query retries. Only HTTP data is replaced;
// these cases do not contact a backend, provider, or chain.
const rider = {
  id: 'threshold-state-rider',
  wallet: '11111111111111111111111111111111',
  username: 'threshold-state-rider',
  display_name: 'Threshold State Rider',
  weight_kg: 75,
  is_public: true,
  theme_id: 'hoo-breddin',
  is_dark_mode: false,
  preferred_units: 'metric',
};

type ReadState = 'loading' | 'failed' | 'pending' | 'establishing' | 'evening';

async function trainingFixture(page: Page, initial: ReadState) {
  let state = initial;
  let release: () => void = () => {};
  const ready = new Promise<void>((resolve) => { release = resolve; });
  const unexpected: string[] = [];
  const calls = { training: 0, threshold: 0, timezone: 0 };

  await page.addInitScript(() => {
    localStorage.setItem('br_authenticated', 'true');
    localStorage.removeItem('br_auth_handoff_pending');
  });
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const isApi = ['fetch', 'xhr'].includes(request.resourceType()) && (
      url.pathname.startsWith('/api/')
      || (url.hostname === '127.0.0.1' && url.port === '9')
      || (url.hostname.startsWith('api.boulderroller.') && !url.pathname.startsWith('/basemap/'))
    );
    if (!isApi) {
      if (['localhost', '127.0.0.1'].includes(url.hostname)) await route.continue();
      else await route.abort();
      return;
    }

    const path = url.pathname.replace(/^\/api/, '');
    let body: unknown;
    if (path === '/analytics/timezone') {
      calls.timezone += 1;
      expect(request.method()).toBe('POST');
      expect(request.postDataJSON()).toEqual({ timezone: 'America/New_York' });
      await route.fulfill({ json: { timezone: 'America/New_York' } });
      return;
    }
    if (state === 'evening' && ['/analytics/fitness', '/analytics/training-load', '/analytics/riding-days'].includes(path)) {
      expect(url.searchParams.get('timezone')).toBe('America/New_York');
      const authority = { threshold_state: 'estimated', threshold_version: 'training:2', threshold_training_state: null };
      const fitness = { ...authority, ctl: 2, atl: 11, tsb: -9, form: 'Grey zone', training_available: true };
      const load = { ...authority, daily_loads: [{ date: '2026-10-07', total_tss: 80 }], total_tss: 80 };
      body = path === '/analytics/riding-days'
        ? { start_date: '2026-01-01', end_date: '2026-10-07', days: [{ date: '2026-10-07', ride_count: 1, moving_s: 1800 }] }
        : path === '/analytics/fitness' ? fitness
          : { ...load, snapshot: { revision: 'training:2', as_of: '2026-10-07', initialization: 'initializing',
            coverage: { completeness: 'complete', population: 'fixture' }, fitness_metrics: fitness, training_load: load } };
      await route.fulfill({ json: body });
      return;
    }
    if (path === '/auth/bootstrap' || path === '/auth/onboarding/state') {
      body = { authenticated: true, needs_profile_setup: false, invite_required: false, invite_validated: true, auth_method_hint: 'wallet', user: rider };
    } else if (path === '/me' || path === '/users/me') {
      body = rider;
    } else if (path === '/status') {
      body = { environment: 'test', solana_stub_mode: true, version: 'fixture' };
    } else if (path === '/admin/check') {
      body = { is_admin: false, role: null };
    } else if (path === '/social/followers/threshold-state-rider' || path === '/social/following/threshold-state-rider') {
      body = { users: [], total: 0 };
    } else if (path === '/portfolio') {
      body = { contract_version: 'portfolio.v5', staked_positions: [], pending_claims: [] };
    } else if (path === '/climbs/list') {
      body = { climbs: [] };
    } else if (path === '/users/me/leaderboard-positions') {
      body = { stats: {}, positions: [] };
    } else if (path === '/notifications') {
      body = { notifications: [], unread_count: 0, has_more: false };
    } else if (path === '/analytics/riding-days') {
      body = { contract_version: 'riding_days.v1', start_date: '2026-01-01', end_date: '2026-09-04', days: [] };
    } else if (path === '/analytics/power-curve') {
      body = { contract_version: 'power_curve.v1', durations_s: [], best_w: [], sampled_rides: 0, ride_count: 0, available: false };
    } else if (path === '/users/me/threshold' || path === '/analytics/fitness' || path === '/analytics/training-load') {
      if (path === '/users/me/threshold') calls.threshold += 1;
      else calls.training += 1;
      if (state === 'loading') await ready;
      if (state === 'failed') {
        await route.fulfill({ status: 503, json: { detail: 'Read temporarily unavailable' } });
        return;
      }
      const pending = state === 'pending';
      if (path === '/users/me/threshold') {
        body = {
          contract_version: 'threshold.v1', state: pending ? 'established' : 'establishing',
          current_w: pending ? 245 : null, established_at: pending ? '2026-08-31T12:00:00Z' : null,
          last_raised_at: null, sealing_in_progress: false,
          pending_monday: pending ? { watts: 251, effective_at: '2026-09-07T12:00:00Z' } : null,
        };
      } else {
        const authority = {
          threshold_state: pending ? 'established' : 'establishing',
          threshold_training_state: pending ? 'pending' : null,
          threshold_version: pending ? 'pending:251:test-promotion' : 'establishing',
        };
        body = path === '/analytics/fitness'
          ? { ...authority, ctl: pending ? 48 : null, atl: pending ? 54 : null, tsb: pending ? -6 : null, form: pending ? 'Optimal' : null }
          : { ...authority, daily_loads: [], total_tss: pending ? 192 : null, avg_daily_tss: pending ? 96 : null };
      }
    } else {
      unexpected.push(`${request.method()} ${path}`);
      await route.fulfill({ status: 501, json: { detail: 'Unmocked API route' } });
      return;
    }
    await route.fulfill({ status: 200, json: body });
  });
  return {
    calls, unexpected,
    setState(next: ReadState) { state = next; release(); },
  };
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test.describe(`Threshold reads at ${viewport.width}px`, () => {
    test.use({ viewport, timezoneId: 'America/New_York' });

    test('20:30 EDT keeps tonight’s Fatigue, Form and streak', async ({ page }) => {
      const fixture = await trainingFixture(page, 'evening');
      await page.clock.setFixedTime(new Date('2026-10-08T00:30:00Z'));
      await page.goto('/profile?tab=training', { waitUntil: 'domcontentloaded' });
      await expect(page.locator('.training-trio strong')).toHaveText(['2', '11', '-9']);
      await expect(page.locator('.training-consistency .training-sheet__footer')).toContainText('Current streak 1');
      await expect(page.locator('.training-load__snapshot time')).toHaveAttribute('datetime', '2026-10-07');
      expect(fixture.calls.timezone).toBeGreaterThan(0);
      expect(fixture.unexpected).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: `/private/tmp/training-round4-${viewport.width}.png`, fullPage: true });
    });

    test('loading Load and Threshold show absence; returned candidate stays Pending', async ({ page }) => {
      const fixture = await trainingFixture(page, 'loading');
      try {
        await page.goto('/profile?tab=training', { waitUntil: 'domcontentloaded' });
        const load = page.getByRole('region', { name: 'Load', exact: true });
        const threshold = page.getByRole('region', { name: 'Threshold', exact: true });
        await expect(threshold.locator('[aria-busy="true"]')).toBeVisible();
        await expect(load.locator('.training-trio strong .ledger-slot--number')).toHaveCount(3);
        await expect(page.locator('.shell-live-rule')).toHaveAttribute('data-live', 'true');
        await expect(load.getByText('Establishing', { exact: true })).toHaveCount(0);
        await expect(threshold.getByText('Establishing', { exact: true })).toHaveCount(0);

        fixture.setState('pending');
        await expect(load.locator('.training-trio strong')).toHaveText(['', '', '']);
        await expect(load.getByText('Pending', { exact: true })).toBeVisible();
        await expect(threshold.getByText('245 W', { exact: true })).toBeVisible();
        await expect(threshold.getByText('251 W · Pending', { exact: true })).toBeVisible();
        expect(fixture.unexpected).toEqual([]);
      } finally {
        fixture.setState('pending');
      }
    });

    test('failed Load and Threshold reads retry before showing confirmed Establishing', async ({ page }) => {
      // The API client and React Query both retain their production retries.
      test.setTimeout(45_000);
      const fixture = await trainingFixture(page, 'failed');
      await page.goto('/profile?tab=training', { waitUntil: 'domcontentloaded' });
      const load = page.getByRole('region', { name: 'Load', exact: true });
      const threshold = page.getByRole('region', { name: 'Threshold', exact: true });
      await expect(load.getByRole('alert')).toContainText('Could not load training', { timeout: 30_000 });
      await expect(load.locator('.training-trio strong')).toHaveText(['', '', '']);
      await expect(load.getByText('Establishing', { exact: true })).toHaveCount(0);
      await expect(threshold.getByText('Establishing', { exact: true })).toHaveCount(0);
      await expect(threshold.getByRole('button', { name: 'Try again', exact: true })).toBeVisible();
      const before = { ...fixture.calls };

      fixture.setState('establishing');
      await load.getByRole('button', { name: 'Try again', exact: true }).click();
      await threshold.getByRole('button', { name: 'Try again', exact: true }).click();
      await expect(load.getByRole('alert')).toHaveCount(0);
      await expect(threshold.getByText('Establishing', { exact: true })).toBeVisible();
      await expect(threshold.getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0);
      await expect(load.locator('.training-trio strong')).toHaveText(['', '', '']);
      expect(fixture.calls.training).toBeGreaterThan(before.training);
      expect(fixture.calls.threshold).toBeGreaterThan(before.threshold);
      expect(fixture.unexpected).toEqual([]);
    });
  });
}
