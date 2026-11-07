#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
import path from 'node:path';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);
const repoRoot = path.resolve(portalRoot, '../..');

const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

function assertContains(haystack, needle, label) {
  check(haystack.includes(needle), `${label} must contain ${needle}`);
}

function assertNotContains(haystack, needle, label) {
  check(!haystack.includes(needle), `${label} must not contain ${needle}`);
}

async function readRepo(relativePath) {
  return readFile(path.join(repoRoot, relativePath), 'utf8');
}

function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');
}

function extractStringLiterals(source) {
  const withoutComments = stripComments(source);
  const strings = [];
  const quotedPattern = /(['"])([^'"`\n]*?)\1/g;
  const templatePattern = /`([^`\n]*?)`/g;

  for (const line of withoutComments.split('\n')) {
    let match;
    while ((match = quotedPattern.exec(line)) !== null) {
      strings.push(match[2].replace(/\$\{[^}]*\}/g, ''));
    }
    while ((match = templatePattern.exec(line)) !== null) {
      strings.push(match[1].replace(/\$\{[^}]*\}/g, ''));
    }
  }

  return strings;
}

function assertNoVisibleStrings(source, banned, label) {
  const violations = [];
  for (const text of extractStringLiterals(source)) {
    for (const pattern of banned) {
      if (pattern.test(text)) {
        violations.push(`"${text}" matched ${pattern}`);
      }
    }
  }
  check(violations.length === 0, `${label} visible strings drifted: ${violations.join('; ')}`);
}

const languageSpec = await readRepo('docs/design/LANGUAGE_SPEC.md');
const portalTruths = await readRepo('docs/PORTAL_TRUTHS.md');
const mobileTruths = await readRepo('docs/MOBILE_TRUTHS.md');
const packageJson = JSON.parse(await readRepo('web/portal/package.json'));
const vaultView = await readRepo('web/portal/src/pages/VaultView.tsx');
const portfolioView = await readRepo('web/portal/src/pages/Portfolio.tsx');
const accessPanel = await readRepo('web/portal/src/components/auth/AccessPanel.tsx');
const climbDisplay = await readRepo('mobile/src/lib/climbDisplay.ts');
const climbsScreen = await readRepo('mobile/src/screens/ClimbsScreen.tsx');

for (const [label, content] of [
  ['language spec', languageSpec],
  ['portal truths', portalTruths],
  ['mobile truths', mobileTruths],
]) {
  assertContains(content, 'Boulder Roller Balance', label);
  assertContains(content, 'CAL counted', label);
  assertContains(content, 'DUNG ready', label);
  assertContains(content, 'DUNG collected', label);
  assertContains(content, 'Deposit CAL', label);
  assertContains(content, 'Withdraw CAL', label);
  assertContains(content, 'Create Vault', label);
  assertContains(content, 'Pay with USDC', label);
  assertContains(content, 'Pending', label);
  assertContains(content, 'Delayed', label);
  assertContains(content, 'Needs review', label);
}

assertContains(languageSpec, '### Copy QA Targets', 'language spec');
assertContains(languageSpec, 'npm run qa:balance-language --prefix web/portal', 'language spec');
assertContains(portalTruths, '## 10.1 Boulder Roller Balance State Language', 'portal truths');
assertContains(mobileTruths, '## 10.3 Boulder Roller Balance State Language', 'mobile truths');

check(
  packageJson.scripts?.['qa:balance-language'] === 'node scripts/check-balance-language-surface.mjs',
  'package.json must expose qa:balance-language',
);
check(
  Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:balance-language')),
  'package.json perf:release must run qa:balance-language',
);

assertContains(vaultView, 'Collect DUNG', 'VaultView');
assertContains(vaultView, 'DUNG received in your wallet.', 'VaultView');
assertNotContains(vaultView, 'DUNG added to your Balance.', 'VaultView');
assertContains(portfolioView, 'Wallet CAL', 'Portfolio');
assertContains(portfolioView, 'Wallet DUNG', 'Portfolio');
assertContains(portfolioView, 'Wallet snapshot', 'Portfolio');
assertNotContains(portfolioView, 'Balance snapshot', 'Portfolio');
assertContains(portfolioView, "walletDung?.status === 'unavailable'", 'Portfolio');
assertNotContains(portfolioView, "dungBalanceBaseUnits ?? '0'", 'Portfolio');
assertContains(vaultView, 'Deposit CAL', 'VaultView');
assertContains(vaultView, 'Withdraw CAL', 'VaultView');
assertContains(vaultView, 'Leaderboard pool', 'VaultView');
assertContains(vaultView, 'dist.leaderboardAmountBaseUnits', 'Climb DUNG history source');
assertNoVisibleStrings(
  vaultView,
  [
    /record royalty/i,
    /view transaction/i,
    /transaction submitted/i,
    /^harvest/i,
    /^unstake/i,
    /gas/i,
  ],
  'VaultView',
);

assertContains(accessPanel, 'Send code', 'AccessPanel');
assertContains(accessPanel, 'Use your wallet', 'AccessPanel');
assertNotContains(accessPanel, 'Connect wallet', 'AccessPanel');
assertNoVisibleStrings(
  accessPanel,
  [
    /transaction signature/i,
    /explorer link/i,
    /gas/i,
  ],
  'AccessPanel',
);

assertContains(climbDisplay, 'Balance •', 'mobile climbDisplay');
assertContains(climbDisplay, 'Balance open', 'mobile climbDisplay');
assertNotContains(climbDisplay, '`Vault •', 'mobile climbDisplay');

assertContains(climbsScreen, 'Balance •', 'mobile ClimbsScreen');
assertContains(climbsScreen, 'Balance open', 'mobile ClimbsScreen');
assertNotContains(climbsScreen, '`Vault •', 'mobile ClimbsScreen');

if (failures.length > 0) {
  console.error('Balance language surface gate failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Balance language surface gate passed.');
