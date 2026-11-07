import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';
import { stage1Copy } from '../src/lib/stage1Copy';

const hill = '11111111111111111111111111111111';
const climb = '00000000-0000-0000-0000-000000000001';
const user = { id: 'stage1-rider', wallet: '11111111111111111111111111111111', username: 'riderone', is_public: true, preferred_units: 'metric', theme_id: 'hoo-breddin', is_dark_mode: false };
const cashMint = 'DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne';
const stakingMint = 'J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn';
const payout = { hill, climbName: 'Fixture canonical climb', week: '4', mint: cashMint, recipient: user.wallet, amount: '123456789', kind: 'cash', signature: 'fixture-signature', chainSlot: 100 };
const evidence = process.env.STAGE1_PORTAL_EVIDENCE;

export async function fixtures(page: Page, { live = true, actions = true, empty = false, fail = false, signedIn = true, calVault = false } = {}) {
  const stage1Reads: string[] = [];
  await page.addInitScript((signedIn) => {
    if (signedIn) localStorage.setItem('br_authenticated', 'true');
    localStorage.setItem('br_setup_reprompt_dismissed', 'true');
  }, signedIn);
  await page.route('**/*', async route => {
    const req = route.request(); const url = new URL(req.url());
    if (!['fetch', 'xhr'].includes(req.resourceType()) || url.pathname.startsWith('/src/') || url.pathname.startsWith('/node_modules/')) return route.continue();
    const p = url.pathname.replace(/^\/api/, '');
    let body: unknown = {};
    if (p.startsWith('/stage1/')) {
      stage1Reads.push(p);
      if (fail) return route.fulfill({ status: 503, contentType: 'application/json', body: '{}' });
      if (p.endsWith('/hill')) body = { hill };
      else if (p.endsWith('/bonding')) body = { hill, bonded: true, foundingCount: '7', lineLamports: '10000000000', week: 4,
        split: { everyRiderByAscents: 65, topTen: 25, localLegend: 10 },
        assets: empty ? [] : [{ mint: stakingMint, backingLamports: '8750000000' }, { mint: cashMint, backingEligible: false, weekPool: { available: '5000000', pool: '700000', published: false } }] };
      else if (p.endsWith('/lookups')) body = { tables: [], nextOffset: null };
      else if (p.endsWith('/eligibility')) body = { chainTime:'1794000000', week:'4', actions:{'convert-pledge':{refreshRate:true},'begin-withdrawal':{refreshRate:true},'complete-withdrawal':{refreshRate:true}} };
      else if (p.endsWith('/claims')) body = { claims: [], nextOffset: null };
      else if (p.endsWith('/registration')) body = { registration: empty ? null : { person: user.wallet, recipient: user.wallet, registeredAt: '1791201600' }, held: [] };
      else if (p.endsWith('/pay')) body = { paid: empty ? [] : [payout], pending: [] };
      else if (p.endsWith('/dung')) body = { paid: empty ? [] : [{ ...payout, mint: 'CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk', amount: '4250000000', kind: 'dung' }], pending: [] };
      else if (p.endsWith('/pledges')) {
        const lot = { address: 'fixture-lot', depositId:'1', hill, climbName:'Fixture canonical climb', mint:stakingMint, units:'1000000000',basisLamports:'1000000000',lockWeeks:26,lockEnd:'1791201600',founding:true,converted:false,cancelled:false,exiting:false,returnedUnits:'0',pendingRequest:hill,sequence:'2',chainTime:'1793900000',cityState:{seasonAnchor:'1791201600',intakePaused:false,providerSlots:1,assetCount:1},hillState:{bonded:true,foundingCutoff:'1',foundingFreshSlots:1,assetLots:['1']},withdrawals:[] };
        body = { pledges:empty ? [] : [
          {...lot,address:'fixture-unbonded',founding:false,hillState:{...lot.hillState,bonded:false}},
          {...lot,address:'fixture-excluded',founding:false,sequence:'1'},
          {...lot,address:'fixture-active'},
          {...lot,address:'fixture-locked',lockEnd:'1891201600'},
          {...lot,address:'fixture-notice-lot',pendingRequest:'fixture-notice',withdrawals:[{address:'fixture-notice',data:{requestId:'1',lot:'fixture-notice-lot',noticeAt:'1791288000',eligibleAt:'1793707200',status:0}}]},
          {...lot,address:'fixture-exit-lot',exiting:true,exitRequest:'fixture-exit',withdrawals:[{address:'fixture-exit',parentDepositId:'1',data:{requestId:'2',exitLot:'fixture-exit-lot',noticeAt:'1791288000',eligibleAt:'1793707200',status:1}}]},
          {...lot,address:'fixture-returned',units:'0',basisLamports:'0',returnedUnits:'1000000000'},
          {...lot,address:'fixture-cancelled',cancelled:true},
        ] };
      }
    } else if (p.startsWith('/auth/')) body = { authenticated: signedIn, invite_required: false, invite_validated: true, needs_profile_setup: false, user: signedIn ? user : null };
    else if (p === '/users/me' || p === '/me') body = user;
    else if (p.startsWith('/compliance/deletion')) return route.fulfill({ status: 404, json: { detail: 'No request' } });
    else if (p === '/status') body = { stage1: { live, actions }, balanceRollout: { enforced: true, orderValid: true, enabledActions: [], blockers: [] } };
    else if (p === '/portfolio/snapshot') body = { portfolio: { stakedPositions: [] }, distributions: { distributions: [] } };
    else if (p === '/users/me/leaderboard-positions') body = { positions: [], stats: {} };
    else if (p === '/notifications') body = { notifications: empty ? [] : [{ id: 'stage1-payout', notificationType: 'payout_received', title: 'payout_received', read: false, createdAt: '2026-10-15T12:00:00Z', actionUrl: '/profile?tab=portfolio', metadata: { stage1: true, kind: 'cash', amountBaseUnits: payout.amount, mint: payout.mint, week: 4 } }], unreadCount: empty ? 0 : 1 };
    else if (p === `/climbs/${climb}`) body = { id: climb, canonId: climb, name: 'Fixture climb', revisionState: 'current', hasVault: calVault, vaultId: calVault ? 42 : null, elevationProfile: [{ distanceM: 0, elevationM: 0 }, { distanceM: 1000, elevationM: 50 }], vaultCreation: { state: 'unavailable', paymentMethods: [] } };
    else if (p === `/public/previews/climbs/${climb}`) body = { contractVersion: 'public_preview.v1', objectType: 'climb', id: climb, title: 'Fixture climb', canonicalPath: `/climbs/${climb}`, previewPolicy: { mode: 'public_preview', objectType: 'climb' }, seo: { title: 'Fixture climb' }, assets: {}, freshness: { source: 'fixture' }, climb: { id: climb, canonId: climb, name: 'Fixture climb', hasVault: false } };
    else if (p === '/vaults/42') body = { id: 42, name: 'Fixture climb', onChainActive: true, totalStakedBaseUnits: '10000000000', signatureHex: 'fixture-signature' };
    else if (p === '/vaults/my/stakes') body = { stakes: [] };
    else if (p.includes('/my-completions')) body = { efforts: [], totalCount: 0 };
    else if (p.endsWith('/leaderboard')) body = { leaderboard: [] };
    else if (p === '/rides') body = [];
    else if (p === '/climbs/list') body = { climbs: [] };
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  return stage1Reads;
}

for (const [surface, url] of [['climb', `/climbs/${climb}`], ['portfolio', '/profile?tab=portfolio'], ['notifications', '/notifications']] as const) {
  test(`${surface}: dark gate issues no stage1 reads and hides stage1 rows`, async ({ page }) => {
    const reads = await fixtures(page, { live: false }); await page.goto(url);
    await expect(page.locator('main')).toBeVisible();
    await expect(page.getByText(/^TIM:/)).toHaveCount(0);
    expect(reads).toEqual([]);
  });
  test(`${surface}: empty`, async ({ page }) => {
    await fixtures(page, { empty: true }); await page.goto(url);
    if (surface === 'notifications') await expect(page.getByText('Nothing here yet')).toBeVisible();
    else await expect(page.getByText(stage1Copy.empty, { exact: true }).first()).toBeVisible();
  });
  for (const width of [1440, 390]) test(`${surface}: populated fixture ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await fixtures(page); await page.goto(url);
    if (surface === 'notifications') {
      await expect(page.locator('[data-kind="money"]')).toContainText('123.456789');
      await expect(page.locator('[data-kind="money"]')).not.toContainText('DUNG');
      await expect(page.getByText(stage1Copy.payoutNotification, { exact: true })).toBeVisible();
      const value = page.locator('.notifications-log__value');
      expect(await value.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
      expect((await value.boundingBox())!.x + (await value.boundingBox())!.width).toBeLessThanOrEqual(width);
    } else {
      await expect(page.locator(`[data-stage1="${surface}"]`)).toBeVisible();
      await expect(page.locator(`[data-stage1="${surface}"]`)).toContainText('123.456789');
      await expect(page.locator(`[data-stage1="${surface}"] [data-stage1-action="registration"]`)).toHaveCount(0);
      await expect(page.locator(`[data-stage1="${surface}"] [data-stage1-action="self-claim"]`)).toHaveCount(0);
      await expect(page.getByRole('button',{name:stage1Copy.pledgeActions,exact:true})).toHaveCount(6);
      for (const control of await page.getByRole('button',{name:stage1Copy.pledgeActions,exact:true}).all()) await control.click();
      await expect(page.locator('[data-stage1-pledge="fixture-notice-lot"] [data-stage1-action="begin-withdrawal"]')).toBeVisible();
      await expect(page.locator('[data-stage1-pledge="fixture-exit-lot"] [data-stage1-action="complete-withdrawal"]')).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (evidence) {
      if (surface === 'climb' && width === 390) await page.getByText(new RegExp('^' + stage1Copy.split.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))).scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(evidence, `phase3-${surface}-fixture-${width}.png`), fullPage: true });
      if (surface === 'climb' && width === 390) {
        await page.getByText(stage1Copy.pay, { exact: true }).scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(evidence, 'phase3-climb-pay-fixture-390.png'), fullPage: true });
        await page.getByText(stage1Copy.eligible, { exact: true }).first().scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(evidence, 'phase3-climb-pledges-fixture-390.png'), fullPage: true });
      }
    }
    if (surface === 'notifications') {
      await page.getByRole('button', { name: 'Open notifications', exact: true }).click();
      await expect(page.locator('.portal-shell-notification__title')).toBeVisible();
      const value = page.locator('.portal-shell-notification__value');
      expect(await value.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    }
  });
}

for (const [surface, url] of [['climb', `/climbs/${climb}`], ['portfolio', '/profile?tab=portfolio']] as const) {
  test(`${surface}: failure is a ratified state without invented amounts`, async ({ page }) => {
    await fixtures(page, { fail: true }); await page.goto(url);
    await expect(page.getByText(stage1Copy.unavailable, { exact: true }).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText('123.456789')).toHaveCount(0);
  });
}

test('public climb reads aggregate bonding without owner routes', async ({ page }) => {
  const reads = await fixtures(page, { signedIn: false }); await page.goto(`/climbs/${climb}`);
  await expect(page.locator('[data-stage1="climb"]')).toContainText('8.75 SOL');
  expect(reads.some(p => p.includes('/me/'))).toBe(false);
});

for (const fail of [false, true]) test(`CAL Vault survives Stage 1 ${fail ? '503' : 'success'}`, async ({ page }) => {
  await fixtures(page, { calVault: true, fail }); await page.goto(`/climbs/${climb}`);
  await expect(page.locator('#climb-vault')).toBeVisible();
  await expect(page.getByRole('link', { name: /Deposit CAL/ })).toBeVisible();
  if (fail) await expect(page.getByText(stage1Copy.unavailable, { exact: true }).first()).toBeVisible();
  else await expect(page.locator('[data-stage1="climb"]')).toBeVisible();
});

test('indexer lapse leaves section unavailable states and payout notifications visible',async({page})=>{
  await fixtures(page,{fail:true});await page.goto('/profile?tab=portfolio');
  await expect(page.locator('[data-stage1="portfolio"]')).toBeVisible();
  await expect(page.getByText(stage1Copy.unavailable,{exact:true}).first()).toBeVisible();
  await page.goto('/notifications');
  await expect(page.getByText(stage1Copy.payoutNotification,{exact:true})).toBeVisible();
  await expect(page.locator('[data-kind="money"]')).toContainText('123.456789');
});
