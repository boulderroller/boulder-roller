import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { StyleSpecification } from 'maplibre-gl';
import { describe, expect, it } from 'vitest';
import { CLIMB_MAP_STYLE_URL, nightLedgerMapStyle, TERRAIN_TILES } from './climbMapStyle.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const portalCopy = path.resolve(here, '../../../../portal/src/components/climb');
const GROUND_ASSETS = 'https://api.boulderroller.xyz/basemap/';

const undefinedSources = (style: StyleSpecification) => style.layers.flatMap((layer) => {
  const source = (layer as { source?: unknown }).source;
  return typeof source === 'string' && !Object.hasOwn(style.sources, source) ? [`${layer.id} -> ${source}`] : [];
});
const pinnedGround = () => JSON.parse(readFileSync(new URL(CLIMB_MAP_STYLE_URL), 'utf8')) as StyleSpecification;

// On 21 Oct 2026 CARTO's hosted Voyager style moved to a 'protomaps' source and every
// ground layer on 'carto' lost its source. The base style ships with the app.
describe('pinned ground style', () => {
  it('ships with the app and every ground layer reads a source the style defines', () => {
    const pinned = new URL(CLIMB_MAP_STYLE_URL);
    expect(pinned.protocol, `${CLIMB_MAP_STYLE_URL} must be the copy served with the app`).toBe('file:');
    const base = pinnedGround();
    expect(String((base.sources.carto as { url?: string } | undefined)?.url)).toMatch(/^pmtiles:\/\/https:\/\/api\.boulderroller\.xyz\/basemap\/tiles\/[\w.-]+\.pmtiles$/);
    for (const style of [base, nightLedgerMapStyle(base), nightLedgerMapStyle(base, { landNames: false })]) {
      expect(style.layers.length).toBeGreaterThan(0);
      expect(undefinedSources(style)).toEqual([]);
    }
    expect(undefinedSources(nightLedgerMapStyle({ ...base, sources: { protomaps: base.sources.carto } }))).not.toEqual([]);
  });

  it('sends no basemap request off our host; only the relief reads AWS open terrain tiles', () => {
    const style = nightLedgerMapStyle(pinnedGround());
    const urls = [style.glyphs, typeof style.sprite === 'string' ? style.sprite : undefined, ...Object.values(style.sources).flatMap((source) => {
      const { url, tiles } = source as { url?: string; tiles?: string[] };
      return [url, ...(tiles ?? [])];
    })].filter((url): url is string => typeof url === 'string');
    for (const url of urls) {
      const target = url.replace(/^pmtiles:\/\//, '');
      if (/^https?:/.test(target)) expect(target.startsWith(GROUND_ASSETS), url).toBe(true);
      else expect(url).toMatch(/^dem-[\w-]+:\/\//);
    }
    expect(TERRAIN_TILES).toBe('https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png');
  });

  it.skipIf(!existsSync(portalCopy))('stays byte-identical to the portal copy', () => {
    for (const name of ['climbMapStyle.ts', 'mapGroundPalette.ts', 'carto-voyager-style.json', 'carto-voyager-style.LICENSE.md']) {
      const scan = readFileSync(path.join(here, name));
      expect(scan.equals(readFileSync(path.join(portalCopy, name))), `${name} drifted between web/scan and web/portal; run node scripts/sync-map-ground.mjs in web/portal`).toBe(true);
    }
  });
});
