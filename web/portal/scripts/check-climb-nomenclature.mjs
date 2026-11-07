#!/usr/bin/env node

import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);
const srcRoot = path.join(portalRoot, 'src');

const forbiddenSymbolPatterns = [
  /\bSegmentView\b/,
  /\buseSegments\b/,
  /\bSegmentDetailModal\b/,
  /\bSegmentResponse\b/,
  /\bSegments\b/,
];

const segmentRouteAllowedFiles = new Set([
  'AuthenticatedApp.tsx',
  'components/layout/DashboardLayout.tsx',
  'components/loading/LoadingSystem.tsx',
  'components/portal/PortalShell.tsx',
  'lib/api.ts',
  'lib/routePrefetch.ts',
  'pages/ClimbView.tsx',
]);

const failures = [];

async function walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    if (entry.name === 'build-manifest') continue;

    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...await walk(fullPath));
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      files.push(fullPath);
    }
  }

  return files;
}

function relativeSrcPath(filePath) {
  return path.relative(srcRoot, filePath).split(path.sep).join('/');
}

function lineNumberFor(content, index) {
  return content.slice(0, index).split('\n').length;
}

const files = await walk(srcRoot);

for (const filePath of files) {
  const relativePath = relativeSrcPath(filePath);
  const content = await readFile(filePath, 'utf8');

  for (const pattern of forbiddenSymbolPatterns) {
    const match = pattern.exec(content);
    if (match) {
      failures.push(`${relativePath}:${lineNumberFor(content, match.index)} contains retired Segment-era symbol ${match[0]}`);
    }
  }

  const routeIndex = content.indexOf('/segments');
  if (routeIndex >= 0 && !segmentRouteAllowedFiles.has(relativePath)) {
    failures.push(`${relativePath}:${lineNumberFor(content, routeIndex)} uses /segments outside the explicit compatibility lane`);
  }
}

if (failures.length > 0) {
  console.error('Portal Climb nomenclature gate failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Portal Climb nomenclature gate passed.');
