#!/usr/bin/env node
// Builds the self-hosted glyph ranges for the map ground's font stacks.
//
//   cd tools/basemap && npm install && npm run glyphs
//
// Fonts come from fonts.json (open fonts, pinned by URL and SHA-256). Every stack gets all
// 256 ranges, empty ones included, so MapLibre never meets a missing range and the map's
// error handler never fires for one. Output: out/fonts/<stack>/<start>-<end>.pbf, uploaded
// as-is to the droplet's /basemap/fonts/<version>/ (see build-tiles.sh for the layout).
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const fontnik = createRequire(import.meta.url)('fontnik');
const here = path.dirname(fileURLToPath(import.meta.url));
const manifest = JSON.parse(readFileSync(path.join(here, 'fonts.json'), 'utf8'));
const cache = path.join(here, '.cache', 'fonts');
const out = path.join(here, 'out', 'fonts');
mkdirSync(cache, { recursive: true });

const sha256 = (buffer) => createHash('sha256').update(buffer).digest('hex');
const call = (fn, arg) => new Promise((resolve, reject) => fn(arg, (error, data) => (error ? reject(error) : resolve(data))));

async function font(name) {
  const { url, sha256: expected } = manifest.fonts[name];
  const file = path.join(cache, path.basename(new URL(url).pathname));
  if (!existsSync(file)) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${name}: ${response.status} from ${url}`);
    writeFileSync(file, Buffer.from(await response.arrayBuffer()));
  }
  const buffer = readFileSync(file);
  if (sha256(buffer) !== expected) throw new Error(`${name}: ${file} does not match its pinned SHA-256`);
  return buffer;
}

const starts = Array.from({ length: 256 }, (_, i) => i * 256);
const ranges = new Map();
for (const name of new Set(Object.values(manifest.stacks).flat())) {
  const buffer = await font(name);
  const byStart = new Map();
  for (const start of starts) byStart.set(start, await call(fontnik.range, { font: buffer, start, end: start + 255 }));
  ranges.set(name, byStart);
}

rmSync(out, { recursive: true, force: true });
let files = 0, bytes = 0;
for (const [stack, faces] of Object.entries(manifest.stacks)) {
  const dir = path.join(out, stack);
  mkdirSync(dir, { recursive: true });
  for (const start of starts) {
    const parts = faces.map((face) => ranges.get(face).get(start));
    const pbf = parts.length === 1 ? parts[0] : await new Promise((resolve, reject) => fontnik.composite(parts, (error, data) => (error ? reject(error) : resolve(data))));
    writeFileSync(path.join(dir, `${start}-${start + 255}.pbf`), pbf);
    files += 1; bytes += pbf.length;
  }
}
console.log(`${Object.keys(manifest.stacks).length} stacks, ${files} ranges, ${(bytes / 1048576).toFixed(1)} MB in ${path.relative(process.cwd(), out) || out}`);
