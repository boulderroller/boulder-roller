import { useEffect, useRef, useState } from 'react';
import { Map, LngLatBounds, type GeoJSONSource } from 'maplibre-gl';
import { CLIMB_MAP_STYLE_URL, cartoResourceUrl } from '../../src/components/climb/climbMapStyle';
import {mastheadGround} from '../climb/ClimbV15Map';
import {v13HeroPadding} from './feedV13Model';
import type { Scenario, Climb, Sample } from '../scenario';

function line(points: Sample[]) {
  const coordinates: number[][][] = []; let run: number[][] = [];
  points.forEach((p, i) => { if (i > 0 && p.t - points[i - 1].t > 30) { if (run.length > 1) coordinates.push(run); run = []; } run.push([p.lon, p.lat]); });
  if (run.length > 1) coordinates.push(run);
  return { type: 'Feature' as const, properties: {}, geometry: { type: 'MultiLineString' as const, coordinates } };
}

const images=new WeakMap<Scenario,string>();
export function FeedV13Map({ scenario, climb, active }: { scenario: Scenario; climb?: Climb; active: boolean }) {
  const host = useRef<HTMLDivElement>(null), map = useRef<Map | null>(null);
  const [snapshot,setSnapshot]=useState(images.get(scenario));
  const [visible, setVisible] = useState(false), [ready, setReady] = useState(false), [failed, setFailed] = useState(false);
  useEffect(() => { const observer = new IntersectionObserver(entries => { setVisible(entries[0].isIntersecting); }, { rootMargin: '300px' }); if (host.current) observer.observe(host.current); return () => observer.disconnect(); }, []);
  useEffect(() => {
    if (!visible || !host.current) return;
    let instance: Map | null = null;
    const abort = new AbortController(); setReady(false); setFailed(false);
    const key = (import.meta.env.VITE_CARTO_API_KEY ?? '').trim(), points = scenario.ride.samples;
    const copy = host.current.closest('.c15-hero-art')?.querySelector('.c15-hero-copy');
    const fit = () => { if (!instance || !host.current?.clientWidth || !copy) return; instance.resize(); const bounds = new LngLatBounds(); points.forEach(p => bounds.extend([p.lon, p.lat])); if (!bounds.isEmpty()) instance.fitBounds(bounds, { padding: v13HeroPadding(host.current.clientWidth,host.current.clientHeight,window.matchMedia('(max-width:700px)').matches,copy.getBoundingClientRect().width), maxZoom: 15, duration: 0 }); };
    const resize = new ResizeObserver(fit); resize.observe(host.current); if(copy)resize.observe(copy);
    void (async () => {
      try {
        const response = await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL, key), { signal: abort.signal });
        if (!response.ok) throw Error('Map unavailable');
        const style = mastheadGround(await response.json()); if (abort.signal.aborted || !host.current) return;
        style.layers=style.layers.filter(layer=>layer.type!=='symbol');
        const colors=getComputedStyle(host.current),color=(name:string)=>colors.getPropertyValue(name).trim();
        style.sources = { ...style.sources, 'f13-route': { type: 'geojson', data: line(points) }, 'f13-climb': { type: 'geojson', data: line(climb ? points.filter(p => p.t >= climb.start && p.t <= climb.end) : []) } };
        style.layers.push(
          { id: 'f13-case', type: 'line', source: 'f13-route', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color('--c15-card'), 'line-width': 5.5 } },
          { id: 'f13-route', type: 'line', source: 'f13-route', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color('--c15-route'), 'line-width': 2.5, 'line-opacity': .85 } },
          { id: 'f13-highlight-case', type: 'line', source: 'f13-climb', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color('--c15-card'), 'line-width': 8, 'line-opacity': 0 } },
          { id: 'f13-highlight', type: 'line', source: 'f13-climb', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color('--c15-route-strong'), 'line-width': 4.5, 'line-opacity': 0 } },
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
    (instance.getSource('f13-climb') as GeoJSONSource)?.setData(line(climb ? scenario.ride.samples.filter(p => p.t >= climb.start && p.t <= climb.end) : []));
    instance.setPaintProperty('f13-highlight', 'line-opacity', active ? 1 : .35);
    instance.setPaintProperty('f13-highlight-case', 'line-opacity', active ? 1 : 0);
    instance.setPaintProperty('f13-route', 'line-opacity', active ? .38 : .85);
  }, [active, climb, ready, scenario]);
  return <>{snapshot&&<img className="f13-map-still" src={snapshot} alt="" aria-hidden="true"/>}<div ref={host} className="c15-map-canvas f13-map-canvas" data-map-ready={ready} data-highlighted={active} aria-hidden="true"/>{!ready && !snapshot && <div className="f13-map-loading" role="status">{failed ? 'Map unavailable' : 'Loading map'}</div>}</>;
}
