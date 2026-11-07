#!/usr/bin/env node

import { chromium } from 'playwright';

const DEFAULT_FRONTEND_URL = 'http://127.0.0.1:3004';
const DEFAULT_TIMEOUT_MS = 15_000;

function readEnv(name, fallback = '') {
  const value = process.env[name];
  return value && value.trim() ? value.trim() : fallback;
}

function normalizeBaseUrl(value) {
  return value.replace(/\/$/, '');
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function checkPage(page, label, url, readyText, expectedTexts = []) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: DEFAULT_TIMEOUT_MS });
  await page.waitForSelector(`text=${readyText}`, { timeout: DEFAULT_TIMEOUT_MS });
  for (const text of expectedTexts) {
    await page.waitForSelector(`text=${text}`, { timeout: DEFAULT_TIMEOUT_MS });
  }

  const errorState = page.locator('.state-card--error');
  const errorStateCount = await errorState.count();
  if (errorStateCount > 0) {
    const visibleError = errorState.first();
    const visible = await visibleError.isVisible().catch(() => false);
    if (visible) {
      const text = await visibleError.innerText().catch(() => 'unavailable state');
      throw new Error(`${label}: page rendered an unavailable state (${text.replace(/\s+/g, ' ')})`);
    }
  }

  const loadingTexts = [
    'Loading network state',
    'Resolving climb state',
    'Decoding transaction',
    'Resolving account state',
  ];

  for (const text of loadingTexts) {
    const locator = page.getByText(text);
    if ((await locator.count()) > 0) {
      const visible = await locator.first().isVisible().catch(() => false);
      assert(!visible, `${label}: page stayed in loading state`);
    }
  }

  console.log(`PASS ${label}`);
}

async function firstClimbIdFromObservatoryPage(page) {
  const firstClimbLink = page.locator('a[href*="/climb/"]').first();
  const href = await firstClimbLink.getAttribute('href', { timeout: DEFAULT_TIMEOUT_MS }).catch(() => '');
  const match = href ? href.match(/\/climb\/([^/?#]+)/) : null;
  return match ? decodeURIComponent(match[1]) : '';
}

async function main() {
  const frontendBase = normalizeBaseUrl(readEnv('BOULDERSCAN_FRONTEND_URL', DEFAULT_FRONTEND_URL));
  const configuredClimbId = readEnv('BOULDERSCAN_CLIMB_ID');
  let climbId = configuredClimbId;
  const txSignature = readEnv('BOULDERSCAN_TX_SIGNATURE');
  const accountPubkey = readEnv('BOULDERSCAN_ACCOUNT_PUBKEY');

  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1800 } });

  try {
    console.log(`Checking browser routes at ${frontendBase}`);
    const projectionResponse = page.waitForResponse(r => r.url().includes('/v1/observatory') && r.status() === 200);
    await checkPage(page, 'observatory browser', `${frontendBase}/`, 'Recent');
    const projection = await (await projectionResponse).json();
    await page.waitForSelector('[data-room-loaded="true"]');
    await page.locator('[data-ground-ready="true"]').waitFor({ timeout: 45_000 });
    assert(await page.locator('.week-column').count() === 1, 'home: Week column');
    const week = projection.week || {};
    if (week.epoch != null) {
      assert(await page.locator('.week-desktop-head').innerText().then(t => t.includes(`Week ${week.epoch}`)), 'home: indexed Week');
      assert(await page.title() === `Week ${week.epoch} · BoulderScan`, 'home: Week tab');
    }
    for (const key of ['climbs_registered', 'cal_deposited', 'riders', 'rides_attested', 'dung_distributed']) {
      const attested = week[key] != null && Number(week[key]) > 0;
      assert(await page.locator(`[data-week-key="${key}"]`).count() === (attested ? 1 : 0), `home: ${key} is present only when attested`);
    }
    const expectedEvents = projection.recent_events.filter(e => e.kind && e.object && e.signature);
    for (const event of expectedEvents) {
      assert(await page.locator(`.observatory-row[href="/tx/${event.signature}"]`).count() > 0, 'home: Recent transaction row');
    }
    assert(await page.locator('.week-stamp').count() === (projection.indexed ? 1 : 0), 'home: indexed stamp abstains without a checkpoint');
    if (projection.indexed) assert((await page.locator('.week-stamp').innerText()).startsWith(`Indexed to slot ${Number(projection.indexed.slot).toLocaleString('en-US')} · `), 'home: indexed slot');
    const homeText = await page.locator('body').innerText();
    for (const retired of ['Top Climbs', 'No climb activity indexed yet', 'Observatory unavailable', 'Supply State', 'Universal Lookup', 'CAL Staked', 'Indexer Lagging', 'Loading network state', 'No recent protocol events']) {
      assert(!homeText.includes(retired), `home: retired species ${retired}`);
    }
    assert(await page.locator('.week-ledger .state-card, .week-ledger .inline-notice').count() === 0, 'home: absent figures have no replacement sentence');
    await page.getByRole('button', { name: 'Search climbs, riders, transactions', exact: true }).click();
    await page.getByRole('dialog', { name: 'Search', exact: true }).waitFor();
    for (const name of ['Climbs', 'Riders', 'Transactions']) assert(await page.getByRole('button', { name, exact: true }).count() === 1, `home: Search ${name} scope`);
    await page.getByRole('button', { name: 'Done', exact: true }).click();
    if (!configuredClimbId) {
      climbId = await firstClimbIdFromObservatoryPage(page);
      if (climbId) {
        console.log(`INFO using climb id ${climbId} from observatory browser links`);
      } else {
        assert(await page.locator('.week-column').count() === 1, 'clean-slate: Week column remains');
        assert(!homeText.includes('No climb activity indexed yet'), 'clean-slate: no substitute sentence');
        console.log('PASS clean-slate climb browser state');
      }
    }

    if (climbId) {
      const climbResponse = page.waitForResponse(r => r.url().includes(`/v1/climbs/${climbId}`) && r.status() === 200);
      await page.goto(`${frontendBase}/climb/${climbId}`, { waitUntil: 'domcontentloaded', timeout: DEFAULT_TIMEOUT_MS });
      const climbProjection = await (await climbResponse).json();
      await checkPage(page, 'climb browser', `${frontendBase}/climb/${climbId}`, 'Leaderboard', [
        'Completions', 'Positions', 'Settlements', 'Registration',
      ]);
      const identity = page.locator('[data-climb-identity]');
      assert(await identity.isVisible(), 'climb: rendered identity card');
      assert(await identity.locator('h1').innerText() === climbProjection.climb.name, 'climb: indexed identity');
      const text = await page.locator('main').innerText();
      for (const retired of ['Distribution History', 'Vault Balances', 'DUNG Ready', 'Next Week', 'DUNG Carry', 'No distribution history indexed', 'Claimable Rewards', 'Next Settlement', 'Carry Forward', 'Record Royalty', 'Climb Identity']) {
        assert(!text.includes(retired), `climb: ${retired} is absent`);
      }
      assert(await page.locator('.climb-ledger .state-card, .climb-ledger .inline-notice').count() === 0, 'climb: absent figures have no replacement sentence');
      for (const section of ['completions', 'positions', 'settlements']) {
        const rows = climbProjection[section] ?? [];
        const rendered = page.locator(`[data-climb-section="${section}"] [data-ledger-row]`);
        assert(await rendered.count() === Math.min(rows.length, section === 'completions' ? 3 : section === 'settlements' ? 3 : rows.length), `climb: ${section} rows follow indexed projection`);
      }
      for (const key of ['deposited', 'leaderboard_pool']) {
        const present = climbProjection[key] != null && Number(climbProjection[key]) > 0;
        assert(await page.locator(`[data-climb-figure="${key}"]`).count() === (present ? 1 : 0), `climb: ${key} absent when not indexed`);
      }
      for (const key of ['climb_account', 'vault_account', 'signature', 'canon_version']) {
        const present = climbProjection.registration?.[key] != null;
        assert(await page.locator(`[data-registration-key="${key}"]`).count() === (present ? 1 : 0), `climb: registration ${key} follows indexed projection`);
      }
    } else {
      console.log('SKIP climb browser (clean-slate V4-B registry)');
    }

    if (txSignature) {
      await checkPage(page, 'transaction browser', `${frontendBase}/tx/${txSignature}`, 'On chain', ['Accounts', 'Solana Explorer']);
      const text = await page.locator('main').innerText();
      for (const retired of ['Chain Details', 'Token Flow', 'Overview', 'Protocol token movements', 'What this transaction touched', 'Slot, fee, and decoded counts']) assert(!text.includes(retired), `transaction: ${retired} is absent`);
    } else {
      console.log('SKIP transaction browser (set BOULDERSCAN_TX_SIGNATURE)');
    }

    if (accountPubkey) {
      await checkPage(page, 'account browser', `${frontendBase}/account/${accountPubkey}`, 'Balances', ['Rides attested', 'Positions', 'Completions', 'Settlements', 'Activity']);
      const text = await page.locator('main').innerText();
      for (const retired of ['Protocol Summary', 'Beetle Cards', 'Beetle Score', 'Training Load', 'Ride Proofs', 'Live Token Accounts', 'Indexed Soulbound Progress']) assert(!text.includes(retired), `account: ${retired} is absent`);
    } else {
      console.log('SKIP account browser (set BOULDERSCAN_ACCOUNT_PUBKEY)');
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`FAIL ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
