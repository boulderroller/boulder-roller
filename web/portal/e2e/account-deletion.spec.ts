import { expect, test, type Page } from '@playwright/test';

const requestId = 'b55fa9f6-44ae-4ad5-a080-2829af46f954';
const statusToken = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const deletionWallet = 'AccountDeletionRider1111111111111111111111';
const activeWalletKey = 'br_account_deletion_active_wallet_v2';
const capabilityKey = `br_account_deletion_capability_v2:${deletionWallet}`;
const recoveryActiveWalletKey = 'br_account_deletion_unconfirmed_active_wallet_v1';
const recoveryKey = `br_account_deletion_unconfirmed_v1:${deletionWallet}`;

async function seedDeletionCapability(page: Page) {
  await page.addInitScript(({ storedRequestId, storedStatusToken, storedWallet, storedCapabilityKey, storedActiveWalletKey }) => {
    localStorage.setItem(storedCapabilityKey, JSON.stringify({
      version: 2,
      wallet: storedWallet,
      requestId: storedRequestId,
      statusToken: storedStatusToken,
      createdAt: '2026-08-24T12:00:00.000Z',
    }));
    localStorage.setItem(storedActiveWalletKey, storedWallet);
  }, {
    storedRequestId: requestId,
    storedStatusToken: statusToken,
    storedWallet: deletionWallet,
    storedCapabilityKey: capabilityKey,
    storedActiveWalletKey: activeWalletKey,
  });
}

async function seedUnconfirmedDeletionRecovery(page: Page) {
  await page.addInitScript(({
    storedRequestId,
    storedStatusToken,
    storedWallet,
    storedRecoveryKey,
    storedRecoveryActiveWalletKey,
  }) => {
    localStorage.setItem(storedRecoveryKey, JSON.stringify({
      version: 1,
      state: 'unconfirmed',
      capability: {
        version: 2,
        wallet: storedWallet,
        requestId: storedRequestId,
        statusToken: storedStatusToken,
        createdAt: '2026-08-24T12:00:00.000Z',
      },
      persistedAt: '2026-08-24T12:00:01.000Z',
    }));
    localStorage.setItem(storedRecoveryActiveWalletKey, storedWallet);
  }, {
    storedRequestId: requestId,
    storedStatusToken: statusToken,
    storedWallet: deletionWallet,
    storedRecoveryKey: recoveryKey,
    storedRecoveryActiveWalletKey: recoveryActiveWalletKey,
  });
}

test.describe('Account deletion status', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/auth/bootstrap', (route) => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Not authenticated' }),
    }));
  });

  test('stays reachable without authentication and only reports verified completion', async ({ page }) => {
    await seedDeletionCapability(page);
    let statusHeader: string | undefined;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => {
      statusHeader = route.request().headers()['x-account-deletion-token'];
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1',
          request_id: requestId,
          status: 'completed',
          requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:03Z',
          completed_at: '2026-08-24T12:00:03Z',
          blockers: [],
          failure_code: null,
          retryable: true,
          attempt_count: 1,
        }),
      });
    });
    await page.route('**/auth/bootstrap', (route) => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Not authenticated' }),
    }));

    await page.goto('/account-deletion');

    await expect(page.getByRole('heading', { name: 'Account deletion complete' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Finish' })).toBeVisible();
    expect(statusHeader).toBe(statusToken);
    expect(page.url()).not.toContain(statusToken);
    await expect(page.locator('body')).not.toContainText(statusToken);
    await expect.poll(() => page.evaluate(() => (
      localStorage.getItem('br_account_deletion_active_wallet_v2')
    ))).not.toBeNull();
    await expect(page.getByText('Removing the saved status from this device does not cancel the server request.')).toBeVisible();
    const discard = page.getByRole('button', { name: 'Remove saved status from this device' });
    await expect(discard).toBeVisible();
    await expect(page.locator('.account-deletion-status-screen__state-line')).toHaveCSS('font-variant-numeric', /tabular-nums/);
    await discard.click();
    await expect.poll(() => page.evaluate((keys) => ({
      active: localStorage.getItem(keys.active),
      capability: localStorage.getItem(keys.capability),
    }), { active: activeWalletKey, capability: capabilityKey })).toEqual({ active: null, capability: null });
  });

  test('promotes a confirmed recovery envelope after reload without authentication', async ({ page }) => {
    await seedUnconfirmedDeletionRecovery(page);
    let statusHeader: string | undefined;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => {
      statusHeader = route.request().headers()['x-account-deletion-token'];
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1',
          request_id: requestId,
          status: 'processing',
          requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:03Z',
          completed_at: null,
          blockers: [],
          failure_code: null,
          retryable: false,
          attempt_count: 1,
        }),
      });
    });

    await page.goto('/settings?tab=privacy');

    await expect(page).toHaveURL(/\/account-deletion$/);
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(statusHeader).toBe(statusToken);
    expect(await page.evaluate((key) => localStorage.getItem(key), recoveryKey)).toBeNull();
    expect(await page.evaluate((key) => localStorage.getItem(key), recoveryActiveWalletKey)).toBeNull();
    expect(await page.evaluate((key) => localStorage.getItem(key), capabilityKey)).not.toBeNull();
    expect(await page.evaluate((key) => localStorage.getItem(key), activeWalletKey)).toBe(deletionWallet);
  });

  test('keeps an uncertain recovery reachable after a transient status failure', async ({ page }) => {
    await seedUnconfirmedDeletionRecovery(page);
    let statusCount = 0;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => {
      statusCount += 1;
      if (statusCount === 1) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'temporarily unavailable' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: requestId,
          status: 'processing', requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:03Z', completed_at: null,
          blockers: [], failure_code: null, retryable: false, attempt_count: 1,
        }),
      });
    });

    await page.goto('/settings?tab=privacy');

    await expect(page.getByRole('heading', { name: 'Account deletion recovery' })).toBeVisible();
    await page.getByRole('button', { name: 'Check again' }).click();
    await expect(page).toHaveURL(/\/account-deletion$/);
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(statusCount).toBeGreaterThanOrEqual(2);
  });

  test('clears a deletion return path when invalid saved status is discarded', async ({ page }) => {
    await page.addInitScript(({ wallet, activeKey, savedKey }) => {
      localStorage.setItem(activeKey, wallet);
      localStorage.setItem(savedKey, '{"version":2,"invalid":true}');
      sessionStorage.setItem('br_return_url', '/account-deletion');
    }, { wallet: deletionWallet, activeKey: activeWalletKey, savedKey: capabilityKey });

    await page.goto('/account-deletion');
    await expect(page.getByRole('heading', { name: 'Account deletion status unavailable' })).toBeVisible();
    await page.getByRole('button', { name: 'Remove saved status from this device' }).click();

    await expect(page).toHaveURL(/\/$/);
    expect(await page.evaluate(() => sessionStorage.getItem('br_return_url'))).toBeNull();
  });

  test('clears the prior request view when another tab activates a different request', async ({ page }) => {
    await seedDeletionCapability(page);
    const nextRequestId = '855fa9f6-44ae-4ad5-a080-2829af46f954';
    const nextWallet = 'AccountDeletionRider2222222222222222222222';
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', request_id: requestId, status: 'completed',
        requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z',
        completed_at: '2026-08-24T12:00:03Z', blockers: [], failure_code: null,
        retryable: false, attempt_count: 1,
      }),
    }));
    await page.route(`**/compliance/deletion-status/${nextRequestId}`, (route) => route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'temporarily unavailable' }),
    }));

    await page.goto('/account-deletion');
    await expect(page.getByRole('heading', { name: 'Account deletion complete' })).toBeVisible();

    await page.evaluate(({ activeKey, nextId, wallet }) => {
      localStorage.setItem(`br_account_deletion_capability_v2:${wallet}`, JSON.stringify({
        version: 2,
        wallet,
        requestId: nextId,
        statusToken: 'FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF',
        createdAt: '2026-08-24T12:05:00.000Z',
      }));
      localStorage.setItem(activeKey, wallet);
      window.dispatchEvent(new StorageEvent('storage', { key: activeKey, newValue: wallet }));
    }, { activeKey: activeWalletKey, nextId: nextRequestId, wallet: nextWallet });

    await expect(page.getByRole('heading', { name: 'Account deletion complete' })).toHaveCount(0);
    await expect(page.getByText('Account deletion status could not be checked.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Finish' })).toHaveCount(0);
  });

  test('does not report completion for a malformed lifecycle contract', async ({ page }) => {
    await seedDeletionCapability(page);
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v0',
        request_id: requestId,
        status: 'completed',
        requested_at: '2026-08-24T12:00:00Z',
        updated_at: '2026-08-24T12:00:03Z',
        completed_at: '2026-08-24T12:00:03Z',
        blockers: [],
        failure_code: null,
        retryable: false,
        attempt_count: 1,
      }),
    }));

    await page.goto('/account-deletion');

    await expect(page.getByText('Account deletion status could not be checked.')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Account deletion complete' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Finish' })).toHaveCount(0);
  });

  test('only opens saved deletion status on its real route', async ({ page }) => {
    await seedDeletionCapability(page);
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        request_id: requestId,
        status: 'processing',
        requested_at: '2026-08-24T12:00:00Z',
        updated_at: '2026-08-24T12:00:03Z',
        completed_at: null,
        blockers: [],
        failure_code: null,
        retryable: false,
        attempt_count: 1,
      }),
    }));
    await page.route('**/auth/bootstrap', (route) => route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Not authenticated' }),
    }));

    await page.goto('/portfolio');

    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toHaveCount(0);
    await expect(page).toHaveURL(/\/portfolio$/);

    await page.goto('/account-deletion');
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
  });

  test('fails soft when the saved authentication hint cannot be read', async ({ page }) => {
    await page.addInitScript(() => {
      const originalGetItem = Storage.prototype.getItem;
      Storage.prototype.getItem = function getItem(key: string) {
        if (key === 'br_authenticated') {
          throw new DOMException('Storage unavailable', 'SecurityError');
        }
        return originalGetItem.call(this, key);
      };
      const originalRemoveItem = Storage.prototype.removeItem;
      Storage.prototype.removeItem = function removeItem(key: string) {
        if (['br_access_token', 'br_refresh_token', 'br_token_expires_at'].includes(key)) {
          throw new DOMException('Storage unavailable', 'SecurityError');
        }
        return originalRemoveItem.call(this, key);
      };
    });
    const pageErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));

    await page.goto('/');
    await page.waitForTimeout(500);

    expect(pageErrors).toEqual([]);
  });

  test('retries a retryable failure exactly once and keeps the status capability', async ({ page }) => {
    await seedDeletionCapability(page);
    let retryCount = 0;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1',
        request_id: requestId,
        status: 'failed_retryable',
        requested_at: '2026-08-24T12:00:00Z',
        updated_at: '2026-08-24T12:00:03Z',
        completed_at: null,
        blockers: [],
        failure_code: 'storage_unavailable',
        retryable: true,
        attempt_count: 1,
      }),
    }));
    await page.route(`**/compliance/deletion-status/${requestId}/retry`, (route) => {
      retryCount += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1',
          request_id: requestId,
          status: 'queued',
          requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:04Z',
          completed_at: null,
          blockers: [],
          failure_code: null,
          retryable: false,
          attempt_count: 1,
        }),
      });
    });

    await page.goto('/account-deletion');
    await expect(page.getByRole('heading', { name: 'Account deletion needs retry' })).toBeVisible();
    await page.getByRole('button', { name: 'Retry deletion' }).click();

    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(retryCount).toBe(1);
    await expect.poll(() => page.evaluate(() => (
      localStorage.getItem('br_account_deletion_active_wallet_v2')
    ))).not.toBeNull();
  });

  test('renders long retryable blockers and retries with the durable acknowledgement', async ({ page }) => {
    await page.setViewportSize({ width: 568, height: 320 });
    await seedDeletionCapability(page);
    let statusCount = 0;
    let retryBody: unknown = null;
    const blockers = Array.from({ length: 8 }, (_, index) => ({
      code: `server_requirement_${index}`,
      category: 'processing',
      source: `authority_${index}`,
      action: 'retry',
    }));
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => {
      statusCount += 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1',
          request_id: requestId,
          status: 'blocked',
          requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:03Z',
          completed_at: null,
          blockers,
          failure_code: null,
          retryable: true,
          attempt_count: 1,
        }),
      });
    });
    await page.route(`**/compliance/deletion-status/${requestId}/retry`, (route) => {
      retryBody = route.request().postDataJSON();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1',
          request_id: requestId,
          status: 'queued',
          requested_at: '2026-08-24T12:00:00Z',
          updated_at: '2026-08-24T12:00:04Z',
          completed_at: null,
          blockers: [],
          failure_code: null,
          retryable: false,
          attempt_count: 1,
        }),
      });
    });

    await page.goto('/account-deletion');

    const heading = page.getByRole('heading', { name: 'Account deletion blocked' });
    await expect(heading).toBeVisible();
    expect((await heading.boundingBox())?.y).toBeGreaterThanOrEqual(0);
    await expect(page.getByRole('link', { name: 'Contact support' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Open Portfolio' })).toHaveCount(0);
    const recheck = page.getByRole('button', { name: 'Retry deletion' });
    await recheck.scrollIntoViewIfNeeded();
    await recheck.click();
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(statusCount).toBe(1);
    expect(retryBody).toEqual({});
  });

  test('polls a post-authorization worker recovery without offering rider retry', async ({ page }) => {
    await seedDeletionCapability(page);
    let statusCount = 0;
    let retryCount = 0;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => {
      statusCount += 1;
      const recovering = statusCount === 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: requestId,
          status: recovering ? 'failed_retryable' : 'processing',
          requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z', completed_at: null,
          blockers: [], failure_code: recovering ? 'deletion_failed' : null,
          retryable: false, attempt_count: recovering ? 1 : 2,
        }),
      });
    });
    await page.route(`**/compliance/deletion-status/${requestId}/retry`, (route) => {
      retryCount += 1;
      return route.abort();
    });

    await page.goto('/account-deletion');

    await expect(page.getByRole('heading', { name: 'Account deletion recovering' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry deletion' })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible({ timeout: 10_000 });
    expect(statusCount).toBeGreaterThanOrEqual(2);
    expect(retryCount).toBe(0);
  });

  test('preserves durable acknowledgement when retrying', async ({ page }) => {
    await seedDeletionCapability(page);
    let retryBody: unknown;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', request_id: requestId, status: 'failed_retryable',
        requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z', completed_at: null,
        blockers: [], failure_code: 'preflight_unavailable', retryable: true, attempt_count: 1,
      }),
    }));
    await page.route(`**/compliance/deletion-status/${requestId}/retry`, (route) => {
      retryBody = route.request().postDataJSON();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: requestId, status: 'queued',
          requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:04Z', completed_at: null,
          blockers: [], failure_code: null, retryable: false, attempt_count: 2,
        }),
      });
    });

    await page.goto('/account-deletion');
    await expect(page.getByText('Account check unavailable')).toBeVisible();
    await page.getByRole('button', { name: 'Retry deletion' }).click();
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(retryBody).toEqual({});
  });

  test('guides a human-boundary retry conflict to support without changing the saved status', async ({ page }) => {
    await seedDeletionCapability(page);
    let retryCount = 0;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', request_id: requestId, status: 'failed_retryable',
        requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z', completed_at: null,
        blockers: [], failure_code: 'preflight_unavailable', retryable: true, attempt_count: 1,
      }),
    }));
    await page.route(`**/compliance/deletion-status/${requestId}/retry`, (route) => {
      retryCount += 1;
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { code: 'retry_requires_support' } }),
      });
    });

    await page.goto('/account-deletion');
    await page.getByRole('button', { name: 'Retry deletion' }).click();

    await expect(page.getByRole('heading', { name: 'Account deletion needs support' })).toBeVisible();
    await expect(page.getByText('This request needs support before it can be retried.')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Contact support' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry deletion' })).toHaveCount(0);
    await page.getByRole('button', { name: 'Refresh status' }).click();
    await expect(page.getByRole('heading', { name: 'Account deletion needs support' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry deletion' })).toHaveCount(0);
    expect(retryCount).toBe(1);
  });

  test('does not offer rider retry for a non-retryable blocked request', async ({ page }) => {
    await seedDeletionCapability(page);
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', request_id: requestId, status: 'blocked',
        requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z', completed_at: null,
        blockers: [], failure_code: null, retryable: false, attempt_count: 1,
      }),
    }));

    await page.goto('/account-deletion');

    await expect(page.getByRole('heading', { name: 'Account deletion needs support' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Retry deletion' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Contact support' })).toBeVisible();
  });

  test('renders one support action for a non-retryable support blocker', async ({ page }) => {
    await seedDeletionCapability(page);
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        contract_version: 'account-deletion.v1', request_id: requestId, status: 'blocked',
        requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z', completed_at: null,
        blockers: [{ code: 'policy_review_required', category: 'policy', action: 'contact_support' }],
        failure_code: null, retryable: false, attempt_count: 1,
      }),
    }));

    await page.goto('/account-deletion');

    await expect(page.getByRole('link', { name: 'Contact support' })).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Retry deletion' })).toHaveCount(0);
  });

  test('lets a support-routed request refresh into its new durable state', async ({ page }) => {
    await seedDeletionCapability(page);
    let statusCount = 0;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => {
      statusCount += 1;
      const support = statusCount === 1;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: requestId,
          status: support ? 'needs_support' : 'queued',
          requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z', completed_at: null,
          blockers: support ? [{ code: 'policy_review_required', category: 'policy', action: 'contact_support' }] : [],
          failure_code: null, retryable: !support, attempt_count: 1,
        }),
      });
    });

    await page.goto('/account-deletion');
    await expect(page.getByRole('heading', { name: 'Account deletion needs support' })).toBeVisible();
    await page.getByRole('button', { name: 'Refresh status' }).click();

    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    expect(statusCount).toBe(2);
  });

  test('keeps polling after a transient error and pauses while the page is hidden', async ({ page }) => {
    test.setTimeout(30_000);
    await seedDeletionCapability(page);
    let statusCount = 0;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => {
      statusCount += 1;
      if (statusCount === 2) return route.abort('connectionreset');
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: requestId,
          status: statusCount >= 3 ? 'completed' : 'processing',
          requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z',
          completed_at: statusCount >= 3 ? '2026-08-24T12:00:03Z' : null,
          blockers: [], failure_code: null, retryable: false, attempt_count: 1,
        }),
      });
    });

    await page.goto('/account-deletion');
    await expect(page.getByRole('heading', { name: 'Account deletion in progress' })).toBeVisible();
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForTimeout(3_000);
    expect(statusCount).toBe(1);
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await expect.poll(() => statusCount, { timeout: 22_000 }).toBeGreaterThanOrEqual(3);
    await expect(page.getByRole('heading', { name: 'Account deletion complete' })).toBeVisible();
  });

  test('recovers when the initial status check has a transient network failure', async ({ page }) => {
    test.setTimeout(25_000);
    await seedDeletionCapability(page);
    let statusCount = 0;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => {
      statusCount += 1;
      if (statusCount === 1) return route.abort('connectionreset');
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          contract_version: 'account-deletion.v1', request_id: requestId, status: 'completed',
          requested_at: '2026-08-24T12:00:00Z', updated_at: '2026-08-24T12:00:03Z',
          completed_at: '2026-08-24T12:00:03Z', blockers: [], failure_code: null,
          retryable: false, attempt_count: 1,
        }),
      });
    });

    await page.goto('/account-deletion');

    await expect(page.getByText('Account deletion status could not be checked.')).toBeVisible();
    await expect.poll(() => statusCount, { timeout: 16_000 }).toBeGreaterThanOrEqual(2);
    await expect(page.getByRole('heading', { name: 'Account deletion complete' })).toBeVisible();
  });

  test('treats inaccessible browser storage as unavailable instead of an invalid saved request', async ({ page }) => {
    await page.addInitScript(() => {
      const originalGetItem = Storage.prototype.getItem;
      Storage.prototype.getItem = function getItem(key: string) {
        if (key.startsWith('br_account_deletion_')) {
          throw new DOMException('Storage unavailable', 'SecurityError');
        }
        return originalGetItem.call(this, key);
      };
    });

    await page.goto('/account-deletion');

    await expect(page.getByRole('heading', { name: 'Account deletion status unavailable' })).toBeVisible();
    await expect(page.getByText('This browser cannot read saved request status.')).toBeVisible();
    await expect(page.getByText(/invalid/i)).toHaveCount(0);
  });

  test('routes a missing accepted request to support without re-filing it', async ({ page }) => {
    await seedDeletionCapability(page);
    let deleteCount = 0;
    await page.route(`**/compliance/deletion-status/${requestId}`, (route) => route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: { code: 'request_not_found' } }),
    }));
    await page.route('**/compliance/account', (route) => {
      if (route.request().method() !== 'DELETE') return route.fallback();
      deleteCount += 1;
      return route.fulfill({ status: 500, body: 'unexpected request' });
    });

    await page.goto('/account-deletion');

    await expect(page.getByRole('link', { name: 'Contact support' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Submit saved request' })).toHaveCount(0);
    expect(deleteCount).toBe(0);
  });
});
