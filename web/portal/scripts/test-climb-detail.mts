import { existsSync, readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import { climbRouteSegments } from '../src/lib/climbGeometry.ts';
import { climbPosition, operationPhase, positionReflectsOperation } from '../src/lib/climbVaultOperation.ts';
import type { StyleSpecification } from 'maplibre-gl';
import { cartoResourceUrl, CLIMB_MAP_STYLE_URL, nightLedgerMapStyle, TERRAIN_TILES } from '../src/components/climb/climbMapStyle.ts';

const position = { vaultId: 1, calStakedBaseUnits: '9007199254740993', lpTokensBaseUnits: '1180000000000' } as any;

test('invalid route points preserve gaps instead of inventing a connecting climb', () => {
  const climb = { routePreview: { source: 'canon_centerline', bounds: { minLat: 40, maxLat: 41, minLon: -76, maxLon: -75 }, points: [{x:0,y:0},{x:0.2,y:0.2},{x:NaN,y:0.4},{x:0.6,y:0.6},{x:1,y:1}] } } as any;
  assert.equal(climbRouteSegments(climb).length, 2);
  assert.equal(climbRouteSegments({ ...climb, routePreview: { ...climb.routePreview, source: 'raw_ride_stream' } }).length, 0);
});

test('recorded actions remain unresolved until their own exact fresh projection changes', () => {
  const deposit = { action: 'deposit' as const, clientRequestId: 'a', priorBaseUnits: '9007199254740992' };
  assert.equal(positionReflectsOperation(deposit, position), true);
  assert.equal(positionReflectsOperation({ ...deposit, priorBaseUnits: position.calStakedBaseUnits }, position), false);
  assert.equal(positionReflectsOperation({ ...deposit, priorBaseUnits: undefined }, position), false);
  const withdraw = { action: 'withdraw' as const, clientRequestId: 'b', priorBaseUnits: '1180000000000' };
  assert.equal(positionReflectsOperation(withdraw, position), false);
  assert.equal(positionReflectsOperation(withdraw, { ...position, lpTokensBaseUnits: '1179999999999' }), true);
  assert.equal(positionReflectsOperation(withdraw, null), true);
  const collect = { action: 'collect' as const, clientRequestId: 'c' };
  assert.equal(positionReflectsOperation(collect, position, '1'), false);
  assert.equal(positionReflectsOperation(collect, position, '0'), true);
});

test('lookup identity and both recorded fields must agree; review and delay override', () => {
  const operation = { action: 'withdraw' as const, clientRequestId: 'b' };
  const status = { actionType: 'withdraw_cal', referenceType: 'vault', referenceId: '1', recorded: true, readState: 'recorded', riderState: null } as any;
  assert.equal(operationPhase(operation, status, 1), 'recorded');
  assert.equal(operationPhase(operation, { ...status, referenceId: '2' }, 1), 'review');
  assert.equal(operationPhase(operation, { ...status, actionType: 'deposit_cal' }, 1), 'review');
  assert.equal(operationPhase(operation, { ...status, recorded: false }, 1), 'review');
  assert.equal(operationPhase(operation, { ...status, readState: 'delayed' }, 1), 'delayed');
});

test('duplicate or unresolved positions cannot become a proven zero', () => {
  assert.throws(() => climbPosition([position, position], 1));
  assert.throws(() => climbPosition([{ ...position, vaultId: null, vaultSignature: 'unresolved' }], 1));
  assert.equal(climbPosition([], 1), null);
});

test('the existing map key is only appended to the existing CARTO hosts', () => {
  assert.equal(new URL(cartoResourceUrl('https://tiles-a.basemaps.cartocdn.com/a', 'test-key')).searchParams.get('key'), 'test-key');
  assert.equal(cartoResourceUrl('https://example.test/tiles', 'test-key'), 'https://example.test/tiles');
  assert.equal(cartoResourceUrl('https://basemaps.cartocdn.com.attacker.test/tiles', 'test-key'), 'https://basemaps.cartocdn.com.attacker.test/tiles');
  // Every workshop map still routes requests through it; our PMTiles URL must come back intact.
  assert.equal(cartoResourceUrl('pmtiles://https://api.boulderroller.xyz/basemap/tiles/x.pmtiles', 'test-key'), 'pmtiles://https://api.boulderroller.xyz/basemap/tiles/x.pmtiles');
  assert.equal(cartoResourceUrl('pmtiles://https://api.boulderroller.xyz/basemap/tiles/x.pmtiles', ''), 'pmtiles://https://api.boulderroller.xyz/basemap/tiles/x.pmtiles');
});

test('ratified ground includes shared terrain and keeps feed labels quiet', () => {
  const source = { version: 8, sources: { carto: { type: 'vector', tiles: [] } }, layers: [
    { id: 'background', type: 'background' }, { id: 'water', type: 'fill' },
    { id: 'tunnel_service_case', type: 'line' }, { id: 'place', type: 'symbol' },
  ] } as any;
  const style = nightLedgerMapStyle(source);
  assert.equal(style.sources.dem.type, 'raster-dem');
  const ids = style.layers.map(layer => layer.id);
  for (const [below, above] of [['r-hillshade', 'water'], ['r-contour-index', 'r-building'], ['r-building', 'tunnel_service_case'], ['r-unpaved', 'r-waterway-name'], ['r-peak-name', 'place']]) {
    assert.ok(ids.includes(below) && ids.indexOf(below) < ids.indexOf(above));
  }
  const band = nightLedgerMapStyle(source, { landNames: false });
  assert.ok(band.layers.some(layer => layer.id === 'r-hillshade'));
  assert.ok(band.layers.some(layer => layer.id === 'r-contour-index'));
  assert.ok(!band.layers.some(layer => ['r-contour-label', 'r-waterway-name', 'r-park-name', 'r-peak-name'].includes(layer.id)));
  assert.equal(cartoResourceUrl('https://s3.amazonaws.com/elevation-tiles-prod/terrarium/1/0/0.png', 'secret'), 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/1/0/0.png');
});

const undefinedSources = (style: StyleSpecification) => style.layers.flatMap((layer) => {
  const source = (layer as { source?: unknown }).source;
  return typeof source === 'string' && !Object.hasOwn(style.sources, source) ? [`${layer.id} -> ${source}`] : [];
});
const pinnedGround = () => JSON.parse(readFileSync(new URL(CLIMB_MAP_STYLE_URL), 'utf8')) as StyleSpecification;
const grounds = (base: StyleSpecification) => ({ base, rooms: nightLedgerMapStyle(base), bands: nightLedgerMapStyle(base, { landNames: false }), readOnly: nightLedgerMapStyle(base, { quiet: true }) });
const GROUND_ASSETS = 'https://api.boulderroller.xyz/basemap/';

// On 21 Oct 2026 CARTO's hosted Voyager style moved to a 'protomaps' source and every
// ground layer on 'carto' lost its source, so all map rooms failed. The base style ships with the app.
test('the ground base style ships with the app and every ground layer reads a source the style defines', () => {
  const pinned = new URL(CLIMB_MAP_STYLE_URL);
  assert.equal(pinned.protocol, 'file:', `${CLIMB_MAP_STYLE_URL} must be the copy served with the app, not a moving upstream URL`);
  const base = pinnedGround();
  // Our own OpenMapTiles-schema build feeds the recipe's `carto` source.
  assert.match(String((base.sources.carto as { url?: string } | undefined)?.url), /^pmtiles:\/\/https:\/\/api\.boulderroller\.xyz\/basemap\/tiles\/[\w.-]+\.pmtiles$/);
  for (const [name, style] of Object.entries(grounds(base))) {
    assert.ok(style.layers.length > 0);
    assert.deepEqual(undefinedSources(style), [], `${name} ground has layers on undefined sources`);
  }
  // The guard bites on the upstream shape that broke the rooms.
  assert.notDeepEqual(undefinedSources(nightLedgerMapStyle({ ...base, sources: { protomaps: base.sources.carto } })), []);
});

test('no basemap request leaves our host; only the relief reads AWS open terrain tiles', () => {
  for (const [name, style] of Object.entries(grounds(pinnedGround()))) {
    const urls = [style.glyphs, typeof style.sprite === 'string' ? style.sprite : undefined, ...Object.values(style.sources).flatMap((source) => {
      const { url, tiles } = source as { url?: string; tiles?: string[] };
      return [url, ...(tiles ?? [])];
    })].filter((url): url is string => typeof url === 'string');
    assert.ok(urls.length >= 3);
    for (const url of urls) {
      const target = url.replace(/^pmtiles:\/\//, '');
      if (/^https?:/.test(target)) assert.ok(target.startsWith(GROUND_ASSETS), `${name}: ${url} is not one of our basemap assets`);
      else assert.match(url, /^dem-[\w-]+:\/\//, `${name}: ${url} uses an unknown protocol`);
    }
  }
  // The terrain protocols above read this, the one third party left in the ground.
  assert.equal(TERRAIN_TILES, 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png');
});

const FONTS = new URL('../../../tools/basemap/fonts.json', import.meta.url);
test('every label font stack has self-hosted glyphs and every icon is in our sprite', { skip: existsSync(FONTS) ? false : 'tools/basemap is not in this checkout' }, () => {
  const built = new Set(Object.keys(JSON.parse(readFileSync(FONTS, 'utf8')).stacks));
  const stacks = new Set<string>(), icons = new Set<string>();
  for (const style of Object.values(grounds(pinnedGround()))) for (const layer of style.layers) {
    const layout = (layer as { layout?: Record<string, unknown> }).layout ?? {};
    if (Array.isArray(layout['text-font'])) stacks.add(layout['text-font'].join(','));
    if (typeof layout['icon-image'] === 'string' && layout['icon-image']) icons.add(layout['icon-image']);
  }
  assert.ok(stacks.size >= 4);
  assert.deepEqual([...stacks].filter((stack) => !built.has(stack)), [], 'build these stacks in tools/basemap/fonts.json');
  assert.deepEqual([...icons], ['circle-11'], 'tools/basemap/build-sprite.py draws exactly this icon');
});

// BoulderScan carries a generated copy of the ground module; the two may never drift apart.
const SCAN_GROUND = new URL('../../scan/src/components/ground/', import.meta.url);
const SHARED_GROUND = ['climbMapStyle.ts', 'mapGroundPalette.ts', 'carto-voyager-style.json', 'carto-voyager-style.LICENSE.md'];
test('BoulderScan serves the same ground module byte for byte', { skip: existsSync(SCAN_GROUND) ? false : 'web/scan is not in this checkout' }, () => {
  for (const name of SHARED_GROUND) {
    const portal = readFileSync(new URL(name, CLIMB_MAP_STYLE_URL));
    assert.ok(portal.equals(readFileSync(new URL(name, SCAN_GROUND))), `${name} drifted between web/portal and web/scan; run node scripts/sync-map-ground.mjs`);
  }
});

// The frozen harness lives under history/, which the Vercel build excludes; parity runs where the repo is whole.
const HARNESS = new URL('../../../history/ground-2026-09-06/ground.html', import.meta.url);
test('every ground layer is identical to the ratified rich harness', { skip: existsSync(HARNESS) ? false : 'history/ground-2026-09-06 is not in this checkout' }, () => {
  const harness = readFileSync(HARNESS, 'utf8');
  const source = { version: 8, sources: { carto: { type: 'vector', tiles: [] } }, layers: [
    { id: 'background', type: 'background' }, { id: 'landcover', type: 'fill' },
    { id: 'water', type: 'fill' }, { id: 'waterway', type: 'line' },
    { id: 'tunnel_service_case', type: 'line' }, { id: 'place', type: 'symbol' },
  ] } as any;
  const actual = nightLedgerMapStyle(source);
  const palette = harness.slice(harness.indexOf('const G='), harness.indexOf("const INK="));
  const today = harness.slice(harness.indexOf('function today('), harness.indexOf('/* ---- rich:'));
  const rich = harness.slice(harness.indexOf('function rich('), harness.indexOf('  const style='));
  let options: unknown;
  const dem = { sharedDemProtocolUrl: (actual.sources.dem as any).tiles[0], contourProtocolUrl(value: unknown) { options = value; return (actual.sources.contours as any).tiles[0]; } };
  const expected = new Function('src', 'dem', palette + today + rich + '; return rich(src);')(source, dem);
  assert.deepEqual(actual, expected);
  assert.deepEqual(options, { multiplier: 1, thresholds: { 10: [250,250], 11: [100,100], 12: [50,100], 13: [10,50], 14: [10,50], 15: [5,25] }, elevationKey: 'ele', levelKey: 'level', contourLayer: 'contours' });
});
