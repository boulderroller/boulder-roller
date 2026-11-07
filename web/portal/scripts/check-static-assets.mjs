#!/usr/bin/env node

import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const portalRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publicRoot = path.join(portalRoot, 'public');
const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

async function readJson(relativePath) {
  return JSON.parse(await readFile(path.join(portalRoot, relativePath), 'utf8'));
}

async function readText(relativePath) {
  return readFile(path.join(portalRoot, relativePath), 'utf8');
}

async function readPngDimensions(publicPath) {
  const buffer = await readFile(path.join(publicRoot, publicPath.replace(/^\//, '')));
  const signature = buffer.subarray(0, 8).toString('hex');
  check(signature === '89504e470d0a1a0a', `${publicPath} must be a PNG`);
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20),
  };
}

async function listJavaScriptFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await listJavaScriptFiles(entryPath));
    else if (entry.isFile() && entry.name.endsWith('.js')) files.push(entryPath);
  }
  return files;
}

function parseIconSize(sizeValue) {
  const match = /^(\d+)x(\d+)$/.exec(sizeValue || '');
  if (!match) return null;
  return {
    width: Number(match[1]),
    height: Number(match[2]),
  };
}

const manifest = await readJson('public/manifest.json');
const indexHtml = await readText('index.html');

check(manifest.name === 'Boulder Roller', 'Manifest must keep the canonical app name');
check(manifest.start_url === '/', 'Manifest start_url must stay rooted at /');
check(Array.isArray(manifest.icons) && manifest.icons.length >= 2, 'Manifest must declare app icons');
check(indexHtml.includes('<link rel="manifest" href="/manifest.json" />'), 'index.html must link the manifest');
check(indexHtml.includes('<meta name="mobile-web-app-capable" content="yes" />'), 'index.html must include the modern mobile web app capability meta tag');
check(indexHtml.includes('<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />'), 'index.html must link the Apple touch icon');

const seenIcons = new Set();
for (const icon of manifest.icons ?? []) {
  check(icon.type === 'image/png', `${icon.src} must declare image/png`);
  check(typeof icon.src === 'string' && icon.src.startsWith('/icons/'), 'Manifest icon src must point into /icons');

  const expected = parseIconSize(icon.sizes);
  check(Boolean(expected), `${icon.src} must use an explicit WxH size`);
  if (!expected) continue;

  const actual = await readPngDimensions(icon.src);
  check(
    actual.width === expected.width && actual.height === expected.height,
    `${icon.src} is ${actual.width}x${actual.height}, but manifest declares ${icon.sizes}`,
  );
  seenIcons.add(`${actual.width}x${actual.height}`);
}

for (const requiredSize of ['192x192', '512x512']) {
  check(seenIcons.has(requiredSize), `Manifest must include a real ${requiredSize} PNG icon`);
}

const appleTouch = await readPngDimensions('/icons/apple-touch-icon.png');
check(
  appleTouch.width === 180 && appleTouch.height === 180,
  `Apple touch icon must be 180x180, got ${appleTouch.width}x${appleTouch.height}`,
);

const buildJavaScriptFiles = await listJavaScriptFiles(path.join(portalRoot, 'build'));
for (const buildFile of buildJavaScriptFiles) {
  const source = await readFile(buildFile, 'utf8');
  check(
    !source.includes('nominatim.openstreetmap.org'),
    `${path.relative(portalRoot, buildFile)} must not bundle direct public Nominatim access`,
  );
}

if (failures.length > 0) {
  console.error('Static asset check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Static asset check passed.');
