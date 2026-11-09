import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const geometry = {
  contractVersion: 'route_preview.v1',
  source: 'server_gps',
  segments: [
    [
      { x: 0.12, y: 0.8 },
      { x: 0.28, y: 0.55 },
      { x: 0.48, y: 0.38 },
    ],
    [
      { x: 0.65, y: 0.24 },
      { x: 0.78, y: 0.32 },
      { x: 0.9, y: 0.12 },
    ],
  ],
  bounds: { minLat: 40.01, maxLat: 40.055, minLon: -75.25, maxLon: -75.2 },
  placeLabel: 'Philadelphia, PA',
  privacy: { redactedGps: true },
};
const base = (objectType: string, id: string, title: string) => ({
  contractVersion: 'public_preview.v1',
  objectType,
  id,
  title,
  canonicalPath: `/${objectType}s/${id}`,
  previewPolicy: {
    mode: 'public_preview',
    objectType,
    rawGpsAvailable: false,
    streamsAvailable: false,
  },
  seo: { title, robots: 'index,follow' },
  assets: {},
  freshness: {
    source: 'fixture',
    loadedAt: '2026-09-06T12:00:00Z',
    cacheTtlSeconds: 60,
  },
});
async function previews(page: Page) {
  const auth = {
    authenticated: false,
    invite_required: true,
    invite_validated: false,
    needs_profile_setup: false,
    user: null,
  };
  for (const endpoint of ['bootstrap', 'onboarding/state'])
    await page.route(`**/auth/${endpoint}`, (r) => r.fulfill({ json: auth }));
  await page.route('**/public/previews/**', (r) => {
    const url = new URL(r.request().url());
    if (/\/(rides|activities)\//.test(url.pathname))
      return r.fulfill({
        json: {
          ...base('ride', 'preview-ride', 'Shawmont Morning'),
          ride: {
            id: 'preview-ride',
            title: 'Shawmont Morning',
            startedAt: '2026-09-06T12:00:00Z',
            distanceM: 31800,
            elevationM: 524,
            durationS: 4860,
            rider: { username: 'tim', displayName: 'Tim Trail' },
            routePreview: geometry,
            privacy: { redactGps: true },
            media: [],
          },
        },
      });
    if (url.pathname.includes('/climbs/'))
      return r.fulfill({
        json: {
          ...base('climb', 'preview-climb', 'Shawmont Rise'),
          climb: {
            id: 'preview-climb',
            name: 'Shawmont Rise',
            region: 'Philadelphia, PA',
            lengthM: 620,
            elevGainM: 58,
            avgGradientPct: 9.4,
            routePreview: {
              ...geometry,
              source: 'canon_centerline',
              segments: [geometry.segments[0]],
              privacy: {},
            },
            elevationProfile: [
              { distanceM: 0, elevationM: 40 },
              { distanceM: 180, elevationM: 47 },
              { distanceM: 380, elevationM: 79 },
              { distanceM: 620, elevationM: 98 },
            ],
            recordBoard: {
              entries: Array.from({ length: 10 }, (_, i) => ({
                rank: i + 1,
                bestTimeSeconds: 251 + i * 11,
                avgPowerW: 400 - i * 9,
                rider:
                  i === 3
                    ? { identityHidden: true, displayLabel: 'Rider 4' }
                    : {
                        username: `rider${i}`,
                        displayName: `Public Rider ${i + 1}`,
                      },
              })),
              rowLimit: 10,
              hiddenRows: 0,
            },
          },
        },
      });
    const privateProfile = url.pathname.endsWith('/private');
    return r.fulfill({
      json: {
        ...base(
          'rider',
          privateProfile ? 'private' : 'tim',
          privateProfile ? 'Private Rider' : 'Tim Trail',
        ),
        seo: {
          title: privateProfile ? 'Private Rider' : 'Tim Trail',
          robots: privateProfile ? 'noindex,nofollow' : 'index,follow',
        },
        rider: {
          displayName: privateProfile ? 'Private Rider' : 'Tim Trail',
          username: privateProfile ? 'private' : 'tim',
        },
        profile: privateProfile
          ? {}
          : {
              totalRides: 12,
              followerCount: 3,
              followingCount: 7,
              createdAt: '2024-05-01',
            },
        leaderboard: privateProfile
          ? null
          : {
              stats: {
                totalPositions: 2,
                top10Count: 2,
                komCount: 1,
                podiumCount: 1,
                totalVaultsCompleted: 2,
              },
              positions: [
                {
                  vaultId: 19,
                  vaultName: 'Shawmont Rise',
                  rank: 1,
                  bestTimeSeconds: 251,
                  isKom: true,
                  totalRiders: 14,
                },
                {
                  vaultId: 20,
                  vaultName: 'Wises Mill Road',
                  rank: 7,
                  bestTimeSeconds: 355,
                  isKom: false,
                  totalRiders: 22,
                },
              ],
            },
        recentRides: {
          isPublic: !privateProfile,
          rides: privateProfile
            ? []
            : [
                {
                  id: 'preview-ride',
                  title: 'Shawmont Morning',
                  startedAt: '2026-09-06T12:00:00Z',
                  distanceM: 31800,
                  elevationGainM: 524,
                  durationSec: 4860,
                },
              ],
          count: privateProfile ? 0 : 1,
        },
      },
    });
  });
}

test('stranger ride uses the page and one access door without unavailable slots', async ({
  page,
}) => {
  await previews(page);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const privateReads: string[] = [];
  page.on('request', (request) => {
    if (/\/(streams|gps|vaults|portfolio)(\/|\?|$)/.test(request.url()))
      privateReads.push(request.url());
  });
  await page.goto('/activities/preview-ride?from=share#ride');
  await expect(page.locator('.ride-page-card')).toContainText(
    'Shawmont Morning',
  );
  await expect(page.locator('.ride-page-stats')).toContainText('31.8');
  await expect(
    page.locator(
      '.ride-band, .ride-page-spine, .ride-page-summary, .ride-page-social, .ride-page-social-footer, .ride-page-climbs, .ride-page-ledger-right',
    ),
  ).toHaveCount(0);
  await expect(
    page.getByRole('button', { name: /^(Start|Finish)$/ }),
  ).toHaveCount(0);
  await expect(page.locator('main')).not.toContainText(/CAL|DUNG|—/);
  await page.getByRole('button', { name: 'Ride analysis Sign in' }).click();
  await expect(page).toHaveURL('/');
  await expect(page.locator('main.invite-gate')).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.public-page, .sign-in-dialog-overlay')).toHaveCount(0);
  await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Email', { exact: true })).toBeFocused();
  expect(
    await page.evaluate(() => sessionStorage.getItem('br_return_url')),
  ).toBe('/activities/preview-ride?from=share#ride');
  await page.keyboard.press('Escape');
  await expect(page.locator('main.invite-gate')).toBeVisible();
  for (let i = 0; i < 12; i += 1) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.activeElement?.closest('.public-page'))).toBeNull();
  }
  await page.goBack();
  await expect(page).toHaveURL('/activities/preview-ride?from=share#ride');
  await expect(page.getByRole('button', { name: 'Ride analysis Sign in' })).toBeVisible();
  expect(errors).toEqual([]);
  expect(privateReads).toEqual([]);
});

for (const width of [1440, 390])
  test(`public pages and door render at ${width}`, async ({ page }) => {
    test.setTimeout(90000);
    await previews(page);
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    const dir = process.env.BR_PUBLIC_PREVIEW_CAPTURE_DIR;
    if (dir) fs.mkdirSync(dir, { recursive: true });
    const capture = async (name: string) => {
      if (dir) {
        await page.evaluate(() => document.fonts.ready);
        await page.screenshot({
          path: path.join(dir, `${name}-${width}.png`),
          fullPage: true,
        });
      }
    };
    for (const [route, name, title] of [
      ['rides/preview-ride', 'ride', 'Shawmont Morning'],
      ['climbs/preview-climb', 'climb', 'Shawmont Rise'],
      ['riders/tim', 'rider', 'Tim Trail'],
      ['riders/private', 'private-rider', 'Private Rider'],
    ]) {
      await page.goto('/' + route);
      await expect(
        page.getByRole('heading', { name: title, exact: true }),
      ).toBeVisible();
      await expect(page.locator('main')).not.toContainText(/CAL|DUNG|—/);
      await expect(
        page.getByRole('button', { name: 'Sign in', exact: true }),
      ).toHaveCSS('color', 'rgb(85, 146, 226)');
      if (name === 'climb') {
        await expect(page.locator('.climb-map')).toHaveAttribute(
          'data-canon-ready',
          'true',
        );
        await expect(page.locator('.climb-result-row')).toHaveCount(10);
        await expect(page.locator('.climb-result-row').nth(9)).toBeVisible();
        await expect(
          page.getByText('Names use public profiles only.'),
        ).toBeVisible();
        await expect(page.getByText('Rider', { exact: true })).toBeVisible();
        await expect(
          page.getByText(/Your history|Your position|Local Legend/),
        ).toHaveCount(0);
      }
      if (name === 'private-rider') {
        await expect(
          page.getByText('Private profile', { exact: true }),
        ).toBeVisible();
        await expect(
          page.getByText('Sign in to request full profile access.'),
        ).toBeVisible();
        await expect(
          page.locator('.profile-ledger__trio, .profile-tabs, .profile-recent'),
        ).toHaveCount(0);
      }
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      if (name === 'ride')
        await expect(page.locator('.ride-map')).toHaveAttribute(
          'data-route-ready',
          'true',
        );
      await capture(name);
      if (name === 'rider') {
        await page.getByRole('tab', { name: 'Rides', exact: true }).click();
        await expect(
          page.getByRole('region', { name: 'Rides', exact: true }),
        ).toBeVisible();
        await page
          .getByRole('tab', { name: 'Rides', exact: true })
          .press('Home');
        await expect(page.getByRole('tab', { name: 'Overview' })).toBeFocused();
        await expect(
          page.getByRole('region', { name: 'Recent rides' }),
        ).toBeVisible();
      }
      if (name === 'ride') {
        await page
          .getByRole('button', { name: 'Sign in', exact: true })
          .click();
        await expect(page).toHaveURL('/');
        await expect(page.getByRole('dialog')).toHaveCount(0);
        await expect(page.locator('.public-page')).toHaveCount(0);
        const entry = page.locator('main.invite-gate');
        await expect(entry).toBeVisible();
        const box = await entry.boundingBox();
        expect(box!.width).toBe(width);
        await capture('ride-door');
        await page.keyboard.press('Escape');
      }
    }
    await page.goto('/unknown-public-path');
    await expect(page.getByLabel('Email', { exact: true })).toBeVisible();
    await expect(page.locator('.public-page')).toHaveCount(0);
  });

test('stranger projections omit missing metrics and revoke cached identities on focus', async ({
  page,
}) => {
  await previews(page);
  await page.route('**/public/previews/climbs/sparse', (r) =>
    r.fulfill({
      json: {
        ...base('climb', 'sparse', 'Sparse climb'),
        climb: {
          id: 'sparse',
          name: 'Sparse climb',
          recordBoard: {
            entries: [{ rank: 1, rider: { identityHidden: true } }],
            rowLimit: 10,
            hiddenRows: 0,
          },
        },
      },
    }),
  );
  await page.goto('/climbs/sparse');
  await expect(
    page.getByRole('heading', { name: 'Sparse climb' }),
  ).toBeVisible();
  await expect(
    page.locator(
      '.climb-summary > div, .climb-result-value, .climb-profile-hero',
    ),
  ).toHaveCount(0);
  await expect(page.locator('main')).not.toContainText(
    /—|CAL|DUNG|Profile unavailable/,
  );
  await page.route('**/public/previews/riders/sparse*', (r) =>
    r.fulfill({
      json: {
        ...base('rider', 'sparse', 'Sparse rider'),
        rider: { displayName: 'Sparse rider' },
        profile: {},
        recentRides: {
          isPublic: true,
          rides: [{ id: 'undated', title: 'Undated ride' }],
          count: 1,
        },
      },
    }),
  );
  await page.goto('/riders/sparse');
  await expect(
    page.getByRole('heading', { name: 'Sparse rider' }),
  ).toBeVisible();
  await expect(page.locator('main')).not.toContainText(/—|CAL|DUNG/);
  await page.goto('/riders/tim');
  await expect(page.getByRole('heading', { name: 'Tim Trail' })).toBeVisible();
  let revoked = 0;
  await page.route('**/public/previews/riders/tim*', (r) => {
    revoked++;
    return r.fulfill({ status: 404, json: { detail: 'Preview unavailable' } });
  });
  // Headless Chromium keeps background tabs visible; send the browser visibility
  // lifecycle explicitly to React Query's unchanged focus listener.
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'hidden',
    });
    window.dispatchEvent(new Event('visibilitychange'));
  });
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'visible',
    });
    window.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(
    page.getByText('Preview unavailable', { exact: true }),
  ).toBeVisible();
  expect(revoked).toBeGreaterThan(0);
  await expect(page.getByRole('heading', { name: 'Tim Trail' })).toHaveCount(0);
});

// Preserve the door-time write, including query and fragment, across entry and Back.
test('public preview return URL survives navigating to entry and back', async ({ page }) => {
  await previews(page);
  const destination = '/rides/preview-ride?from=share&view=route#ride';
  await page.goto(destination);
  await expect(page.locator('.ride-page-card')).toContainText('Shawmont Morning');
  await page.evaluate(() => sessionStorage.setItem('br_return_url', '/climbs/previous'));
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page).toHaveURL('/');
    await expect(page.locator('main.invite-gate')).toBeVisible();
    await expect(page.locator('.public-page, [role="dialog"]')).toHaveCount(0);
    await expect(page.getByLabel('Email', { exact: true })).toBeFocused();
    expect(await page.evaluate(() => sessionStorage.getItem('br_return_url'))).toBe(destination);
    await page.goBack();
    await expect(page).toHaveURL(destination);
    await expect(page.locator('.ride-page-card')).toContainText('Shawmont Morning');
    expect(await page.evaluate(() => sessionStorage.getItem('br_return_url'))).toBe(destination);
  }
});
