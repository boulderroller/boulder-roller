#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

function loadJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    console.error(`[perf-budget] Failed to read JSON: ${filePath}`);
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(2);
  }
}

function getAuditValue(report, key) {
  const audit = report?.audits?.[key];
  if (!audit || typeof audit.numericValue !== 'number') return null;
  return audit.numericValue;
}

function formatNumber(value, unit = '') {
  if (typeof value !== 'number') return 'n/a';
  if (unit === 'score') return value.toFixed(0);
  if (unit === 'cls') return value.toFixed(3);
  if (unit === 'bytes') return `${Math.round(value).toLocaleString()} B`;
  return `${Math.round(value).toLocaleString()} ${unit}`.trim();
}

const reportPath = process.argv[2] || '.lighthouse/latest.json';
if (!fs.existsSync(path.resolve(process.cwd(), reportPath))) {
  console.error(`Usage: node scripts/check-lighthouse-budget.mjs <report.json> [budget.json]`);
  console.error(`[perf-budget] Could not find Lighthouse report at: ${reportPath}`);
  process.exit(2);
}

const budgetPath = process.argv[3] || path.resolve(process.cwd(), 'perf/lighthouse-budget.json');
const report = loadJson(path.resolve(process.cwd(), reportPath));
const budget = loadJson(path.resolve(process.cwd(), budgetPath));

const checks = [];

if (typeof budget.performanceScoreMin === 'number') {
  const rawScore = report?.categories?.performance?.score;
  const score = typeof rawScore === 'number' ? rawScore * 100 : null;
  checks.push({
    label: 'Performance score',
    actual: score,
    max: null,
    min: budget.performanceScoreMin,
    unit: 'score',
    optional: false,
  });
}

for (const [auditKey, rule] of Object.entries(budget.metrics || {})) {
  checks.push({
    label: auditKey,
    actual: getAuditValue(report, auditKey),
    max: typeof rule.max === 'number' ? rule.max : null,
    min: typeof rule.min === 'number' ? rule.min : null,
    unit: auditKey === 'cumulative-layout-shift' ? 'cls' : 'ms',
    optional: Boolean(rule.optional),
  });
}

for (const [auditKey, rule] of Object.entries(budget.diagnostics || {})) {
  checks.push({
    label: auditKey,
    actual: getAuditValue(report, auditKey),
    max: typeof rule.max === 'number' ? rule.max : null,
    min: typeof rule.min === 'number' ? rule.min : null,
    unit: typeof rule.unit === 'string' ? rule.unit : 'ms',
    optional: Boolean(rule.optional),
  });
}

let failed = 0;
let skipped = 0;

for (const check of checks) {
  const { label, actual, min, max, unit, optional } = check;

  if (actual === null) {
    if (optional) {
      skipped += 1;
      console.log(`- [skip] ${label}: metric unavailable in report`);
      continue;
    }
    failed += 1;
    console.log(`- [fail] ${label}: metric unavailable in report`);
    continue;
  }

  let pass = true;
  let threshold = '';

  if (typeof min === 'number') {
    threshold = `>= ${formatNumber(min, unit)}`;
    if (actual < min) pass = false;
  }
  if (typeof max === 'number') {
    threshold = `<= ${formatNumber(max, unit)}`;
    if (actual > max) pass = false;
  }

  if (!pass) failed += 1;
  const marker = pass ? 'pass' : 'fail';
  console.log(`- [${marker}] ${label}: ${formatNumber(actual, unit)} (budget ${threshold})`);
}

if (skipped > 0) {
  console.log(`[perf-budget] Skipped optional checks: ${skipped}`);
}

if (failed > 0) {
  console.error(`[perf-budget] Budget check failed with ${failed} violation(s).`);
  process.exit(1);
}

console.log('[perf-budget] All budget checks passed.');
