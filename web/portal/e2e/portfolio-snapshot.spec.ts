import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';
import { readSubjectStates } from '../src/lib/protocolStates';
import { describePush } from '../src/lib/notificationLedger';
const evidence = path.resolve(__dirname, '../../../history/portal-audit-2026-09-07/build/lane-a');
const user = { id: 'lane-a-rider', wallet: '8xF6yDbvJfRiderWallet111111111111111111111', username: 'riderone', is_public: true, preferred_units: 'metric', theme_id: 'hoo-breddin', is_dark_mode: false, total_rides: 1 };
const collection = () => ({ revision: 'collection-7', asOf: '2026-09-08T12:00:00Z', coverage: { completeness: 'complete', population: 'rider-vault-positions', observedCount: 2, expectedCount: 2 }, positions: [{ vaultId: 1, dungReadyBaseUnits: '4250000000' }, { vaultId: 2, dungReadyBaseUnits: '800000000' }], uncollectedDungBaseUnits: '5050000000' });
function snapshot(): any {
  return { contractVersion: 'portfolio_snapshot.v4', collectionSnapshot: collection(), portfolio: {
    calBalanceBaseUnits: '22154000000000', freshness: { calStatus: 'live' }, walletDung: { amountBaseUnits: '18750000000', status: 'live', source: 'spl_wallet_ata' },
    balanceLifecycle: { canAddFunds: true, canWithdrawToWallet: true, projectionStatus: 'recorded', blockers: [], setupSteps: [], assets: [
      { asset: 'CAL', exists: true, sourceStatus: 'live', balanceBaseUnits: '12345000000' }, { asset: 'DUNG', exists: true, sourceStatus: 'live', balanceBaseUnits: '7125000000' },
    ] }, stakedPositions: [1, 2].map(id => ({ id: `position-${id}`, vaultId: id, climbId: `climb-${id}`, climbName: `Climb ${id}`, calDepositedBaseUnits: '1200000000000', dungReadyBaseUnits: '99000000000', status: 'Finalized' })),
  }, distributions: { distributions: [] } };
}
async function fixtures(page: Page, data: unknown) {
  page.on('pageerror', e => console.log('PAGE ERROR', e.message));
  await page.addInitScript(() => { localStorage.setItem('br_authenticated', 'true'); localStorage.setItem('br_setup_reprompt_dismissed', 'true'); });
  await page.route('**/*', async route => {
    const req = route.request(); const url = new URL(req.url());
    if (!['fetch', 'xhr'].includes(req.resourceType()) || url.pathname.startsWith('/src/') || url.pathname.startsWith('/node_modules/')) return route.continue();
    const p = url.pathname.replace(/^\/api/, '');
    let body: unknown = {};
    if (p.startsWith('/auth/')) body = { authenticated: true, invite_required: false, invite_validated: true, needs_profile_setup: false, auth_method_hint: 'wallet', user };
    else if (p === '/users/me' || p === '/me') body = user;
    else if (p === '/privacy/settings') body = { contract_version: 'privacy.v2', profile_visibility: 'public', default_ride_visibility: 'public', default_map_visibility: 'hide_start_end', default_map_hide_start_m: 200, default_map_hide_end_m: 200, privacy_zone_count: 0, privacy_zones_loaded: true, defaults_apply_to: 'future_rides', provider_privacy_inherited: false, ride_override_mode: 'optional', protocol_public_fields: [] };
    else if (p === '/status') body = { balanceRollout: { enforced: true, orderValid: true, blockers: [], actionOrder: ['collect_dung', 'deposit_cal', 'withdraw_cal', 'add_funds', 'withdraw_to_wallet'], enabledActions: ['collect_dung', 'deposit_cal', 'withdraw_cal', 'add_funds', 'withdraw_to_wallet'] } };
    else if (p === '/portfolio/snapshot') body = data;
    else if (p === '/users/me/leaderboard-positions') body = { positions: [], stats: { totalPositions: 0, komCount: 0, top10Count: 0 } };
    else if (p === '/notifications') body = { notifications: [], unreadCount: 0, hasMore: false };
    else if (p === '/feed/home') body = { feed: { activities: [], has_more: false }, social_counts: {}, notifications: { unread_count: 0 }, suggested_riders: [], popular_climbs: [], achievements: [] };
    else if (p === '/rides') body = [];
    else if (p === '/climbs/list') body = { climbs: [] };
    else if (p.endsWith('/pending-rewards')) body = { totalPendingBaseUnits: '1000000000', harvestFeeBps: '500', feeEstimateBaseUnits: '50000000', netEstimateBaseUnits: '950000000' };
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
}
async function openPortfolio(page: Page, data: unknown) {
  await fixtures(page, data); await page.goto('/profile?tab=portfolio');
  await expect(page.locator('[data-object-page="portfolio"]')).toBeVisible();
  await expect(page.locator('.portfolio-row--position')).toHaveCount(2);
}
for (const width of [1440, 390]) test(`01 complete snapshot rows and total at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 }); await openPortfolio(page, snapshot());
  await expect(page.locator('.portfolio-row--position').nth(0)).toContainText('4.25 DUNG ready');
  await expect(page.locator('.portfolio-row--position').nth(1)).toContainText('0.8 DUNG ready');
  await expect(page.locator('.portfolio-uncollected strong')).toHaveText('5.05');
  await expect(page.getByText('99 DUNG ready', { exact: true })).toHaveCount(0);
  await expect(page.getByText('CAL deposited on climbs', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: path.join(evidence, `portfolio-${width}.png`), fullPage: true });
});
for (const scenario of ['zero', 'unknown', 'partial', 'mixed', 'missing']) test(`01 snapshot ${scenario}`, async ({ page }) => {
  const data = snapshot();
  if (scenario === 'zero') { data.collectionSnapshot.positions.forEach((p: any) => p.dungReadyBaseUnits = '0'); data.collectionSnapshot.uncollectedDungBaseUnits = '0'; }
  if (scenario === 'unknown') data.collectionSnapshot.uncollectedDungBaseUnits = null;
  if (scenario === 'partial') data.collectionSnapshot.coverage.completeness = 'partial';
  if (scenario === 'mixed') data.portfolio.collectionSnapshot = { ...collection(), revision: 'collection-8' };
  if (scenario === 'missing') data.collectionSnapshot = null;
  await openPortfolio(page, data);
  if (scenario === 'zero') await expect(page.locator('.portfolio-uncollected strong')).toHaveText('0');
  else await expect(page.locator('.portfolio-uncollected')).toHaveCount(0);
});

for (const malformed of ['row', 'revision', 'population', 'overflow']) test(`01 malformed ${malformed} abstains`, async ({ page }) => {
  const data = snapshot();
  if (malformed === 'row') data.collectionSnapshot.positions[0] = null;
  if (malformed === 'revision') data.collectionSnapshot.revision = 7;
  if (malformed === 'population') data.collectionSnapshot.coverage.population = 7;
  if (malformed === 'overflow') data.collectionSnapshot.positions[0].dungReadyBaseUnits = '18446744073709551616';
  await openPortfolio(page, data);
  await expect(page.locator('.portfolio-uncollected')).toHaveCount(0);
});

test('01 absent snapshot cannot relabel lifetime rewards as ready', async ({ page }) => {
  const data = snapshot(); data.collectionSnapshot = null;
  await openPortfolio(page, data);
  await expect(page.locator('.portfolio-row--position').getByText(/DUNG ready/)).toHaveCount(0);
});
test('01 complete empty population renders authoritative zero', async ({ page }) => {
  const data = snapshot(); data.portfolio.stakedPositions = [];
  data.collectionSnapshot.positions = [];
  data.collectionSnapshot.coverage.observedCount = 0;
  data.collectionSnapshot.coverage.expectedCount = 0;
  data.collectionSnapshot.uncollectedDungBaseUnits = '0';
  await fixtures(page, data); await page.goto('/profile?tab=portfolio');
  await expect(page.locator('.portfolio-uncollected strong')).toHaveText('0');
});

 test('11 custody sources and unavailable versus authoritative zero', async ({ page }) => {
  const data = snapshot();
  data.portfolio.balanceLifecycle.assets[0].sourceStatus = 'unavailable';
  data.portfolio.balanceLifecycle.assets[0].balanceBaseUnits = '12345000000';
  data.portfolio.balanceLifecycle.assets[1].balanceBaseUnits = '0';
  await openPortfolio(page, data);
  await expect(page.locator('.portfolio-sheet__head').getByText('Boulder Roller Balance', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Wallet CAL')).toContainText('22,154');
  await expect(page.getByLabel('Wallet snapshot')).toContainText('18.75');
  const assets = page.getByLabel('Balance assets');
  await expect(assets.locator('.portfolio-row').nth(0).locator('strong')).toBeEmpty();
  await expect(assets.locator('.portfolio-row').nth(1).locator('strong')).toHaveText('0');
 });
 test('11 distinct named custody groups', async ({ page }) => {
  await openPortfolio(page, snapshot());
  await expect(page.getByLabel('Wallet CAL')).toContainText('22,154');
  await expect(page.getByLabel('Wallet snapshot')).toContainText('18.75');
  await expect(page.getByLabel('Balance assets')).toContainText('12.35');
  await expect(page.getByLabel('Balance assets')).toContainText('7.13');
  await expect(page.getByLabel('Balance assets')).not.toContainText('22,154');
  await expect(page.getByLabel('Balance assets')).not.toContainText('18.75');
 });
 test('11 unavailable wallet does not inherit Balance, missing account is not zero', async ({ page }) => {
  const data = snapshot(); data.portfolio.freshness.calStatus = 'unavailable';
  data.portfolio.walletDung.status = 'not_initialized'; data.portfolio.walletDung.amountBaseUnits = '0';
  await openPortfolio(page, data);
  await expect(page.getByLabel('Wallet CAL').locator('strong')).toBeEmpty();
  await expect(page.getByLabel('Wallet snapshot').locator('strong')).toBeEmpty();
  await expect(page.getByLabel('Balance assets')).toContainText('12.35');
 });
 test('11 Add funds preserves exact action payload', async ({ page }) => {
  await openPortfolio(page, snapshot());
  await page.route('**/portfolio/balance/add-funds/prepare', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{}' }));
  await page.getByRole('button', { name: 'Add funds', exact: true }).click();
  const sheet = page.getByRole('dialog', { name: 'Add funds' });
  await sheet.getByLabel('Add funds amount').fill('9007199.254740993');
  const button = sheet.getByRole('button', { name: 'Hold to Add 9,007,199.25 CAL' });
  const request = page.waitForRequest(r => r.url().endsWith('/portfolio/balance/add-funds/prepare'));
  await button.focus(); await page.keyboard.down('Space'); await page.waitForTimeout(1000); await page.keyboard.up('Space');
  expect((await request).postDataJSON()).toEqual({ asset: 'CAL', amount_base_units: '9007199254740993' });
 });

test('11 ambiguous live wallet CAL zero is absent without account existence', async ({ page }) => {
  const data = snapshot(); data.portfolio.calBalanceBaseUnits = '0';
  await openPortfolio(page, data);
  await expect(page.getByLabel('Wallet CAL').locator('strong')).toBeEmpty();
});

test('11 live wallet CAL zero renders 0 once the account is known to exist', async ({ page }) => {
  const data = snapshot(); data.portfolio.calBalanceBaseUnits = '0'; data.portfolio.freshness.calAccountExists = true;
  await openPortfolio(page, data);
  await expect(page.getByLabel('Wallet CAL').locator('strong')).toHaveText(/^0(\.00)?$/);
});

async function savedUpload(page: Page, subjectStates?: unknown) {
  await fixtures(page, snapshot());
  const ride = { id: 'lane-a-ride', title: 'Saved ride', startedAt: '2026-09-08T12:00:00Z', distanceM: 12000, status: 'completed', attestationStatus: 'attested', finalizedAt: '2026-09-08T12:01:00Z', patterns: [{ id: 'climb-1', type: 'climb' }], thresholdEconomyState: 'held', subjectStates };
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()); const p = url.pathname.replace(/^\/api/, '');
    const json = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (p === '/rides/upload/init') return json({ upload_id: 'lane-a-upload', signed_url: `${url.origin}/lane-a-storage`, expires_in: 600 });
    if (p === '/lane-a-storage') return json({ Key: 'rides/lane-a.gpx' });
    if (p === '/rides/upload/complete') return json({ ride_id: ride.id, status: 'completed' });
    if (p === `/rides/${ride.id}`) return json(ride);
    if (p === '/rides') return json([ride]);
    return route.fallback();
  });
  await page.goto('/upload');
  await page.locator('input[type="file"]').setInputFiles({ name: 'lane-a.gpx', mimeType: 'application/gpx+xml', buffer: Buffer.from('<gpx version="1.1"><trk><name>Lane A</name></trk></gpx>') });
  const sheet = page.getByRole('dialog', { name: 'Upload ride', exact: true });
  await sheet.getByRole('button', { name: 'Upload ride', exact: true }).click();
  await expect(sheet.getByText('Ride saved', { exact: true })).toBeVisible();
  await expect(sheet.getByRole('button', { name: 'Saved ride', exact: true })).toBeVisible();
  return sheet;
}
for (const width of [1440, 390]) test(`12 stored matched ride with held CAL at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  const sheet = await savedUpload(page);
  await expect(sheet.getByText(/^(Stamped|Counting|Finalized)$/)).toHaveCount(0);
  await expect(sheet.locator('[data-state-subject="storage"]')).toContainText('Saved');
  await expect(sheet.locator('[data-state-subject="cal"], [data-state-subject="collection"], [data-state-subject="matching"]')).toHaveCount(0);
  await expect(sheet.getByText('Climbs on this ride').locator('..')).toContainText('1');
  await page.screenshot({ path: path.join(evidence, `upload-saved-${width}.png`), fullPage: true });
});
 test('12 explicit subjects never fall back to generic ride or another subject', async ({ page }) => {
  const sheet = await savedUpload(page, { matching: { state: 'needs_review', reason: 'fixture_reason' }, cal: { state: 'held' }, collection: null });
  await expect(sheet.locator('[data-state-subject="matching"]')).toContainText('Needs review');
  await expect(sheet.locator('[data-state-subject="cal"], [data-state-subject="position"], [data-state-subject="collection"]')).toHaveCount(0);
 });
 test('12 Portfolio omits generic status and retains only explicit position state', async ({ page }) => {
  const data = snapshot(); data.portfolio.stakedPositions[1].subjectStates = { position: { state: 'needs_review', reason: 'fixture_reason' } };
  await openPortfolio(page, data);
  await expect(page.locator('.portfolio-row--position').first()).not.toContainText('Finalized');
  await expect(page.locator('.portfolio-row--position').nth(1)).toContainText('Needs review');
 });

for (const width of [1440, 390]) test(`13 lost seat omits unsupported historical ordinal at ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
  await fixtures(page, snapshot());
  const event = { id: 'lost-seat-event', notificationType: 'leaderboard_bumped', title: 'Seat lost', createdAt: '2026-09-08T12:00:00Z', read: false, metadata: { climbName: 'Climb 1', rank: 4 }, target: { type: 'climb', id: 'climb-1', label: 'Climb 1' }, transition: { climbId: 'climb-1', revision: 'board-7', occurredAt: '2026-09-08T12:00:00Z', beforePlace: 4, afterPlace: null } };
  await page.route('**/notifications?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ notifications: [event], unreadCount: 1, hasMore: false }) }));
  await page.goto('/notifications');
  await expect(page.getByRole('heading', { name: 'Notifications', exact: true })).toBeVisible();
  await expect(page.locator('.notifications-log__row')).toContainText('Climb 1');
  await expect(page.locator('.notifications-log__row')).not.toContainText(/4th|11th/);
  await page.screenshot({ path: path.join(evidence, `notifications-${width}.png`), fullPage: true });
  await page.getByRole('button', { name: 'Open notifications', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Notifications', exact: true })).not.toContainText(/4th|11th/);
  await page.route('**/climbs/climb-1/leaderboard', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ rank: 11, revision: 'board-8' }) }));
  await page.evaluate(async () => { await fetch('/api/climbs/climb-1/leaderboard'); });
  await expect(page.getByRole('dialog', { name: 'Notifications', exact: true })).not.toContainText(/4th|11th/);
  await page.getByRole('button', { name: 'Open notifications', exact: true }).click();
  await page.locator('.notifications-log__row').click();
  await expect(page).toHaveURL(/\/climbs\/climb-1$/);
});

for (const surface of ['portfolio', 'upload']) for (const mode of ['320', 'text-200', 'text-spacing', 'font-blocked']) {
  test(`reflow ${surface} ${mode}`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    if (mode === 'font-blocked') await page.route('**/*', route => route.request().resourceType() === 'font' ? route.abort() : route.fallback());
    if (surface === 'portfolio') await openPortfolio(page, snapshot());
    else await savedUpload(page);
    if (mode === 'text-200') await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    if (mode === 'text-spacing') await page.addStyleTag({ content: '* { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; } p { margin-bottom: 2em !important; }' });
    const root = surface === 'portfolio' ? page.locator('[data-object-page="portfolio"]') : page.getByRole('dialog', { name: 'Upload ride', exact: true });
    expect(await root.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
    await expect(root.getByText(surface === 'portfolio' ? 'Boulder Roller Balance' : 'Saved', { exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(evidence, `${surface}-${mode}.png`), fullPage: true });
  });
}

test('12 each subject retains its own state and known reason', () => {
  const projection = { storage: { state: 'saved', reason: null }, matching: { state: 'needs_review', reason: 'match_reason' }, cal: { state: 'not_counted', reason: 'cal_reason' }, position: { state: 'counting', reason: null }, collection: { state: 'finalized', reason: null } };
  const all = readSubjectStates(projection);
  expect(all.map(row => row.label)).toEqual(['Saved', 'Needs review', 'Not counted', 'Counting', 'Finalized']);
  for (const subject of Object.keys(projection)) {
    const partial = { ...projection }; delete partial[subject as keyof typeof partial];
    expect(readSubjectStates(partial)).toEqual(all.filter(row => row.subject !== subject));
  }
});
test('13 no historical value without S08 even with a retained transition', () => {
  for (const transition of [null, { climbId: 'climb-1', revision: 'board-7', occurredAt: '2026-09-08T12:00:00Z', beforePlace: 4, afterPlace: 11 }]) {
    const event = { id: 'seat-lost', notificationType: 'leaderboard_bumped', title: 'Seat lost', createdAt: '2026-09-08T12:00:00Z', metadata: { rank: 4 }, transition };
    expect(describePush(event as any, '12:00').value).toBeNull();
  }
});

for (const state of ['enabled', 'disabled', 'loading', 'error'] as const) {
  for (const width of [1440, 390]) test(`Balance rollout Portfolio ${state} ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await fixtures(page, snapshot());
    const actions = ['collect_dung', 'deposit_cal', 'withdraw_cal', 'add_funds', 'withdraw_to_wallet'];
    await page.route('**/status', async route => {
      if (state === 'loading') return;
      if (state === 'error') return route.fulfill({ status: 503, json: {} });
      return route.fulfill({ json: { balanceRollout: { enforced: true, orderValid: true, blockers: [], actionOrder: actions, enabledActions: state === 'enabled' ? actions : actions.slice(0, 2) } } });
    });
    await page.goto('/profile?tab=portfolio');
    for (const label of ['Add funds', 'Withdraw to wallet']) {
      const row = page.getByRole('button', { name: new RegExp(label) });
      if (state === 'enabled') await expect(row).toBeEnabled();
      else { await expect(row).toBeDisabled(); await expect(row).toContainText('Not open yet'); }
    }
    await expect(page.locator('.portfolio-row--position')).toHaveCount(2);
    await expect(page.getByLabel('Balance assets')).toContainText('12.35');
    if (state === 'enabled' || state === 'disabled') {
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: path.resolve(__dirname, `../../../history/balance-rollout-th6fs/portfolio-${state}-${width}.png`), fullPage: true });
    }
    if (state === 'enabled') {
      for (const label of ['Add funds', 'Withdraw to wallet']) {
        await page.getByRole('button', { name: label, exact: true }).click();
        await expect(page.getByRole('dialog').getByRole('textbox')).toBeVisible();
        await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      }
    } else await expect(page.getByRole('dialog')).toHaveCount(0);
  });
}

for (const label of ['Add funds', 'Withdraw to wallet']) {
  for (const state of ['disabled', 'loading', 'error']) test(`Balance rollout sheet ${label} ${state}`, async ({ page }) => {
    await openPortfolio(page, snapshot());
    const row = page.getByRole('button', { name: label, exact: true });
    await expect(row).toBeEnabled();
    // A direct sheet mount must check status too, even if its parent previously read enabled.
    await page.route('**/status', route => state === 'loading' ? undefined : route.fulfill({ status: state === 'error' ? 503 : 200, json: {} }));
    await row.click();
    await expect(page.getByRole('dialog').getByText('Not open yet', { exact: true })).toBeVisible();
    await expect(page.getByRole('dialog').getByRole('textbox')).toHaveCount(0);
    await expect(page.getByRole('dialog').getByRole('button', { name: /Hold to/ })).toHaveCount(0);
  });
}
