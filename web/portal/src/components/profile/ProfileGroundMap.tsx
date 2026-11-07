import MapAttribution from '../climb/MapAttribution';
import { useEffect, useRef } from 'react';
import { Map, Marker, LngLatBounds, MercatorCoordinate, setWorkerUrl, type StyleSpecification, type GeoJSONSource } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { CLIMB_MAP_STYLE_URL, MAP_GROUND, nightLedgerMapStyle } from '../climb/climbMapStyle';
setWorkerUrl(workerUrl);
import { resolveRankMarkAsset } from '../../assets/rankmarks';
import { formatRaceTime } from '../../lib/formatters';
import { GROUND } from '../../lib/mapColors';
import { groundRouteSegments, type GroundClimb } from './groundModel';

// The ground (Profile — Ground, Tim-ratified 2026-09-02): the map is the
// room. The shared vector ground; every canon
// climb drawn faint; the ones this rider has ridden in ink; the ones they
// hold in cobalt over the casing with the white start dot and their rank
// mark at the summit, the time beside it. The viewport fits the rider's
// held-or-ridden climbs and falls back to the whole canon.

interface ProfileGroundMapProps {
  ground: GroundClimb[];
  onOpenClimb: (climbId: string) => void;
  /** The 200px masthead under the profile's other tabs: tighter fit, no column inset. */
  compact?: boolean;
}

const DEFAULT_CENTER: [number, number] = [40.03, -75.23];
const DEFAULT_ZOOM = 12;
const COLUMN_INSET_MIN_WIDTH = 1024;
const COLUMN_INSET_PX = 400;

function fitPadding(container: HTMLElement, compact: boolean): { topLeft: [number, number]; bottomRight: [number, number] } {
  if (compact) return { topLeft: [24, 24], bottomRight: [24, 24] };
  const wide = container.clientWidth >= COLUMN_INSET_MIN_WIDTH;
  return {
    topLeft: [wide ? COLUMN_INSET_PX : 24, 48],
    bottomRight: [48, 96],
  };
}

function summitMark(entry: GroundClimb): HTMLElement | null {
  const position = entry.position;
  if (!position) return null;
  const asset = resolveRankMarkAsset(position.rank);
  if (!asset) return null;

  const mark = document.createElement('span');
  mark.className = 'profile-ground__mark';

  const image = document.createElement('img');
  image.src = asset.src;
  image.srcset = asset.srcSet;
  image.width = 28;
  image.height = 28;
  image.alt = '';
  mark.appendChild(image);

  const label = document.createElement('span');
  label.className = 'profile-ground__label';
  const time = document.createElement('i');
  time.textContent = formatRaceTime(position.bestTimeSeconds);
  label.append(time);
  mark.appendChild(label);

  return mark;
}

export default function ProfileGroundMap({ ground, onOpenClimb, compact = false }: ProfileGroundMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const openClimbRef = useRef(onOpenClimb);
  const drawRef = useRef<() => void>(() => {});
  const groundRef = useRef(ground);
  const compactRef = useRef(compact);
  openClimbRef.current = onOpenClimb;
  groundRef.current = ground;
  compactRef.current = compact;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    let disposed = false;
    const controller = new AbortController();
    const map = new Map({
      container, center: [DEFAULT_CENTER[1], DEFAULT_CENTER[0]], zoom: DEFAULT_ZOOM - 1,
      maxZoom: 19, scrollZoom: false, attributionControl: false,
      pitchWithRotate: false, dragRotate: false, touchPitch: false,
      style: { version: 8, sources: {}, layers: [{ id: 'ground', type: 'background', paint: { 'background-color': MAP_GROUND.paper } }] },
    });
    map.touchZoomRotate.disableRotation();
    mapRef.current = map;
    let markers: Marker[] = [];
    let styleReady = false;
    const longitudeFirst = ([lat, lon]: number[]): [number, number] => [lon, lat];
    const draw = () => {
      if (disposed || !styleReady) return;
      markers.forEach(marker => marker.remove());
      markers = [];
      const features: GeoJSON.Feature[] = [];
      const starts: GeoJSON.Feature[] = [];
      const focus: [number, number][] = [], everything: [number, number][] = [];
      for (const entry of [...groundRef.current].sort((a, b) => tierOrder(a.tier) - tierOrder(b.tier))) {
        const segments = groundRouteSegments(entry.climb.routePreview);
        if (!segments.length) continue;
        const held = entry.tier === 'seat' || entry.tier === 'crown';
        for (const segment of segments) {
          const coordinates = segment.map(longitudeFirst);
          everything.push(...coordinates);
          if (entry.tier !== 'faint') focus.push(...coordinates);
          features.push({ type: 'Feature', properties: { climbId: entry.climb.id, tier: entry.tier, held }, geometry: { type: 'LineString', coordinates } });
        }
        if (held) {
          starts.push({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: longitudeFirst(segments[0][0]) } });
          const last = segments[segments.length - 1];
          const mark = summitMark(entry);
          if (mark) {
            mark.dataset.climbId = entry.climb.id;
            mark.addEventListener('click', event => { event.stopPropagation(); openClimbRef.current(entry.climb.id); });
            markers.push(new Marker({ element: mark, anchor: 'center' }).setLngLat(longitudeFirst(last[last.length - 1])).addTo(map));
          }
        }
      }
      const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features };
      const startData: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: starts };
      if (map.getSource('profile-canon')) {
        (map.getSource('profile-canon') as GeoJSONSource).setData(data);
        (map.getSource('profile-starts') as GeoJSONSource).setData(startData);
      } else {
        map.addSource('profile-canon', { type: 'geojson', data });
        map.addSource('profile-starts', { type: 'geojson', data: startData });
        const layout = { 'line-cap': 'round', 'line-join': 'round' } as const;
        map.addLayer({ id: 'profile-faint', type: 'line', source: 'profile-canon', filter: ['==', ['get', 'tier'], 'faint'], layout, paint: { 'line-color': GROUND.faint, 'line-width': 1.6, 'line-opacity': 0.8 } });
        map.addLayer({ id: 'profile-ridden', type: 'line', source: 'profile-canon', filter: ['==', ['get', 'tier'], 'ridden'], layout, paint: { 'line-color': GROUND.ridden, 'line-width': 2, 'line-opacity': 0.6 } });
        map.addLayer({ id: 'profile-casing', type: 'line', source: 'profile-canon', filter: ['==', ['get', 'held'], true], layout, paint: { 'line-color': GROUND.casing, 'line-width': 7, 'line-opacity': 0.6 } });
        map.addLayer({ id: 'profile-held', type: 'line', source: 'profile-canon', filter: ['==', ['get', 'held'], true], layout, paint: { 'line-color': GROUND.held, 'line-width': 2.5, 'line-opacity': 1 } });
        map.addLayer({ id: 'profile-start', type: 'circle', source: 'profile-starts', paint: { 'circle-radius': 3, 'circle-color': GROUND.start } });
      }
      const target = focus.length ? focus : everything;
      if (target.length) {
        const bounds = new LngLatBounds();
        target.forEach(point => bounds.extend(point));
        const padding = fitPadding(container, compactRef.current);
        // Leaflet used quarter-zoom snapping and a 256px world; MapLibre's
        // 512px world needs the equivalent zoom minus one.
        const camera = map.cameraForBounds(bounds, { padding: { left: padding.topLeft[0], top: padding.topLeft[1], right: padding.bottomRight[0], bottom: padding.bottomRight[1] }, maxZoom: (compactRef.current ? 13.5 : focus.length ? 14.5 : 13) - 1 });
        if (camera) {
          const zoom = Math.floor((camera.zoom! + 1) * 4) / 4 - 1;
          const sw = MercatorCoordinate.fromLngLat(bounds.getSouthWest());
          const ne = MercatorCoordinate.fromLngLat(bounds.getNorthEast());
          const worldSize = 512 * 2 ** zoom;
          // Apply the asymmetric inset at the snapped zoom, as Leaflet did.
          const center = new MercatorCoordinate(
            (sw.x + ne.x) / 2 + (padding.bottomRight[0] - padding.topLeft[0]) / (2 * worldSize),
            (sw.y + ne.y) / 2 + (padding.bottomRight[1] - padding.topLeft[1]) / (2 * worldSize),
          ).toLngLat();
          map.jumpTo({ center, zoom });
        }
      }
    };
    drawRef.current = draw;
    map.on('style.load', () => { styleReady = true; draw(); });
    map.on('render', () => {
      if (!map.getLayer('profile-held')) return;
      const held = map.queryRenderedFeatures({ layers: ['profile-held'] });
      container.dataset.renderedHeldClimbs = String(new Set(held.map(feature => feature.properties.climbId)).size);
    });
    map.on('click', ['profile-ridden', 'profile-held'], event => {
      const id = event.features?.[0]?.properties?.climbId;
      if (typeof id === 'string') openClimbRef.current(id);
    });
    map.on('mouseenter', ['profile-ridden', 'profile-held'], () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', ['profile-ridden', 'profile-held'], () => { map.getCanvas().style.cursor = ''; });
    void fetch(CLIMB_MAP_STYLE_URL, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error('Map unavailable'); return response.json() as Promise<StyleSpecification>; })
      .then(style => { if (!disposed) { styleReady = false; map.setStyle(nightLedgerMapStyle(style)); } })
      .catch(() => { /* Canon stays visible when the geographic provider is absent. */ });
    const observer = new ResizeObserver(() => { map.resize(); });
    observer.observe(container);
    const dispose = () => {
      if (disposed) return;
      disposed = true; controller.abort(); observer.disconnect();
      markers.forEach(marker => marker.remove()); map.remove(); mapRef.current = null;
      drawRef.current = () => {};
    };
    const pageHide = (event: PageTransitionEvent) => { if (!event.persisted) dispose(); };
    window.addEventListener('pagehide', pageHide);
    return () => { window.removeEventListener('pagehide', pageHide); dispose(); };
  }, []);

  useEffect(() => { mapRef.current?.resize(); drawRef.current(); }, [compact, ground]);

  return <div ref={containerRef} className="profile-ground__map" aria-hidden="true">
    <div className="profile-ground-attribution"><MapAttribution /></div>
  </div>;
}

function tierOrder(tier: GroundClimb['tier']): number {
  if (tier === 'faint') return 0;
  if (tier === 'ridden') return 1;
  return 2;
}
