#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import process from 'node:process';

const liveUrl = (process.env.PORTAL_LIVE_URL || 'https://app.boulderroller.xyz').replace(/\/$/, '');
const apiUrl = (process.env.API_LIVE_URL || 'https://api.boulderroller.xyz').replace(/\/$/, '');
const expectedSha = process.env.EXPECTED_PORTAL_SHA || readGitSha();
const failures = [];
const expectedBalanceActionOrder = [
  'collect_dung',
  'deposit_cal',
  'withdraw_cal',
  'add_funds',
  'create_vault_usdc',
  'withdraw_to_wallet',
];
const bannedPrimaryLanguage = /\b(gas|transaction|tx|signature|explorer)\b/i;

function readGitSha() {
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return '';
  }
}

function check(condition, message) {
  if (!condition) failures.push(message);
}

function checkCanonicalHost(url, expectedHost, label) {
  const host = new URL(url).host;
  check(host === expectedHost, `${label} must use ${expectedHost}, got ${host}`);
}

async function readText(pathname, init) {
  const response = await fetch(`${liveUrl}${pathname}`, {
    redirect: 'follow',
    cache: 'no-store',
    ...init,
  });
  return {
    response,
    text: await response.text(),
  };
}

function isOrderedPrefix(enabledActions, actionOrder) {
  const highestIndex = Math.max(...enabledActions.map((action) => actionOrder.indexOf(action)), -1);
  if (highestIndex < 0) return true;
  const expectedPrefix = actionOrder.slice(0, highestIndex + 1);
  return JSON.stringify(enabledActions) === JSON.stringify(expectedPrefix);
}

checkCanonicalHost(liveUrl, 'app.boulderroller.xyz', 'Portal live URL');
checkCanonicalHost(apiUrl, 'api.boulderroller.xyz', 'API live URL');

const versionResponse = await fetch(`${liveUrl}/version.json?check=${Date.now()}`, {
  redirect: 'follow',
  cache: 'no-store',
});
check(versionResponse.ok, `Live version.json must return 2xx, got ${versionResponse.status}`);

const version = await versionResponse.json().catch(() => null);
check(version?.app === 'portal', 'Live version.json must identify the portal app');
check(typeof version?.sha === 'string' && version.sha.length >= 12, 'Live version.json must include a build SHA');
if (expectedSha) {
  check(version?.sha === expectedSha, `Live portal SHA ${version?.sha || 'unknown'} must match expected ${expectedSha}`);
}

const root = await readText('/', {
  headers: { Accept: 'text/html' },
});
check(root.response.ok, `Live portal root must return 2xx, got ${root.response.status}`);
check(root.text.includes('<div id="root"></div>'), 'Live portal root must serve the Vite shell');
check(root.text.includes('name="br-portal-build-sha"'), 'Live portal root must include the build SHA meta tag');
if (expectedSha) {
  check(root.text.includes(expectedSha), 'Live portal root meta tag must match the expected SHA');
}

const missingChunk = await fetch(`${liveUrl}/assets/br-missing-${Date.now()}.js`, {
  redirect: 'manual',
  cache: 'no-store',
  headers: { Accept: '*/*' },
});
check(missingChunk.status === 404, `Missing asset chunks must return 404, got ${missingChunk.status}`);
check(
  !(missingChunk.headers.get('content-type') || '').includes('text/html'),
  'Missing asset chunks must not return HTML',
);

const apiStatusResponse = await fetch(`${apiUrl}/status?check=${Date.now()}`, {
  redirect: 'follow',
  cache: 'no-store',
});
check(apiStatusResponse.ok, `Canonical API /status must return 2xx, got ${apiStatusResponse.status}`);

const apiStatus = await apiStatusResponse.json().catch(() => null);
check(apiStatus?.environment === 'production', `Canonical API environment must be production, got ${apiStatus?.environment || 'unknown'}`);
check(apiStatus?.solana_stub_mode === false, 'Canonical API must not run in Solana stub mode');
check(apiStatus?.auth_signature_bypass_effective === false, 'Canonical API must not allow auth signature bypass');
check(apiStatus?.dev_routes_enabled === false, 'Canonical API must not expose dev routes');

const rollout = apiStatus?.balance_rollout;
check(Boolean(rollout), 'Canonical API /status must expose balance_rollout');
if (rollout) {
  check(rollout.enforced === true, 'Balance rollout controls must be enforced on production');
  check(rollout.order_valid === true, 'Balance rollout action order must be valid');
  check(Array.isArray(rollout.blockers) && rollout.blockers.length === 0, 'Balance rollout must not report blockers');
  check(
    JSON.stringify(rollout.action_order) === JSON.stringify(expectedBalanceActionOrder),
    'Balance rollout action order must match the staged production order',
  );
  check(
    Array.isArray(rollout.enabled_actions) && isOrderedPrefix(rollout.enabled_actions, expectedBalanceActionOrder),
    'Enabled Balance actions must be an ordered rollout prefix',
  );
  check(
    Array.isArray(rollout.actions) && rollout.actions.length === expectedBalanceActionOrder.length,
    'Balance rollout must report every action status',
  );
  for (const action of rollout.actions ?? []) {
    check(!bannedPrimaryLanguage.test(action.label || ''), `Balance action label must avoid primary crypto jargon: ${action.label}`);
  }
}

if (failures.length > 0) {
  console.error('Live deploy check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log(`Live deploy check passed for ${liveUrl} at ${version.sha}.`);
