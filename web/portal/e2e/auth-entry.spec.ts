import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

// These renders exercise portal components with local API/provider contracts.
// They are never physical-device, delivered-email, or live-auth evidence.
async function captureAccessRendering(page: Page, state: string) {
  const captureDir = process.env.BR_CAPTURE_NIGHT_LEDGER_ACCESS_DIR;
  if (!captureDir) return;
  const originalViewport = page.viewportSize();
  const originalFontSize = await page.evaluate(() => document.documentElement.style.fontSize);
  fs.mkdirSync(captureDir, { recursive: true });
  await page.evaluate(() => document.fonts.ready);
  for (const [width, height, textScale] of [[1440, 1000, 1], [390, 844, 1], [320, 720, 1], [320, 720, 2]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate((scale) => { document.documentElement.style.fontSize = `${16 * scale}px`; }, textScale);
    const problems = await page.locator('.access-gate').evaluate((root) => {
      const failures: string[] = [];
      if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1) failures.push('horizontal page overflow');
      for (const control of root.querySelectorAll('button, a, input')) {
        const rect = control.getBoundingClientRect();
        if (!rect.width || !rect.height) continue;
        const minimum = control.matches('.auth-entry-row, .auth-entry-action') ? 52 : 44;
        if (rect.height < minimum || rect.width < 44) failures.push(`undersized ${control.textContent || control.getAttribute('id')}`);
      }
      for (const element of root.querySelectorAll('h1, label, .auth-entry-row, .auth-entry-action, .auth-entry-footer, .auth-surface-notice__body')) {
        const rect = element.getBoundingClientRect();
        if (!rect.width || !rect.height) continue;
        const style = getComputedStyle(element);
        if (parseFloat(style.fontSize) < 12) failures.push(`small text: ${element.textContent}`);
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          if (!walker.currentNode.textContent?.trim()) continue;
          const range = document.createRange();
          range.selectNodeContents(walker.currentNode);
          for (const textRect of range.getClientRects()) {
            if (textRect.right > rect.right + 1 || textRect.left < rect.left - 1) failures.push(`text outside row: ${element.textContent}`);
            // Glyph metrics may extend beyond a heading's line box. They are
            // clipped only when an ancestor actually clips that painted area.
            for (let ancestor: Element | null = element; ancestor && root.contains(ancestor); ancestor = ancestor.parentElement) {
              const box = ancestor.getBoundingClientRect();
              if (['hidden', 'clip'].includes(getComputedStyle(ancestor).overflowY)
                && (textRect.bottom > box.bottom + 1 || textRect.top < box.top - 1)) failures.push(`clipped text: ${element.textContent}`);
            }
          }
        }
      }
      for (const field of root.querySelectorAll('[aria-invalid="true"]')) {
        const ids = field.getAttribute('aria-describedby')?.split(/\s+/) ?? [];
        if (!ids.length || ids.some((id) => !document.getElementById(id)?.textContent?.trim())) failures.push('invalid field missing contextual description');
      }
      return failures;
    });
    expect(problems, `${state}: ${width}px at ${textScale * 100}% text`).toEqual([]);
    await page.screenshot({ path: path.join(captureDir, `${state}-${width}-${textScale * 100}-local.png`), fullPage: textScale > 1, animations: 'disabled' });
  }
  await page.evaluate((size) => { document.documentElement.style.fontSize = size; }, originalFontSize);
  if (originalViewport) await page.setViewportSize(originalViewport);
}

const FIRST_HOME_ACTIVITY = {
  id: 'ride-umbria-repeats',
  type: 'ride',
  title: 'Umbria Street repeats',
  created_at: '2026-07-13T13:30:00Z',
  occurred_at: '2026-07-13T13:30:00Z',
  user: {
    id: 'philly-rider-2',
    username: 'maya_rides',
    display_name: 'Maya Chen',
    avatar_url: null,
  },
  target: { type: 'ride', id: 'ride-umbria-repeats' },
  metadata: {
    distance_m: 31_200,
    elevation_m: 640,
    duration_s: 5_410,
    kudos_count: 7,
    comment_count: 2,
  },
};

async function routeUnauthenticatedBootstrap(
  page: Page,
  options: { inviteRequired?: boolean; inviteValidated?: boolean; feedActivities?: unknown[] } = {},
) {
  const authState = {
    authenticated: false,
    invite_required: options.inviteRequired ?? true,
    invite_validated: options.inviteValidated ?? false,
    needs_profile_setup: false,
    auth_method_hint: null,
    user: null,
  };

  await page.route('**/auth/bootstrap', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(authState),
    });
  });

  await page.route('**/auth/onboarding/state', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(authState),
    });
  });

  await page.route('**/feed/global**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contractVersion: 'feed.v1',
        activities: options.feedActivities ?? [],
        has_more: false,
        next_cursor: null,
      }),
    });
  });

  await page.route('**/feed/home**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contractVersion: 'home_feed.v1',
        feed: {
          contractVersion: 'feed.v1',
          activities: options.feedActivities ?? [],
          has_more: false,
          next_cursor: null,
        },
        sidecars: {},
      }),
    });
  });
}

async function routeAuthenticatedBootstrap(
  page: Page,
  options: {
    authMethodHint?: 'wallet' | 'privy';
    displayName?: string | null;
    needsProfileSetup?: boolean;
    username?: string | null;
  } = {},
) {
  const username = options.username === undefined ? 'placeholder-rider' : options.username;
  const displayName = options.displayName === undefined ? 'Setup Rider' : options.displayName;
  const authState = {
    authenticated: true,
    invite_required: false,
    invite_validated: true,
    needs_profile_setup: options.needsProfileSetup ?? false,
    auth_method_hint: options.authMethodHint ?? 'wallet',
    user: {
      id: 'setup-user-1',
      wallet: '11111111111111111111111111111111',
      username,
      display_name: displayName,
      beetle_number: 1542,
      weight_kg: null,
      avatar_url: null,
    },
  };

  await page.route('**/*', async (route) => {
    if (!['fetch', 'xhr'].includes(route.request().resourceType())) {
      await route.continue();
      return;
    }

    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, '') || '/';
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (path === '/auth/bootstrap' || path === '/auth/onboarding/state') {
      await json(authState);
      return;
    }

    if (path === '/users/me' || path === '/me') {
      await json(authState.user);
      return;
    }

    if (path === '/auth/refresh') {
      await json({ access_token: 'fixture-token' });
      return;
    }

    if (path === '/feed/home') {
      await json({
        contractVersion: 'feed_home.v1',
        scope: 'global',
        viewer: {
          authenticated: true,
          userId: authState.user.id,
          wallet: authState.user.wallet,
        },
        feed: {
          contractVersion: 'feed.v1',
          activities: [],
          hasMore: false,
          nextCursor: null,
        },
        suggestedRiders: [],
        popularClimbs: [],
        achievements: [],
        socialCounts: { followerCount: 0, followingCount: 0 },
        notifications: { unreadCount: 0 },
      });
      return;
    }

    if (path === '/feed/global' || path === '/feed') {
      await json({ contractVersion: 'feed.v1', activities: [], has_more: false, next_cursor: null });
      return;
    }

    await json({ detail: 'not found' }, 404);
  });
}

async function routeFirstRunOnboarding(
  page: Page,
  options: {
    deferHomeFeed?: boolean;
    homeActivities?: unknown[];
    omitTotalRides?: boolean;
    profileRefreshFailures?: number;
    profileSaveError?: string;
  } = {},
) {
  let profileSaved = false;
  let profilePayload: Record<string, unknown> | null = null;
  let stravaAuthUrlRequests = 0;
  let remainingProfileRefreshFailures = options.profileRefreshFailures ?? 0;
  let releaseHomeFeed = () => {};
  const homeFeedGate = new Promise<void>((resolve) => {
    releaseHomeFeed = resolve;
  });

  const currentUser = () => ({
    id: 'first-run-user-1',
    wallet: '11111111111111111111111111111111',
    username: typeof profilePayload?.username === 'string' ? profilePayload.username : null,
    display_name: typeof profilePayload?.username === 'string' ? profilePayload.username : null,
    beetle_number: 1542,
    weight_kg: null,
    avatar_url: null,
    ...(options.omitTotalRides ? {} : { total_rides: 0 }),
  });

  const bootstrap = () => ({
    authenticated: true,
    invite_required: false,
    invite_validated: true,
    needs_profile_setup: !profileSaved,
    auth_method_hint: 'privy',
    user: currentUser(),
  });

  await page.route('**/*', async (route) => {
    if (!['fetch', 'xhr'].includes(route.request().resourceType())) {
      await route.continue();
      return;
    }

    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, '') || '/';
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (path === '/auth/bootstrap' || path === '/auth/onboarding/state') {
      if (profileSaved && remainingProfileRefreshFailures > 0) {
        remainingProfileRefreshFailures -= 1;
        await json({ detail: 'temporary bootstrap failure' }, 503);
        return;
      }
      await json(bootstrap());
      return;
    }

    if (path === '/users/me' && route.request().method() === 'PUT') {
      profilePayload = JSON.parse(route.request().postData() || '{}') as Record<string, unknown>;
      if (options.profileSaveError) {
        await json({ detail: options.profileSaveError }, 400);
        return;
      }
      profileSaved = true;
      await json(currentUser());
      return;
    }

    if (path === '/strava/auth/url') {
      stravaAuthUrlRequests += 1;
      await json({ detail: 'Strava is unavailable' }, 503);
      return;
    }

    if (path === '/vaults') {
      await json({
        vaults: [
          {
            id: 11,
            signatureHex: 'manayunk-wall-signature',
            name: 'Manayunk Wall',
            vertM: 72,
            distanceM: 750,
            avgGradientPct: 9.6,
            totalCompletions: 184,
            totalStaked: 3240,
            komHolder: '22222222222222222222222222222222',
            komTimeS: 123,
            minter: '33333333333333333333333333333333',
            onChainActive: true,
          },
          {
            id: 12,
            signatureHex: 'leverington-signature',
            name: 'Leverington Avenue',
            vertM: 54,
            distanceM: 620,
            avgGradientPct: 8.7,
            totalCompletions: 96,
            totalStaked: 1780,
            komHolder: '44444444444444444444444444444444',
            komTimeS: 109,
            minter: '33333333333333333333333333333333',
            onChainActive: true,
          },
          {
            id: 13,
            signatureHex: 'wigard-signature',
            name: 'Wigard Avenue',
            vertM: 63,
            distanceM: 810,
            avgGradientPct: 7.8,
            totalCompletions: 71,
            totalStaked: 940,
            komHolder: null,
            komTimeS: 0,
            minter: '33333333333333333333333333333333',
            onChainActive: true,
          },
        ],
        total: 3,
        offset: 0,
        limit: 50,
      });
      return;
    }

    if (path === '/vaults/my/stakes') {
      await json({ stakes: [] });
      return;
    }

    if (path === '/portfolio') {
      await json({
        contractVersion: 'portfolio.v5',
        dungBalance: '0',
        dungBalanceBaseUnits: '0',
        walletDung: {
          amount: '0',
          amountBaseUnits: '0',
          source: 'spl_wallet_ata',
          status: 'not_initialized',
          tokenAccount: 'wallet-dung-ata',
          slot: 1,
        },
        balanceDung: {
          amount: '0',
          amountBaseUnits: '0',
          source: 'rider_balance_token_pda',
          status: 'not_initialized',
          tokenAccount: 'balance-dung-pda',
          slot: 1,
        },
        calBalance: '0',
        calBalanceBaseUnits: '0',
        stakedPositions: [],
        pendingClaims: [],
      });
      return;
    }

    if (path === '/notifications') {
      await json({ notifications: [], unreadCount: 0 });
      return;
    }

    if (path === '/admin/check') {
      await json({ isAdmin: false, role: null });
      return;
    }

    if (path === '/users/me' || path === '/me') {
      await json(currentUser());
      return;
    }

    if (path === '/auth/refresh') {
      await json({ access_token: 'fixture-token' });
      return;
    }

    if (path === '/feed/home') {
      if (options.deferHomeFeed) {
        await homeFeedGate;
      }
      const rider = currentUser();
      await json({
        contractVersion: 'feed_home.v1',
        scope: 'global',
        viewer: {
          authenticated: true,
          userId: rider.id,
          wallet: rider.wallet,
        },
        feed: {
          contractVersion: 'feed.v1',
          activities: options.homeActivities ?? [],
          hasMore: false,
          nextCursor: null,
        },
        suggestedRiders: [],
        popularClimbs: [],
        achievements: [],
        socialCounts: { followerCount: 0, followingCount: 0 },
        notifications: { unreadCount: 0 },
      });
      return;
    }

    if (path === '/feed/global' || path === '/feed') {
      await json({ contractVersion: 'feed.v1', activities: [], has_more: false, next_cursor: null });
      return;
    }

    await json({ detail: 'not found' }, 404);
  });

  return {
    getProfilePayload: () => profilePayload,
    getStravaAuthUrlRequests: () => stravaAuthUrlRequests,
    releaseHomeFeed,
  };
}

async function routeAuthenticatedVaultView(page: Page) {
  const authState = {
    authenticated: true,
    invite_required: false,
    invite_validated: true,
    needs_profile_setup: false,
    auth_method_hint: 'wallet',
    user: {
      id: 'vault-user-1',
      wallet: '11111111111111111111111111111111',
      username: 'vault-rider',
      display_name: 'Vault Rider',
      beetle_number: 1542,
      weight_kg: null,
      avatar_url: null,
    },
  };

  await page.route('**/*', async (route) => {
    if (!['fetch', 'xhr'].includes(route.request().resourceType())) {
      await route.continue();
      return;
    }

    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api/, '') || '/';
    const json = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (path === '/auth/bootstrap' || path === '/auth/onboarding/state') {
      await json(authState);
      return;
    }

    if (path === '/users/me' || path === '/me') {
      await json(authState.user);
      return;
    }

    if (path === '/auth/refresh') {
      await json({ access_token: 'fixture-token' });
      return;
    }

    if (path === '/vaults/42/leaderboard') {
      await json({
        contractVersion: 'client.v1',
        truthSource: 'attested',
        climbId: 'climb-42',
        climbName: 'Flagstaff Climb',
        vaultId: 42,
        leaderboard: [],
        entries: [],
        komHolder: null,
        komTimeS: null,
      });
      return;
    }

    if (path === '/climbs/climb-42') {
      await json({
        contractVersion: 'client.v1',
        truthSource: 'attested',
        id: 'climb-42',
        name: 'Flagstaff Climb',
        region: 'Boulder, CO',
        lengthM: 4800,
        elevGainM: 312,
        avgGradientPct: 6.5,
        hasVault: true,
        vaultId: 42,
        vaultEconomy: {
          contractVersion: 'client.v1',
          truthSource: 'attested',
          hasVault: true,
          vaultId: 42,
          vaultSignature: 'vault-signature-42',
          totalStaked: '2400',
          totalStakedBaseUnits: '2400000000000',
          totalCalStaked: '2400',
          totalCalStakedBaseUnits: '2400000000000',
          totalCompletions: 18,
        },
      });
      return;
    }

    if (path === '/climbs/climb-42/leaderboard') {
      await json({
        contractVersion: 'client.v1',
        truthSource: 'attested',
        climbId: 'climb-42',
        climbName: 'Flagstaff Climb',
        vaultId: 42,
        leaderboard: [
          {
            rank: 1,
            wallet: '22222222222222222222222222222222',
            displayName: 'Fast Rider',
            bestTimeSeconds: 1120,
            avgPowerW: 318,
          },
        ],
        entries: [
          {
            rank: 1,
            wallet: '22222222222222222222222222222222',
            displayName: 'Fast Rider',
            bestTimeSeconds: 1120,
            avgPowerW: 318,
          },
        ],
        komHolder: '22222222222222222222222222222222',
        komTimeS: 1120,
      });
      return;
    }

    if (path === '/vaults/42') {
      await json({
        id: 42,
        signatureHex: 'vault-signature-42',
        signatureHashHex: 'vault-hash-42',
        name: 'Flagstaff Climb',
        vertM: 312,
        distanceM: 4800,
        avgGradientPct: 6.5,
        totalCompletions: 18,
        totalStaked: '2400',
        totalStakedBaseUnits: '2400000000000',
        totalCalStaked: '2400',
        totalCalStakedBaseUnits: '2400000000000',
        komHolder: '22222222222222222222222222222222',
        komTimeS: 1120,
        minter: '33333333333333333333333333333333',
        onChainActive: true,
        leaderboard: [
          {
            rank: 1,
            wallet: '22222222222222222222222222222222',
            displayName: 'Fast Rider',
            bestTimeSeconds: 1120,
            avgPowerW: 318,
          },
        ],
        totalLpTokens: 2400,
        localLegend: null,
      });
      return;
    }

    if (path === '/vaults/my/stakes') {
      await json({ stakes: [] });
      return;
    }

    if (path === '/portfolio') {
      await json({
        contractVersion: 'portfolio.v5',
        dungBalance: '0',
        dungBalanceBaseUnits: '0',
        walletDung: {
          amount: '0',
          amountBaseUnits: '0',
          source: 'spl_wallet_ata',
          status: 'not_initialized',
          tokenAccount: 'wallet-dung-ata',
          slot: 1,
        },
        balanceDung: {
          amount: '0',
          amountBaseUnits: '0',
          source: 'rider_balance_token_pda',
          status: 'not_initialized',
          tokenAccount: 'balance-dung-pda',
          slot: 1,
        },
        calBalance: '1200',
        calBalanceBaseUnits: '1200000000000',
        stakedPositions: [],
        pendingClaims: [],
      });
      return;
    }

    if (path === '/vaults/42/my-completions') {
      await json({
        vaultId: 42,
        vaultName: 'Flagstaff Climb',
        efforts: [],
        totalCount: 0,
        bestTimeSeconds: null,
        totalPrs: 0,
      });
      return;
    }

    if (path === '/feed/global' || path === '/feed') {
      await json({ contractVersion: 'feed.v1', activities: [], has_more: false, next_cursor: null });
      return;
    }

    await json({ detail: 'not found' }, 404);
  });
}

function accessPanel(page: Page) {
  return page.locator('.access-panel');
}

test.describe('Auth Entry Flow', () => {
  test('Night Ledger combines email and invite before requesting a code', async ({ page }) => {
    test.setTimeout(90_000);
    await routeUnauthenticatedBootstrap(page);
    await page.addInitScript(() => {
      (window as Window & { __accessCodeRequests?: unknown[] }).__accessCodeRequests = [];
      window.addEventListener('br:e2e:privy-email-code-requested', (event) => {
        (window as Window & { __accessCodeRequests?: unknown[] }).__accessCodeRequests?.push((event as CustomEvent).detail);
      });
    });
    let inviteCalls = 0;
    await page.route('**/auth/invite/validate', async (route) => {
      inviteCalls++;
      await route.fulfill({ json: { valid: inviteCalls > 1, message: 'invite_invalid', code_id: null } });
    });
    await page.goto('/');
    await expect(page.getByLabel('Email')).toHaveAttribute('autocomplete', 'username');
    await captureAccessRendering(page, 'sign-in');
    await page.getByLabel('Email').fill('rider@example.com');
    await page.getByLabel('Email').press('Tab');
    await expect(page.getByRole('button', { name: 'Send code', exact: true })).toBeFocused();
    await expect(page.getByRole('button', { name: 'Send code', exact: true })).toHaveCSS('outline-style', 'solid');
    await page.getByRole('button', { name: 'Enter invite code' }).click();
    await expect(page.getByLabel('Email', { exact: true })).toHaveValue('rider@example.com');
    await captureAccessRendering(page, 'invite-email');
    await page.getByRole('textbox', { name: 'Invite code', exact: true }).fill('alpha-rider-42');
    await page.getByRole('textbox', { name: 'Invite code', exact: true }).press('Enter');
    await expect(page.getByRole('alert')).toBeVisible();
    await captureAccessRendering(page, 'invite-invalid');
    expect(await page.evaluate(() => (window as Window & { __accessCodeRequests?: unknown[] }).__accessCodeRequests)).toEqual([]);
    await page.getByRole('button', { name: 'Send code', exact: true }).click();
    await expect(page.getByLabel('Code', { exact: true })).toBeVisible();
    await expect(page.getByText('rider@example.com', { exact: true })).toBeVisible();
    expect(inviteCalls).toBe(2);
    expect(await page.evaluate(() => (window as Window & { __accessCodeRequests?: unknown[] }).__accessCodeRequests)).toEqual([{ email: 'rider@example.com' }]);
    const code = page.getByLabel('Code', { exact: true });
    await expect(code).toHaveAttribute('autocomplete', 'one-time-code');
    await expect(code).toBeFocused();
    await captureAccessRendering(page, 'verification-code');
    await code.press('Enter');
    await expect(page.getByRole('alert')).toHaveText('Enter the code.');
    await expect(code).toHaveAttribute('aria-describedby', 'social-login-error');
    await captureAccessRendering(page, 'verification-missing-code');
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.evaluate(() => navigator.clipboard.writeText('123456'));
    await code.press(process.platform === 'darwin' ? 'Meta+V' : 'Control+V');
    await expect(code).toHaveValue('123456');
    await page.getByRole('button', { name: 'Send code', exact: true }).click();
    await expect(code).toHaveValue('');
    await expect.poll(() => page.evaluate(() => (window as Window & { __accessCodeRequests?: unknown[] }).__accessCodeRequests?.length)).toBe(2);
    await page.getByRole('button', { name: 'Change email' }).click();
    await expect(page.getByLabel('Email')).toHaveValue('rider@example.com');
    await expect(page.getByText('Invite accepted', { exact: true })).toBeVisible();
    await captureAccessRendering(page, 'invite-accepted');
    await page.getByLabel('Email').fill('changed@example.com');
    await page.getByLabel('Email').press('Enter');
    await expect(code).toBeVisible();
    await expect(page.getByText('changed@example.com', { exact: true })).toBeVisible();
    await expect.poll(() => page.evaluate(() => (window as Window & { __accessCodeRequests?: unknown[] }).__accessCodeRequests?.length)).toBe(3);
  });

  for (const target of ['https://foreign.example/rides/1?from=share#ride', '//foreign.example/rides/1', '/\\foreign.example/rides/1', 'javascript:alert(1)']) {
    test(`rejects foreign-origin stored return intent: ${target}`, async ({ page }) => {
      await routeAuthenticatedBootstrap(page);
      await page.addInitScript((destination) => sessionStorage.setItem('br_return_url', destination), target);
      await page.goto('/');
      await expect.poll(() => page.evaluate(() => sessionStorage.getItem('br_return_url'))).toBeNull();
      await expect(page).toHaveURL('/');
      await expect(page.locator('.portal-shell')).toBeVisible();
    });
  }

  for (const width of [1440, 390])
  test(`mounts public ride links for unauthenticated viewers and returns after full-page entry at ${width}`, async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    let authenticated = false;
    const objectReads: boolean[] = [];
    const user = { id: 'entry-rider', wallet: 'e2ePrivyWallet11111111111111111111111111111', username: 'entry-rider', display_name: 'Entry Rider', beetle_number: 1542 };
    const captureLane = async (state: string) => {
      const dir = process.env.BR_LANE_D_CAPTURE_DIR;
      if (!dir) return;
      fs.mkdirSync(dir, { recursive: true });
      await page.evaluate(() => document.fonts.ready);
      await expect(page.locator('.ledger-slot')).toHaveCount(0);
      await expect(page.locator('.shell-live-rule[data-live="true"]')).toHaveCount(0);
      await page.screenshot({ path: path.join(dir, `${state}-${width}.png`), fullPage: true, animations: 'disabled' });
    };
    const captureDir = process.env.BR_CAPTURE_EYEBROW_REVIEW_DIR;
    await page.route('**/*', async (route) => {
      if (!['fetch', 'xhr'].includes(route.request().resourceType())) {
        await route.continue();
        return;
      }

      const url = new URL(route.request().url());
      const path = url.pathname.replace(/^\/api/, '') || '/';
      const json = (body: unknown, status = 200) => route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });

      if (path === '/auth/privy/verify') {
        authenticated = true;
        await json({ user_id: user.id, wallet: user.wallet, access_token: 'e2e-access-token', access_expires_at: '2099-01-01T00:00:00Z', refresh_token: 'e2e-refresh-token', refresh_expires_at: '2099-01-02T00:00:00Z' });
        return;
      }
      if (path === '/users/me' || path === '/me') {
        await json(user);
        return;
      }
      if (path === '/auth/bootstrap' || path === '/auth/onboarding/state') {
        await json({
          authenticated,
          invite_required: true,
          invite_validated: authenticated,
          needs_profile_setup: false,
          auth_method_hint: authenticated ? 'privy' : null,
          user: authenticated ? user : null,
        });
        return;
      }

      if (path === '/feed/global') {
        await json({
          contractVersion: 'feed.v1',
          activities: [],
          has_more: false,
          next_cursor: null,
        });
        return;
      }

      if (path === '/public/previews/rides/public-ride-1') {
        await json({
          contractVersion: 'public_preview.v1',
          objectType: 'ride',
          id: 'public-ride-1',
          canonicalPath: '/rides/public-ride-1',
          compatPaths: ['/activities/public-ride-1'],
          title: 'Public Share Ride',
          previewPolicy: {
            mode: 'public_preview',
            objectType: 'ride',
            rawGpsAvailable: false,
            streamsAvailable: false,
            tilesAvailable: false,
            privateRideHistoryAvailable: false,
            unreviewedProjectionsAvailable: false,
            walletRequired: false,
            loginRequiredFor: ['full_detail', 'upload_ride'],
            blockedSurfaces: ['raw_gps', 'streams', 'tiles', 'private_ride_history'],
            privacy: {
              visibility: 'public',
              canView: true,
              isOwner: false,
              redactGps: true,
              reason: 'public',
            },
          },
          seo: {
            title: 'Public Share Ride · Ride · Boulder Roller',
            description: 'Public ride preview on Boulder Roller.',
            canonicalPath: '/rides/public-ride-1',
            robots: 'index,follow',
            openGraph: {
              type: 'ride',
              image: {
                kind: 'public_preview_card',
                url: null,
                alt: 'Public Share Ride',
              },
            },
          },
          assets: {
            contractVersion: 'public_preview.v1',
            objectType: 'ride',
            openGraphImage: {
              kind: 'public_preview_card',
              status: 'available',
              alt: 'Public Share Ride',
            },
            routePreview: {
              kind: 'redacted_route_preview',
              preview: {
                contractVersion: 'route_preview.v1',
                source: 'fixture',
                points: [],
                pointCount: 0,
                bounds: null,
                placeLabel: 'Public preview',
                fallbackReason: 'privacy_redacted',
                privacy: { redactedGps: true },
              },
            },
          },
          ride: {
            id: 'public-ride-1',
            title: 'Public Share Ride',
            status: 'completed',
            startedAt: '2026-05-14T12:00:00Z',
            createdAt: '2026-05-14T12:00:00Z',
            distanceM: 42195,
            elevationM: 540,
            durationS: 5400,
            visibility: 'public',
            attestationStatus: 'attested',
            privacy: {
              visibility: 'public',
              canView: true,
              isOwner: false,
              redactGps: true,
              reason: 'public',
            },
            routePreview: {
              contractVersion: 'route_preview.v1',
              source: 'fixture',
              points: [],
              pointCount: 0,
              bounds: null,
              placeLabel: 'Public preview',
              fallbackReason: 'privacy_redacted',
              privacy: { redactedGps: true },
            },
            rider: {
              contractVersion: 'public_rider_ref.v1',
              id: 'public-rider-1',
              username: 'public-rider',
              displayName: 'Public Rider',
              displayLabel: 'Public Rider',
              identityHidden: false,
            },
          },
          freshness: {
            source: 'backend',
            loadedAt: '2026-05-14T12:30:00Z',
            cacheTtlSeconds: 120,
          },
        });
        return;
      }

      if (path === '/rides/public-ride-1') {
        objectReads.push(authenticated);
        await json({
          contract_version: 'client.v1',
          truth_source: 'backend',
          id: 'public-ride-1',
          rider_id: 'public-rider-1',
          title: 'Public Share Ride revalidated',
          started_at: '2026-05-14T12:00:00Z',
          distance_m: 42195,
          elevation_m: 540,
          duration_s: 5400,
          tss: 86,
          visibility: 'public',
          is_owner: false,
          privacy: {
            visibility: 'public',
            can_view: true,
            is_owner: false,
            is_follower: false,
            redact_gps: true,
            protocol_public: false,
            protocol_public_fields: [],
            reason: 'public',
          },
          media: [],
        });
        return;
      }

      if (path === '/rides/public-ride-1/status') {
        await json({
          contract_version: 'client.v1',
          truth_source: 'backend',
          ride_id: 'public-ride-1',
          status: 'completed',
          error_message: null,
          attestation_status: 'attested',
          has_gps: true,
          has_patterns: false,
          has_leaderboards: false,
          has_achievements: false,
        });
        return;
      }

      if (path === '/rides/public-ride-1/gps') {
        await json({ gps_points: [] });
        return;
      }

      if (path === '/rides/public-ride-1/patterns') {
        await json({
          ride_id: 'public-ride-1',
          patterns: { climb_patterns: [], steady_pattern: null, exploration_pattern: null },
          summary: 'No climbs found',
          total_patterns: 0,
        });
        return;
      }

      if (path === '/rides/public-ride-1/tiles') {
        await json({ ride_id: 'public-ride-1', tile_samples: [], total_samples: 0, unique_tiles: 0, redacted: true });
        return;
      }

      if (path.startsWith('/rides/public-ride-1/streams')) {
        await json({ timestamps: [], values: [], sample_count: 0, min_value: null, max_value: null, avg_value: null });
        return;
      }

      if (path === '/rides/public-ride-1/interactions') {
        await json({ kudos_count: 0, comments_count: 0, viewer_has_kudos: false, viewer_reported: false, comments_enabled: true });
        return;
      }

      await json({ detail: 'not found' }, 404);
    });

    if (captureDir) {
      await page.setViewportSize({ width: 1440, height: 1000 });
    }
    await page.goto('/rides/public-ride-1?from=share#ride');

    await expect(page.getByRole('button', { name: 'Enter invite', exact: true })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Public Share Ride' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Ride analysis Sign in' })).toBeVisible();
    await expect(page.getByText('Please connect your wallet')).toHaveCount(0);
    await expect(page.locator('.public-preview-hero__object')).toHaveCount(0);
    await expect(page.locator('.ride-page-card-head')).toBeVisible();

    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.waitForTimeout(800);
      await page.screenshot({
        path: path.join(captureDir, 'public-preview-ride-desktop-1440x1000.png'),
        fullPage: true,
        animations: 'disabled',
      });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByRole('heading', { name: 'Public Share Ride' })).toBeVisible();
      await expect(page.locator('.ride-page-card-head')).toBeVisible();
      await page.waitForTimeout(800);
      await page.screenshot({
        path: path.join(captureDir, 'public-preview-ride-mobile-390x844.png'),
        fullPage: true,
        animations: 'disabled',
      });
    }
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await captureLane('public-ride');
    expect(objectReads).toEqual([]);
    await page.getByRole('button', { name: 'Ride analysis Sign in' }).click();
    await expect(page).toHaveURL('/');
    await expect(page.locator('main.invite-gate')).toBeVisible();
    await expect(page.locator('.public-page, .sign-in-dialog-overlay, [role="dialog"]')).toHaveCount(0);
    await expect(page.getByLabel('Email', { exact: true })).toBeFocused();
    expect(await page.evaluate(() => sessionStorage.getItem('br_return_url'))).toBe('/rides/public-ride-1?from=share#ride');
    await captureLane('entry');
    await page.getByLabel('Email', { exact: true }).fill('rider@example.com');
    await page.getByRole('button', { name: 'Send code', exact: true }).click();
    await page.getByLabel('Code', { exact: true }).fill('123456');
    await page.getByRole('button', { name: 'Verify code', exact: true }).click();
    await expect(page).toHaveURL('/rides/public-ride-1?from=share#ride');
    await expect(page.getByRole('heading', { name: 'Public Share Ride revalidated', exact: true })).toBeVisible();
    expect(objectReads.length).toBeGreaterThan(0);
    expect(objectReads.every(Boolean)).toBe(true);
    expect(await page.evaluate(() => sessionStorage.getItem('br_return_url'))).toBeNull();
    await expect(page.locator('.public-page, main.invite-gate')).toHaveCount(0);
    await captureLane('return');
  });

  test('renders the direct email form before provider runtime is requested', async ({ page }) => {
    const runtimeRequests: string[] = [];

    page.on('request', (request) => {
      const url = request.url();
      if (
        url.includes('AuthRuntimeProviders')
        || url.includes('PrivyContext')
        || url.includes('WalletContext')
        || url.includes('@privy-io')
        || url.includes('wallet-adapter')
      ) {
        runtimeRequests.push(url);
      }
    });

    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Use wallet instead' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Enter invite code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Request access' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Continue with email' })).toHaveCount(0);
    await page.waitForTimeout(250);

    expect(runtimeRequests, 'auth runtime requests before sign-in intent').toEqual([]);
  });

  test('renders one quiet direct-email shell', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'entry');
    await expect(accessPanel(page)).not.toHaveAttribute('aria-modal', 'true');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Enter invite', exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Use wallet instead' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Enter invite code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Request access' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Continue with email' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Public site' })).toHaveCount(0);
    await expect(page.getByText('BoulderScan')).toHaveCount(0);
    await expect(page.getByText('APP ENTRY')).toHaveCount(0);
    await expect(page.getByText('Alpha access')).toHaveCount(0);
    await expect(page.locator('.access-entry-page')).toHaveAttribute('data-public-meta-shape', 'app-entry');
    await expect(page.locator('.access-entry-page')).toHaveClass(/access-entry-page--app-threshold/);
    await expect(page.locator('.access-entry-page__brand-mark')).toHaveCount(0);
    await expect(page.locator('.access-entry-page__visual')).toHaveCount(0);
    await expect(page.locator('.access-entry-route')).toHaveCount(0);
    await expect(page.locator('.access-entry-board')).toHaveCount(0);
    await expect(page.locator('.access-entry-receipt')).toHaveCount(0);
    await expect(page.getByText('87 more riders after sign-in')).toHaveCount(0);
    await expect(page.getByText('Manayunk Wall')).toHaveCount(0);
    await expect(page.getByText('Record rides. Match climbs. See what counted.')).toHaveCount(0);
    await expect(page.getByText('How it works', { exact: true })).toHaveCount(0);
    await expect(page.getByText('FAQ', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Sign in to Boulder Roller' })).toHaveCount(0);

    const entryShape = await page.evaluate(() => ({
      visibleWordmarkCount: Array.from(document.querySelectorAll('a, span'))
        .filter((element) => element.textContent?.trim() === 'Boulder Roller')
        .filter((element) => window.getComputedStyle(element).display !== 'none').length,
      hasRouteMaterial: Boolean(document.querySelector('.access-entry-route')),
    }));
    expect(entryShape.visibleWordmarkCount).toBe(1);
    expect(entryShape.hasRouteMaterial).toBe(false);
  });

  test('keeps email primary and reveals new-rider access progressively', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Enter invite code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Use wallet instead' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Request access' })).toHaveCount(0);

    await page.getByRole('button', { name: 'Enter invite code' }).click();

    await expect(page.getByRole('heading', { name: 'Start your account', level: 1 })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Invite code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Request access' })).toBeVisible();
  });

  test('keeps the page heading aligned with the active entry task', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Enter invite code' }).click();
    await expect(page.getByRole('heading', { name: 'Start your account', level: 1 })).toBeVisible();
    const inviteInput = page.getByRole('textbox', { name: 'Invite code' });
    await expect(inviteInput).toBeFocused();
    await expect(inviteInput).toHaveAttribute('aria-describedby', 'access-invite-helper');

    await page.getByRole('button', { name: 'Request access' }).click();
    await expect(page.getByRole('heading', { name: 'Request access', level: 1 })).toBeVisible();
    const requestEmail = page.getByRole('textbox', { name: 'Email' });
    await expect(requestEmail).toBeFocused();
    await expect(requestEmail).toHaveAttribute('aria-describedby', 'access-request-helper');

    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page.getByRole('heading', { name: 'Start your account', level: 1 })).toBeVisible();
    await expect(inviteInput).toBeFocused();
    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Email' })).toBeFocused();
  });

  test('does not turn sign-in intent into an accepted invite', async ({ page }) => {
    await page.addInitScript(() => {
      window.sessionStorage.setItem('br_access_sign_in_intent', JSON.stringify({ createdAt: Date.now() }));
    });
    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'method_choice');
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await expect(page.getByText('Invite accepted', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Enter invite code' })).toBeVisible();
  });

  test('does not turn invite-free server policy into an accepted invite', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page, { inviteRequired: false });
    await page.goto('/');

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'method_choice');
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await expect(page.getByText('Invite accepted', { exact: true })).toHaveCount(0);
  });

  test('does not trust a browser-stored invite as accepted', async ({ page }) => {
    let validationRequests = 0;
    await page.addInitScript(() => {
      window.sessionStorage.setItem('br_pending_invite_code', JSON.stringify({
        code: 'tampered-browser-value',
        createdAt: Date.now(),
      }));
    });
    await routeUnauthenticatedBootstrap(page);
    await page.route('**/auth/invite/validate', async (route) => {
      validationRequests += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ valid: false, message: 'Invalid invite code', code_id: null }),
      });
    });
    await page.goto('/');

    await expect.poll(() => validationRequests).toBe(1);
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'invite_entry');
    await expect(page.getByRole('heading', { name: 'Start your account', level: 1 })).toBeVisible();
    await expect(page.getByRole('alert')).toContainText('invite');
    await expect(page.getByText('Invite accepted', { exact: true })).toHaveCount(0);
  });

  test('validates an invite link automatically before showing account email', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    let validateCalls = 0;

    await page.route('**/auth/invite/validate', async (route) => {
      validateCalls += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          valid: true,
          message: 'Invite code valid',
          code_id: null,
        }),
      });
    });

    await page.goto('/invite/test-invite-code');

    await expect.poll(() => validateCalls).toBe(1);
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'method_choice');
    await expect(page.getByRole('heading', { name: 'Start your account', level: 1 })).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect.poll(async () => page.evaluate(() => window.sessionStorage.getItem('br_pending_invite_code'))).toContain('test-invite-code');
  });

  test('sends one neutral email code without a membership lookup or signup branch', async ({ page }) => {
    let membershipLookupRequests = 0;
    await page.addInitScript(() => {
      const trackedWindow = window as Window & { __emailCodeRequestDetails?: unknown[] };
      trackedWindow.__emailCodeRequestDetails = [];
      window.addEventListener('br:e2e:privy-email-code-requested', (event) => {
        trackedWindow.__emailCodeRequestDetails?.push((event as CustomEvent).detail);
      });
    });
    await page.route('**/auth/email/preflight', async (route) => {
      membershipLookupRequests += 1;
      await route.abort();
    });
    await routeUnauthenticatedBootstrap(page);

    await page.goto('/');
    await page.getByLabel('Email').fill('unlisted@example.com');
    await page.getByRole('button', { name: 'Send code' }).click();

    await expect(page.getByRole('region', { name: 'Account sign in' }).getByLabel('Code')).toBeVisible();
    await expect.poll(() => page.evaluate(() => (
      window as Window & { __emailCodeRequestDetails?: unknown[] }
    ).__emailCodeRequestDetails)).toEqual([{ email: 'unlisted@example.com' }]);
    expect(membershipLookupRequests).toBe(0);
  });

  test('resumes the authenticated email session after invite recovery without a second code', async ({ page }) => {
    const captureDir = process.env.BR_ENTRY_RECOVERY_CAPTURE_DIR || null;
    const captureMobile = process.env.BR_ENTRY_RECOVERY_VIEWPORT === 'mobile';
    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.setViewportSize(captureMobile
        ? { width: 390, height: 844 }
        : { width: 1440, height: 1000 });
    }
    const firstRunUser = {
      id: 'invite-recovery-user',
      wallet: 'e2ePrivyWallet11111111111111111111111111111',
      username: 'recovered_rider',
      display_name: 'Recovered Rider',
      beetle_number: 1842,
      weight_kg: null,
      avatar_url: null,
      total_rides: 0,
    };
    let authenticated = false;
    let membershipLookupRequests = 0;
    let verifyCalls = 0;
    const verifyBodies: Array<Record<string, unknown>> = [];
    let releaseSecondVerify: (() => void) | null = null;
    const secondVerifyGate = captureDir
      ? new Promise<void>((resolve) => {
          releaseSecondVerify = resolve;
        })
      : null;

    await page.addInitScript(() => {
      const trackedWindow = window as Window & {
        __brE2ESimulatePrivyBridge?: boolean;
        __brE2EUseProviderCodeExchange?: boolean;
        __emailCodeRequests?: number;
      };
      trackedWindow.__brE2ESimulatePrivyBridge = true;
      trackedWindow.__brE2EUseProviderCodeExchange = true;
      trackedWindow.__emailCodeRequests = 0;
      window.addEventListener('br:e2e:privy-email-code-requested', () => {
        trackedWindow.__emailCodeRequests = (trackedWindow.__emailCodeRequests ?? 0) + 1;
      });
    });
    await page.route('**/auth/email/preflight', async (route) => {
      membershipLookupRequests += 1;
      await route.abort();
    });
    await page.route('**/auth/privy/verify', async (route) => {
      verifyCalls += 1;
      verifyBodies.push(route.request().postDataJSON() as Record<string, unknown>);
      if (verifyCalls === 1) {
        await route.fulfill({
          status: 403,
          contentType: 'application/json',
          body: JSON.stringify({ detail: { code: 'invite_required', message: 'Invite required' } }),
        });
        return;
      }
      if (secondVerifyGate) {
        await secondVerifyGate;
      }
      authenticated = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: firstRunUser.id,
          wallet: firstRunUser.wallet,
          access_token: 'e2e-access-token',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_token: 'e2e-refresh-token',
          refresh_expires_at: '2099-01-02T00:00:00Z',
        }),
      });
    });
    await page.route('**/auth/bootstrap', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated,
          invite_required: true,
          invite_validated: authenticated,
          needs_profile_setup: false,
          auth_method_hint: authenticated ? 'privy' : null,
          user: authenticated ? firstRunUser : null,
        }),
      });
    });
    await page.route('**/auth/onboarding/state', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated,
          invite_required: true,
          invite_validated: authenticated,
          needs_profile_setup: false,
          auth_method_hint: authenticated ? 'privy' : null,
          user: authenticated ? firstRunUser : null,
        }),
      });
    });
    let releaseInviteClear!: () => void;
    const inviteClearResult = new Promise<void>((resolve) => { releaseInviteClear = resolve; });
    await page.route('**/auth/invite/clear', async (route) => {
      await inviteClearResult;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ cleared: true }) });
    });
    await page.route('**/auth/invite/validate', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ valid: true, message: 'Invite code valid', code_id: null }),
      });
    });
    await page.route('**/users/me', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(firstRunUser) });
    });
    await page.route('**/feed/global**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ contractVersion: 'feed.v1', activities: [], has_more: false, next_cursor: null }),
      });
    });
    await page.route('**/feed/home**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contractVersion: 'home_feed.v1',
          feed: { contractVersion: 'feed.v1', activities: [], has_more: false, next_cursor: null },
          sidecars: {},
        }),
      });
    });

    await page.goto('/');
    await page.getByLabel('Email').fill('new-rider@example.com');
    await page.getByRole('button', { name: 'Send code' }).click();
    const emailSurface = page.getByRole('region', { name: 'Account sign in' });
    await emailSurface.getByLabel('Code').fill('123456');
    await emailSurface.getByRole('button', { name: 'Verify code' }).click();

    await expect(emailSurface).toHaveAttribute('data-auth-recovery', 'invite_required');
    await emailSurface.getByRole('button', { name: 'Invite code' }).click();
    await expect(emailSurface.getByRole('button', { name: 'Checking', exact: true })).toBeDisabled();
    await captureAccessRendering(page, 'email-invite-clearing');
    releaseInviteClear();
    const inviteInput = page.getByRole('textbox', { name: 'Invite code' });
    await expect(inviteInput).toBeFocused();
    await expect(page.getByLabel('Email', { exact: true })).toHaveValue('new-rider@example.com');
    const recoveryLayout = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
    }));
    expect(recoveryLayout.scrollWidth).toBeLessThanOrEqual(recoveryLayout.viewportWidth);
    if (captureDir) {
      await page.screenshot({
        path: path.join(captureDir, captureMobile
          ? '03-mobile-invite-recovery-390x844.png'
          : '01-desktop-invite-recovery-1440x1000.png'),
        fullPage: false,
        animations: 'disabled',
      });
    }

    await inviteInput.fill('alpha-rider-42');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();

    await expect.poll(() => verifyCalls).toBe(2);
    await expect.poll(() => page.evaluate(() => (
      window as Window & { __emailCodeRequests?: number }
    ).__emailCodeRequests)).toBe(1);
    expect(membershipLookupRequests).toBe(0);
    expect(verifyBodies[0]?.invite_code).toBeUndefined();
    expect(verifyBodies[1]?.invite_code).toBe('alpha-rider-42');
    if (captureDir) {
      await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
      await expect(page.getByRole('link', { name: 'Boulder Roller' })).toBeVisible();
      await expect(page.getByText('Finishing sign in.', { exact: true }).filter({ visible: true }).first()).toBeVisible();
      await expect(page.getByRole('textbox', { name: 'Code' })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Send code' })).toHaveCount(0);
      const resumeLayout = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        viewportWidth: document.documentElement.clientWidth,
      }));
      expect(resumeLayout.scrollWidth).toBeLessThanOrEqual(resumeLayout.viewportWidth);
      await page.screenshot({
        path: path.join(captureDir, captureMobile
          ? '04-mobile-resume-same-session-390x844.png'
          : '02-desktop-resume-same-session-1440x1000.png'),
        fullPage: false,
        animations: 'disabled',
      });
      releaseSecondVerify?.();
    }
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toHaveCount(0);
  });

  test('moves a refused email signup into invite entry without losing the email', async ({ page }) => {
    let membershipLookupRequests = 0;
    await page.route('**/auth/email/preflight', async (route) => {
      membershipLookupRequests += 1;
      await route.abort();
    });
    await page.route('**/src/contexts/PrivyContext.tsx*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: `
          export function PrivyProvider({ children }) { return children; }
          export function usePrivyAuth() {
            return { login() {}, async logout() {}, authenticated: false, ready: true, user: null, walletAddress: null };
          }
          export function usePrivySessionResume() {
            return { authenticated: false, active: false };
          }
          export function usePrivyBridgeState() {
            return {
              walletPending: false,
              syncError: null,
              syncRecovery: null,
              retrySync() {},
              resetSyncError() {},
            };
          }
          export function usePrivyEmailAuth() {
            return {
              sendCode: async () => {
                const error = new Error('Signup is disabled');
                error.privyErrorCode = 'allowlist_rejected';
                throw error;
              },
              loginWithCode: async () => {},
              state: { status: 'initial' },
            };
          }
          export function usePrivySolanaBridge() { return {}; }
          export default PrivyProvider;
        `,
      });
    });
    await routeUnauthenticatedBootstrap(page);
    await page.route('**/auth/invite/validate', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ valid: true, message: 'Invite code valid', code_id: null }),
      });
    });

    await page.goto('/');
    await page.getByLabel('Email').fill('rider@example.com');
    await page.getByRole('button', { name: 'Send code' }).click();

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'invite_entry');
    expect(membershipLookupRequests).toBe(0);
    await expect(page.getByRole('heading', { name: 'Start your account', level: 1 })).toBeVisible();
    await expect(page.getByLabel('Email', { exact: true })).toHaveValue('rider@example.com');
    await expect(page.getByRole('textbox', { name: 'Invite code' })).toBeFocused();

    await page.getByRole('textbox', { name: 'Invite code' }).fill('alpha-rider-42');
    await page.getByRole('button', { name: 'Send code', exact: true }).click();

    await expect(page.getByRole('region', { name: 'Account sign in' })).toHaveAttribute('data-auth-transaction-stage', 'email_provider');
    await expect(page.getByLabel('Email')).toHaveValue('rider@example.com');
    await expect(page.getByLabel('Email')).toBeFocused();
    await expect(page.getByText('Invite accepted', { exact: true })).toBeVisible();
    await expect(page.getByRole('alert')).toContainText('Account setup is unavailable. Try again.');
    await captureAccessRendering(page, 'email-provider-failed');
  });

  test('does not present an unvalidated invite as accepted after Back', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    await page.getByRole('button', { name: 'Enter invite code' }).click();
    await page.getByRole('textbox', { name: 'Invite code' }).fill('not-validated');
    await page.getByRole('button', { name: 'Back' }).click();

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'entry');
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await expect(page.getByText('Invite accepted', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Enter invite code' })).toBeVisible();
  });

  test('maps provider code-verification failure to newest-code recovery guidance', async ({ page }) => {
    await page.addInitScript(() => {
      (window as Window & { __brE2EUseProviderCodeExchange?: boolean })
        .__brE2EUseProviderCodeExchange = true;
    });
    await page.route('**/src/contexts/PrivyContext.tsx*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: `
          export function PrivyProvider({ children }) { return children; }
          export function usePrivyAuth() {
            return { login() {}, async logout() {}, authenticated: false, ready: true, user: null, walletAddress: null };
          }
          export function usePrivySessionResume() {
            return { authenticated: false, active: false };
          }
          export function usePrivyBridgeState() {
            return {
              walletPending: false,
              syncError: null,
              syncRecovery: null,
              retrySync() {},
              resetSyncError() {},
            };
          }
          export function usePrivyEmailAuth() {
            return {
              sendCode: async () => {},
              loginWithCode: async () => {
                const error = new Error('Invalid login code');
                error.code = 'invalid_credentials';
                throw error;
              },
              state: { status: 'initial' },
            };
          }
          export function usePrivySolanaBridge() { return {}; }
          export default PrivyProvider;
        `,
      });
    });
    await routeUnauthenticatedBootstrap(page);

    await page.goto('/');
    await page.getByLabel('Email').fill('rider@example.com');
    await page.getByRole('button', { name: 'Send code' }).click();
    await expect(page.getByLabel('Code')).toBeVisible();
    await page.getByLabel('Code').fill('123456');
    await page.getByRole('button', { name: 'Verify code' }).click();

    await expect(page.getByRole('alert')).toContainText("That code didn't match.");
    await expect(page.getByRole('alert')).toContainText('Use the code from the newest email, or send a fresh one.');
    await expect(page.getByLabel('Code')).toHaveValue('123456');
    await expect(page.getByRole('button', { name: 'Change email' })).toBeVisible();
  });

  test('keeps the same quiet shell through the first email submission', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    await page.getByLabel('Email').fill('rider@example.com');
    await page.evaluate(() => {
      (window as Window & { __entryShell?: Element }).__entryShell = document.querySelector('.access-entry-page') ?? undefined;
    });

    await page.getByRole('button', { name: 'Send code' }).click();

    await expect(page.locator('.app-boot-screen')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => {
      const saved = (window as Window & { __entryShell?: Element }).__entryShell;
      return Boolean(saved?.isConnected && saved === document.querySelector('.access-entry-page'));
    })).toBe(true);
    await expect(page.getByRole('button', { name: /Preparing sign-in|Sending/ })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Continue with email' })).toHaveCount(0);
  });

  test('prefills invite links inline without saving them as a return URL', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    await page.goto('/invite/Alpha-Rider-42');

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'invite_entry');
    await expect(page.getByPlaceholder('Invite code')).toHaveValue('alpha-rider-42');
    await expect.poll(async () => page.evaluate(() => window.sessionStorage.getItem('br_return_url'))).toBeNull();
  });

  test('keeps the access panel free of preview media and feed-backed chrome', async ({ page }) => {
    let staticCaptureRequested = false;
    let feedRequests = 0;
    page.on('request', (request) => {
      if (request.url().includes('/access/feed-preview.png')) {
        staticCaptureRequested = true;
      }
      if (request.url().includes('/feed/home') || request.url().includes('/feed/global')) {
        feedRequests += 1;
      }
    });

    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    await expect(page.locator('.access-entry-page')).toHaveClass(/access-entry-page--app-threshold/);
    await expect(page.locator('.access-entry-page__visual')).toHaveCount(0);
    await expect(page.locator('.access-entry-route')).toHaveCount(0);
    await expect(page.locator('.access-entry-board')).toHaveCount(0);
    await expect(page.locator('.access-entry-receipt')).toHaveCount(0);
    await expect(page.getByText('87 more riders after sign-in')).toHaveCount(0);
    await expect(page.locator('.access-preview-card')).toHaveCount(0);
    await expect(page.locator('.access-preview__capture')).toHaveCount(0);
    expect(staticCaptureRequested, 'access gate should not request frozen feed capture').toBe(false);
    expect(feedRequests, 'access gate should not request feed-backed media previews').toBe(0);
  });

  test('keeps app entry in the public-root meta shape on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await routeUnauthenticatedBootstrap(page);
    await page.goto('/');

    const entryPage = page.locator('.access-entry-page');
    await expect(entryPage).toHaveAttribute('data-public-meta-shape', 'app-entry');
    await expect(entryPage).toHaveClass(/access-entry-page--app-threshold/);
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Use wallet instead' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Enter invite code' })).toBeVisible();
    await expect(page.locator('.access-entry-page__visual')).toHaveCount(0);
    await expect(page.locator('.access-entry-route')).toHaveCount(0);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByText('BoulderScan')).toHaveCount(0);

    const layout = await page.evaluate(() => {
      const viewportWidth = document.documentElement.clientWidth;
      const readRect = (selector: string) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        return {
          bottom: rect.bottom,
          height: rect.height,
          left: rect.left,
          right: rect.right,
          top: rect.top,
          width: rect.width,
        };
      };

      return {
        h1: readRect('#access-entry-title'),
        panel: readRect('.auth-entry-sheet'),
        walletChoice: readRect('.auth-entry-row'),
        scrollOverflow: document.documentElement.scrollWidth - viewportWidth,
        viewportWidth,
      };
    });

    expect(layout.scrollOverflow).toBeLessThanOrEqual(1);
    expect(layout.h1?.right ?? 0).toBeLessThanOrEqual(layout.viewportWidth + 1);
    expect(layout.panel?.right ?? 0).toBeLessThanOrEqual(layout.viewportWidth + 1);
    expect(layout.walletChoice?.right ?? 0).toBeLessThanOrEqual(layout.viewportWidth + 1);
    expect(layout.panel?.top ?? 0).toBeGreaterThan(layout.h1?.top ?? 0);
  });

  test('shows login options after successful invite validation', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    await page.route('**/auth/onboarding/state', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: false,
          invite_required: true,
          invite_validated: false,
          needs_profile_setup: false,
          auth_method_hint: null,
        }),
      });
    });

    await page.route('**/auth/invite/validate', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          valid: true,
          message: 'Invite code valid',
          code_id: null,
        }),
      });
    });

    await page.goto('/invite/test-invite-code');
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'method_choice');
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-method', '');
    await expect(page.getByRole('heading', { name: 'Start your account', level: 1 })).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
    await expect(page.getByText('Invite accepted', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page.getByRole('button', { name: 'Use wallet instead' })).toBeVisible();
    await expect.poll(async () => page.evaluate(() => window.sessionStorage.getItem('br_pending_invite_code'))).toContain('test-invite-code');
  });

  test('clears validated invite only through the explicit reset path', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    let clearInviteCalls = 0;
    let finishClear!: () => void;
    const clearResult = new Promise<void>((resolve) => { finishClear = resolve; });

    await page.route('**/auth/invite/validate', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          valid: true,
          message: 'Invite code valid',
          code_id: null,
        }),
      });
    });
    await page.route('**/auth/invite/clear', async (route) => {
      clearInviteCalls += 1;
      await clearResult;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok' }),
      });
    });

    await page.goto('/invite/test-invite-code');
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'method_choice');
    await expect.poll(async () => page.evaluate(() => window.sessionStorage.getItem('br_pending_invite_code'))).toContain('test-invite-code');

    await page.getByRole('button', { name: 'Use a different invite' }).click();
    await expect(page.getByRole('button', { name: 'Back', exact: true })).toBeDisabled();
    await expect(page.getByLabel('Email')).toBeDisabled();
    await captureAccessRendering(page, 'invite-clearing');
    finishClear();
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'invite_entry');
    await expect(page.getByRole('textbox', { name: 'Invite code' })).toHaveValue('');
    await expect.poll(async () => page.evaluate(() => window.sessionStorage.getItem('br_pending_invite_code'))).toBeNull();
    expect(clearInviteCalls, 'explicit reset should clear backend invite state').toBe(1);
  });

  test('keeps the accepted invite truthful when server clear fails', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page, { inviteValidated: true });
    await page.route('**/auth/invite/clear', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'temporary failure' }),
      });
    });

    await page.goto('/');
    await expect(page.getByText('Invite accepted', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Use a different invite' }).click();

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'method_choice');
    await expect(page.getByText('Invite accepted', { exact: true })).toBeVisible();
    await expect(page.getByRole('alert')).toContainText('Could not clear this invite. Try again.');
    await captureAccessRendering(page, 'invite-clear-failed');
  });

  test('lets returning riders sign in before invite entry', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);

    await page.goto('/');
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'entry');
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Use wallet instead' })).toBeVisible();
  });

  test('captures request-invite email through the waitlist endpoint', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    let waitlistPayload: unknown = null;
    const captureDir = process.env.BR_CAPTURE_WAITLIST_TRUTH_DIR || null;

    if (captureDir) {
      await page.setViewportSize({ width: 1440, height: 1000 });
    }

    await page.route('**/waitlist', async (route) => {
      const submitted = JSON.parse(route.request().postData() || '{}') as {
        email: string;
        source: string;
      };
      waitlistPayload = submitted;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'waitlist.v1',
          status: 'success',
          state: 'accepted',
          message: 'Request received',
          email: submitted.email,
          source: 'portal_access',
          submitted_at: '2026-05-18T18:10:00Z',
        }),
      });
    });

    await page.goto('/');
    await page.getByRole('button', { name: 'Enter invite code' }).click();
    await page.getByRole('button', { name: 'Request access' }).click();
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'request_invite');
    await expect(page.getByPlaceholder('you@example.com')).toBeFocused();
    await expect(page.getByText('Enter your email to join the alpha waitlist.')).toBeVisible();
    await captureAccessRendering(page, 'waitlist-request');
    await expect(page.getByText(/we'll email you/i)).toHaveCount(0);

    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({
        path: path.join(captureDir, 'request-invite-desktop-1440x1000.png'),
        fullPage: true,
        animations: 'disabled',
      });
    }

    await page.getByPlaceholder('you@example.com').fill('rider@example.com');
    await page.locator('form').getByRole('button', { name: 'Request invite' }).click();

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'waitlist_submitted');
    await expect(page.getByRole('heading', { name: 'Request received' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Request received' })).toBeFocused();
    await expect(page.getByText('rider@example.com')).toBeVisible();
    await expect(page.getByText('You are on the alpha waitlist.', { exact: true })).toBeVisible();
    await expect(page.getByText(/we'll email you/i)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'I have an invite' })).toBeVisible();
    expect(waitlistPayload).toEqual({ email: 'rider@example.com', source: 'portal_access' });
    await captureAccessRendering(page, 'waitlist-received');

    if (captureDir) {
      await page.screenshot({
        path: path.join(captureDir, 'request-received-desktop-1440x1000.png'),
        fullPage: true,
        animations: 'disabled',
      });

      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto('/');
      await page.getByRole('button', { name: 'Enter invite code' }).click();
      await page.getByRole('button', { name: 'Request access' }).click();
      await expect(page.getByText('Enter your email to join the alpha waitlist.')).toBeVisible();
      await page.screenshot({
        path: path.join(captureDir, 'request-invite-mobile-390x844.png'),
        fullPage: true,
        animations: 'disabled',
      });

      await page.getByPlaceholder('you@example.com').fill('mobile-rider@example.com');
      await page.locator('form').getByRole('button', { name: 'Request invite' }).click();
      await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'waitlist_submitted');
      await expect(page.getByText(/we'll email you/i)).toHaveCount(0);
      await page.screenshot({
        path: path.join(captureDir, 'request-received-mobile-390x844.png'),
        fullPage: true,
        animations: 'disabled',
      });
    }
  });

  test('keeps request-invite retryable when waitlist storage fails', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page);
    let waitlistAttempts = 0;
    let recoveredPayload: unknown = null;
    let allowRecovery = false;

    await page.route('**/waitlist', async (route) => {
      waitlistAttempts += 1;

      if (allowRecovery) {
        recoveredPayload = JSON.parse(route.request().postData() || '{}');
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            contract_version: 'waitlist.v1',
            status: 'success',
            state: 'accepted',
            message: 'Request received',
            email: 'rider@example.com',
            source: 'portal_access',
            submitted_at: '2026-05-18T18:10:00Z',
          }),
        });
        return;
      }

      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Waitlist signup is temporarily unavailable' }),
      });
    });

    await page.goto('/');
    await page.getByRole('button', { name: 'Enter invite code' }).click();
    await page.getByRole('button', { name: 'Request access' }).click();
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'request_invite');
    await expect(page.getByText('Enter your email to join the alpha waitlist.')).toBeVisible();
    await expect(page.getByText(/we'll email you/i)).toHaveCount(0);
    await page.getByPlaceholder('you@example.com').fill('rider@example.com');
    await page.locator('form').getByRole('button', { name: 'Request invite' }).click();

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'request_invite');
    await expect(page.getByText('Could not request invite.')).toBeVisible();
    await captureAccessRendering(page, 'waitlist-failed');
    await expect(page.getByPlaceholder('you@example.com')).toHaveAttribute(
      'aria-describedby',
      'access-request-helper access-request-error',
    );
    await expect(page.locator('form').getByRole('button', { name: 'Request invite' })).toBeEnabled();
    await expect(page.getByText('Enter your email to join the alpha waitlist.')).toBeVisible();
    await expect(page.getByText(/we'll email you/i)).toHaveCount(0);
    const failedAttemptCount = waitlistAttempts;
    expect(failedAttemptCount).toBeGreaterThan(0);

    allowRecovery = true;
    await page.locator('form').getByRole('button', { name: 'Request invite' }).click();

    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'waitlist_submitted');
    await expect(page.getByRole('heading', { name: 'Request received' })).toBeVisible();
    await expect(page.getByText('rider@example.com')).toBeVisible();
    await expect(page.getByText(/we'll email you/i)).toHaveCount(0);
    expect(waitlistAttempts).toBeGreaterThan(failedAttemptCount);
    expect(recoveredPayload).toEqual({ email: 'rider@example.com', source: 'portal_access' });
  });

  test('skips invite step when server says invite already validated', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page, { inviteValidated: true });
    await page.route('**/auth/onboarding/state', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: false,
          invite_required: true,
          invite_validated: true,
          needs_profile_setup: false,
          auth_method_hint: null,
        }),
      });
    });

    await page.goto('/');
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'method_choice');
    await expect(accessPanel(page)).toHaveAttribute('data-auth-runtime', 'idle');
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
  });

  test('keeps wallet signing runtime out of read-only vault views', async ({ page }) => {
    const runtimeRequests: string[] = [];

    page.on('request', (request) => {
      const url = request.url();
      if (
        url.includes('AuthRuntimeProviders')
        || url.includes('PrivyContext')
        || url.includes('WalletContext')
        || url.includes('@privy-io')
        || url.includes('wallet-adapter')
      ) {
        runtimeRequests.push(url);
      }
    });

    await routeAuthenticatedVaultView(page);
    await page.goto('/vaults/42');

    await expect(page).toHaveURL(/\/climbs\/climb-42$/);
    await expect(page.getByRole('heading', { name: 'Flagstaff Climb' })).toBeVisible();
    await expect(page.locator('#climb-vault')).toBeVisible();
    const deposit = page.getByRole('region', { name: 'Your position', exact: true }).getByRole('link', { name: 'Deposit CAL', exact: true });
    await expect(deposit).toBeVisible();
    await expect(deposit).toHaveAttribute('href', '/climbs/climb-42?climbView=deposit');
    await page.waitForTimeout(300);

    expect(runtimeRequests, 'wallet runtime requests before signature action').toEqual([]);
  });

  test('recovers from an authenticated Privy runtime module failure', async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem('br_chunk_reload_guard', '1');
    });
    await routeAuthenticatedBootstrap(page, { authMethodHint: 'privy' });
    let runtimeModuleRequests = 0;
    await page.route('**/src/components/auth/AuthRuntimeProviders.tsx*', async (route) => {
      runtimeModuleRequests += 1;
      if (runtimeModuleRequests > 1) {
        await route.continue();
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        headers: { 'cache-control': 'no-store' },
        body: 'throw new Error("Auth runtime module test failure");',
      });
    });

    await page.goto('/');

    await expect(page.getByRole('alert')).toContainText('Sign-in failed to load.');
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
    await expect(page.locator('.app-boot-screen')).toHaveCount(0);
    expect(runtimeModuleRequests).toBeGreaterThanOrEqual(2);
  });

  test('carries transaction identity into the email provider surface', async ({ page }) => {
    await page.addInitScript(() => {
      const trackedWindow = window as Window & { __emailCodeRequests?: number };
      trackedWindow.__emailCodeRequests = 0;
      window.addEventListener('br:e2e:privy-email-code-requested', () => {
        trackedWindow.__emailCodeRequests = (trackedWindow.__emailCodeRequests ?? 0) + 1;
      });
    });
    await routeUnauthenticatedBootstrap(page, { inviteValidated: true });

    await page.goto('/');
    const authPanel = accessPanel(page);
    await expect(authPanel).toHaveAttribute('data-auth-runtime', 'idle');
    const transactionId = await authPanel.getAttribute('data-auth-transaction-id');

    await page.getByLabel('Email').fill('rider@example.com');
    await page.getByRole('button', { name: 'Send code' }).click();

    const emailSurface = page.getByRole('region', { name: 'Account sign in' });
    await expect(emailSurface).toHaveAttribute('data-auth-transaction-id', transactionId ?? '');
    await expect(emailSurface).toHaveAttribute('data-auth-transaction-stage', 'email_provider');
    await expect(emailSurface).toHaveAttribute('data-auth-transaction-method', 'email');
    await expect(emailSurface).toHaveAttribute('data-auth-recovery', '');
    await expect(emailSurface.getByLabel('Code')).toBeVisible();
    const verifyCode = emailSurface.getByRole('button', { name: 'Verify code' });
    const changeEmail = emailSurface.getByRole('button', { name: 'Change email' });
    await expect(verifyCode).toBeVisible();
    await expect(verifyCode).toHaveAttribute('data-variant', 'primary');
    await expect(changeEmail).toHaveClass(/auth-entry-row/);
    await expect(changeEmail).not.toHaveAttribute('data-variant', 'primary');
    await expect.poll(() => page.evaluate(() => (
      window as Window & { __emailCodeRequests?: number }
    ).__emailCodeRequests)).toBe(1);
    await expect(page.getByRole('button', { name: 'Continue with email' })).toHaveCount(0);
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  test('keeps invite recovery primary when email sign-in needs an invite', async ({ page }) => {
    await page.route('**/src/contexts/PrivyContext.tsx*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: `
          export function PrivyProvider({ children }) { return children; }
          export function usePrivyAuth() {
            return { login() {}, async logout() {}, authenticated: false, ready: true, user: null, walletAddress: null };
          }
          export function usePrivySessionResume() {
            return { authenticated: false, active: false };
          }
          export function usePrivyBridgeState() {
            return {
              walletPending: false,
              syncError: null,
              syncRecovery: 'invite_required',
              retrySync() {},
              resetSyncError() {},
            };
          }
          export function usePrivyEmailAuth() {
            return { sendCode: async () => {}, loginWithCode: async () => {}, state: { status: 'initial' } };
          }
          export function usePrivySolanaBridge() { return {}; }
          export default PrivyProvider;
        `,
      });
    });
    await routeUnauthenticatedBootstrap(page, { inviteValidated: true });
    await page.route('**/auth/invite/clear', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'temporary failure' }),
      });
    });

    await page.goto('/');
    await page.getByLabel('Email').fill('rider@example.com');
    await page.getByRole('button', { name: 'Send code' }).click();

    const emailSurface = page.getByRole('region', { name: 'Account sign in' });
    await expect(emailSurface).toHaveAttribute('data-auth-recovery', 'invite_required');
    const inviteCode = emailSurface.getByRole('button', { name: 'Invite code' });
    await expect(inviteCode.locator('.auth-entry-chevron')).toBeVisible();
    await expect(emailSurface.getByRole('button', { name: 'Change email' })).toHaveCount(0);
    await inviteCode.click();
    await expect(emailSurface.getByRole('alert')).toContainText('Could not clear this invite. Try again.');
    await expect(emailSurface).toHaveAttribute('data-auth-transaction-stage', 'email_provider');
  });

  test('carries transaction identity into the wallet provider surface', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page, { inviteValidated: true });

    await page.goto('/');
    await expect(accessPanel(page)).toHaveAttribute('data-auth-runtime', 'idle');
    const transactionId = await accessPanel(page).getAttribute('data-auth-transaction-id');

    await page.getByRole('button', { name: 'Back' }).click();
    await page.getByRole('button', { name: 'Use wallet instead' }).click();

    const walletSurface = page.getByRole('region', { name: 'Use your wallet' });
    await expect(walletSurface.getByRole('group', { name: 'Detected Solana wallets' })).toBeVisible();
    await expect(walletSurface).toHaveAttribute('data-auth-transaction-id', transactionId ?? '');
    await expect(walletSurface).toHaveAttribute('data-auth-transaction-stage', 'wallet_provider');
    await expect(walletSurface).toHaveAttribute('data-auth-transaction-method', 'wallet');
    await expect(walletSurface).toHaveAttribute('data-auth-step', 'select');
    await captureAccessRendering(page, 'wallet-provider-options');
    await expect(walletSurface).toHaveAttribute('data-auth-recovery', '');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });

  test('returns from wallet provider surface to the same direct sign-in transaction', async ({ page }) => {
    await routeUnauthenticatedBootstrap(page, { inviteValidated: true });

    await page.goto('/');
    await expect(accessPanel(page)).toHaveAttribute('data-auth-runtime', 'idle');
    const transactionId = await accessPanel(page).getAttribute('data-auth-transaction-id');

    await page.getByRole('button', { name: 'Back' }).click();
    await page.getByRole('button', { name: 'Use wallet instead' }).click();
    const walletSurface = page.getByRole('region', { name: 'Use your wallet' });
    await expect(walletSurface.getByRole('group', { name: 'Detected Solana wallets' })).toBeVisible();
    await expect(walletSurface).toHaveAttribute('data-auth-transaction-stage', 'wallet_provider');
    await expect(page.getByRole('dialog')).toHaveCount(0);

    await walletSurface.getByRole('button', { name: 'Back' }).click();

    const authPanel = accessPanel(page);
    await expect(authPanel).toHaveAttribute('data-auth-transaction-id', transactionId ?? '');
    await expect(authPanel).toHaveAttribute('data-auth-transaction-stage', 'method_choice');
    await expect(authPanel).toHaveAttribute('data-auth-transaction-method', '');
    await expect(authPanel.getByLabel('Email')).toBeVisible();
    await expect(authPanel.getByRole('button', { name: 'Send code' })).toBeVisible();
  });

  [
    { caseName: 'accented rider names', displayName: 'José Álvarez', initials: 'JÁ' },
    { caseName: 'canonically equivalent rider names', displayName: 'A\u030Asa', initials: 'ÅS' },
    { caseName: 'non-Latin rider names', displayName: '李 雷', initials: '李雷' },
  ].forEach(({ caseName, displayName, initials }) => {
    test(`keeps provenance legible for ${caseName}`, async ({ page }) => {
      await routeAuthenticatedBootstrap(page, { displayName, username: 'profile_rider' });

      await page.goto('/');

      const accountButton = page.getByRole('button', { name: `Open account menu for ${displayName}` });
      await expect(accountButton.locator('.portal-shell__account-mini-mark')).toHaveText(initials);
    });
  });

  test('keeps provenance deterministic across browser locales', async ({ page }) => {
    await page.addInitScript(() => {
      const localeUpperCase = String.prototype.toLocaleUpperCase;
      String.prototype.toLocaleUpperCase = function (locales?: string | string[]) {
        return localeUpperCase.call(this, locales ?? 'tr-TR');
      };
    });
    await routeAuthenticatedBootstrap(page, { displayName: 'istanbul_rider', username: 'profile_rider' });

    await page.goto('/');

    await expect.poll(() => page.evaluate(() => 'istanbul'.toLocaleUpperCase())).toBe('İSTANBUL');
    const accountButton = page.getByRole('button', { name: 'Open account menu for istanbul_rider' });
    await expect(accountButton.locator('.portal-shell__account-mini-mark')).toHaveText('IR');
  });

  test('uses backend setup state instead of username to enter onboarding', async ({ page }) => {
    await routeAuthenticatedBootstrap(page, {
      needsProfileSetup: true,
      username: 'placeholder-rider',
    });

    await page.goto('/');

    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole('heading', { name: 'Rider name', level: 1 })).toBeVisible();
  });

  test('renders quiet first-run identity setup in the approved sign-in shell', async ({ page }) => {
    await routeFirstRunOnboarding(page);

    await page.goto('/');

    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole('heading', { name: 'Rider name', level: 1 })).toBeVisible();
    await expect(page.getByText('Shown with your rides and leaderboard positions.')).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'Rider name' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeVisible();
    await expect(page.getByText('Loading your first screen.')).toHaveCount(0);
    await expect(page.getByText('SET UP YOUR RIDER PROFILE')).toHaveCount(0);
    await expect(page.getByText('Rider Type')).toHaveCount(0);
    await expect(page.locator('.access-entry-page__brand-mark')).toHaveCount(0);

    const layout = await page.evaluate(() => {
      const readRect = (selector: string) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        return { height: rect.height, width: rect.width };
      };

      return {
        column: readRect('.first-run-onboarding .access-entry-page__intro'),
        input: readRect('#first-run-rider-name'),
        action: readRect('.first-run-onboarding .auth-entry-action'),
        wordmarks: Array.from(document.querySelectorAll('a, span'))
          .filter((element) => element.textContent?.trim() === 'Boulder Roller')
          .filter((element) => window.getComputedStyle(element).display !== 'none').length,
      };
    });

    expect(layout.column?.width).toBeCloseTo(388, 0);
    expect(layout.input?.height).toBeCloseTo(44, 0);
    expect(layout.action?.height).toBeGreaterThanOrEqual(52);
    expect(layout.wordmarks).toBe(1);
    await captureAccessRendering(page, 'rider-name');
  });

  test('saves rider identity before offering real first-ride destinations', async ({ page }) => {
    const onboarding = await routeFirstRunOnboarding(page);
    const captureDir = process.env.BR_CAPTURE_FIRST_RIDE_DIR || null;

    if (captureDir) {
      await page.setViewportSize({ width: 1440, height: 1000 });
    }

    await page.goto('/');
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();

    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole('heading', { name: 'First ride', level: 1 })).toBeFocused();
    await expect(page.getByText('Upload a ride to see its climbs, times, and leaderboard positions.')).toBeVisible();
    const choices = page.getByRole('group', { name: 'First ride choices' });
    await expect(choices.getByRole('button', { name: 'Upload ride', exact: true })).toBeVisible();
    await expect(choices.getByRole('button', { name: 'Browse climbs', exact: true })).toBeVisible();
    await expect(choices.getByRole('button', { name: 'Continue without upload', exact: true })).toBeVisible();
    await expect(page.getByText('Connect Strava', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Weight')).toHaveCount(0);
    await expect(page.getByText('Wallet')).toHaveCount(0);
    await expect(page.getByText('Vault')).toHaveCount(0);
    expect(onboarding.getProfilePayload()).toEqual({ username: 'philly_rider' });
    expect(onboarding.getStravaAuthUrlRequests()).toBe(0);
    await expect.poll(() => page.evaluate(() => localStorage.getItem('br_first_ride_pending')))
      .toContain('first-run-user-1');

    const desktopLayout = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      actionHeights: Array.from(document.querySelectorAll(
        '.first-run-onboarding .auth-entry-action, .first-run-onboarding .auth-entry-row',
      )).map((element) => element.getBoundingClientRect().height),
    }));
    expect(desktopLayout.overflow).toBeLessThanOrEqual(1);
    expect(desktopLayout.actionHeights).toHaveLength(3);
    await captureAccessRendering(page, 'first-ride');
    expect(desktopLayout.actionHeights.every((height) => height >= 44)).toBe(true);

    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({
        path: path.join(captureDir, 'first-ride-desktop-1440x1000.png'),
        fullPage: true,
        animations: 'disabled',
      });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    const mobileLayout = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      actionHeights: Array.from(document.querySelectorAll(
        '.first-run-onboarding .auth-entry-action, .first-run-onboarding .auth-entry-row',
      )).map((element) => element.getBoundingClientRect().height),
    }));
    expect(mobileLayout.overflow).toBeLessThanOrEqual(1);
    expect(mobileLayout.actionHeights.every((height) => height >= 44)).toBe(true);

    if (captureDir) {
      await page.screenshot({
        path: path.join(captureDir, 'first-ride-mobile-390x844.png'),
        fullPage: true,
        animations: 'disabled',
      });
    }

    await page.setViewportSize({ width: 320, height: 720 });
    const narrowLayout = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      actionHeights: Array.from(document.querySelectorAll(
        '.first-run-onboarding .auth-entry-action, .first-run-onboarding .auth-entry-row',
      )).map((element) => element.getBoundingClientRect().height),
    }));
    expect(narrowLayout.overflow).toBeLessThanOrEqual(1);
    expect(narrowLayout.actionHeights.every((height) => height >= 44)).toBe(true);
  });

  test('opens Upload ride from the first-ride handoff', async ({ page }) => {
    const onboarding = await routeFirstRunOnboarding(page);

    await page.goto('/');
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await page.getByRole('button', { name: 'Upload ride', exact: true }).click();

    await expect(page).toHaveURL(/\/upload$/);
    const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
    await expect(sheet).toBeVisible();
    await expect(sheet.locator('.portal-sheet__bar').getByRole('heading', { name: 'Upload ride', exact: true })).toBeVisible();
    await expect.poll(() => page.evaluate(() => localStorage.getItem('br_first_ride_pending'))).toBeNull();
    expect(onboarding.getStravaAuthUrlRequests()).toBe(0);
  });

  test('opens Browse climbs from the first-ride handoff', async ({ page }) => {
    const onboarding = await routeFirstRunOnboarding(page);

    await page.goto('/');
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await page.getByRole('button', { name: 'Browse climbs', exact: true }).click();

    await expect(page).toHaveURL(/\/climbs$/);
    await expect(page.getByRole('heading', { name: 'Climbs', level: 1 })).toBeVisible();
    await expect.poll(() => page.evaluate(() => localStorage.getItem('br_first_ride_pending'))).toBeNull();
    expect(onboarding.getStravaAuthUrlRequests()).toBe(0);
  });

  test('continues without upload into the real Home feed inside the portal shell', async ({ page }) => {
    const onboarding = await routeFirstRunOnboarding(page, {
      homeActivities: [FIRST_HOME_ACTIVITY],
    });

    await page.goto('/');

    const riderNameMobileCapture = process.env.PORTAL_RIDER_NAME_MOBILE_SCREENSHOT;
    if (riderNameMobileCapture) {
      await page.setViewportSize({ width: 390, height: 844 });
      await expect(page.getByRole('heading', { name: 'Rider name', level: 1 })).toBeVisible();
      await page.screenshot({ path: riderNameMobileCapture });
      await page.setViewportSize({ width: 1280, height: 720 });
    }

    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'First ride', level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Continue without upload', exact: true }).click();

    await expect(page).toHaveURL(/\/$/);
    const primaryNavigation = page.getByRole('navigation', { name: 'Primary navigation' });
    await expect(primaryNavigation).toBeVisible();
    await expect(primaryNavigation.getByRole('link', { name: 'Feed' })).toHaveAttribute('aria-current', 'page');
    await expect(primaryNavigation.getByRole('link', { name: 'Map' })).toHaveAttribute('href', '/climbs');
    await expect(page.getByRole('button', { name: 'Upload ride', exact: true })).toHaveCount(1);
    const accountButton = page.getByRole('button', { name: 'Open account menu for philly_rider' });
    await expect(accountButton.locator('.portal-shell__account-mini-mark')).toHaveText('PR');
    await expect(page.getByText('Training inputs need attention')).toHaveCount(0);
    await expect(page.locator('.first-run-onboarding')).toHaveCount(0);
    await expect(page.locator('.feed-first-run-panel')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Rides and climbs' })).toHaveCount(0);
    await expect(page.getByRole('group', { name: 'Rider options' })).toHaveCount(0);
    await expect(page.getByText('Browse climbs', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Connect Strava', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Welcome to Boulder Roller')).toHaveCount(0);
    await expect(page.getByText(/first ride/i)).toHaveCount(0);
    await expect(page.getByText(/see what counts/i)).toHaveCount(0);
    await expect(page.locator('.feed-rail .portal-stack[hidden]')).toHaveCount(0);
    // Ratified Feed board (2026-09-01): a first-run rider gets the feed and its
    // scope words, but no crown card, no week card, no streak.
    await expect(page.locator('.feed-crown')).toBeHidden();
    await expect(page.getByRole('group', { name: 'Feed scope' })).toBeVisible();
    await expect(page.locator('.feed-week__pairs')).toBeHidden();
    await expect(page.getByText('Latest ride', { exact: true })).toBeHidden();
    await expect(page.getByText('Current streak', { exact: true })).toBeHidden();
    await expect(page.getByRole('button', { name: 'Everyone', exact: true })).toBeVisible();
    const firstFeedActivity = page.locator('.feed-activity-card').first();
    await expect(firstFeedActivity.getByRole('heading', { name: 'Umbria Street repeats' })).toBeVisible();
    expect(onboarding.getProfilePayload()).toEqual({ username: 'philly_rider' });
    await expect(page.locator('.auth-handoff-overlay')).toHaveCount(0);
    await expect.poll(() => page.locator('.feed-page').evaluate((element) => (
      element.getAnimations().every((animation) => animation.playState === 'finished')
    ))).toBe(true);
    await expect(page.locator('.background-fetch-indicator')).toHaveCount(0);

    const desktopCapture = process.env.PORTAL_FIRST_PORTAL_HOME_DESKTOP_SCREENSHOT;
    if (desktopCapture) {
      await page.screenshot({ path: desktopCapture });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole('button', { name: 'Return to previous page' })).toHaveCount(0);
    await expect(firstFeedActivity).toBeVisible();

    const mobileCapture = process.env.PORTAL_FIRST_PORTAL_HOME_MOBILE_SCREENSHOT;
    if (mobileCapture) {
      await page.screenshot({ path: mobileCapture });
    }
  });

  test('keeps an omitted first-run ride total quiet while rendering real Home activity', async ({ page }) => {
    await routeFirstRunOnboarding(page, {
      homeActivities: [FIRST_HOME_ACTIVITY],
      omitTotalRides: true,
    });

    await page.goto('/');
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await page.getByRole('button', { name: 'Continue without upload', exact: true }).click();

    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('.feed-activity-card').first()).toContainText('Umbria Street repeats');
    await expect(page.locator('.feed-crown')).toHaveCount(0);
    await expect(page.getByRole('group', { name: 'Feed scope' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Everyone', exact: true })).toBeVisible();
    await expect(page.getByLabel('Feed status')).toHaveCount(0);
    await expect(page.locator('.feed-rail-summary')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Rides and climbs' })).toHaveCount(0);
    await expect(page.getByRole('group', { name: 'Rider options' })).toHaveCount(0);
  });

  test('keeps the first visible Home frame quiet while feed data is unresolved', async ({ page }) => {
    const onboarding = await routeFirstRunOnboarding(page, { deferHomeFeed: true });

    await page.goto('/');
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await page.getByRole('button', { name: 'Continue without upload', exact: true }).click();

    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Rides and climbs' })).toHaveCount(0);
    await expect(page.getByRole('group', { name: 'Rider options' })).toHaveCount(0);
    await expect(page.getByText('Connect Strava', { exact: true })).toHaveCount(0);
    await expect(page.locator('.feed-rail .portal-stack[hidden]')).toHaveCount(0);
    await expect(page.locator('.feed-page .ledger-slot-row')).toHaveCount(10);
    await expect(page.locator('.shell-live-rule')).toHaveAttribute('data-live', 'true');

    onboarding.releaseHomeFeed();
    await expect(page.locator('.ledger-state-row')).toContainText('No rides yet');
    await expect(page.locator('.ledger-state-row p')).toHaveCount(0);
    await expect(page.locator('.feed-page .ledger-slot-row')).toHaveCount(0);
    await expect(page.locator('.background-fetch-indicator')).toHaveCount(0);
  });

  test('resumes a pending first-ride handoff after reload and clears it on a choice', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('br_first_ride_pending', JSON.stringify({ userId: 'setup-user-1' }));
    });
    await routeAuthenticatedBootstrap(page, { username: 'philly_rider' });

    await page.goto('/onboarding');

    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole('heading', { name: 'First ride', level: 1 })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'First ride', level: 1 })).toBeVisible();
    await expect.poll(() => page.evaluate(() => localStorage.getItem('br_first_ride_pending')))
      .toContain('setup-user-1');

    await page.getByRole('button', { name: 'Continue without upload', exact: true }).click();

    await expect(page).toHaveURL(/\/$/);
    await expect.poll(() => page.evaluate(() => localStorage.getItem('br_first_ride_pending'))).toBeNull();
  });

  test('returns a deep-linked rider after identity setup instead of discarding the route', async ({ page }) => {
    await routeFirstRunOnboarding(page);

    await page.goto('/rides/deep-link-ride');
    await expect(page).toHaveURL(/\/onboarding$/);
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();

    await expect(page).toHaveURL(/\/rides\/deep-link-ride$/);
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('br_return_url'))).toBeNull();
    await expect(page.getByRole('heading', { name: 'First ride', level: 1 })).toHaveCount(0);
  });

  test('states the rider-name contract without sending an invalid profile update', async ({ page }) => {
    const onboarding = await routeFirstRunOnboarding(page);

    await page.goto('/');
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly-rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();

    await expect(page.getByRole('alert')).toHaveText('Use 3–20 letters, numbers, or underscores.');
    await expect(page.getByRole('heading', { name: 'Rider name', level: 1 })).toBeVisible();
    expect(onboarding.getProfilePayload()).toBeNull();
  });

  test('maps a taken backend username to rider-facing language', async ({ page }) => {
    await routeFirstRunOnboarding(page, { profileSaveError: 'Username is already taken' });

    await page.goto('/');
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();

    await expect(page.getByRole('alert')).toHaveText('That rider name is already taken.');
    await captureAccessRendering(page, 'rider-name-taken');
    await expect(page.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled();
  });

  test('recovers inline when a first-ride destination cannot open', async ({ page }) => {
    await routeFirstRunOnboarding(page, { profileRefreshFailures: 1 });

    await page.goto('/');
    await page.getByRole('textbox', { name: 'Rider name' }).fill('philly_rider');
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    await page.getByRole('button', { name: 'Browse climbs', exact: true }).click();

    await expect(page.getByRole('alert')).toHaveText('Could not open climbs.');
    await captureAccessRendering(page, 'first-ride-failed');
    await expect(page.getByRole('button', { name: 'Browse climbs', exact: true })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Upload ride', exact: true })).toBeEnabled();

    await page.getByRole('button', { name: 'Browse climbs', exact: true }).click();
    await expect(page).toHaveURL(/\/climbs$/);
  });

  test('moves from code verification to Rider name without a handoff page', async ({ page }) => {
    let authenticated = false;
    let authenticatedAppRequests = 0;
    let releaseAuthenticatedApp = () => {};
    const authenticatedAppGate = new Promise<void>((resolve) => {
      releaseAuthenticatedApp = resolve;
    });
    const firstRunUser = {
      id: 'code-first-run-user',
      wallet: 'e2ePrivyWallet11111111111111111111111111111',
      username: null,
      display_name: null,
      beetle_number: 1542,
      weight_kg: null,
      avatar_url: null,
      total_rides: 0,
    };

    await page.route('**/*', async (route) => {
      if (!['fetch', 'xhr'].includes(route.request().resourceType())) {
        await route.continue();
        return;
      }

      const url = new URL(route.request().url());
      const path = url.pathname.replace(/^\/api/, '') || '/';
      const json = (body: unknown, status = 200) => route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });

      if (path === '/auth/privy/verify') {
        authenticated = true;
        await json({
          user_id: firstRunUser.id,
          wallet: firstRunUser.wallet,
          access_token: 'e2e-access-token',
          access_expires_at: '2099-01-01T00:00:00Z',
          refresh_token: 'e2e-refresh-token',
          refresh_expires_at: '2099-01-02T00:00:00Z',
        });
        return;
      }

      if (path === '/auth/bootstrap' || path === '/auth/onboarding/state') {
        await json({
          authenticated,
          invite_required: true,
          invite_validated: true,
          needs_profile_setup: authenticated,
          auth_method_hint: authenticated ? 'privy' : null,
          user: authenticated ? firstRunUser : null,
        });
        return;
      }

      if (path === '/users/me' || path === '/me') {
        await json(firstRunUser);
        return;
      }

      await json({ detail: 'not found' }, 404);
    });

    await page.route('**/src/AuthenticatedApp.tsx*', async (route) => {
      authenticatedAppRequests += 1;
      await authenticatedAppGate;
      await route.continue();
    });

    await page.goto('/');
    await page.getByLabel('Email').fill('rider@example.com');
    await page.getByRole('button', { name: 'Send code' }).click();
    const emailSurface = page.getByRole('region', { name: 'Account sign in' });
    await expect(emailSurface.getByLabel('Code')).toBeVisible();
    await expect.poll(() => authenticatedAppRequests).toBe(1);

    await emailSurface.getByLabel('Code').fill('123456');
    await emailSurface.getByRole('button', { name: 'Verify code' }).click();
    await expect(emailSurface).toBeVisible();
    await expect(page.getByText('Loading your first screen.')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Rider name', level: 1 })).toHaveCount(0);

    releaseAuthenticatedApp();
    await expect(page.getByRole('heading', { name: 'Rider name', level: 1 })).toBeVisible();
    await expect(page.getByText('Loading your first screen.')).toHaveCount(0);
  });

  test('keeps quiet first-run onboarding inside the mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await routeFirstRunOnboarding(page);

    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Rider name', level: 1 })).toBeVisible();

    const layout = await page.evaluate(() => ({
      viewportWidth: document.documentElement.clientWidth,
      scrollOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      columnWidth: document.querySelector('.first-run-onboarding .access-entry-page__intro')?.getBoundingClientRect().width ?? 0,
    }));

    expect(layout.scrollOverflow).toBeLessThanOrEqual(1);
    expect(layout.columnWidth).toBeCloseTo(350, 0);
    expect(layout.columnWidth).toBeLessThan(layout.viewportWidth);
  });

  test('keeps the quiet sign-in shell up while cookie bootstrap is unresolved', async ({ page }) => {
    let releaseBootstrap!: () => void;
    const bootstrapReleased = new Promise<void>((resolve) => {
      releaseBootstrap = resolve;
    });

    await page.route('**/auth/bootstrap', async (route) => {
      await bootstrapReleased;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: false,
          invite_required: true,
          invite_validated: false,
          needs_profile_setup: false,
          auth_method_hint: null,
          user: null,
        }),
      });
    });

    await page.goto('/');

    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Checking session' })).toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('.app-boot-screen')).toHaveCount(0);

    releaseBootstrap();
    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
  });

  test('times out session checking in place and retries the same shell', async ({ page }) => {
    let bootstrapRequests = 0;
    await page.route('**/auth/bootstrap', async (route) => {
      bootstrapRequests += 1;
      if (bootstrapRequests === 1) {
        await new Promise(() => {});
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          authenticated: false,
          invite_required: true,
          invite_validated: false,
          needs_profile_setup: false,
          auth_method_hint: null,
          user: null,
        }),
      });
    });

    await page.goto('/');
    await expect(page.locator('.access-entry-page')).toBeVisible();
    await page.evaluate(() => {
      (window as Window & { __entryShell?: Element }).__entryShell = document.querySelector('.access-entry-page') ?? undefined;
    });

    await expect(page.getByRole('button', { name: 'Retry session check' })).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('.app-boot-screen')).toHaveCount(0);
    await expect(page.getByLabel('Email')).not.toHaveAttribute('aria-invalid', 'true');

    await page.getByLabel('Email').press('Enter');

    await expect(page.getByRole('button', { name: 'Send code' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => {
      const saved = (window as Window & { __entryShell?: Element }).__entryShell;
      return Boolean(saved?.isConnected && saved === document.querySelector('.access-entry-page'));
    })).toBe(true);
    expect(bootstrapRequests).toBeGreaterThanOrEqual(2);
  });

  test('bounds a hanging cookie refresh without clearing pending invite state', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('br_authenticated', 'true');
      sessionStorage.setItem('br_pending_invite_code', 'alpha-rider-42');
    });
    await page.route('**/auth/bootstrap', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Access token expired' }),
      });
    });
    await page.route('**/auth/refresh', async () => {
      await new Promise(() => {});
    });

    await page.goto('/');
    await expect(page.locator('.access-entry-page')).toBeVisible();
    await page.evaluate(() => {
      (window as Window & { __entryShell?: Element }).__entryShell = document.querySelector('.access-entry-page') ?? undefined;
    });

    await expect(page.getByRole('button', { name: 'Retry session check' })).toBeVisible({ timeout: 10_000 });
    await expect.poll(() => page.evaluate(() => {
      const saved = (window as Window & { __entryShell?: Element }).__entryShell;
      return Boolean(saved?.isConnected && saved === document.querySelector('.access-entry-page'));
    })).toBe(true);
    await expect.poll(() => page.evaluate(() => localStorage.getItem('br_authenticated'))).toBe('true');
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('br_pending_invite_code'))).toBe('alpha-rider-42');
  });

  test.describe('detected wallet option styling', () => {
    test.use({
      viewport: { width: 390, height: 844 },
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    });

    test('contains the Phantom option frame after choosing linked wallet', async ({ page }) => {
      const captureDir = process.env.BR_CAPTURE_EYEBROW_REVIEW_DIR;
      await routeUnauthenticatedBootstrap(page);

      await page.goto('/');
      await page.getByRole('button', { name: 'Use wallet instead' }).click();

      const walletSurface = page.getByRole('region', { name: 'Use your wallet' });
      const phantomCard = walletSurface.getByRole('button', { name: /Phantom/ });

      await expect(phantomCard).toBeVisible();
      await expect(phantomCard).toHaveCSS('box-shadow', 'none');
      await expect(phantomCard).toHaveCSS('border-radius', '0px');
      await expect(walletSurface.locator('.auth-entry-sheet').first()).toHaveCSS('border-radius', '20px');
      await expect(phantomCard.locator('.auth-entry-chevron')).toBeVisible();
      await captureAccessRendering(page, 'wallet-loadable-mobile');
      await expect(walletSurface.getByText('Detected Solana wallets')).toHaveCount(0);

      if (captureDir) {
        fs.mkdirSync(captureDir, { recursive: true });
        await page.waitForTimeout(800);
        await page.screenshot({
          path: path.join(captureDir, 'wallet-select-mobile-390x844.png'),
          fullPage: true,
          animations: 'disabled',
        });
        await page.setViewportSize({ width: 1440, height: 1000 });
        await page.goto('/');
        await page.getByRole('button', { name: 'Use wallet instead' }).click();
        await expect(page.getByRole('region', { name: 'Use your wallet' })).toBeVisible();
        await page.waitForTimeout(800);
        await page.screenshot({
          path: path.join(captureDir, 'wallet-select-desktop-1440x1000.png'),
          fullPage: true,
          animations: 'disabled',
        });
      }
    });
  });
});

test.describe('Entry capture', () => {
  test('entry capture states', async ({ page }) => {
    test.setTimeout(60_000);
    await routeUnauthenticatedBootstrap(page);
    let finishInvite!: () => void;
    const inviteResult = new Promise<void>((resolve) => { finishInvite = resolve; });
    await page.route('**/auth/invite/validate', async (route) => {
      await inviteResult;
      await route.fulfill({ json: { valid: true, message: 'Invite code valid', code_id: null } });
    });
    await page.goto('/invite/test-invite-code');
    await expect(page.getByRole('button', { name: 'Checking', exact: true })).toBeDisabled();
    await captureAccessRendering(page, 'invite-link-checking');
    await page.getByRole('button', { name: 'Back' }).click();
    const validationFinished = page.waitForResponse('**/auth/invite/validate');
    finishInvite();
    await validationFinished;
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'entry');
    expect(await page.evaluate(() => sessionStorage.getItem('br_pending_invite_code'))).toBeNull();

    let finishWaitlist!: () => void;
    const waitlistResult = new Promise<void>((resolve) => { finishWaitlist = resolve; });
    await page.route('**/waitlist', async (route) => {
      await waitlistResult;
      await route.fulfill({ json: { status: 'success', state: 'accepted', email: 'rider@example.com', source: 'portal_access' } });
    });
    await page.getByRole('button', { name: 'Enter invite code' }).click();
    await page.getByRole('button', { name: 'Request access' }).click();
    await page.getByLabel('Email').fill('rider@example.com');
    await page.getByRole('button', { name: 'Request invite' }).click();
    await expect(page.getByRole('button', { name: 'Sending', exact: true })).toBeDisabled();
    await captureAccessRendering(page, 'waitlist-sending');
    await page.getByRole('button', { name: 'Back' }).click();
    const waitlistFinished = page.waitForResponse('**/waitlist');
    finishWaitlist();
    await waitlistFinished;
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(accessPanel(page)).toHaveAttribute('data-auth-transaction-stage', 'invite_entry');
    await expect(page.getByLabel('Email')).toHaveValue('rider@example.com');

    await routeAuthenticatedBootstrap(page);
    await page.goto('/');
    await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
    // The same event boundary used by the API on an expired session.
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('br:session-expired', { detail: { reason: 'token_expired' } })));
    await expect(page.getByRole('dialog', { name: 'Sign in', exact: true })).toBeVisible();
    await expect(page.getByText('Session has expired. Please sign in again.', { exact: true })).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Sign in', exact: true }).getByLabel('Email')).toHaveCSS('outline-offset', '2px');
    await expect(page.getByRole('dialog', { name: 'Sign in', exact: true }).getByLabel('Email')).toHaveCSS('box-shadow', 'none');
    await captureAccessRendering(page, 'session-expired');
    await page.context().setOffline(true);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('br:session-expired', { detail: { reason: 'network_error' } })));
    await expect(page.locator('.offline-pinned-row')).toContainText('No connection. Try again.');
    await expect(page.locator('.shell-live-rule')).toHaveAttribute('data-offline', 'true');
    await expect(page.locator('.retained-page-content')).toHaveCSS('opacity', '0.55');
    await captureAccessRendering(page, 'connection-lost');
    await expect(page.getByRole('dialog', { name: 'Sign in', exact: true })).toHaveCount(0);
    await expect(page.locator('.offline-pinned-row')).toHaveCount(1);
    await captureAccessRendering(page, 'connection-still-offline');
    await page.context().setOffline(false);
  });
});
