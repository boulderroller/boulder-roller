import { useEffect, useMemo, useRef, useState } from 'react';
import { Map, Marker, LngLatBounds, ScaleControl, setWorkerUrl, type StyleSpecification, type GeoJSONSource } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Expand, Minus, Plus, RotateCcw } from 'lucide-react';
import { CLIMB_MAP_STYLE_URL, cartoResourceUrl, nightLedgerMapStyle } from '../src/components/climb/climbMapStyle';
import { climbSamples, type Scenario } from './scenario';

setWorkerUrl(workerUrl);
const line = (coordinates: number[][], id = '') => ({ type: 'Feature' as const, properties: { id }, geometry: { type: 'LineString' as const, coordinates } });
const collection = (features: ReturnType<typeof line>[]) => ({ type: 'FeatureCollection' as const, features });

/** Candidate cartography preserves geographic classes and scale expressions,
 * while reducing the road network's luminance and giving water/land more range. */
function candidateGround(source: StyleSpecification): StyleSpecification {
  const style = nightLedgerMapStyle(source);
  return { ...style, layers: style.layers.map(layer => {
    if (layer.type === 'hillshade') return { ...layer, paint: { ...layer.paint, 'hillshade-exaggeration': 0.22 } };
    if (layer.type === 'line' && /road|highway|bridge|tunnel/.test(layer.id)) {
      return { ...layer, paint: { ...layer.paint, 'line-opacity': /case/.test(layer.id) ? 0.15 : /motorway|trunk|primary/.test(layer.id) ? 0.48 : 0.28 } };
    }
    if (layer.type === 'fill' && /water/.test(layer.id)) return { ...layer, paint: { ...layer.paint, 'fill-color': '#233c43' } };
    if (layer.type === 'symbol') {
      if (/poi|housenumber/.test(layer.id)) return { ...layer, layout: { ...layer.layout, visibility: 'none' } };
      return { ...layer, paint: { ...layer.paint, 'text-color': /water/.test(layer.id) ? '#91acb2' : /place|settlement/.test(layer.id) ? '#c6c7b8' : '#858d80', 'text-halo-width': 1, 'text-halo-color': '#1b201c' } };
    }
    return layer;
  }) };
}

/** V2 changes geographic color relationships while retaining scale-dependent paint. */
function candidateGroundV2(source: StyleSpecification): StyleSpecification {
  const style = nightLedgerMapStyle(source);
  const fills: Record<string, string> = {
    'r-landuse-residential': '#252b23', 'r-landcover-wood': '#273824',
    'r-landcover-grass': '#35432e', 'r-park': '#31432d',
    'r-landcover-farmland': '#373d2a', 'r-landcover-wetland': '#293f35',
    'r-landuse-pitch': '#3a4932', 'r-building': '#394134',
  };
  return { ...style, layers: style.layers.map(layer => {
    if (layer.type === 'background') return { ...layer, paint: { ...layer.paint, 'background-color': '#20261f' } };
    if (layer.type === 'fill') {
      const color = fills[layer.id] ?? (/water/.test(layer.id) ? '#24434b' : undefined);
      if (color) return { ...layer, paint: { ...layer.paint, 'fill-color': color, ...(layer.paint?.['fill-outline-color'] === layer.paint?.['fill-color'] ? { 'fill-outline-color': color } : {}) } };
    }
    if (layer.type === 'hillshade') return { ...layer, paint: { ...layer.paint, 'hillshade-shadow-color': '#172319', 'hillshade-highlight-color': '#657456', 'hillshade-accent-color': '#354530' } };
    if (layer.type === 'line' && layer['source-layer'] === 'transportation' && layer.id !== 'r-unpaved') {
      const color = /_case/.test(layer.id) ? '#30382e' : /_(mot|trunk|pri)_/.test(layer.id) ? '#69715f' : /_sec_/.test(layer.id) ? '#535d4e' : /_(minor|service)_/.test(layer.id) ? '#465143' : /_path/.test(layer.id) ? '#3b4b3a' : undefined;
      if (color) return { ...layer, paint: { ...layer.paint, 'line-color': color } };
    }
    if (layer.type === 'symbol') {
      const sourceLayer = layer['source-layer'];
      const color = sourceLayer === 'place' ? '#d0d4c4' : sourceLayer === 'transportation_name' ? '#a0ac94' : sourceLayer === 'water_name' || sourceLayer === 'waterway' ? '#94b9c2' : layer.id === 'r-park-name' ? '#a9bf97' : undefined;
      if (color) return { ...layer, paint: { ...layer.paint, 'text-color': color } };
    }
    return layer;
  }) };
}

export function WorkshopMap({ scenario, selected, scrub, onScrub, onSelect , v2 = false }: { revision?: boolean; v2?: boolean;
  scenario: Scenario; selected: string | null; scrub: number | null;
  onScrub: (index: number | null) => void; onSelect: (id: string) => void;
}) {
  const moved = useRef(false);
  const selectedEndpoints = useRef<Marker[]>([]);
  const container = useRef<HTMLDivElement>(null), map = useRef<Map | null>(null), marker = useRef<Marker | null>(null);
  const onSelectRef = useRef(onSelect), onScrubRef = useRef(onScrub), selectedRef = useRef(selected);
  onSelectRef.current = onSelect; onScrubRef.current = onScrub; selectedRef.current = selected;
  const [ready, setReady] = useState(false), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0);
  const samples = scenario.ride.samples;
  const routes = useMemo(() => collection([line(samples.map(p => [p.lon, p.lat]))]), [samples]);
  const climbs = useMemo(() => collection(scenario.climbs.map(c => line(climbSamples(scenario, c).map(p => [p.lon, p.lat]), c.id))), [scenario]);
  const fit = (duration = 350) => {
    moved.current = false;
    const c = scenario.climbs.find(c => c.id === selectedRef.current), points = c ? climbSamples(scenario, c) : samples;
    const bounds = new LngLatBounds(); points.forEach(p => bounds.extend([p.lon, p.lat]));
    if (!bounds.isEmpty()) map.current?.fitBounds(bounds, { padding: { top: 55, bottom: 45, left: 45, right: c ? 90 : 50 }, maxZoom: 16, duration, essential: false });
  };
  useEffect(() => {
    if (!container.current) return;
    const abort = new AbortController(), markers: Marker[] = [];
    const key = (import.meta.env.VITE_CARTO_API_KEY ?? '').trim();
    setReady(false); setFailed(false);
    let instance: Map | null = null;
    const start = async () => {
      try {
        const response = await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL, key), { signal: abort.signal });
        if (!response.ok) throw Error('Map style unavailable');
        const sourceStyle = await response.json();
        const style = v2 ? candidateGroundV2(sourceStyle) : candidateGround(sourceStyle);
        if (abort.signal.aborted || !container.current) return;
        style.sources = { ...style.sources, 'workshop-ride': { type: 'geojson', data: routes }, 'workshop-climbs': { type: 'geojson', data: climbs }, 'workshop-selection': { type: 'geojson', data: collection([]) } };
        style.layers.push(
          { id: 'workshop-route-case', type: 'line', source: 'workshop-ride', paint: { 'line-color': '#141c19', 'line-width': 6 } },
          { id: 'workshop-route', type: 'line', source: 'workshop-ride', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#e1e4d6', 'line-width': 2.7, 'line-opacity': 0.94 } },
          { id: 'workshop-climbs', type: 'line', source: 'workshop-climbs', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#5592e2', 'line-width': 4.5 } },
          { id: 'workshop-selected-case', type: 'line', source: 'workshop-selection', paint: { 'line-color': '#16221d', 'line-width': 9 } },
          { id: 'workshop-selected', type: 'line', source: 'workshop-selection', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#72a9f0', 'line-width': 5 } },
          { id: 'workshop-hit', type: 'line', source: 'workshop-climbs', paint: { 'line-width': 22, 'line-opacity': 0 } },
        );
        instance = new Map({ container: container.current, style, attributionControl: { compact: true }, center: [samples[0].lon, samples[0].lat], zoom: 11, dragRotate: false, pitchWithRotate: false, transformRequest: url => ({ url: cartoResourceUrl(url, key) }) });
        map.current = instance;
        instance.touchZoomRotate.disableRotation();
        instance.scrollZoom.disable();
        instance.getCanvas().setAttribute('aria-label', 'Ride route map. Use climb buttons or the elevation profile to inspect a result.');
        instance.addControl(new ScaleControl({ maxWidth: 90, unit: 'metric' }), 'bottom-left');
        instance.on('load', () => {
          if (!instance) return;
          setReady(true); fit(0);
          const c = scenario.climbs.find(c => c.id === selectedRef.current);
          (instance.getSource('workshop-selection') as GeoJSONSource)?.setData(c ? collection([line(climbSamples(scenario, c).map(p => [p.lon, p.lat]))]) : collection([]));
        });
        instance.on('movestart', e => { if (e.originalEvent) moved.current = true; });
        instance.on('click', 'workshop-hit', e => { const id = e.features?.[0]?.properties?.id; if (id) onSelectRef.current(id); });
        const boundaries = new Set(scenario.climbs.flatMap(c => [c.start, c.end]));
        const indexed = samples.map((p, i) => ({ p, i }));
        const sparse = indexed.filter(({ p }, i) => i === 0 || i === samples.length - 1 || boundaries.has(p.t) || i % Math.max(1, Math.floor(samples.length / 1800)) === 0);
        const scoped = new globalThis.Map(scenario.climbs.map(c => [c.id, indexed.filter(({ p }) => p.t >= c.start && p.t <= c.end)]));
        instance.on('mousemove', e => {
          if (!instance) return;
          let nearest: number | null = null, best = 18;
          for (const { p, i } of (selectedRef.current ? scoped.get(selectedRef.current) ?? sparse : sparse)) { const xy = instance.project([p.lon, p.lat]), d = Math.hypot(xy.x - e.point.x, xy.y - e.point.y); if (d < best) { best = d; nearest = i; } }
          onScrubRef.current(nearest);
        });
        instance.on('mouseout', () => onScrubRef.current(null));
        scenario.climbs.forEach((c, i) => {
          const p = samples.find(p => p.t === c.start)!;
          const el = document.createElement('button'); el.type = 'button'; el.className = 'map-climb-marker'; el.textContent = String(i + 1); el.setAttribute('aria-label', `Inspect ${c.name}`); el.onclick = () => onSelectRef.current(c.id);
          markers.push(new Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(instance!));
        });
        const first = samples[0], last = samples.at(-1)!;
        const together = Math.hypot(first.lon - last.lon, first.lat - last.lat) < 0.001;
        (together ? [first] : [first, last]).forEach((p, i) => {
          const endpoint = document.createElement('button'); endpoint.type = 'button'; endpoint.className = `map-route-endpoint ${i ? 'finish' : ''}`;
          endpoint.setAttribute('aria-label', together ? 'Start and finish' : i ? 'Finish' : 'Start');
          const label = document.createElement('span'); label.textContent = together ? 'Start · Finish' : i ? 'Finish' : 'Start'; endpoint.append(label);
          endpoint.onclick = () => onScrubRef.current(i ? samples.length - 1 : 0);
          markers.push(new Marker({ element: endpoint }).setLngLat([p.lon, p.lat]).addTo(instance!));
        });
        const el = document.createElement('span'); el.className = 'map-inspection-point'; el.hidden = true;
        marker.current = new Marker({ element: el }).setLngLat([samples[0].lon, samples[0].lat]).addTo(instance);
      } catch (error) { if (!abort.signal.aborted) setFailed(true); }
    };
    void start();
    const resize = new ResizeObserver(() => { map.current?.resize(); if (!moved.current && map.current) fit(0); }); resize.observe(container.current);
    return () => { abort.abort(); resize.disconnect(); markers.forEach(m => m.remove()); selectedEndpoints.current.forEach(m => m.remove()); selectedEndpoints.current = []; marker.current?.remove(); marker.current = null; instance?.remove(); map.current = null; };
  }, [scenario, retry, v2]);
  useEffect(() => {
    if (!ready || !map.current) return;
    const c = scenario.climbs.find(c => c.id === selected);
    selectedEndpoints.current.forEach(m => m.remove()); selectedEndpoints.current = [];
    container.current?.querySelectorAll<HTMLElement>('.map-climb-marker').forEach(el => { el.style.visibility = c ? 'hidden' : 'visible'; });
    if (c) {
      const points = climbSamples(scenario, c);
      [points[0], points.at(-1)!].forEach((p, i) => {
        const el = document.createElement('button'); el.type = 'button'; el.className = `map-route-endpoint ${i ? 'finish' : ''}`;
        el.setAttribute('aria-label', i ? 'Climb finish' : 'Climb start');
        const label = document.createElement('span'); label.textContent = i ? 'Finish' : 'Start'; el.append(label);
        el.onclick = () => onScrubRef.current(samples.findIndex(s => s.t === p.t));
        selectedEndpoints.current.push(new Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(map.current!));
      });
    }
    (map.current.getSource('workshop-selection') as GeoJSONSource)?.setData(c ? collection([line(climbSamples(scenario, c).map(p => [p.lon, p.lat]))]) : collection([]));
    fit(window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 400);
  }, [selected, ready]);
  useEffect(() => { const el = marker.current?.getElement(), p = scrub === null ? null : samples[scrub]; if (el) el.hidden = !p; if (p) marker.current?.setLngLat([p.lon, p.lat]); }, [scrub, ready, samples]);
  return <div className="candidate-map" data-map-ready={ready}>
    <div className="map-canvas" ref={container} />
    {!ready && <div className="map-message" role="status">{failed ? <><span>Map unavailable</span><button onClick={() => setRetry(n => n + 1)}><RotateCcw size={15} /> Try again</button></> : 'Loading map…'}</div>}
    <div className="map-key" aria-hidden="true"><i />Ride <i className="climb-key" />Climbs</div>
    <div className="map-tools"><button aria-label="Fit route" onClick={() => fit()}><Expand size={17} /></button><button aria-label="Zoom in" onClick={() => { moved.current = true; map.current?.zoomIn(); }}><Plus size={17} /></button><button aria-label="Zoom out" onClick={() => { moved.current = true; map.current?.zoomOut(); }}><Minus size={17} /></button></div>
  </div>;
}
