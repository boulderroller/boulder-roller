import fs from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const settingsUser = {
  id: 'user-settings-1',
  wallet: '8xF6yDbvJfRiderWallet111111111111111111111',
  username: 'riderone',
  bio: 'Beta rider',
  location: 'Boulder, CO',
  ftp_w: 250,
  weight_kg: 75,
  rider_type: 'climber',
  preferred_units: 'metric',
  theme_id: 'hoo-breddin',
  is_dark_mode: true,
  is_public: true,
  default_ride_visibility: 'public',
  total_rides: 3,
  total_distance_km: 88,
  total_elevation_m: 1200,
  total_tss: 185,
  total_kcals: 2400,
  total_duration_sec: 7200,
  total_dung_earned: 12,
  cal_earned_today: 0,
  dung_earned_today: 0,
};
const deletionCapabilityKey = `br_account_deletion_capability_v2:${settingsUser.wallet}`;
const deletionActiveWalletKey = 'br_account_deletion_active_wallet_v2';
const deletionRecoveryKey = `br_account_deletion_unconfirmed_v1:${settingsUser.wallet}`;

async function routeAuthenticatedSettings(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('br_authenticated', 'true');
  });

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, '');

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
        user: settingsUser,
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
      if (request.method() === 'PUT') {
        const body = request.postDataJSON() as Record<string, unknown>;
        return fulfillJson({
          ...settingsUser,
          username: body.username ?? settingsUser.username,
          bio: body.bio ?? settingsUser.bio,
          location: body.location ?? settingsUser.location,
          ftp_w: body.ftp_w ?? settingsUser.ftp_w,
          weight_kg: body.weight_kg ?? settingsUser.weight_kg,
          rider_type: body.rider_type ?? settingsUser.rider_type,
          preferred_units: body.units ?? settingsUser.preferred_units,
          theme_id: body.theme_id ?? settingsUser.theme_id,
          is_dark_mode: body.is_dark_mode ?? settingsUser.is_dark_mode,
          is_public: body.is_public ?? settingsUser.is_public,
          default_ride_visibility: body.default_ride_visibility ?? settingsUser.default_ride_visibility,
        });
      }

      return fulfillJson(settingsUser);
    }

    if (path === '/users/me/threshold') {
      return fulfillJson({
        contract_version: 'threshold.v1',
        state: 'established',
        current_w: 245,
        established_at: '2026-08-17T12:00:00Z',
        last_raised_at: null,
        pending_monday: null,
        sealing_in_progress: false,
      });
    }

    if (path === '/privacy/settings') {
      const body = request.method() === 'PUT'
        ? request.postDataJSON() as Record<string, unknown>
        : {};
      return fulfillJson({
        contract_version: 'privacy.v2',
        profile_visibility: body.is_public === false ? 'private' : 'public',
        default_ride_visibility: body.default_ride_visibility ?? 'public',
        default_map_visibility: body.default_map_visibility ?? 'hide_start_end',
        default_map_hide_start_m: body.default_map_hide_start_m ?? 200,
        default_map_hide_end_m: body.default_map_hide_end_m ?? 200,
        defaults_apply_to: 'future_rides',
        provider_privacy_inherited: false,
        privacy_zone_count: 0,
        privacy_zones_loaded: true,
        ride_override_mode: 'optional',
        protocol_public_fields: [],
      });
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

    if (path === '/notifications/preferences') {
      if (request.method() === 'PUT') {
        return fulfillJson(request.postDataJSON());
      }
      return fulfillJson({
        email_enabled: true,
        push_enabled: false,
        in_app_enabled: true,
        leaderboard_updates: true,
        payout_alerts: true,
        social_activity: true,
        system_announcements: false,
      });
    }

    if (path === '/privacy/zones') {
      if (request.method() === 'POST') {
        const body = request.postDataJSON() as {
          latitude: number;
          longitude: number;
          radius_m: number;
          label?: string;
        };

        return fulfillJson({
          id: 'privacy-zone-new',
          latitude: body.latitude,
          longitude: body.longitude,
          radiusM: body.radius_m,
          label: body.label,
          createdAt: '2026-08-02T12:00:00.000Z',
          updatedAt: '2026-08-02T12:00:00.000Z',
        }, 201);
      }

      return fulfillJson({ zones: [], maxZones: 5 });
    }

    return route.continue();
  });
}

function expectNoGeocodingRequests(requestUrls: string[]) {
  const nominatimRequests = requestUrls.filter((requestUrl) => (
    new URL(requestUrl).hostname === 'nominatim.openstreetmap.org'
  ));
  const geocodingEndpointRequests = requestUrls.filter((requestUrl) => (
    /\/(?:geocod(?:e|ing)|nominatim|locations?\/search)(?:\/|$)/i.test(new URL(requestUrl).pathname)
  ));

  expect(nominatimRequests).toEqual([]);
  expect(geocodingEndpointRequests).toEqual([]);
}

test.describe('Settings', () => {
  test.beforeEach(async ({ page }) => {
    await routeAuthenticatedSettings(page);
  });

  for (const initial of [undefined, false, true]) {
    test(`Show my W/kg loads ${initial}, saves only the explicit opt-in and retains a failed draft`, async ({ page }) => {
      let saved = initial;
      let fail = false;
      const writes: unknown[] = [];
      await page.route('**/privacy/settings', async route => {
        if (route.request().method() === 'PUT') {
          const body = route.request().postDataJSON();
          writes.push(body);
          if (fail) return route.fulfill({ status: 400, json: { detail: 'Cannot save' } });
          saved = body.share_wkg;
        }
        return route.fulfill({ json: {
          contract_version: 'privacy.v2', profile_visibility: 'public',
          default_ride_visibility: 'public', default_map_visibility: 'hide_start_end',
          default_map_hide_start_m: 200, default_map_hide_end_m: 200,
          defaults_apply_to: 'future_rides', provider_privacy_inherited: false,
          privacy_zone_count: 0, privacy_zones_loaded: true, ride_override_mode: 'optional',
          protocol_public_fields: [], ...(saved === undefined ? {} : { share_wkg: saved }),
        } });
      });
      await page.goto('/settings?tab=privacy');
      const toggle = page.getByRole('switch', { name: 'Show my W/kg', exact: true });
      await expect(toggle).toHaveAttribute('aria-checked', String(initial === true));
      await expect(toggle).toHaveAccessibleDescription('Other riders see your watts per kilo next to your power. Together they reveal your weight.');
      await toggle.click();
      expect(writes).toEqual([]);
      await page.getByRole('button', { name: 'Save', exact: true }).click();
      await expect.poll(() => writes).toEqual([{ share_wkg: initial !== true }]);
      await expect(page.getByRole('button', { name: 'Save', exact: true })).toHaveCount(0);
      await page.reload();
      await expect(toggle).toHaveAttribute('aria-checked', String(initial !== true));
      fail = true;
      await toggle.click();
      await page.getByRole('button', { name: 'Save', exact: true }).click();
      await expect(page.getByText('Could not save settings', { exact: true })).toBeVisible();
      await expect(toggle).toHaveAttribute('aria-checked', String(initial === true));
      await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();
      // Like the existing privacy controls, an unsaved draft remains editable.
      // A reload proves the failed request did not change the saved preference.
      await page.reload();
      await expect(toggle).toHaveAttribute('aria-checked', String(initial !== true));
    });
  }

  for (const width of [1440, 390]) {
    test(`keeps essential privacy notes readable at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
      await page.goto('/settings?tab=privacy');
      await expect(page.getByText('No privacy zones saved.', { exact: true })).toBeVisible();
      const notes = page.locator('.settings-page .ride-privacy-controls__summary, .settings-page .ride-privacy-controls__zones, .settings-sheet__note, .settings-v2-actions__status .portal-truth-pill');
      const measurements = await notes.evaluateAll((elements) => {
        const rgb = (value: string) => (value.match(/[\d.]+/g) ?? []).map(Number);
        const luminance = (channels: number[]) => channels.slice(0, 3).map((value) => {
          const s = value / 255;
          return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
        }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
        return elements.filter((el) => el.getClientRects().length > 0).map((el) => {
          let ancestor: Element | null = el;
          let background: number[] = [];
          while (ancestor) {
            const candidate = rgb(getComputedStyle(ancestor).backgroundColor);
            if (candidate.length === 3 || candidate[3] === 1) { background = candidate; break; }
            ancestor = ancestor.parentElement;
          }
          const foreground = luminance(rgb(getComputedStyle(el).color));
          const back = luminance(background);
          return { text: el.textContent?.trim(), opaqueBackgroundFound: background.length >= 3, contrast: (Math.max(foreground, back) + 0.05) / (Math.min(foreground, back) + 0.05) };
        });
      });
      expect(measurements.length).toBeGreaterThanOrEqual(4);
      for (const item of measurements) {
        expect(item.opaqueBackgroundFound, item.text).toBe(true);
        expect(item.contrast, item.text).toBeGreaterThanOrEqual(4.5);
      }
      await page.screenshot({ path: `test-results/settings-privacy-readable-${width}.png`, fullPage: true });
    });
  }

  test('keeps the selected settings section in the URL after saving', async ({ page }) => {
    let privacyUpdateCount = 0;
    const profileUpdates: Array<Record<string, unknown>> = [];
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'PUT' && path === '/privacy/settings') {
        privacyUpdateCount += 1;
      }
      if (request.method() === 'PUT' && path === '/users/me') {
        profileUpdates.push(request.postDataJSON() as Record<string, unknown>);
      }
    });
    await page.goto('/settings?tab=performance');

    await expect(page).toHaveURL(/\/settings\?tab=performance$/);
    await expect(page.getByRole('heading', { name: 'Threshold' })).toBeVisible();
    await expect(page.getByText('derived from your rides', { exact: true })).toBeVisible();
    await expect(page.getByText('245 W', { exact: true })).toBeVisible();
    await expect(page.getByLabel(/FTP/i)).toHaveCount(0);
    await expect(page.getByText(/recalculate all historical stress scores/i)).toHaveCount(0);

    // Save appears only once something changed (the avatar-sheet header rule).
    await page.getByRole('spinbutton', { name: /Weight/ }).fill('74');
    await page.getByRole('button', { name: 'Save' }).click();

    await expect(page).toHaveURL(/\/settings\?tab=performance$/);
    await expect(page.getByRole('heading', { name: 'Threshold' })).toBeVisible();
    expect(privacyUpdateCount).toBe(0);
    expect(profileUpdates).toHaveLength(1);
    expect(profileUpdates[0]).not.toHaveProperty('is_public');
    expect(profileUpdates[0]).not.toHaveProperty('rider_type');
    expect(profileUpdates[0]).not.toHaveProperty('ftp_w');
  });

  test('keeps Threshold absence honest and retries a failed authority read', async ({ page }) => {
    let authorityAvailable = false;
    let readCount = 0;
    await page.route('**/users/me/threshold', (route) => {
      readCount += 1;
      if (!authorityAvailable) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: { code: 'threshold_authority_unavailable' } }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'threshold.v1',
          state: 'established',
          current_w: 245,
          established_at: '2026-08-17T12:00:00Z',
          last_raised_at: null,
          pending_monday: null,
          sealing_in_progress: false,
        }),
      });
    });

    await page.goto('/settings?tab=performance');
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
    await expect(page.getByText('null W', { exact: true })).toHaveCount(0);

    authorityAvailable = true;
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.getByText('245 W', { exact: true })).toBeVisible();
    expect(readCount).toBeGreaterThanOrEqual(2);
  });

  test('files a blocked account deletion request so the server can route it', async ({ page }) => {
    let deleteCount = 0;
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        allowed: false,
        available: true,
        blockers: [{
          code: 'stake_remains',
          category: 'stake',
          amount_base_units: '42',
          action: 'open_balance',
        }],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    await page.route('**/compliance/account', (route) => {
      if (route.request().method() !== 'DELETE') return route.fallback();
      deleteCount += 1;
      const body = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: body.request_id, status: 'blocked',
          requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:00Z', completed_at: null,
          blockers: [{ code: 'stake_remains', category: 'stake', action: 'open_balance' }],
          failure_code: null, retryable: true, attempt_count: 0,
        }),
      });
    });
    await page.route('**/compliance/deletion-status/*', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', request_id: route.request().url().split('/').at(-1), status: 'blocked',
        requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:00Z', completed_at: null,
        blockers: [{ code: 'stake_remains', category: 'stake', action: 'open_balance' }],
        failure_code: null, retryable: true, attempt_count: 0,
      }),
    }));

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();

    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await expect(dialog.getByText('Account deletion blocked')).toBeVisible();
    await expect(dialog.getByText('Vault position remains')).toBeVisible();
    await expect(dialog).not.toContainText('permanent');
    await expect(dialog.locator('[data-slot="dialog-description"]')).toHaveText(
      'Your identity and personal data will be removed. Your climb times, leaderboard history, and settled economics will remain linked to an anonymous account.',
    );
    await dialog.getByRole('checkbox', { name: 'Unuploaded rides reviewed' }).check();
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE');
    await dialog.getByRole('button', { name: 'Request account deletion' }).click();
    await expect(page).toHaveURL(/\/account-deletion$/);
    await expect(page.getByRole('heading', { name: 'Account deletion blocked' })).toBeVisible();
    expect(deleteCount).toBe(1);
  });

  test('fails closed on a malformed server preflight without sending DELETE', async ({ page }) => {
    let deleteCount = 0;
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v0',
        allowed: true,
        available: true,
        blockers: [],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    page.on('request', (request) => {
      const requestPath = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'DELETE' && requestPath === '/compliance/account') {
        deleteCount += 1;
      }
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();

    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await expect(dialog.getByText('Account check unavailable')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Request account deletion' })).toHaveCount(0);
    expect(deleteCount).toBe(0);
  });

  test('does not send DELETE until unuploaded rides are acknowledged', async ({ page }) => {
    let deleteCount = 0;
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        allowed: true,
        available: true,
        blockers: [],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    page.on('request', (request) => {
      const requestPath = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'DELETE' && requestPath === '/compliance/account') {
        deleteCount += 1;
      }
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE');

    await expect(dialog.getByRole('button', { name: 'Request account deletion' })).toBeDisabled();
    expect(deleteCount).toBe(0);
  });

  test('does not send DELETE when wallet-scoped browser storage is unavailable', async ({ page }) => {
    let deleteCount = 0;
    await page.addInitScript(() => {
      const originalSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function setItem(key: string, value: string) {
        if (key.startsWith('br_account_deletion_capability_v2:') || key === 'br_account_deletion_storage_probe_v2') {
          throw new DOMException('Storage unavailable', 'QuotaExceededError');
        }
        return originalSetItem.call(this, key, value);
      };
    });
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        allowed: true,
        available: true,
        blockers: [],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    page.on('request', (request) => {
      const requestPath = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'DELETE' && requestPath === '/compliance/account') {
        deleteCount += 1;
      }
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await dialog.getByRole('checkbox', { name: 'Unuploaded rides reviewed' }).check();
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE');
    await dialog.getByRole('button', { name: 'Request account deletion' }).click();

    await expect(dialog.getByText('This browser cannot save account deletion status.')).toBeVisible();
    expect(deleteCount).toBe(0);
  });

  test('does not claim a deletion request when browser storage cannot be read', async ({ page }) => {
    await page.addInitScript(() => {
      const originalGetItem = Storage.prototype.getItem;
      Storage.prototype.getItem = function getItem(key: string) {
        if (key.startsWith('br_account_deletion_')) {
          throw new DOMException('Storage unavailable', 'SecurityError');
        }
        return originalGetItem.call(this, key);
      };
    });

    await page.goto('/settings?tab=privacy');

    await expect(page.getByText('Account deletion request', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Browser storage unavailable' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'View deletion status' })).toHaveCount(0);
  });

  test('routes a support preflight to support instead of Portfolio', async ({ page }) => {
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        allowed: false,
        available: true,
        blockers: [{
          code: 'policy_review_required',
          category: 'policy',
          source: 'on_chain_deletion_boundary',
          action: 'contact_support',
        }],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    await page.route('**/compliance/account', (route) => {
      if (route.request().method() !== 'DELETE') return route.fallback();
      const body = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: body.request_id, status: 'needs_support',
          requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:00Z', completed_at: null,
          blockers: [{
            code: 'policy_review_required', category: 'policy', source: 'on_chain_deletion_boundary', action: 'contact_support',
          }],
          failure_code: null, retryable: false, attempt_count: 0,
        }),
      });
    });
    await page.route('**/compliance/deletion-status/*', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', request_id: route.request().url().split('/').at(-1), status: 'needs_support',
        requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:00Z', completed_at: null,
        blockers: [{
          code: 'policy_review_required', category: 'policy', source: 'on_chain_deletion_boundary', action: 'contact_support',
        }],
        failure_code: null, retryable: false, attempt_count: 0,
      }),
    }));

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();

    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await expect(dialog.getByText('Support review')).toBeVisible();
    await expect(dialog.getByRole('link', { name: 'Contact support' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Open Portfolio' })).toHaveCount(0);
    await expect(dialog.getByRole('button', { name: 'Request account deletion' })).toBeVisible();
    await expect(dialog).not.toContainText('Server preflight');
    await dialog.getByRole('checkbox', { name: 'Unuploaded rides reviewed' }).check();
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE');
    await dialog.getByRole('button', { name: 'Request account deletion' }).click();
    await expect(page.getByRole('heading', { name: 'Account deletion needs support' })).toBeVisible();
  });

  test('routes a lifecycle creation conflict to support without saving an unaccepted request', async ({ page }) => {
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', allowed: true, available: true, blockers: [],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    await page.route('**/compliance/account', (route) => {
      if (route.request().method() !== 'DELETE') return route.fallback();
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'account_unavailable' } }),
      });
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await dialog.getByRole('checkbox', { name: 'Unuploaded rides reviewed' }).check();
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE');
    await dialog.getByRole('button', { name: 'Request account deletion' }).click();

    await expect(dialog.getByText('This account cannot file a new deletion request.')).toBeVisible();
    await expect(dialog.getByRole('link', { name: 'Contact support' })).toBeVisible();
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionCapabilityKey)).toBeNull();
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionRecoveryKey)).toBeNull();
  });

  test('does not overwrite a deletion capability saved while the modal is open', async ({ page }) => {
    let deleteCount = 0;
    const existingRequestId = '477e40d2-930e-4cb1-8a9c-0059401a68f1';
    const existingStatusToken = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        allowed: true,
        available: true,
        blockers: [],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    await page.route('**/compliance/deletion-status/*', (route) => route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { code: 'request_not_found' } }),
    }));
    page.on('request', (request) => {
      const requestPath = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'DELETE' && requestPath === '/compliance/account') {
        deleteCount += 1;
      }
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await dialog.getByRole('checkbox', { name: 'Unuploaded rides reviewed' }).check();
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE');
    await page.evaluate(({ requestId, token }) => {
      const wallet = '8xF6yDbvJfRiderWallet111111111111111111111';
      localStorage.setItem(`br_account_deletion_capability_v2:${wallet}`, JSON.stringify({
        version: 2,
        wallet,
        requestId,
        statusToken: token,
        createdAt: '2026-08-24T12:00:00.000Z',
      }));
      localStorage.setItem('br_account_deletion_active_wallet_v2', wallet);
    }, { requestId: existingRequestId, token: existingStatusToken });

    await dialog.getByRole('button', { name: 'Request account deletion' }).click();

    await expect(page).toHaveURL(/\/account-deletion$/);
    expect(deleteCount).toBe(0);
    expect(await page.evaluate(() => JSON.parse(
      localStorage.getItem('br_account_deletion_capability_v2:8xF6yDbvJfRiderWallet111111111111111111111') || '{}',
    ).requestId)).toBe(existingRequestId);
  });

  test('recovers and re-submits the identical request after an ambiguous response and reload', async ({ page }) => {
    const submittedBodies: Array<Record<string, unknown>> = [];
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        allowed: true,
        available: true,
        blockers: [],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    await page.route('**/compliance/account', (route) => {
      if (route.request().method() !== 'DELETE') return route.fallback();
      const body = route.request().postDataJSON() as Record<string, unknown>;
      submittedBodies.push(body);
      if (submittedBodies.length === 1) {
        return route.abort('connectionreset');
      }
      return route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1',
          request_id: body.request_id,
          status: 'queued',
          requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:04Z',
          completed_at: null,
          blockers: [],
          failure_code: null,
          retryable: false,
          attempt_count: 0,
        }),
      });
    });
    await page.route('**/compliance/deletion-status/*', (route) => {
      if (submittedBodies.length < 2) return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'request_not_found' } }),
      });
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1',
          request_id: route.request().url().split('/').at(-1),
          status: 'queued',
          requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:04Z',
          completed_at: null,
          blockers: [],
          failure_code: null,
          retryable: false,
          attempt_count: 0,
        }),
      });
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await dialog.getByRole('checkbox', { name: 'Unuploaded rides reviewed' }).check();
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE');
    await dialog.getByRole('button', { name: 'Request account deletion' }).click();

    await expect(dialog.getByText('The request was not confirmed. You can reload or try again with the same saved request.')).toBeVisible();
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionCapabilityKey)).toBeNull();
    expect(await page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}'), deletionRecoveryKey)).toMatchObject({
      version: 1,
      state: 'unconfirmed',
      capability: {
        version: 2,
        wallet: settingsUser.wallet,
      },
    });

    await page.reload();
    await page.getByRole('button', { name: 'Continue deletion request' }).click();
    const recoveryDialog = page.getByRole('dialog', { name: 'Delete account' });
    await recoveryDialog.getByRole('checkbox', { name: 'Unuploaded rides reviewed' }).check();
    await recoveryDialog.getByLabel('Type DELETE to confirm').fill('DELETE');
    await recoveryDialog.getByRole('button', { name: 'Try request again' }).click();
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(submittedBodies).toHaveLength(2);
    expect(submittedBodies[1]).toEqual(submittedBodies[0]);
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionRecoveryKey)).toBeNull();
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionCapabilityKey)).not.toBeNull();
  });

  test('can remove an unconfirmed recovery without claiming to cancel the server request', async ({ page }) => {
    await page.addInitScript(({ wallet, recoveryKey }) => {
      localStorage.setItem(recoveryKey, JSON.stringify({
        version: 1,
        state: 'unconfirmed',
        capability: {
          version: 2,
          wallet,
          requestId: '377e40d2-930e-4cb1-8a9c-0059401a68f1',
          statusToken: 'GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG',
          createdAt: '2026-08-24T12:00:00.000Z',
        },
        persistedAt: '2026-08-24T12:00:01.000Z',
      }));
      localStorage.setItem('br_account_deletion_unconfirmed_active_wallet_v1', wallet);
    }, { wallet: settingsUser.wallet, recoveryKey: deletionRecoveryKey });
    await page.route('**/compliance/deletion-status/*', (route) => route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { code: 'request_not_found' } }),
    }));
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', allowed: true, available: true,
        blockers: [], checked_at: '2026-08-24T12:00:00Z',
      }),
    }));

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Continue deletion request' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await expect(dialog.getByText('Removing this saved recovery does not cancel a server request.')).toBeVisible();
    await dialog.getByRole('button', { name: 'Remove saved recovery request' }).click();

    expect(await page.evaluate((key) => localStorage.getItem(key), deletionRecoveryKey)).toBeNull();
    await expect(page.getByRole('button', { name: 'Delete account' })).toBeVisible();
  });

  test('can remove a malformed current-wallet recovery without filing a request', async ({ page }) => {
    await page.addInitScript(({ recoveryKey, wallet }) => {
      localStorage.setItem(recoveryKey, '{"version":1,"state":"unconfirmed","capability":{"wallet":"broken"}}');
      localStorage.setItem('br_account_deletion_unconfirmed_active_wallet_v1', wallet);
    }, { recoveryKey: deletionRecoveryKey, wallet: settingsUser.wallet });
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', allowed: true, available: true,
        blockers: [], checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    let deleteCount = 0;
    page.on('request', (request) => {
      const requestPath = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'DELETE' && requestPath === '/compliance/account') {
        deleteCount += 1;
      }
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Review saved recovery' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await expect(dialog.getByText('The saved account deletion recovery request is invalid.')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Request account deletion' })).toBeDisabled();
    await dialog.getByRole('button', { name: 'Remove saved recovery request' }).click();

    expect(deleteCount).toBe(0);
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionRecoveryKey)).toBeNull();
    await expect(page.getByRole('button', { name: 'Delete account' })).toBeVisible();
  });

  test('never reuses an unconfirmed recovery that belongs to another wallet', async ({ page }) => {
    const otherWallet = 'OtherRiderWallet111111111111111111111111111';
    await page.addInitScript(({ recoveryKey, wallet }) => {
      localStorage.setItem(recoveryKey, JSON.stringify({
        version: 1,
        state: 'unconfirmed',
        capability: {
          version: 2,
          wallet,
          requestId: '397e40d2-930e-4cb1-8a9c-0059401a68f1',
          statusToken: 'HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH',
          createdAt: '2026-08-24T12:00:00.000Z',
        },
        persistedAt: '2026-08-24T12:00:01.000Z',
      }));
    }, { recoveryKey: deletionRecoveryKey, wallet: otherWallet });
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', allowed: true, available: true,
        blockers: [], checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    let deleteCount = 0;
    page.on('request', (request) => {
      const requestPath = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'DELETE' && requestPath === '/compliance/account') {
        deleteCount += 1;
      }
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Review saved recovery' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await expect(dialog.getByText('The saved account deletion recovery request is invalid.')).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Request account deletion' })).toBeDisabled();
    await dialog.getByRole('button', { name: 'Remove saved recovery request' }).click();

    expect(deleteCount).toBe(0);
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionRecoveryKey)).toBeNull();
  });

  test('persists wallet-scoped status only after server acceptance and reports queued state', async ({ page }) => {
    let deleteCount = 0;
    let capabilityAtDelete: unknown = null;
    let recoveryEnvelopeAtDelete: unknown = null;
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        allowed: true,
        available: true,
        blockers: [],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));
    await page.route('**/compliance/account', async (route) => {
      if (route.request().method() !== 'DELETE') return route.fallback();
      deleteCount += 1;
      capabilityAtDelete = await page.evaluate(() => {
        const raw = localStorage.getItem('br_account_deletion_capability_v2:8xF6yDbvJfRiderWallet111111111111111111111');
        return raw ? JSON.parse(raw) : null;
      });
      recoveryEnvelopeAtDelete = await page.evaluate(() => {
        const raw = localStorage.getItem('br_account_deletion_unconfirmed_v1:8xF6yDbvJfRiderWallet111111111111111111111');
        return raw ? JSON.parse(raw) : null;
      });
      const body = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1',
          request_id: body.request_id,
          status: 'queued',
          requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:00Z',
          completed_at: null,
          blockers: [],
          failure_code: null,
          retryable: false,
          attempt_count: 0,
        }),
      });
    });
    await page.route('**/compliance/deletion-status/*', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        request_id: route.request().url().split('/').at(-1),
        status: 'processing',
        requested_at: '2026-08-24T12:00:00Z',
        updated_at: '2026-08-24T12:00:01Z',
        completed_at: null,
        blockers: [],
        failure_code: null,
        retryable: false,
        attempt_count: 1,
      }),
    }));

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Delete account' }).click();
    const dialog = page.getByRole('dialog', { name: 'Delete account' });
    await expect(dialog.getByText('Account check passed')).toBeVisible();
    await dialog.getByRole('checkbox', { name: 'Unuploaded rides reviewed' }).check();
    await dialog.getByLabel('Type DELETE to confirm').fill('DELETE');
    await dialog.getByRole('button', { name: 'Request account deletion' }).click();

    await expect(page).toHaveURL(/\/account-deletion$/);
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    await expect(page.getByText('Account deleted')).toHaveCount(0);
    expect(deleteCount).toBe(1);
    expect(capabilityAtDelete).toBeNull();
    expect(recoveryEnvelopeAtDelete).toMatchObject({
      version: 1,
      state: 'unconfirmed',
      capability: { version: 2, wallet: settingsUser.wallet },
    });
    expect(await page.evaluate((key) => JSON.parse(localStorage.getItem(key) || '{}'), deletionCapabilityKey)).toMatchObject({
      version: 2,
      wallet: settingsUser.wallet,
    });
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionActiveWalletKey)).toBe(settingsUser.wallet);
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionRecoveryKey)).toBeNull();
  });

  test('does not surface another wallet deletion request in this rider settings', async ({ page }) => {
    await page.addInitScript(() => {
      const otherWallet = 'OtherRiderWallet111111111111111111111111111';
      localStorage.setItem(`br_account_deletion_capability_v2:${otherWallet}`, JSON.stringify({
        version: 2,
        wallet: otherWallet,
        requestId: '477e40d2-930e-4cb1-8a9c-0059401a68f1',
        statusToken: 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB',
        createdAt: '2026-08-24T12:00:00.000Z',
      }));
      localStorage.setItem('br_account_deletion_active_wallet_v2', otherWallet);
    });
    await page.route('**/compliance/account/preflight', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', allowed: true, available: true, blockers: [],
        checked_at: '2026-08-24T12:00:00Z',
      }),
    }));

    await page.goto('/settings?tab=privacy');

    await expect(page.getByRole('button', { name: 'Delete account' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'View deletion status' })).toHaveCount(0);
  });

  test('opens the current wallet status when another wallet is marked active', async ({ page }) => {
    const currentRequestId = '577e40d2-930e-4cb1-8a9c-0059401a68f1';
    const otherWallet = 'OtherRiderWallet111111111111111111111111111';
    await page.addInitScript(({ currentWallet, currentKey, activeKey, currentId, other }) => {
      localStorage.setItem(currentKey, JSON.stringify({
        version: 2,
        wallet: currentWallet,
        requestId: currentId,
        statusToken: 'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC',
        createdAt: '2026-08-24T12:00:00.000Z',
      }));
      localStorage.setItem(`br_account_deletion_capability_v2:${other}`, JSON.stringify({
        version: 2,
        wallet: other,
        requestId: '677e40d2-930e-4cb1-8a9c-0059401a68f1',
        statusToken: 'DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD',
        createdAt: '2026-08-24T12:00:00.000Z',
      }));
      localStorage.setItem(activeKey, other);
    }, {
      currentWallet: settingsUser.wallet,
      currentKey: deletionCapabilityKey,
      activeKey: deletionActiveWalletKey,
      currentId: currentRequestId,
      other: otherWallet,
    });
    let currentStatusReads = 0;
    await page.route(`**/compliance/deletion-status/${currentRequestId}`, (route) => {
      currentStatusReads += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: currentRequestId, status: 'queued',
          requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:00Z', completed_at: null,
          blockers: [], failure_code: null, retryable: false, attempt_count: 0,
        }),
      });
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'View deletion status' }).click();

    await expect(page).toHaveURL(/\/account-deletion$/);
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(currentStatusReads).toBeGreaterThan(0);
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionActiveWalletKey)).toBe(settingsUser.wallet);
  });

  test('tracking banner activates the current wallet when the active pointer is missing', async ({ page }) => {
    const currentRequestId = '777e40d2-930e-4cb1-8a9c-0059401a68f1';
    await page.addInitScript(({ currentWallet, currentKey, activeKey, currentId }) => {
      localStorage.setItem(currentKey, JSON.stringify({
        version: 2,
        wallet: currentWallet,
        requestId: currentId,
        statusToken: 'EEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEEE',
        createdAt: '2026-08-24T12:00:00.000Z',
      }));
      localStorage.removeItem(activeKey);
    }, {
      currentWallet: settingsUser.wallet,
      currentKey: deletionCapabilityKey,
      activeKey: deletionActiveWalletKey,
      currentId: currentRequestId,
    });
    await page.route(`**/compliance/deletion-status/${currentRequestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', request_id: currentRequestId, status: 'queued',
        requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:00Z', completed_at: null,
        blockers: [], failure_code: null, retryable: true, attempt_count: 0,
      }),
    }));

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'View status', exact: true }).click();

    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(await page.evaluate((key) => localStorage.getItem(key), deletionActiveWalletKey)).toBe(settingsUser.wallet);
  });

  test('sends profile visibility only after the rider intentionally changes it', async ({ page }) => {
    await page.goto('/settings?tab=privacy');
    await expect(page.getByRole('heading', { name: 'Privacy', exact: true })).toBeVisible();

    await page.getByRole('button', { name: /^Private/ }).click();
    const profileUpdatePromise = page.waitForRequest((request) => {
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      return request.method() === 'PUT' && path === '/users/me';
    });
    await page.getByRole('button', { name: 'Save' }).click();
    const profileUpdate = await profileUpdatePromise;

    expect(profileUpdate.postDataJSON()).toMatchObject({ is_public: false });
  });

  test('changes sections when using the settings navigation', async ({ page }) => {
    await page.goto('/settings?tab=profile');

    await expect(page.getByRole('heading', { name: 'Profile', exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Performance' }).click();

    await expect(page).toHaveURL(/\/settings\?tab=performance$/);
    await expect(page.getByRole('heading', { name: 'Threshold' })).toBeVisible();

    await page.getByRole('button', { name: 'Connections' }).click();

    await expect(page).toHaveURL(/\/settings\?tab=connections$/);
    await expect(page.getByRole('heading', { name: 'Connections' })).toBeVisible();
  });

  test('canonicalizes legacy hash tab links without losing the selected section', async ({ page }) => {
    await page.goto('/settings#connections');

    await expect(page).toHaveURL(/\/settings\?tab=connections$/);
    await expect(page.getByRole('heading', { name: 'Connections' })).toBeVisible();
  });

  test('keeps the alert switches on the Alerts section and saves each flip', async ({ page }) => {
    const preferenceUpdates: Array<Record<string, unknown>> = [];
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'PUT' && path === '/notifications/preferences') {
        preferenceUpdates.push(request.postDataJSON() as Record<string, unknown>);
      }
    });
    await page.goto('/settings');

    await page.getByRole('button', { name: 'Alerts' }).click();

    await expect(page).toHaveURL(/\/settings\?tab=alerts$/);
    await expect(page.getByRole('heading', { name: 'Alerts' })).toBeVisible();
    await expect(page.getByText('Saved', { exact: true }).first()).toBeVisible();
    for (const label of ['Rank moves', 'Vault payouts', 'Rider activity', 'Ride updates']) {
      await expect(page.getByRole('switch', { name: label })).toBeVisible();
    }
    await expect(page.getByRole('switch', { name: 'Rider activity' })).toBeChecked();
    await expect(page.getByRole('switch', { name: 'Ride updates' })).not.toBeChecked();

    await page.getByRole('switch', { name: 'Rider activity' }).click();

    await expect(page.getByRole('switch', { name: 'Rider activity' })).not.toBeChecked();
    await expect.poll(() => preferenceUpdates.length).toBe(1);
    expect(preferenceUpdates[0]).toMatchObject({ social_activity: false, leaderboard_updates: true });
    // No Save button appears: a switch commits as it flips.
    await expect(page.getByRole('button', { name: 'Save' })).toHaveCount(0);
  });

  test('saves future ride audience and map defaults separately', async ({ page }) => {
    const captureDir = process.env.BR_CAPTURE_PRIVACY_PACKAGE_DIR;
    await page.goto('/settings?tab=privacy');

    await expect(page.getByRole('group', { name: 'Who can see new rides?' })).toBeVisible();
    await expect(page.getByText('These defaults apply to future rides. Existing rides keep their current privacy.')).toBeVisible();
    if (captureDir) {
      fs.mkdirSync(captureDir, { recursive: true });
      await page.screenshot({
        path: path.join(captureDir, 'privacy-settings-desktop.png'),
        fullPage: true,
      });
    }

    await page.getByRole('radio', { name: 'Only you', exact: true }).check();
    await page.getByRole('radio', { name: 'Hide entire map', exact: true }).check();

    const updateRequestPromise = page.waitForRequest((request) => {
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      return request.method() === 'PUT' && path === '/privacy/settings';
    });
    await page.getByRole('button', { name: 'Save' }).click();
    const updateRequest = await updateRequestPromise;

    expect(updateRequest.postDataJSON()).toMatchObject({
      default_ride_visibility: 'private',
      default_map_visibility: 'hide_entire',
      default_map_hide_start_m: 0,
      default_map_hide_end_m: 0,
    });

    if (captureDir) {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload({ waitUntil: 'domcontentloaded' });
      await expect(page.getByRole('group', { name: 'Who can see new rides?' })).toBeVisible();
      await page.screenshot({
        path: path.join(captureDir, 'privacy-settings-mobile.png'),
        fullPage: true,
      });
    }
  });

  test('adds a privacy zone from coordinates without sending location data to geocoding', async ({ page }) => {
    const requestUrls: string[] = [];
    let privacyZonePostCount = 0;
    let privacySettingsGetCount = 0;
    page.on('request', (request) => {
      requestUrls.push(request.url());
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (request.method() === 'POST' && path === '/privacy/zones') {
        privacyZonePostCount += 1;
      }
      if (request.method() === 'GET' && path === '/privacy/settings') {
        privacySettingsGetCount += 1;
      }
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Add privacy zone' }).click();

    await expect(page.getByText('This location is sent only to Boulder Roller to hide ride endpoints.')).toBeVisible();
    await page.getByLabel('Label (optional)').fill('Trailhead');
    await page.getByLabel('Latitude').fill('91');
    await page.getByLabel('Longitude').fill('-75.165222');
    await page.getByRole('button', { name: /^(0\.8 km|800 ?m)/ }).click();
    await page.getByRole('button', { name: 'Add zone', exact: true }).click();

    await expect(page.locator('#privacy-zone-location-error')).toHaveText('Latitude must be a number from -90 to 90.');
    expect(privacyZonePostCount).toBe(0);

    await page.getByLabel('Latitude').fill('39.952583');

    const addRequestPromise = page.waitForRequest((request) => {
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      return request.method() === 'POST' && path === '/privacy/zones';
    });
    await page.getByRole('button', { name: 'Add zone', exact: true }).click();
    const addRequest = await addRequestPromise;

    expect(addRequest.postDataJSON()).toEqual({
      latitude: 39.952583,
      longitude: -75.165222,
      radius_m: 800,
      label: 'Trailhead',
    });
    await expect(page.getByText('Trailhead', { exact: true })).toBeVisible();
    await expect.poll(() => privacySettingsGetCount).toBeGreaterThanOrEqual(2);
    expectNoGeocodingRequests(requestUrls);
  });

  test('omits frozen identity, card, and provider-connect surfaces at desktop and mobile', async ({ page }) => {
    const removedSurfaceRequests: string[] = [];
    page.on('request', (request) => {
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      if (path.startsWith('/strava/') || path === '/beetles/my-cards') {
        removedSurfaceRequests.push(path);
      }
    });

    for (const viewport of [
      { width: 1440, height: 1000 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await page.goto('/settings?tab=profile');

      await expect(page.getByLabel('Rider type')).toHaveCount(0);
      await expect(page.getByText('Beetle cards', { exact: true })).toHaveCount(0);
      await expect(page.getByText('Strava', { exact: true })).toHaveCount(0);

      await page.getByRole('button', { name: 'Connections' }).click();
      await expect(page.getByRole('heading', { name: 'Connections' })).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Connections' })).toBeVisible();
      await expect(page.getByText('Strava', { exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Import rides' })).toHaveCount(0);
    }

    expect(removedSurfaceRequests).toEqual([]);
  });

  test('uses browser location for a privacy zone without geocoding it', async ({ page, context }) => {
    const requestUrls: string[] = [];
    page.on('request', (request) => requestUrls.push(request.url()));
    await context.grantPermissions(['geolocation']);
    await context.setGeolocation({ latitude: 40.014984, longitude: -105.270546 });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Add privacy zone' }).click();
    await page.getByRole('button', { name: 'Use current location' }).click();

    await expect(page.getByLabel('Latitude')).toHaveValue('40.014984');
    await expect(page.getByLabel('Longitude')).toHaveValue('-105.270546');

    const addRequestPromise = page.waitForRequest((request) => {
      const path = new URL(request.url()).pathname.replace(/^\/api/, '');
      return request.method() === 'POST' && path === '/privacy/zones';
    });
    await page.getByRole('button', { name: 'Add zone', exact: true }).click();
    const addRequest = await addRequestPromise;

    expect(addRequest.postDataJSON()).toEqual({
      latitude: 40.014984,
      longitude: -105.270546,
      radius_m: 400,
    });
    expectNoGeocodingRequests(requestUrls);
  });

  test('ignores a delayed browser location after cancel and starts clean when reopened', async ({ page }) => {
    await page.addInitScript(() => {
      const pendingLocations: PositionCallback[] = [];

      Object.defineProperty(navigator, 'geolocation', {
        configurable: true,
        value: {
          getCurrentPosition(success: PositionCallback) {
            pendingLocations.push(success);
          },
        },
      });

      (window as Window & {
        resolvePrivacyLocation?: (requestIndex: number, latitude: number, longitude: number) => void;
      }).resolvePrivacyLocation = (requestIndex, latitude, longitude) => {
        pendingLocations[requestIndex]?.({
          coords: { latitude, longitude },
          timestamp: Date.now(),
        } as GeolocationPosition);
      };
    });

    await page.goto('/settings?tab=privacy');
    await page.getByRole('button', { name: 'Add privacy zone' }).click();
    await page.getByRole('button', { name: 'Use current location' }).click();
    await expect(page.getByRole('button', { name: 'Getting location…' })).toBeDisabled();

    await page.getByRole('button', { name: 'Cancel adding privacy zone' }).click();
    await page.getByRole('button', { name: 'Add privacy zone' }).click();

    await expect(page.getByRole('button', { name: 'Use current location' })).toBeEnabled();
    await page.evaluate(() => {
      (window as Window & {
        resolvePrivacyLocation?: (requestIndex: number, latitude: number, longitude: number) => void;
      }).resolvePrivacyLocation?.(0, 40.014984, -105.270546);
    });
    await expect(page.getByLabel('Latitude')).toHaveValue('');
    await expect(page.getByLabel('Longitude')).toHaveValue('');
    await expect(page.getByRole('button', { name: 'Use current location' })).toBeEnabled();

    await page.getByRole('button', { name: 'Use current location' }).click();
    await expect(page.getByRole('button', { name: 'Getting location…' })).toBeDisabled();
    await page.evaluate(() => {
      (window as Window & {
        resolvePrivacyLocation?: (requestIndex: number, latitude: number, longitude: number) => void;
      }).resolvePrivacyLocation?.(1, 39.952583, -75.165222);
    });

    await expect(page.getByLabel('Latitude')).toHaveValue('39.952583');
    await expect(page.getByLabel('Longitude')).toHaveValue('-75.165222');
    await expect(page.getByRole('button', { name: 'Use current location' })).toBeEnabled();
  });
});
