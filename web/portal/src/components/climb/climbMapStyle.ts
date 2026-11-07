import { addProtocol, type StyleSpecification, type LayerSpecification, type FilterSpecification, type FillLayerSpecification } from 'maplibre-gl';
import mlcontour from 'maplibre-contour';
import { Protocol } from 'pmtiles';

// web/scan/src/components/ground holds a generated copy of this module, its palette and
// the pinned style; edit them here and run `node scripts/sync-map-ground.mjs`.

/**
 * CARTO's Voyager style (design and layer recipe), pinned and served with the app;
 * provenance and license in carto-voyager-style.LICENSE.md. Everything the base style
 * loads is ours: the `carto` source is our OpenMapTiles-schema PMTiles, and the glyphs
 * and sprite are self-hosted, all under https://api.boulderroller.xyz/basemap/
 * (tools/basemap builds them). CARTO's hosted style moved to another schema on
 * 21 Oct 2026 and every map room failed; nothing here follows a CARTO URL any more.
 * The relief below still reads AWS's open terrain tiles.
 */
export const CLIMB_MAP_STYLE_URL = new URL('./carto-voyager-style.json', import.meta.url).href;

import { MAP_GROUND } from './mapGroundPalette.ts';
export { MAP_GROUND } from './mapGroundPalette.ts';

// Every map that imports this module reads `pmtiles://` sources with HTTP range requests.
addProtocol('pmtiles', new Protocol().tile);

/**
 * Legacy CARTO key handling, kept for callers that still pass every request through it;
 * the ground needs no key. Anything that is not a CARTO URL comes back untouched: a URL
 * round trip would turn `pmtiles://https://host/…` into `pmtiles://https//host/…`.
 */
export function cartoResourceUrl(resource: string, key: string): string {
  if (!key || !/^https:\/\/(?:basemaps|tiles(?:-[a-d])?\.basemaps)\.cartocdn\.com\//.test(resource)) return resource;
  const url = new URL(resource);
  url.searchParams.set('key', key);
  return url.toString();
}

/** Keep CARTO's geographic classes, labels and scale hierarchy; replace only the palette. */
function recolor(source: StyleSpecification): StyleSpecification {
  const g = MAP_GROUND;
  return { ...source, layers: source.layers.map((layer) => {
    const id = layer.id;
    if (layer.type === 'background') return { ...layer, paint: { ...layer.paint, 'background-color': g.paper } };
    if (layer.type === 'fill') {
      const color = /water/.test(id) ? g.water : /landcover|park|landuse(?!_residential)/.test(id) ? g.green : /building/.test(id) ? g.building : g.land;
      return { ...layer, paint: { ...layer.paint, 'fill-color': color, 'fill-outline-color': color } };
    }
    if (layer.type === 'line') {
      const color = /water/.test(id) ? g.waterEdge : /case|boundary/.test(id) ? g.boundary : /path|rail/.test(id) ? g.path : /minor|service/.test(id) ? g.minorRoad : g.majorRoad;
      return { ...layer, paint: { ...layer.paint, 'line-color': color } };
    }
    if (layer.type === 'symbol') return { ...layer, paint: { ...layer.paint, 'text-color': g.label, 'text-halo-color': g.paper, 'text-halo-width': 1.5 } };
    return layer;
  }) };
}

/** The one third party left in the ground: AWS's open terrain tiles behind relief and contours. */
export const TERRAIN_TILES = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';

// One shared worker/cache for all mounted map rooms. Node-only style tests use
// the local manager; browsers trace contours in the shared worker.
const dem = new mlcontour.DemSource({
  url: TERRAIN_TILES,
  encoding: 'terrarium', maxzoom: 15, worker: typeof Worker !== 'undefined', cacheSize: 200,
});
dem.setupMaplibre({ addProtocol });

/** Ratified rich() recipe, history/ground-2026-09-06/ground.html. */
export function nightLedgerMapStyle(src: StyleSpecification, options: { landNames?: boolean; quiet?: boolean } = {}): StyleSpecification {
    const base=recolor(src);
    const G = MAP_GROUND, R = MAP_GROUND;
    // drop Voyager's own cover fills; we paint cover by class ourselves
    const keep=base.layers.filter(l=>!['landcover','park_national_park','park_nature_reserve','landuse_residential','landuse','building','building-top','water_shadow'].includes(l.id));
    const sources: StyleSpecification['sources']={...base.sources,
      dem:{type:'raster-dem',tiles:[dem.sharedDemProtocolUrl],encoding:'terrarium',tileSize:256,maxzoom:15},
      contours:{type:'vector',tiles:[dem.contourProtocolUrl({multiplier:1,thresholds:{10:[250,250],11:[100,100],12:[50,100],13:[10,50],14:[10,50],15:[5,25]},elevationKey:'ele',levelKey:'level',contourLayer:'contours'})],maxzoom:16}};
    const fill=(id: string, layer: string, filter: FilterSpecification, color: string, extra: FillLayerSpecification['paint'] = {}): FillLayerSpecification =>({id,type:'fill',source:'carto','source-layer':layer,filter,paint:{'fill-color':color,'fill-antialias':false,...extra}});
    const cover: LayerSpecification[]=[
      fill('r-landuse-residential','landuse',['==','class','residential'],R.residential),
      fill('r-landuse-commercial','landuse',['in','class','commercial','retail'],R.commercial),
      fill('r-landuse-industrial','landuse',['in','class','industrial','quarry','railway'],R.industrial),
      fill('r-landuse-school','landuse',['in','class','school','university','college','hospital'],R.school),
      fill('r-landuse-cemetery','landuse',['==','class','cemetery'],R.cemetery),
      fill('r-landuse-pitch','landuse',['in','class','pitch','stadium','playground','garden','zoo','theme_park'],R.pitch),
      fill('r-landcover-farmland','landcover',['==','class','farmland'],R.farmland),
      fill('r-landcover-grass','landcover',['==','class','grass'],R.grass),
      fill('r-landcover-wood','landcover',['==','class','wood'],R.wood),
      fill('r-landcover-wetland','landcover',['==','class','wetland'],R.wetland),
      fill('r-landcover-sand','landcover',['==','class','sand'],R.sand),
      fill('r-landcover-ice','landcover',['==','class','ice'],R.ice),
      fill('r-park','park',['all'],R.park,{'fill-opacity':0.75}),
      {id:'r-park-line',type:'line',source:'carto','source-layer':'park',minzoom:11,paint:{'line-color':R.parkLine,'line-width':['interpolate',['linear'],['zoom'],11,0.4,15,1.1],'line-opacity':0.8}},
    ];
    const relief: LayerSpecification[]=[{id:'r-hillshade',type:'hillshade',source:'dem',paint:{'hillshade-exaggeration':['interpolate',['linear'],['zoom'],10,0.7,14,0.5,16,0.35],'hillshade-shadow-color':R.hillShadow,'hillshade-highlight-color':R.hillHighlight,'hillshade-accent-color':R.hillAccent,'hillshade-illumination-direction':335}}];
    const contours: LayerSpecification[]=[
      {id:'r-contour',type:'line',source:'contours','source-layer':'contours',minzoom:11,filter:['!=',['get','level'],1],paint:{'line-color':R.contour,'line-width':0.55,'line-opacity':['interpolate',['linear'],['zoom'],13,0.4,15,0.6]}},
      {id:'r-contour-index',type:'line',source:'contours','source-layer':'contours',minzoom:11,filter:['==',['get','level'],1],paint:{'line-color':R.contourIndex,'line-width':0.9,'line-opacity':0.75}},
      {id:'r-contour-label',type:'symbol',source:'contours','source-layer':'contours',minzoom:13.5,filter:['==',['get','level'],1],layout:{'symbol-placement':'line','text-field':['concat',['number-format',['get','ele'],{}],' m'],'text-font':['Montserrat Medium','Open Sans Bold'],'text-size':9.5,'text-letter-spacing':0.04,'symbol-spacing':420},paint:{'text-color':R.contourLabel,'text-halo-color':G.paper,'text-halo-width':1.2}},
    ];
    const buildings: LayerSpecification[]=[{id:'r-building',type:'fill',source:'carto','source-layer':'building',minzoom:13,paint:{'fill-color':G.building,'fill-opacity':['interpolate',['linear'],['zoom'],13,0.35,15,0.85],'fill-outline-color':R.buildingLine}}];
    const unpaved: LayerSpecification[]=[{id:'r-unpaved',type:'line',source:'carto','source-layer':'transportation',minzoom:13,filter:['all',['==',['get','surface'],'unpaved'],['in',['get','class'],['literal',['minor','service','tertiary','secondary','track','path']]]],layout:{'line-cap':'butt'},paint:{'line-color':G.paper,'line-width':['interpolate',['linear'],['zoom'],13,0.9,16,2.2],'line-dasharray':[2.2,2.2],'line-opacity':0.9}}];
    const names: LayerSpecification[]=[
      {id:'r-waterway-name',type:'symbol',source:'carto','source-layer':'waterway',minzoom:12,filter:['all',['has','name'],['in',['get','class'],['literal',['river','stream','canal']]]],layout:{'symbol-placement':'line','text-field':['get','name'],'text-font':['Montserrat Regular Italic','Open Sans Italic'],'text-size':['interpolate',['linear'],['zoom'],12,10,15,12],'symbol-spacing':500,'text-letter-spacing':0.03},paint:{'text-color':R.waterLabel,'text-halo-color':G.water,'text-halo-width':1.2}},
      {id:'r-park-name',type:'symbol',source:'carto','source-layer':'poi',minzoom:12,filter:['all',['has','name'],['==',['get','class'],'park']],layout:{'text-field':['get','name'],'text-font':['Montserrat Medium','Open Sans Bold'],'text-size':['interpolate',['linear'],['zoom'],12,10,15,12],'text-transform':'uppercase','text-letter-spacing':0.12,'text-max-width':7},paint:{'text-color':R.parkLabel,'text-halo-color':G.paper,'text-halo-width':1.2}},
      {id:'r-peak',type:'circle',source:'carto','source-layer':'mountain_peak',minzoom:11,paint:{'circle-radius':2.2,'circle-color':R.peak,'circle-stroke-color':G.paper,'circle-stroke-width':1}},
      {id:'r-peak-name',type:'symbol',source:'carto','source-layer':'mountain_peak',minzoom:11,layout:{'text-field':['case',['has','ele'],['concat',['get','name'],' · ',['number-format',['get','ele'],{}],' m'],['get','name']],'text-font':['Montserrat Medium','Open Sans Bold'],'text-size':10.5,'text-anchor':'left','text-offset':[0.7,0],'text-max-width':10},paint:{'text-color':R.peak,'text-halo-color':G.paper,'text-halo-width':1.3}},
    ];
    // order: cover → relief → water etc. (kept from Voyager) → contours → buildings → roads/labels (kept)
    const iWater=keep.findIndex(l=>l.id==='water');
    const before=keep.slice(0,iWater), after=keep.slice(iWater);
    const iRoads=after.findIndex(l=>l.id==='tunnel_service_case');
    const water=after.slice(0,iRoads), roads=after.slice(iRoads);
    const iLabels=roads.findIndex(l=>l.type==='symbol');
    const roadLines=roads.slice(0,iLabels), labels=roads.slice(iLabels);
    if (options.quiet) {
      // The read-only band: cover, water and the road grid under the route; no relief,
      // contours, buildings, unpaved dashes or names. The room grounds keep the full recipe.
      return {...base, sources, layers:[...before, ...cover, ...water, ...roadLines]};
    }
    return {...base, sources, layers:[...before, ...cover, ...relief, ...water, ...contours.filter(layer => options.landNames !== false || layer.id !== 'r-contour-label'), ...buildings, ...roadLines, ...unpaved, ...names.filter(layer => options.landNames !== false || layer.type !== 'symbol'), ...labels]};
  }
