#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    console.error(`[bundle-budget] Failed to read JSON: ${filePath}`);
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(2);
  }
}

function formatKb(bytes) {
  return `${(bytes / 1024).toFixed(2)} kB`;
}

const buildDir = path.resolve(process.cwd(), process.argv[2] || 'build/assets');
const budgetPath = path.resolve(process.cwd(), process.argv[3] || 'perf/bundle-budget.json');

if (!fs.existsSync(buildDir)) {
  console.error(`[bundle-budget] Build directory not found: ${buildDir}`);
  console.error('Run `npm run build` first or pass a custom assets directory.');
  process.exit(2);
}

if (!fs.existsSync(budgetPath)) {
  console.error(`[bundle-budget] Budget file not found: ${budgetPath}`);
  process.exit(2);
}

const budgetConfig = readJson(budgetPath);
const budgets = Array.isArray(budgetConfig?.budgets) ? budgetConfig.budgets : [];

if (budgets.length === 0) {
  console.error('[bundle-budget] No budgets configured.');
  process.exit(2);
}

const assetFiles = fs.readdirSync(buildDir).filter((fileName) => fileName.endsWith('.js'));

let failed = 0;

function findEntrypointAsset() {
  const indexHtmlPath = path.join(path.dirname(buildDir), 'index.html');
  if (!fs.existsSync(indexHtmlPath)) {
    throw new Error(`index.html not found next to assets directory: ${indexHtmlPath}`);
  }

  const indexHtml = fs.readFileSync(indexHtmlPath, 'utf8');
  const match = indexHtml.match(/<script[^>]+type=["']module["'][^>]+src=["'][^"']*\/assets\/([^"']+\.js)["']/);
  if (!match) {
    throw new Error(`No module entrypoint script found in ${indexHtmlPath}`);
  }

  return match[1];
}

for (const budget of budgets) {
  const { name, pattern, maxGzipKb, optional = false, entrypoint = false, forbidStrings = [] } = budget;
  let matches = [];

  if (entrypoint) {
    try {
      matches = [findEntrypointAsset()];
    } catch (error) {
      failed += 1;
      console.log(`- [fail] ${name}: ${error instanceof Error ? error.message : String(error)}`);
      continue;
    }
  } else {
    if (!pattern) {
      failed += 1;
      console.log(`- [fail] ${name}: missing pattern`);
      continue;
    }

    const matcher = new RegExp(pattern);
    matches = assetFiles.filter((fileName) => matcher.test(fileName));
  }

  if (matches.length === 0) {
    if (optional) {
      console.log(`- [skip] ${name}: no matching asset for ${pattern}`);
      continue;
    }

    failed += 1;
    console.log(`- [fail] ${name}: no matching asset for ${pattern}`);
    continue;
  }

  for (const fileName of matches) {
    const filePath = path.join(buildDir, fileName);
    const contents = fs.readFileSync(filePath);
    const gzipBytes = zlib.gzipSync(contents).length;
    const budgetBytes = Math.round(maxGzipKb * 1024);
    const forbiddenHits = forbidStrings.filter((needle) => contents.includes(needle));
    const pass = gzipBytes <= budgetBytes && forbiddenHits.length === 0;

    if (!pass) failed += 1;

    console.log(
      `- [${pass ? 'pass' : 'fail'}] ${name} (${fileName}): ${formatKb(gzipBytes)} gzip ` +
      `(budget <= ${maxGzipKb.toFixed(2)} kB)`,
    );

    if (forbiddenHits.length > 0) {
      console.log(`  forbidden strings found: ${forbiddenHits.join(', ')}`);
    }
  }
}

if (failed > 0) {
  console.error(`[bundle-budget] Budget check failed with ${failed} violation(s).`);
  process.exit(1);
}

console.log('[bundle-budget] All bundle budgets passed.');
