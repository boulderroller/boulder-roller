import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const boardHtml = readFileSync(path.resolve(__dirname, '../../../history/upload-sheet-2026-09-06/upload-sheet-board.html'), 'utf8');
const boardRide = JSON.parse(boardHtml.match(/<script id="data" type="application\/json">(.*?)<\/script>/s)![1]) as { profile: number[][]; climbs: number[][] };

const uploadUser = {
  id: 'user-upload-1',
  wallet: '8xF6yDbvJfRiderWallet111111111111111111111',
  username: 'riderone',
  bio: 'Beta rider',
  location: 'Boulder, CO',
  weight_kg: null,
  rider_type: 'climber',
  preferred_units: 'metric',
  theme_id: 'hoo-breddin',
  is_dark_mode: false,
  is_public: true,
  default_ride_visibility: 'public',
  total_rides: 0,
  total_distance_km: 0,
  total_elevation_m: 0,
  total_kcals: 0,
  total_duration_sec: 0,
  total_dung_earned: 0,
  cal_earned_today: 0,
  dung_earned_today: 0,
};

async function routeAuthenticatedUpload(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('br_authenticated', 'true');
    window.localStorage.setItem('br_setup_reprompt_dismissed', 'true');
  });

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, '');
    const isApiRequest = url.pathname.startsWith('/api') || ['fetch', 'xhr'].includes(request.resourceType());

    if (!isApiRequest) {
      return route.continue();
    }

    const fulfillJson = (body: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (path === '/auth/bootstrap') {
      return fulfillJson({
        authenticated: true,
        invite_required: false,
        invite_validated: true,
        needs_profile_setup: false,
        auth_method_hint: 'wallet',
        user: uploadUser,
      });
    }

    if (path === '/auth/onboarding/state') {
      return fulfillJson({
        authenticated: true,
        invite_required: false,
        invite_validated: true,
        needs_profile_setup: false,
        auth_method_hint: 'wallet',
      });
    }

    if (path === '/users/me') {
      return fulfillJson(uploadUser);
    }

    if (path === '/privacy/settings') {
      return fulfillJson({
        contract_version: 'privacy.v2',
        profile_visibility: 'public',
        default_ride_visibility: 'public',
        default_map_visibility: 'hide_start_end',
        default_map_hide_start_m: 200,
        default_map_hide_end_m: 200,
        defaults_apply_to: 'future_rides',
        provider_privacy_inherited: false,
        privacy_zone_count: 2,
        privacy_zones_loaded: true,
        ride_override_mode: 'optional',
        protocol_public_fields: [],
      });
    }

    if (path === '/feed' || path === '/feed/global') return fulfillJson({ activities: [], has_more: false });
    if (path === '/feed/home') return fulfillJson({
      contract_version: 'feed_home.v1', scope: 'global',
      viewer: { authenticated: true, user_id: uploadUser.id, wallet: uploadUser.wallet },
      feed: { activities: [], has_more: false, next_cursor: null },
      suggested_riders: [], popular_climbs: [], achievements: [],
      social_counts: { follower_count: 0, following_count: 0 }, notifications: { unread_count: 0 },
    });
    if (path === '/climbs/list') return fulfillJson({ climbs: [] });
    if (path === '/users/me/leaderboard-positions') return fulfillJson({
      wallet: uploadUser.wallet, positions: [],
      stats: { total_positions: 0, kom_count: 0, podium_count: 0, top10_count: 0, total_vaults_completed: 0, best_percentile: null },
    });

    if (path === '/rides') {
      return fulfillJson([]);
    }

    if (path === '/portfolio') {
      return fulfillJson({
        contractVersion: 'portfolio.v5',
        dungBalance: null,
        dungBalanceBaseUnits: null,
        walletDung: { amount: null, amountBaseUnits: null, source: 'spl_wallet_ata', status: 'not_initialized' },
        balanceDung: { amount: null, amountBaseUnits: null, source: 'balance_account', status: 'not_initialized' },
        calBalance: '0',
        calBalanceBaseUnits: '0',
        stakedPositions: [],
        pendingClaims: [],
      });
    }

    if (path === '/climbs/test-climb') {
      return fulfillJson({
        id: 'test-climb',
        name: 'Flagstaff Test Climb',
        length_m: 2400,
        elev_gain_m: 210,
        avg_gradient_pct: 8.8,
        region: 'Boulder, CO',
        truth_source: 'known_climb',
        contract_version: 'client.v1',
      });
    }

    if (path === '/climbs/test-climb/leaderboard') {
      return fulfillJson({
        climb_id: 'test-climb',
        climb_name: 'Flagstaff Test Climb',
        contract_version: 'client.v1',
        truth_source: 'known_climb',
        entries: [],
      });
    }

    if (path === '/strava/connection') {
      return fulfillJson({ connected: false });
    }

    if (path === '/beetles/my-cards') {
      return fulfillJson([]);
    }

    if (path === '/admin/check') {
      return fulfillJson({ is_admin: false, role: null });
    }

    if (path === '/status') {
      return fulfillJson({ solana_stub: false });
    }

    if (path === '/notifications') {
      return fulfillJson({ notifications: [], unread_count: 0 });
    }

    return route.continue();
  });
}

async function expectUploadSurface(page: Page) {
  const uploadSurface = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await expect(uploadSurface).toBeVisible();
  await expect(uploadSurface.locator('.portal-sheet.upload-sheet')).toBeVisible();
  await expect(uploadSurface.getByRole('heading', { name: 'Upload ride', exact: true })).toBeVisible();
  await expect(uploadSurface.getByRole('button', { name: 'Choose file', exact: true })).toBeVisible();
  await expect(uploadSurface.locator('.upload-sheet__field')).toContainText('Choose a FIT, GPX, or TCX file.');
  await expect(uploadSurface.getByRole('button', { name: 'Who can see this ride?', exact: true })).toBeEnabled();
  await expect(uploadSurface.getByRole('button', { name: 'Who can see this ride?', exact: true })).toContainText('Everyone');
  await expect(uploadSurface.getByText('Anyone can open this ride.', { exact: true })).toBeVisible();
  await expect(uploadSurface.getByRole('button', { name: 'Map visibility', exact: true })).toBeEnabled();
  await expect(uploadSurface.getByText('Hide first and last part', { exact: true })).toBeVisible();
  await expect(uploadSurface.getByText('200 m', { exact: true })).toBeVisible();
  await expect(uploadSurface.getByRole('button', { name: 'Privacy zones', exact: true })).toContainText('2');
  await expect(uploadSurface.getByRole('radio')).toHaveCount(0);
  await expect(uploadSurface.getByRole('list', { name: 'Status' })).toHaveCount(0);
  await expect(uploadSurface.getByRole('button', { name: 'Upload ride', exact: true })).toBeDisabled();
  await expect(uploadSurface.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible();
  await expect(uploadSurface.getByText('Training inputs need attention')).toHaveCount(0);
}

async function selectRideFile(page: Page) {
  await page.locator('input[type="file"]').setInputFiles({
    name: 'first-ride.gpx',
    mimeType: 'application/gpx+xml',
    buffer: Buffer.from('<gpx version="1.1"><trk><name>First ride</name></trk></gpx>'),
  });

  const uploadSurface = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await expect(uploadSurface.getByText('first-ride.gpx')).toBeVisible();
  await expect(uploadSurface.getByRole('button', { name: 'Upload ride' })).toBeEnabled();
  await expect(uploadSurface.getByRole('button', { name: 'Cancel', exact: true }).first()).toBeVisible();
  await expect(uploadSurface.getByRole('list', { name: 'Status' })).toHaveCount(0);
}

test.describe('Upload entry points', () => {
  test.beforeEach(async ({ page }) => {
    await routeAuthenticatedUpload(page);
  });

  test('opens the upload flow from the route used by surfaced CTAs', async ({ page }) => {
    await page.goto('/upload');

    await expect(page).toHaveURL(/\/upload$/);
    await expectUploadSurface(page);
    await selectRideFile(page);

    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Cancel', exact: true }).first().click();

    await expect(page).toHaveURL(/\/profile\?tab=rides$/);
  });

  test('blocks upload when the privacy contract is incomplete', async ({ page }) => {
    await page.route('**/privacy/settings', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'privacy.v2',
          profile_visibility: 'public',
          default_ride_visibility: 'public',
          default_map_visibility: 'hide_start_end',
          default_map_hide_start_m: null,
          default_map_hide_end_m: 200,
          defaults_apply_to: 'future_rides',
          provider_privacy_inherited: false,
          privacy_zone_count: 0,
          privacy_zones_loaded: true,
          ride_override_mode: 'optional',
          protocol_public_fields: [],
        }),
      });
    });

    await page.goto('/upload');
    const uploadSurface = page.getByRole('dialog', { name: 'Upload ride', exact: true });
    await expect(uploadSurface.getByRole('alert')).toContainText('Privacy settings unavailable');

    await page.locator('input[type="file"]').setInputFiles({
      name: 'blocked-ride.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Blocked ride</name></trk></gpx>'),
    });
    await expect(uploadSurface.getByRole('button', { name: 'Upload ride' })).toBeDisabled();
  });

  test('keeps upload anchored to the source route from climb pages', async ({ page }) => {
    await page.goto('/climbs/test-climb');

    await page.locator('header').getByRole('button', { name: 'Upload ride', exact: true }).click();

    await expect(page).toHaveURL(/\/climbs\/test-climb$/);
    await expectUploadSurface(page);
    await selectRideFile(page);

    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Cancel', exact: true }).first().click();

    await expect(page).toHaveURL(/\/climbs\/test-climb$/);
  });

  test('routes the existing dashboard upload button to the upload surface', async ({ page }) => {
    await page.goto('/profile?tab=rides');

    await page.locator('header').getByRole('button', { name: 'Upload ride', exact: true }).click();

    await expect(page).toHaveURL(/\/profile\?tab=rides$/);
    await expectUploadSurface(page);
    await selectRideFile(page);

    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Cancel', exact: true }).first().click();

    await expect(page).toHaveURL(/\/profile\?tab=rides$/);
  });

  test('opens the file chooser by mouse and keyboard and keeps drag-and-drop', async ({ page }) => {
    const uploadSurface = page.getByRole('dialog', { name: 'Upload ride', exact: true });

    await page.goto('/upload');
    await expectUploadSurface(page);
    const mouseChooserPromise = page.waitForEvent('filechooser');
    await uploadSurface.getByRole('button', { name: 'Choose file' }).click();
    const mouseChooser = await mouseChooserPromise;
    await mouseChooser.setFiles({
      name: 'mouse-ride.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Mouse ride</name></trk></gpx>'),
    });
    await expect(uploadSurface.getByText('mouse-ride.gpx')).toBeVisible();

    const replacementChooserPromise = page.waitForEvent('filechooser');
    await uploadSurface.getByRole('button', { name: 'Choose another file' }).click();
    const replacementChooser = await replacementChooserPromise;
    await replacementChooser.setFiles({
      name: 'not-a-ride.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('not a ride'),
    });
    await expect(uploadSurface.getByRole('alert')).toHaveText('Choose a FIT, GPX, or TCX file.');
    await expect(uploadSurface.getByText('mouse-ride.gpx')).toHaveCount(0);
    await expect(uploadSurface.getByRole('button', { name: 'Upload ride', exact: true })).toBeDisabled();
    await expect(uploadSurface.getByRole('button', { name: 'Choose file' })).toBeFocused();

    await page.goto('/upload');
    await expectUploadSurface(page);
    const keyboardButton = uploadSurface.getByRole('button', { name: 'Choose file' });
    await keyboardButton.focus();
    const keyboardChooserPromise = page.waitForEvent('filechooser');
    await page.keyboard.press('Enter');
    const keyboardChooser = await keyboardChooserPromise;
    await keyboardChooser.setFiles({
      name: 'keyboard-ride.gpx',
      mimeType: 'application/gpx+xml',
      buffer: Buffer.from('<gpx version="1.1"><trk><name>Keyboard ride</name></trk></gpx>'),
    });
    await expect(uploadSurface.getByText('keyboard-ride.gpx')).toBeVisible();
    await expect(uploadSurface.getByRole('button', { name: 'Upload ride' })).toBeFocused();

    await page.goto('/upload');
    await expectUploadSurface(page);
    await page.locator('.upload-sheet__field').evaluate((target) => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(new File(
        ['<gpx version="1.1"><trk><name>Dropped ride</name></trk></gpx>'],
        'dropped-ride.gpx',
        { type: 'application/gpx+xml' },
      ));
      target.dispatchEvent(new DragEvent('drop', { bubbles: true, dataTransfer }));
    });
    await expect(uploadSurface.getByText('dropped-ride.gpx')).toBeVisible();
  });

  test('captures the quiet upload threshold at approved viewports', async ({ page }) => {
    const artifacts = {
      desktopIdle: process.env.PORTAL_QUIET_UPLOAD_DESKTOP_IDLE ?? 'test-results/quiet-upload-desktop-idle.png',
      desktopSelected: process.env.PORTAL_QUIET_UPLOAD_DESKTOP_SELECTED ?? 'test-results/quiet-upload-desktop-selected.png',
      mobileIdle: process.env.PORTAL_QUIET_UPLOAD_MOBILE_IDLE ?? 'test-results/quiet-upload-mobile-idle.png',
      mobileSelected: process.env.PORTAL_QUIET_UPLOAD_MOBILE_SELECTED ?? 'test-results/quiet-upload-mobile-selected.png',
    };

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto('/upload');
    await expectUploadSurface(page);
    await page.screenshot({ path: artifacts.desktopIdle });
    await selectRideFile(page);
    await page.waitForTimeout(350);
    await page.screenshot({ path: artifacts.desktopSelected });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/upload');
    await expectUploadSurface(page);
    await page.screenshot({ path: artifacts.mobileIdle });
    await selectRideFile(page);
    await page.waitForTimeout(350);
    await page.screenshot({ path: artifacts.mobileSelected });
  });
});

test('opens the approved Upload sheet over the return page', async ({ page }) => {
  await routeAuthenticatedUpload(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/upload');
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await expect(sheet).toBeVisible();
  await expect(sheet).toHaveCSS('width', '640px');
  await expect(sheet).toHaveCSS('top', '84px');
  await expect(sheet.getByRole('button', { name: 'Upload ride', exact: true })).toBeDisabled();
  await expect(sheet.getByRole('radio')).toHaveCount(0);
  await expect(page.locator('.rides-log')).toBeAttached();
});

// Local API fixtures exercise the browser's real upload path, not a live rider upload.
const savedRide = {
  id: 'ride-sheet-1', title: 'In the bag', started_at: '2016-08-28T13:07:00Z',
  distance_m: 128_700, duration_s: 18_000, is_owner: true, attestation_status: 'pending',
  patterns: [1, 2, 3].map((id) => ({ id: `climb-${id}`, type: 'climb' })),
  elevation_profile: boardRide.profile.map(([distance_m, elevation_m]) => ({ distance_m, elevation_m })),
  counted_spans: boardRide.climbs.map(([start_distance_m, end_distance_m]) => ({ start_distance_m, end_distance_m })),
};
function latch() {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => { release = resolve; });
  return { promise, release };
}
async function mockSheetUpload(page: Page, options: { duplicate?: boolean; holdStorage?: boolean; holdProcessing?: boolean; missingRide?: boolean } = {}) {
  const storage = latch(), sending = latch(), processing = latch();
  const requests: Array<{ path: string; method: string; body: string; headers: Record<string, string> }> = [];
  let phase = 'pending';
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, '');
    if (!path.startsWith('/rides') && path !== '/sheet-storage') return route.fallback();
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    requests.push({ path, method: request.method(), body: request.postData() ?? '', headers: request.headers() });
    if (path === '/rides/upload/init') {
      if (options.duplicate) return json({ detail: { error: 'duplicate_file', existing_ride_id: savedRide.id } }, 409);
      return json({ upload_id: 'upload-sheet-1', signed_url: `${url.origin}/sheet-storage`, expires_in: 600 });
    }
    if (path === '/sheet-storage') {
      sending.release();
      if (options.holdStorage) await storage.promise;
      return json({ Key: 'rides/upload-sheet-1.gpx' });
    }
    if (path === '/rides/upload/abort') return json({ status: 'aborted' });
    if (path === '/rides/upload/complete') return json({ ride_id: savedRide.id, status: options.holdProcessing ? 'pending' : 'completed' });
    if (path === `/rides/${savedRide.id}/status`) {
      processing.release();
      return json({ ride_id: savedRide.id, status: phase, phase1_completed_at: phase === 'processing' ? '2026-09-06T12:00:00Z' : null });
    }
    if (path === `/rides/${savedRide.id}`) return options.missingRide ? json({}, 503) : json(savedRide);
    if (path === '/rides') return json(options.missingRide ? [] : [savedRide]);
    return route.fallback();
  });
  return { requests, storage, sending, processing, setPhase: (value: string) => { phase = value; } };
}
async function expectFrozenPrivacy(page: Page) {
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  for (const name of ['Who can see this ride?', 'Map visibility', 'Privacy zones']) {
    await expect(sheet.getByRole('button', { name, exact: true })).toBeDisabled();
  }
  await expect(sheet.locator('.upload-sheet__privacy .upload-sheet__chevron')).toHaveCount(0);
  await expect(sheet.getByRole('radio')).toHaveCount(0);
}
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`choose / saving / saved / duplicate sheet at ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await routeAuthenticatedUpload(page);
    const flow = await mockSheetUpload(page, { holdStorage: true });
    const output = process.env.PORTAL_UPLOAD_SHEET_BUILD ?? 'test-results/upload-sheet';
    const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/');
    await page.locator('header').getByRole('button', { name: 'Upload ride', exact: true }).click();
    await expectUploadSurface(page);
    if (viewport.width === 390) {
      await expect(sheet).toHaveAttribute('data-slot', 'drawer-content');
      await expect(sheet).toHaveCSS('height', '820px');
      await expect(sheet).toHaveCSS('max-height', '820px');
    }
    await settleSheet(page);
    await page.screenshot({ path: `${output}/choose-${viewport.width}.png` });
    await selectRideFile(page);
    await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
    await flow.sending.promise;
    await expectFrozenPrivacy(page);
    await expect(sheet.locator('.upload-sheet__ladder [data-state="live"]')).toHaveText('Saving file');
    await expect(sheet.locator('.upload-sheet__dot')).toHaveCount(3);
    await expect(sheet.locator('[data-upload-bytes]')).toBeEmpty();
    await expect(sheet.locator('[data-upload-percent]')).toHaveText(['', '', '']);
    await settleSheet(page);
    await page.screenshot({ path: `${output}/saving-${viewport.width}.png` });
    if (viewport.width === 1440) {
      await page.mouse.click(12, 12);
      await expect(sheet).toBeVisible();
    }
    flow.storage.release();
    await expect(sheet.getByText('Ride saved', { exact: true })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'In the bag', exact: true })).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
    await expect(sheet.locator('.upload-sheet__ride .climb-shape-glyph')).toHaveAttribute('viewBox', '0 0 120 28');
    await expect(sheet.locator('.climb-shape-glyph__span')).toHaveCount(boardRide.climbs.length);
    await expect(sheet.getByText('128.7 km')).toBeVisible();
    await expect(sheet.getByText('Climbs on this ride').locator('..')).toContainText('3');
    await expect(sheet.locator('[data-state-subject]')).toHaveCount(1);
    await expect(sheet.locator('[data-state-subject="storage"]')).toHaveText('RideSaved');
    await expect(sheet.locator('[data-state-subject="matching"], [data-state-subject="cal"], [data-state-subject="position"], [data-state-subject="collection"]')).toHaveCount(0);
    await expect(sheet.locator('.upload-sheet__states, .upload-sheet__ladder')).toHaveCount(0);
    await expect(sheet.getByText('Stamped', { exact: true })).toHaveCount(0);
    await expect(sheet.getByText('Reading the ride data now.')).toHaveCount(0);
    await settleSheet(page);
    await page.screenshot({ path: `${output}/saved-${viewport.width}.png` });
    await sheet.getByRole('button', { name: 'Close', exact: true }).first().click();
    await expect(page).toHaveURL(/\/$/);
    await expect(sheet).toHaveCount(0);
    const storageRequest = flow.requests.find((request) => request.path === '/sheet-storage');
    expect(storageRequest?.method).toBe('PUT');
    expect(storageRequest?.headers['content-type']).toContain('multipart/form-data;');
    expect(storageRequest?.headers['x-upsert']).toBe('false');
    expect(storageRequest?.body).toContain('name="file"');
    expect(storageRequest?.body).toContain('filename="first-ride.gpx"');
    const init = JSON.parse(flow.requests.find((request) => request.path === '/rides/upload/init')!.body);
    expect(init.visibility).toBe('public');
    expect(init.map_visibility).toBe('hide_start_end');
    expect(init.map_hide_start_m).toBe(200);
    expect(init.map_hide_end_m).toBe(200);
    await mockSheetUpload(page, { duplicate: true });
    await page.goto('/');
    await page.locator('header').getByRole('button', { name: 'Upload ride', exact: true }).click();
    await expectUploadSurface(page);
    await selectRideFile(page);
    await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
    await expect(sheet.getByRole('alert')).toHaveText('This ride is already in your log.');
    await expect(sheet.getByText('Open the ride already in your log.')).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'In the bag', exact: true })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Open saved ride', exact: true })).toHaveCSS('color', 'rgb(241, 238, 232)');
    await expect(sheet.getByRole('button', { name: 'Choose another file', exact: true })).toBeEnabled();
    await settleSheet(page);
    await page.screenshot({ path: `${output}/duplicate-${viewport.width}.png` });
    await sheet.getByRole('button', { name: 'Open saved ride', exact: true }).click();
    await expect(page).toHaveURL(/\/activities\/ride-sheet-1$/);
    expect(errors).toEqual([]);
  });
}

test('privacy rows open shared choices, retain the file, and submit the chosen override', async ({ page }) => {
  await routeAuthenticatedUpload(page);
  const flow = await mockSheetUpload(page);
  await page.goto('/upload');
  await expectUploadSurface(page);
  await selectRideFile(page);
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await sheet.getByRole('button', { name: 'Who can see this ride?', exact: true }).click();
  const audience = page.getByRole('dialog', { name: 'Who can see this ride?', exact: true });
  await expect(audience.getByRole('radio', { name: 'Everyone', exact: true })).toBeChecked();
  await expect(audience.getByRole('radio')).toHaveCount(3);
  await audience.getByRole('radio', { name: 'Only you', exact: true }).check();
  await audience.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(sheet.getByRole('button', { name: 'Who can see this ride?', exact: true })).toContainText('Only you');
  await expect(sheet.getByRole('button', { name: 'Who can see this ride?', exact: true })).toBeFocused();
  await sheet.getByRole('button', { name: 'Map visibility', exact: true }).click();
  const map = page.getByRole('dialog', { name: 'Map visibility', exact: true });
  await expect(map.getByRole('radio', { name: 'Hide first and last part', exact: true })).toBeChecked();
  await expect(map.getByRole('radio')).toHaveCount(3);
  await map.getByLabel('Distance at each end').selectOption('800');
  await map.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(sheet.getByText('800 m', { exact: true })).toBeVisible();
  await expect(sheet.getByText('first-ride.gpx', { exact: true })).toBeVisible();
  await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
  await expect(sheet.getByText('Ride saved', { exact: true })).toBeVisible();
  const init = JSON.parse(flow.requests.find((request) => request.path === '/rides/upload/init')!.body);
  expect(init.visibility).toBe('private');
  expect(init.map_hide_start_m).toBe(800);
  expect(init.map_hide_end_m).toBe(800);
  await sheet.getByRole('button', { name: 'Open ride', exact: true }).click();
  await expect(page).toHaveURL(/\/activities\/ride-sheet-1$/);
});

test('reading and matching keep one live rung and frozen privacy', async ({ page }) => {
  await routeAuthenticatedUpload(page);
  const flow = await mockSheetUpload(page, { holdProcessing: true });
  await page.goto('/upload');
  await expectUploadSurface(page);
  await selectRideFile(page);
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
  await flow.processing.promise;
  await expect(sheet.locator('.upload-sheet__ladder [data-state="live"]')).toHaveText('Reading ride file');
  await expectFrozenPrivacy(page);
  flow.setPhase('processing');
  await expect(sheet.locator('.upload-sheet__ladder [data-state="live"]')).toHaveText('Matching climbs');
  flow.setPhase('metrics_ready');
  await expect(sheet.getByText('Ride saved', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/upload$/);
});

for (const width of [1440, 390]) {
  test(`Cancel aborts once and keeps retry available at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  await routeAuthenticatedUpload(page);
  const flow = await mockSheetUpload(page, { holdStorage: true });
  await page.goto('/upload');
  await expectUploadSurface(page);
  await selectRideFile(page);
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
  await flow.sending.promise;
  await (width === 390 ? sheet : sheet.locator('footer')).getByRole('button', { name: 'Cancel', exact: true }).click();
  flow.storage.release();
  await expect.poll(() => flow.requests.filter((request) => request.path === '/rides/upload/abort').length).toBe(1);
  await expect(sheet.getByRole('button', { name: 'Try again', exact: true })).toBeEnabled();
  expect(flow.requests.filter((request) => request.path === '/rides/upload/complete')).toHaveLength(0);
});
}

async function settleSheet(page: Page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(document.getAnimations().filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity).map((animation) => animation.finished.catch(() => {})));
  });
}

test('leaves missing saved-ride fields empty and still opens the saved id', async ({ page }) => {
  await routeAuthenticatedUpload(page);
  await mockSheetUpload(page, { missingRide: true });
  await page.goto('/upload');
  await expectUploadSurface(page);
  await selectRideFile(page);
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
  await expect(sheet.getByText('Ride saved', { exact: true })).toBeVisible();
  await expect(sheet.locator('.rides-log__name')).toBeEmpty();
  await expect(sheet.locator('.rides-log__sub')).toHaveCount(0);
  await expect(sheet.locator('.rides-log__value')).toHaveText('›');
  await expect(sheet.locator('svg.climb-shape-glyph')).toHaveCount(0);
  await expect(sheet.getByText('Climbs on this ride').locator('..').locator('.upload-sheet__value')).toBeEmpty();
  await expect(sheet.locator('.upload-sheet__state-line')).toHaveCount(0);
  await sheet.locator('footer').getByRole('button', { name: 'Open ride', exact: true }).click();
  await expect(page).toHaveURL(/\/activities\/ride-sheet-1$/);
});

test('replaces a duplicate file and retains the ordinary error retry choices', async ({ page }) => {
  await routeAuthenticatedUpload(page);
  await mockSheetUpload(page, { duplicate: true });
  await page.goto('/upload');
  await expectUploadSurface(page);
  await selectRideFile(page);
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
  await expect(sheet.getByRole('alert')).toHaveText('This ride is already in your log.');
  const chooser = page.waitForEvent('filechooser');
  await sheet.getByRole('button', { name: 'Choose another file', exact: true }).click();
  await (await chooser).setFiles({ name: 'replacement.gpx', mimeType: 'application/gpx+xml', buffer: Buffer.from('<gpx/>') });
  await expect(sheet.getByRole('button', { name: 'Open saved ride', exact: true })).toHaveCount(0);
  await expect(sheet.getByRole('button', { name: 'Upload ride', exact: true })).toBeEnabled();
  await expect(sheet.getByRole('button', { name: 'Map visibility', exact: true })).toBeEnabled();
  await page.route('**/rides/upload/init', (route) => route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'invalid file parse' }) }));
  await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
  await expect(sheet.getByRole('alert')).toHaveText('Could not read this file.');
  await expect(sheet.getByText('Try exporting the original file again.')).toBeVisible();
  await expect(sheet.getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0);
  await expect(sheet.locator('footer').getByRole('button', { name: 'Choose another file', exact: true })).toBeEnabled();
});

test('the phone privacy picker changes map visibility without losing the file', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await routeAuthenticatedUpload(page);
  await page.goto('/upload');
  await expectUploadSurface(page);
  await selectRideFile(page);
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await sheet.getByRole('button', { name: 'Map visibility', exact: true }).click();
  const picker = page.getByRole('dialog', { name: 'Map visibility', exact: true });
  await expect(picker).toHaveAttribute('data-slot', 'drawer-content');
  await picker.getByRole('radio', { name: 'Hide entire map', exact: true }).check();
  await picker.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(sheet.getByText('Hide entire map', { exact: true })).toBeVisible();
  await expect(sheet.getByText('first-ride.gpx', { exact: true })).toBeVisible();
  await expect(sheet.getByRole('button', { name: 'Map visibility', exact: true })).toBeFocused();
});

test('Privacy zones opens the existing Settings privacy destination', async ({ page }) => {
  await routeAuthenticatedUpload(page);
  await page.goto('/upload');
  await expectUploadSurface(page);
  await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Privacy zones', exact: true }).click();
  await expect(page).toHaveURL(/\/settings\?tab=privacy$/);
  await expect(page.getByRole('dialog', { name: 'Upload ride', exact: true })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Privacy zones', exact: true })).toBeVisible();
});

test('deep-link returnTo keeps its query and hash, and rejects external or recursive pages', async ({ page }) => {
  await routeAuthenticatedUpload(page);
  for (const returnTo of ['/profile?tab=rides#upload-return', '//example.com', '/upload?again=1']) {
    await page.goto('/profile?tab=rides');
    await page.evaluate((target) => {
      window.history.pushState({ usr: { returnTo: target } }, '', '/upload');
      window.dispatchEvent(new PopStateEvent('popstate'));
    }, returnTo);
    await expectUploadSurface(page);
    await expect(page.locator('.rides-log')).toBeAttached();
    await page.getByRole('dialog', { name: 'Upload ride', exact: true }).getByRole('button', { name: 'Cancel', exact: true }).click();
    await expect(page).toHaveURL(returnTo.startsWith('/profile') ? /\/profile\?tab=rides#upload-return$/ : /\/profile\?tab=rides$/);
  }
});
