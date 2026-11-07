#!/usr/bin/env node
// BoulderScan builds on its own, so it carries generated copies of the map ground module.
// The portal's copy is the source: edit it, then run `node scripts/sync-map-ground.mjs`.
// Both apps' tests fail when the copies drift (test-climb-detail.mts, climbMapStyle.test.ts).
import { copyFileSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const portal = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src/components/climb');
const scan = path.resolve(portal, '../../../../scan/src/components/ground');
const SHARED = ['climbMapStyle.ts', 'mapGroundPalette.ts', 'carto-voyager-style.json', 'carto-voyager-style.LICENSE.md'];

for (const name of SHARED) {
  const from = path.join(portal, name), to = path.join(scan, name);
  let same = false;
  try { same = readFileSync(from).equals(readFileSync(to)); } catch { /* missing copy */ }
  if (!same) copyFileSync(from, to);
  console.log(`${same ? 'unchanged' : 'copied   '} ${path.relative(process.cwd(), to)}`);
}
