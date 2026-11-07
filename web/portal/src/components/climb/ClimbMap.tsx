import MapAttribution from './MapAttribution';
import { LoadingRows } from '../loading/LoadingSystem';
import { Slot } from '../loading/Slot';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, LocateFixed, Maximize2, Minus, Plus } from 'lucide-react';
import { Map, Marker, LngLatBounds, setWorkerUrl, type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type { Climb } from '../../lib/api';
import { climbRouteSegments } from '../../lib/climbGeometry';
import { CLIMB_MAP_STYLE_URL, nightLedgerMapStyle, MAP_GROUND } from './climbMapStyle';

setWorkerUrl(workerUrl);

function pointAlongRoute(points: number[][], fraction: number): [number, number] {
  const lengths = points.slice(1).map((p, i) => {
    const a = points[i];
    return Math.hypot((p[0] - a[0]) * Math.cos((p[1] + a[1]) * Math.PI / 360), p[1] - a[1]);
  });
  let remaining = Math.max(0, Math.min(1, fraction)) * lengths.reduce((sum, length) => sum + length, 0);
  for (let i = 0; i < lengths.length; i++) {
    if (remaining <= lengths[i] && lengths[i] > 0) {
      const t = remaining / lengths[i];
      return [points[i][0] + t * (points[i + 1][0] - points[i][0]), points[i][1] + t * (points[i + 1][1] - points[i][1])];
    }
    remaining -= lengths[i];
  }
  return points[points.length - 1] as [number, number];
}

export default function ClimbMap({ climb, fraction, onEndpoint, onExpand, expanded = false, fitBox }: {
  climb?: Climb;
  fraction: number | null;
  onEndpoint: (end: 'start' | 'finish') => void;
  onExpand?: (trigger: HTMLButtonElement) => void;
  expanded?: boolean;
  fitBox?: { top: number; bottom: number; left: number; right: number };
}) {
  const container = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const fitBoxRef = useRef(fitBox);
  fitBoxRef.current = fitBox;
  const riderMoved = useRef(false);
  const positionRef = useRef<Marker | null>(null);
  const endpointRef = useRef(onEndpoint);
  endpointRef.current = onEndpoint;
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const [zoom, setZoom] = useState(0);
  const coordinates = useMemo(() => (climb ? climbRouteSegments(climb) : []).map((segment) => segment.map(([lat, lng]) => [lng, lat])), [climb]);
  const bounds = useMemo(() => {
    const result = new LngLatBounds();
    coordinates.flat().forEach((point) => result.extend(point as [number, number]));
    return result;
  }, [coordinates]);
  const fitPadding = useCallback(() => {
    const room = fitBoxRef.current;
    if (room && container.current) {
      const { clientHeight: height, clientWidth: width } = container.current;
      // Keep a usable fit at large text sizes even when the card grows.
      const chromeHeight = bottomRef.current?.offsetHeight ?? 0;
      if (bottomRef.current) bottomRef.current.dataset.liftAttribution = String(chromeHeight <= 44 && room.top + room.bottom <= height - 88);
      const bottom = chromeHeight > 44 || room.top + room.bottom > height - 44
        ? Math.max(room.bottom, chromeHeight + (bottomRef.current ? parseFloat(getComputedStyle(bottomRef.current).bottom) || 0 : 0) + 26)
        : room.bottom;
      const top = Math.min(room.top, Math.max(0, height - bottom - 10));
      return { ...room, top, bottom, left: Math.min(room.left, Math.max(34, width - room.right - 160)) };
    }
    const minimum = expanded ? 75 : 65;
    // Leave the whole 44px endpoint target clear of chrome, including wrapped
    // attribution at large text sizes and the expanded map's safe-area inset.
    return {
      top: Math.max(minimum, (controlsRef.current?.offsetTop ?? 12) + (controlsRef.current?.offsetHeight ?? 44) + 26),
      bottom: Math.max(minimum, (bottomRef.current?.offsetHeight ?? 0) + (bottomRef.current ? parseFloat(getComputedStyle(bottomRef.current).bottom) || 0 : 4) + 26),
      left: minimum,
      right: minimum,
    };
  }, [expanded]);
  const fit = () => {
    riderMoved.current = false;
    if (!bounds.isEmpty()) mapRef.current?.fitBounds(bounds, { padding: fitPadding(), maxZoom: 16, duration: 0 });
  };
  useEffect(() => {
    if (!riderMoved.current && !bounds.isEmpty()) mapRef.current?.fitBounds(bounds, { padding: fitPadding(), maxZoom: 16, duration: 0 });
  }, [fitBox?.top, fitBox?.bottom, fitBox?.left, fitBox?.right, bounds, fitPadding]);

  useEffect(() => {
    if (!container.current) return;
    let disposed = false;
    const controller = new AbortController();
    setFailed(false); setReady(false);
    const routeStyle: StyleSpecification = {
      version: 8,
      sources: { canon: { type: 'geojson', data: { type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates } } } },
      layers: [
        { id: 'ground', type: 'background', paint: { 'background-color': MAP_GROUND.paper } },
        { id: 'canon-casing', type: 'line', source: 'canon', paint: { 'line-color': '#0F0E0C', 'line-width': 7 }, layout: { 'line-cap': 'round', 'line-join': 'round' } },
        { id: 'canon-route', type: 'line', source: 'canon', paint: { 'line-color': '#5592E2', 'line-width': 4 }, layout: { 'line-cap': 'round', 'line-join': 'round' } },
      ],
    };
    let map: Map;
    try {
      map = new Map({ container: container.current, style: routeStyle, attributionControl: false,
        ...(bounds.isEmpty() ? { center: [-75.23, 40.03] as [number, number], zoom: 12 } : { bounds }), fitBoundsOptions: { padding: fitPadding(), maxZoom: 16 },
        maxZoom: 19, minZoom: 3, pitchWithRotate: false, dragRotate: false,
        touchPitch: false, cooperativeGestures: !expanded && !fitBoxRef.current,
      });
    } catch {
      setFailed(true);
      return;
    }
    mapRef.current = map;
    map.touchZoomRotate.disableRotation();
    riderMoved.current = false;
    map.on('movestart', event => { if (event.originalEvent) riderMoved.current = true; });
    if (fitBoxRef.current) {
      map.doubleClickZoom.disable();
      map.on('dblclick', fit);
    }
    map.getCanvas().setAttribute('aria-label', `Map of ${climb?.name || 'climb'}. North is up. Use arrow keys to pan.`);
    map.on('idle', () => { if (!disposed && map.getLayer('canon-route')) setReady(map.queryRenderedFeatures({ layers: ['canon-route'] }).length > 0); });
    map.on('zoomend', () => setZoom(map.getZoom()));
    map.on('error', () => { if (!disposed) setFailed(true); });
    setZoom(map.getZoom());
    const markers: Marker[] = [];
    const flattened = coordinates.flat();
    for (const [name, point] of [['start', flattened[0]], ['finish', flattened[flattened.length - 1]]] as const) {
      if (!point) continue;
      const element = document.createElement('button');
      element.type = 'button';
      element.className = `climb-map-endpoint climb-map-endpoint--${name}`;
      element.setAttribute('aria-label', `${name === 'start' ? 'Start' : 'Finish'} of climb`);
      const label = document.createElement('span');
      label.textContent = name === 'start' ? 'Start' : 'Finish';
      element.append(label);
      element.addEventListener('click', () => endpointRef.current(name));
      markers.push(new Marker({ element }).setLngLat(point as [number, number]).addTo(map));
    }
    const position = document.createElement('span');
    position.className = 'climb-map-position';
    position.setAttribute('role', 'img');
    position.setAttribute('aria-label', 'Position on climb map');
    position.hidden = true;
    if (flattened[0]) positionRef.current = new Marker({ element: position }).setLngLat(flattened[0] as [number, number]).addTo(map);
    void fetch(CLIMB_MAP_STYLE_URL, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error('Map unavailable'); return response.json() as Promise<StyleSpecification>; })
      .then((style) => {
        if (disposed) return;
        const themed = nightLedgerMapStyle(style);
        map.setStyle({ ...themed, sources: { ...themed.sources, ...routeStyle.sources }, layers: [...themed.layers, ...routeStyle.layers.slice(1)] });
      }).catch(() => { if (!disposed) setFailed(true); });
    const observer = new ResizeObserver(() => {
      map.resize();
      if (!riderMoved.current && !bounds.isEmpty()) map.fitBounds(bounds, { padding: fitPadding(), maxZoom: 16, duration: 0 });
    });
    observer.observe(container.current);
    if (controlsRef.current) observer.observe(controlsRef.current);
    if (bottomRef.current) observer.observe(bottomRef.current);
    const dispose = () => {
      if (disposed) return;
      disposed = true;
      controller.abort();
      observer.disconnect();
      markers.forEach((marker) => marker.remove());
      positionRef.current?.remove();
      positionRef.current = null;
      map.remove();
      mapRef.current = null;
    };
    const pageHide = (event: PageTransitionEvent) => { if (!event.persisted) dispose(); };
    window.addEventListener('pagehide', pageHide);
    return () => { window.removeEventListener('pagehide', pageHide); dispose(); };
  }, [bounds, coordinates, climb?.name, expanded, fitPadding, retry]);

  useEffect(() => {
    const marker = positionRef.current;
    if (!marker) return;
    marker.getElement().hidden = fraction === null || coordinates.length !== 1;
    if (fraction !== null && coordinates.length === 1) marker.setLngLat(pointAlongRoute(coordinates[0], fraction));
  }, [fraction, coordinates, retry]);


  return <div data-canon-ready={ready} className={`climb-map${expanded ? ' climb-map--expanded' : ''}`}>
    <div className="climb-map-canvas" ref={container} />
    <span className="climb-map-north" aria-hidden="true"><ArrowUp size={18} />N</span>
    <div className="climb-map-controls" ref={controlsRef}>
      <button type="button" aria-label="Fit climb in map" onClick={fit}><LocateFixed size={18} /></button>
      {onExpand && <button type="button" aria-label="Expand map" onClick={(event) => onExpand(event.currentTarget)}><Maximize2 size={18} /></button>}
    </div>
    <div className="climb-map-bottom" ref={bottomRef}>
      <div className="climb-map-zoom">
        <button type="button" aria-label="Zoom in" disabled={zoom >= 19} onClick={() => { riderMoved.current = true; mapRef.current?.zoomIn({ duration: 0 }); }}><Plus size={18} /></button>
        <button type="button" aria-label="Zoom out" disabled={zoom <= 3} onClick={() => { riderMoved.current = true; mapRef.current?.zoomOut({ duration: 0 }); }}><Minus size={18} /></button>
      </div>
      <div className="climb-map-attribution"><MapAttribution data={climb?.geographicData} /></div>
    </div>
    {failed && <div className="climb-map-status" role="status">Map unavailable <button className="climb-text-button" onClick={() => setRetry((value) => value + 1)}>Try again</button></div>}
  </div>;
}
