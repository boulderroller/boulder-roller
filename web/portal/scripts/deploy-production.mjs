#!/usr/bin/env node

import { execFileSync, spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import process from 'node:process';

const portalRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = path.resolve(portalRoot, '../..');

function readGitValue(args, fallback = '') {
  try {
    return execFileSync('git', args, {
      cwd: repoRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return fallback;
  }
}

const commitSha = (
  process.env.VERCEL_GIT_COMMIT_SHA ||
  process.env.GITHUB_SHA ||
  readGitValue(['rev-parse', 'HEAD'])
).trim();
const commitRef = (
  process.env.VERCEL_GIT_COMMIT_REF ||
  process.env.GITHUB_REF_NAME ||
  readGitValue(['rev-parse', '--abbrev-ref', 'HEAD'])
).trim();

const deployArgs = ['vercel@latest', 'deploy', '--prod', '--yes'];

if (commitSha) {
  deployArgs.push('--build-env', `VERCEL_GIT_COMMIT_SHA=${commitSha}`);
}

if (commitRef && commitRef !== 'HEAD') {
  deployArgs.push('--build-env', `VERCEL_GIT_COMMIT_REF=${commitRef}`);
}

const result = spawnSync(
  'npx',
  deployArgs,
  {
    cwd: repoRoot,
    stdio: 'inherit',
    env: process.env,
  },
);

if (result.error) {
  console.error(`Production deploy failed to start: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
