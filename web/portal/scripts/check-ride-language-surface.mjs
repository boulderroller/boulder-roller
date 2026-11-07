#!/usr/bin/env node

import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const portalRoot = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(portalRoot, '../..');

const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
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

async function sourceFiles(relativeDirectory) {
  const root = path.join(repoRoot, relativeDirectory);
  const files = [];

  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (entry.name === '__tests__' || entry.name === 'node_modules') continue;
      const absolutePath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(absolutePath);
      } else if (/\.(?:ts|tsx)$/.test(entry.name) && !/\.test\.[^.]+$/.test(entry.name)) {
        files.push(absolutePath);
      }
    }
  }

  await visit(root);
  return files;
}

async function markdownFiles(relativeDirectory) {
  const root = path.join(repoRoot, relativeDirectory);
  const files = [];

  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (entry.name === 'node_modules') continue;
      const absolutePath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(absolutePath);
      } else if (entry.name.endsWith('.md')) {
        files.push(path.relative(repoRoot, absolutePath));
      }
    }
  }

  await visit(root);
  return files.sort();
}

const bannedObjectName = /\bride records?\b/i;
const ambiguousRecordLabels = [
  /\bRecord Board\b/i,
  /^Record ready$/i,
  /^App record$/i,
  /^Checking record$/i,
  /^Record pending$/i,
  /^Record unavailable$/i,
  /^Private record$/i,
  /^Chain record$/i,
  /^Record account$/i,
  /^Vault record$/i,
  /^Board$/,
  /^Climb record$/i,
  /^Record and sharing$/i,
  /^Activity record$/i,
  /\bclimb record is ready\b/i,
  /^Copy record$/i,
];

for (const relativeDirectory of ['web/portal/src', 'mobile/src']) {
  for (const absolutePath of await sourceFiles(relativeDirectory)) {
    const source = await readFile(absolutePath, 'utf8');
    const relativePath = path.relative(repoRoot, absolutePath);
    for (const value of extractStringLiterals(source)) {
      if (bannedObjectName.test(value)) {
        failures.push(`${relativePath}: rider-facing string "${value}" gives the ride a second object name`);
      }
      for (const pattern of ambiguousRecordLabels) {
        if (pattern.test(value)) {
          failures.push(`${relativePath}: rider-facing string "${value}" does not name its actual function`);
        }
      }
    }
  }
}

const gitbookDocs = await markdownFiles('docs/gitbook');
const activeProductDocs = [...new Set([
  'docs/design/LANGUAGE_SPEC.md',
  'docs/design/BR_IDENTITY_SYSTEM.md',
  'docs/design/PROOF_ECONOMY_PRIMITIVES.md',
  'docs/design/PORTAL_DESIGN_SYSTEM_2026.md',
  'docs/PORTAL_TRUTHS.md',
  'docs/MOBILE_TRUTHS.md',
  'docs/gitbook/.vitepress/config.ts',
  'docs/gitbook/index.md',
  'docs/gitbook/rides/processing.md',
  'docs/gitbook/rides/results.md',
  'docs/gitbook/reference/glossary.md',
  ...gitbookDocs,
  'backend/tests/fixtures/client_v1/surface_requirements.json',
])];

for (const relativePath of activeProductDocs) {
  const source = await readRepo(relativePath);
  check(!bannedObjectName.test(source), `${relativePath} still gives the ride a second object name`);
}

const languageSpec = await readRepo('docs/design/LANGUAGE_SPEC.md');
const identitySystem = await readRepo('docs/design/BR_IDENTITY_SYSTEM.md');
const mobileTruths = await readRepo('docs/MOBILE_TRUTHS.md');
const climbDetailScreen = await readRepo('mobile/src/screens/ClimbDetailScreen.tsx');
const packageJson = JSON.parse(await readRepo('web/portal/package.json'));

check(
  languageSpec.includes('The rider-facing activity object is `Ride`.'),
  'LANGUAGE_SPEC must define Ride as the rider-facing activity object',
);
check(
  identitySystem.includes('The rider-facing activity object is always `Ride`.'),
  'BR_IDENTITY_SYSTEM must keep Ride as the sole rider-facing activity object',
);
check(
  mobileTruths.includes('`Ride` is the rider-facing activity object'),
  'MOBILE_TRUTHS must keep Ride as the rider-facing activity object',
);
check(
  climbDetailScreen.includes("label: 'Leaderboard'")
    && climbDetailScreen.includes("label: 'Verification'"),
  'ClimbDetail must name leaderboard and verification tabs by function',
);
check(
  packageJson.scripts?.['qa:ride-language'] === 'node scripts/check-ride-language-surface.mjs',
  'package.json must expose qa:ride-language',
);
check(
  Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:ride-language')),
  'package.json perf:release must run qa:ride-language',
);

if (failures.length > 0) {
  console.error('Ride language surface gate failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Ride language surface gate passed.');
