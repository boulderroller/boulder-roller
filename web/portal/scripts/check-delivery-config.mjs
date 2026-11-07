#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
import path from 'node:path';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);
const repoRoot = path.resolve(portalRoot, '../..');
const failures = [];

function fail(message) {
  failures.push(message);
}

async function readJson(filePath) {
  return JSON.parse(await readFile(filePath, 'utf8'));
}

async function readText(filePath) {
  return readFile(filePath, 'utf8');
}

async function readContractFile(filePath, label) {
  try {
    return await readText(filePath);
  } catch (error) {
    if (error?.code === 'ENOENT') {
      fail(`${label} must exist`);
      return '';
    }
    throw error;
  }
}

function hasExactLine(text, line) {
  return text.split(/\r?\n/u).some((candidate) => candidate === line);
}

function findHeaderRule(config, source) {
  return (config.headers ?? []).find((rule) => rule.source === source);
}

function hasHeader(rule, key, value) {
  return (rule?.headers ?? []).some((header) => header.key === key && header.value === value);
}

function hasHtmlAcceptGuard(rule) {
  return (rule?.has ?? []).some((condition) => (
    condition.type === 'header'
    && condition.key === 'accept'
    && condition.value === '.*text/html.*'
  ));
}

function checkVercelConfig(label, config, expectedDeploy) {
  for (const [key, value] of Object.entries(expectedDeploy)) {
    if (config[key] !== value) {
      fail(`${label} must set ${key} to ${JSON.stringify(value)} for the app.boulderroller.xyz deploy path`);
    }
  }

  const assetsRule = findHeaderRule(config, '/assets/:path*');
  const globalRule = findHeaderRule(config, '/(.*)');

  if (!hasHeader(assetsRule, 'Cache-Control', 'public, max-age=31536000, immutable')) {
    fail(`${label} must serve hashed /assets chunks with immutable one-year caching`);
  }

  for (const [key, value] of [
    ['X-Content-Type-Options', 'nosniff'],
    ['X-Frame-Options', 'DENY'],
    ['Referrer-Policy', 'strict-origin-when-cross-origin'],
  ]) {
    if (!hasHeader(globalRule, key, value)) {
      fail(`${label} must set ${key}: ${value}`);
    }
  }

  const rewrites = config.rewrites ?? [];
  const apiRewrite = rewrites.find((rewrite) => rewrite.source === '/api/:path*');
  const spaRewrite = rewrites.find((rewrite) => rewrite.source === '/(.*)');

  if (apiRewrite?.destination !== 'https://api.boulderroller.xyz/:path*') {
    fail(`${label} /api rewrite must target canonical API host`);
  }

  if (spaRewrite?.destination !== '/index.html') {
    fail(`${label} must keep SPA fallback rewrite`);
  }

  if (!hasHtmlAcceptGuard(spaRewrite)) {
    fail(`${label} SPA fallback rewrite must be guarded by Accept: text/html so missing chunks do not return HTML`);
  }
}

const portalVercel = await readJson(path.join(portalRoot, 'vercel.json'));
const webVercel = await readJson(path.join(repoRoot, 'web/vercel.json'));
const portalPackage = await readJson(path.join(portalRoot, 'package.json'));
const edgeNginx = await readText(path.join(repoRoot, 'infrastructure/edge/nginx/api.boulderroller.xyz.conf'));
const vercelIgnore = await readContractFile(path.join(repoRoot, '.vercelignore'), '.vercelignore');
const portalCi = await readContractFile(
  path.join(repoRoot, '.github/workflows/portal-ci.yml'),
  '.github/workflows/portal-ci.yml',
);

const expectedPortalCi = `name: Portal CI

on:
  push:
    branches: [main]
    paths:
      - 'web/portal/**'
      - '.github/workflows/portal-ci.yml'
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    paths:
      - 'web/portal/**'
      - '.github/workflows/portal-ci.yml'

permissions:
  contents: read

concurrency:
  group: \${{ github.workflow }}-\${{ github.event.pull_request.number || github.ref }}-\${{ github.event.pull_request.draft || false }}
  cancel-in-progress: \${{ github.event_name == 'pull_request' }}

jobs:
  release:
    # Drafts skip CI; Codex runs the full suites locally each round.
    if: github.event_name != 'pull_request' || !github.event.pull_request.draft
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web/portal

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: web/portal/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Run mandatory release gate
        run: npm run perf:release
`;

const expectedPerfRelease = 'npm run test:balance-rollout && npm run test:transaction-intent && npm run test:formatters && npm run test:climb-detail && npm run build && npm run typecheck:gate && npm run qa:formatters-contract && npm run perf:bundle && npm run perf:delivery && npm run qa:static-assets && npm run qa:first-traverse && npm run qa:portal-shell && npm run qa:home-feed-footer && npm run qa:object-pages && npm run qa:modal-policy && npm run qa:balance-language && npm run qa:ride-language && npm run qa:ratified-removals && npm run qa:typography && npm run qa:eyebrows && npm run qa:readiness';
const expectedTransactionIntentTest = 'node --no-warnings --experimental-strip-types --test scripts/test-transaction-intent.mts';
const expectedFormatterTest = 'node --no-warnings --experimental-strip-types --test scripts/test-formatters.mts';

checkVercelConfig('web/portal/vercel.json', portalVercel, {
  framework: null,
  buildCommand: 'npm run perf:release',
  outputDirectory: 'build',
  installCommand: 'npm install',
});
checkVercelConfig('web/vercel.json', webVercel, {
  framework: null,
  buildCommand: 'cd portal && npm install && npm run perf:release',
  outputDirectory: 'portal/build',
  installCommand: "echo 'Install handled in buildCommand'",
});

for (const requiredLine of [
  '!.vercelignore',
  '!.github',
  '!.github/workflows',
  '!.github/workflows/portal-ci.yml',
  '!backend',
  '!backend/app',
  '!backend/app/config.py',
  '!backend/app/public_preview_contracts.py',
  '!backend/app/routes',
  '!backend/app/routes/public_previews.py',
  '!backend/tests',
  '!backend/tests/fixtures',
  '!backend/tests/fixtures/client_v1',
  '!backend/tests/fixtures/client_v1/ride_status_response.json',
  '!backend/tests/fixtures/client_v1/surface_requirements.json',
  '!docker-compose.yml',
  '!docs',
  '!docs/PORTAL_TRUTHS.md',
  '!docs/MOBILE_TRUTHS.md',
  '!docs/design',
  '!docs/design/LANGUAGE_SPEC.md',
  '!docs/design/BR_IDENTITY_SYSTEM.md',
  '!docs/design/PROOF_ECONOMY_PRIMITIVES.md',
  '!docs/design/PORTAL_DESIGN_SYSTEM_2026.md',
  '!docs/design/PORTAL_DATA_INTERACTION_CONTRACT.md',
  '!docs/design/FIRST_TRAVERSE_PUBLIC_PREVIEW_ARCHITECTURE.md',
  '!docs/design/README.md',
  '!docs/gitbook',
  '!docs/gitbook/**',
  'docs/gitbook/node_modules',
  'docs/gitbook/.vitepress/dist',
  'docs/gitbook/.vitepress/cache',
  'docs/gitbook/.vercel',
  '!infrastructure',
  '!infrastructure/Caddyfile',
  '!infrastructure/edge',
  '!infrastructure/edge/nginx',
  '!infrastructure/edge/nginx/api.boulderroller.xyz.conf',
  '!mobile',
  '!mobile/src',
  '!mobile/src/**',
  '!web/vercel.json',
]) {
  if (!hasExactLine(vercelIgnore, requiredLine)) {
    fail(`.vercelignore must include ${requiredLine} for npm run perf:release`);
  }
}

if (portalCi.replaceAll('\r\n', '\n') !== expectedPortalCi) {
  fail('.github/workflows/portal-ci.yml must exactly preserve the draft-aware, fail-closed Portal CI contract');
}

if (portalPackage.engines?.node !== '22.x') {
  fail('web/portal/package.json must pin the Vercel and CI Node runtime to 22.x');
}

if (portalPackage.scripts?.['test:transaction-intent'] !== expectedTransactionIntentTest) {
  fail('web/portal/package.json must preserve the transaction-intent test command');
}

if (portalPackage.scripts?.['test:formatters'] !== expectedFormatterTest) {
  fail('web/portal/package.json must preserve the formatter behavior test command');
}

if (portalPackage.scripts?.['perf:release'] !== expectedPerfRelease) {
  fail('web/portal/package.json must preserve the fail-closed mandatory release chain');
}

if (!edgeNginx.includes('Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always')) {
  fail('API edge nginx config must set long-lived HSTS with preload');
}

if (!edgeNginx.includes('proxy_read_timeout 120s;')) {
  fail('API edge nginx config must preserve 120s read timeout for long ride-processing requests');
}

if (failures.length > 0) {
  console.error('Delivery config check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Delivery config check passed.');
