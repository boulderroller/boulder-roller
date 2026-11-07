import { useEffect, useRef, useState } from 'react';
import { Map, LngLatBounds, type GeoJSONSource } from 'maplibre-gl';
import { CLIMB_MAP_STYLE_URL, cartoResourceUrl } from '../../src/components/climb/climbMapStyle';
import { v12Ground } from '../v12Ground';
import type { Scenario, Climb, Sample } from '../scenario';

function line(points: Sample[]) {
  const coordinates: number[][][] = []; let run: number[][] = [];
  points.forEach((p, i) => { if (i > 0 && p.t - points[i - 1].t > 30) { if (run.length > 1) coordinates.push(run); run = []; } run.push([p.lon, p.lat]); });
  if (run.length > 1) coordinates.push(run);
  return { type: 'Feature' as const, properties: {}, geometry: { type: 'MultiLineString' as const, coordinates } };
}

const images=new WeakMap<Scenario,string>();
export function FeedV6Map({ scenario, climb, active }: { scenario: Scenario; climb?: Climb; active: boolean }) {
  const host = useRef<HTMLDivElement>(null), map = useRef<Map | null>(null);
  const [snapshot,setSnapshot]=useState(images.get(scenario));
  const [visible, setVisible] = useState(false), [ready, setReady] = useState(false), [failed, setFailed] = useState(false);
  useEffect(() => { const observer = new IntersectionObserver(entries => { setVisible(entries[0].isIntersecting); }, { rootMargin: '300px' }); if (host.current) observer.observe(host.current); return () => observer.disconnect(); }, []);
  useEffect(() => {
    if (!visible || !host.current) return;
    let instance: Map | null = null;
    const abort = new AbortController(); setReady(false); setFailed(false);
    const key = (import.meta.env.VITE_CARTO_API_KEY ?? '').trim(), points = scenario.ride.samples;
    const fit = () => { if (!instance || !host.current?.clientWidth) return; instance.resize(); const bounds = new LngLatBounds(); points.forEach(p => bounds.extend([p.lon, p.lat])); if (!bounds.isEmpty()) instance.fitBounds(bounds, { padding: { top: 26, bottom: 24, left: 30, right: 30 }, maxZoom: 15, duration: 0 }); };
    const resize = new ResizeObserver(fit); resize.observe(host.current);
    void (async () => {
      try {
        const response = await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL, key), { signal: abort.signal });
        if (!response.ok) throw Error('Map unavailable');
        const style = v12Ground(await response.json()); if (abort.signal.aborted || !host.current) return;
        style.sources = { ...style.sources, 'f3-route': { type: 'geojson', data: line(points) }, 'f3-climb': { type: 'geojson', data: line(climb ? points.filter(p => p.t >= climb.start && p.t <= climb.end) : []) } };
        style.layers.push(
          { id: 'f3-case', type: 'line', source: 'f3-route', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#fafff7', 'line-width': 5.5 } },
          { id: 'f3-route', type: 'line', source: 'f3-route', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#456ca0', 'line-width': 2.5, 'line-opacity': .85 } },
          { id: 'f3-highlight-case', type: 'line', source: 'f3-climb', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#fff', 'line-width': 8, 'line-opacity': 0 } },
          { id: 'f3-highlight', type: 'line', source: 'f3-climb', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#2a64b7', 'line-width': 4.5, 'line-opacity': 0 } },
        );
        instance = new Map({ container: host.current, style, interactive: false, attributionControl: false, canvasContextAttributes: {preserveDrawingBuffer:true}, center: [points[0].lon, points[0].lat], zoom: 10, transformRequest: url => ({ url: cartoResourceUrl(url, key) }) });
        map.current = instance;
        instance.on('load', () => { fit(); setReady(true); });
        instance.on('idle',()=>{try {const next=instance!.getCanvas().toDataURL('image/webp',.82);images.set(scenario,next);setSnapshot(next);}catch{/* Existing ground remains available. */}});
        instance.on('error', e => { if (!instance?.isStyleLoaded() && !(e as {sourceId?: string}).sourceId) setFailed(true); });
      } catch { if (!abort.signal.aborted) setFailed(true); }
    })();
    return () => { abort.abort(); resize.disconnect(); instance?.remove(); map.current = null; setReady(false); };
  }, [scenario, visible]);
  useEffect(() => {
    const instance = map.current; if (!ready || !instance) return;
    (instance.getSource('f3-climb') as GeoJSONSource)?.setData(line(climb ? scenario.ride.samples.filter(p => p.t >= climb.start && p.t <= climb.end) : []));
    instance.setPaintProperty('f3-highlight', 'line-opacity', active ? 1 : .35);
    instance.setPaintProperty('f3-highlight-case', 'line-opacity', active ? 1 : 0);
    instance.setPaintProperty('f3-route', 'line-opacity', active ? .38 : .85);
  }, [active, climb, ready, scenario]);
  return <>{snapshot&&<img className="f6-map-still" src={snapshot} alt="" aria-hidden="true"/>}<div ref={host} className="f3-map-canvas" data-map-ready={ready} data-highlighted={active} aria-hidden="true"/>{!ready && !snapshot && <div className="f3-map-loading" role="status">{failed ? 'Map unavailable' : 'Loading map'}</div>}</>;
}
