import { useEffect, useMemo, useRef, useState } from 'react';
import { Map, Marker, LngLatBounds, ScaleControl, type GeoJSONSource } from 'maplibre-gl';
import { Expand, Minus, Plus, RotateCcw } from 'lucide-react';
import { CLIMB_MAP_STYLE_URL, cartoResourceUrl } from '../src/components/climb/climbMapStyle';
import { v3Ground } from './v3Ground';
import { type Scenario, type Sample } from './scenario';
import { type MapFocus } from './v3Model';

function geometry(points: Sample[], id = '') {
  const coordinates: number[][][] = []; let run: number[][] = [];
  points.forEach((p, i) => {
    if (i > 0 && p.t - points[i - 1].t > 30) { if (run.length > 1) coordinates.push(run); run = []; }
    run.push([p.lon, p.lat]);
  });
  if (run.length > 1) coordinates.push(run);
  return { type: 'Feature' as const, properties: { id }, geometry: { type: 'MultiLineString' as const, coordinates } };
}
const collection = (features: ReturnType<typeof geometry>[]) => ({ type: 'FeatureCollection' as const, features });

export function V5Map({ scenario, focus, cameraKey, scrub, onScrub, onSelect, onPin, onLeave }: {
  scenario: Scenario; focus: MapFocus | null; cameraKey: string; scrub: number | null;
  onScrub: (index: number | null) => void; onSelect: (id: string) => void; onPin: (index: number) => void; onLeave: () => void;
}) {
  const host = useRef<HTMLDivElement>(null), map = useRef<Map | null>(null), marker = useRef<Marker | null>(null);
  const endpoints = useRef<Marker[]>([]), routeMarkers = useRef<Marker[]>([]), moved = useRef(false);
  const focusRef = useRef(focus), callbacks = useRef({ onScrub, onSelect, onPin, onLeave });
  focusRef.current = focus; callbacks.current = { onScrub, onSelect, onPin, onLeave };
  const [ready, setReady] = useState(false), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0);
  const samples = scenario.ride.samples;
  const route = useMemo(() => collection([geometry(samples)]), [samples]);
  const climbs = useMemo(() => collection(scenario.climbs.map(c => geometry(samples.filter(p => p.t >= c.start && p.t <= c.end), c.id))), [scenario]);
  const fit = (duration = 350) => {
    const current = focusRef.current, points = current ? samples.slice(current.startIndex, current.endIndex + 1) : samples;
    const bounds = new LngLatBounds(); points.forEach(p => bounds.extend([p.lon, p.lat]));
    moved.current = false;
    if (!bounds.isEmpty()) map.current?.fitBounds(bounds, { padding: { top: 48, bottom: 38, left: 42, right: 96 }, maxZoom: 16, duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : duration });
  };
  useEffect(() => {
    if (!host.current) return;
    const abort = new AbortController(), key = (import.meta.env.VITE_CARTO_API_KEY ?? '').trim();
    let instance: Map | null = null;
    setReady(false); setFailed(false);
    const start = async () => {
      try {
        const response = await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL, key), { signal: abort.signal });
        if (!response.ok) throw Error('Map unavailable');
        const source = await response.json();
        if (abort.signal.aborted || !host.current) return;
        const style = v3Ground(source);
        style.layers = style.layers.map(layer => layer.type === 'background' ? { ...layer, paint: { ...layer.paint, 'background-color': '#ebebe5' } } : layer);
        style.sources = { ...style.sources, 'v5-ride': { type: 'geojson', data: route }, 'v5-climbs': { type: 'geojson', data: climbs }, 'v5-focus': { type: 'geojson', data: collection([]) } };
        style.layers.push(
          { id: 'v5-route-case', type: 'line', source: 'v5-ride', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#fafff7', 'line-width': 6 } },
          { id: 'v5-route', type: 'line', source: 'v5-ride', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#456ca0', 'line-width': 2.8, 'line-opacity': .9 } },
          { id: 'v5-climbs', type: 'line', source: 'v5-climbs', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#225aad', 'line-width': 4.3 } },
          { id: 'v5-focus-case', type: 'line', source: 'v5-focus', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#ffffff', 'line-width': 8 } },
          { id: 'v5-focus-line', type: 'line', source: 'v5-focus', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#2a64b7', 'line-width': 4.6 } },
          { id: 'v5-climb-hit', type: 'line', source: 'v5-climbs', paint: { 'line-width': 22, 'line-opacity': 0 } },
        );
        instance = new Map({ container: host.current, style, attributionControl: { compact: true }, center: [samples[0].lon, samples[0].lat], zoom: 11, dragRotate: false, pitchWithRotate: false, transformRequest: url => ({ url: cartoResourceUrl(url, key) }) });
        map.current = instance;
        instance.touchZoomRotate.disableRotation(); instance.scrollZoom.disable();
        instance.getCanvas().setAttribute('aria-label', 'Ride map. Inspect a climb or use the linked charts.');
        instance.addControl(new ScaleControl({ maxWidth: 80, unit: 'metric' }), 'bottom-left');
        instance.on('load', () => { setReady(true); fit(0); });
        instance.on('error', e => {
          // Individual relief/contour failures do not discard usable base geography.
          if (!instance?.isStyleLoaded() && !(e as { sourceId?: string }).sourceId) setFailed(true);
        });
        instance.on('movestart', e => { if (e.originalEvent) moved.current = true; });

        const inspect = (e: { point: { x: number; y: number } }, pin = false) => {
          if (!instance) return;
          const current = focusRef.current, start = current?.startIndex ?? 0, end = current?.endIndex ?? samples.length - 1;
          const step = Math.max(1, Math.floor((end - start) / 1000));
          let nearest: number | null = null, best = 16;
          for (let i = start; i <= end; i += step) {
            const xy = instance.project([samples[i].lon, samples[i].lat]), distance = Math.hypot(xy.x - e.point.x, xy.y - e.point.y);
            if (distance < best) { best = distance; nearest = i; }
          }
          if (nearest !== null) { if (pin) callbacks.current.onPin(nearest); else callbacks.current.onScrub(nearest); }
          else if (!pin) callbacks.current.onScrub(null);
        };
        instance.on('mousemove', e => inspect(e));
        instance.on('mouseout', () => callbacks.current.onLeave());
        instance.on('click', e => {
          const hit = instance?.queryRenderedFeatures(e.point, { layers: ['v5-climb-hit'] })[0]?.properties?.id;
          if (!focusRef.current && hit) callbacks.current.onSelect(hit); else inspect(e, true);
        });
        scenario.climbs.forEach((c, i) => {
          const p = samples.find(p => p.t === c.start)!;
          const el = document.createElement('button'); el.type = 'button'; el.className = 'v5-map-climb'; el.textContent = String(i + 1);
          el.setAttribute('aria-label', `Inspect ${c.name}`); el.onclick = event => { event.stopPropagation(); callbacks.current.onSelect(c.id); };
          routeMarkers.current.push(new Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(instance!));
        });
        const el = document.createElement('span'); el.className = 'v5-map-cursor'; el.hidden = true;
        marker.current = new Marker({ element: el }).setLngLat([samples[0].lon, samples[0].lat]).addTo(instance);
      } catch { if (!abort.signal.aborted) setFailed(true); }
    };
    void start();
    const resize = new ResizeObserver(() => { map.current?.resize(); if (!moved.current) fit(0); }); resize.observe(host.current);
    return () => { abort.abort(); resize.disconnect(); routeMarkers.current.forEach(m => m.remove()); routeMarkers.current = []; endpoints.current.forEach(m => m.remove()); endpoints.current = []; marker.current?.remove(); marker.current = null; instance?.remove(); map.current = null; };
  }, [scenario, retry]);
  useEffect(() => {
    const instance = map.current; if (!ready || !instance) return;
    const points = focus ? samples.slice(focus.startIndex, focus.endIndex + 1) : [];
    (instance.getSource('v5-focus') as GeoJSONSource)?.setData(collection(points.length ? [geometry(points)] : []));
    instance.setPaintProperty('v5-route', 'line-opacity', focus ? .23 : .9);
    instance.setPaintProperty('v5-route-case', 'line-opacity', focus ? .4 : .9);
    instance.setPaintProperty('v5-climbs', 'line-opacity', focus ? .18 : 1);
    routeMarkers.current.forEach(m => { m.getElement().hidden = !!focus; });
    endpoints.current.forEach(m => m.remove()); endpoints.current = [];
    const indexes = focus ? [focus.startIndex, focus.endIndex] : [0, samples.length - 1];
    indexes.forEach((index, i) => {
      const p = samples[index], el = document.createElement('button'); el.type = 'button'; el.className = `v5-map-endpoint ${i ? 'finish' : ''}`;
      el.setAttribute('aria-label', `${focus?.kind === 'range' ? 'Range' : focus ? 'Climb' : 'Ride'} ${i ? 'finish' : 'start'}`);
      const label = document.createElement('span'); label.textContent = i ? 'Finish' : 'Start'; el.append(label);
      el.onclick = event => { event.stopPropagation(); callbacks.current.onPin(index); };
      endpoints.current.push(new Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(instance));
    });
  }, [focus?.startIndex, focus?.endIndex, focus?.kind, ready, samples]);
  useEffect(() => { if (ready) fit(); }, [ready, cameraKey]);
  useEffect(() => { const el = marker.current?.getElement(), p = scrub === null ? null : samples[scrub]; if (el) el.hidden = !p; if (p) marker.current?.setLngLat([p.lon, p.lat]); }, [scrub, ready, samples]);
  return <div className="v5-map" data-map-ready={ready}>
    <div className="v5-map-canvas" ref={host} />
    {!ready && <div className="v5-map-state" role="status">{failed ? <><span>Map unavailable</span><button onClick={() => setRetry(x => x + 1)}><RotateCcw size={14} />Try again</button></> : <><span className="v5-fetch-rule" /><span>Loading map</span></>}</div>}
    <div className="v5-map-tools"><button disabled={!ready} aria-label="Fit route" onClick={() => fit()}><Expand size={16} /></button><button disabled={!ready} aria-label="Zoom in" onClick={() => { moved.current = true; map.current?.zoomIn(); }}><Plus size={17} /></button><button disabled={!ready} aria-label="Zoom out" onClick={() => { moved.current = true; map.current?.zoomOut(); }}><Minus size={17} /></button></div>
  </div>;
}
