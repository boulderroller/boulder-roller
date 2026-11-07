import MapAttribution from '../climb/MapAttribution';
import { settleDuration, settleEasing } from '../loading/motion';
import { useEffect, useRef, useState } from 'react';
import { Map as VectorMap, LngLatBounds, NavigationControl, setWorkerUrl, type StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import type { Climb } from '../../lib/api';
import { climbMapPoint, climbRouteSegments, climbRouteCoordinates } from '../../lib/climbGeometry';
export { climbMapPoint, climbRouteSegments, climbRouteCoordinates } from '../../lib/climbGeometry';
import { formatFixed } from '../../lib/formatters';
import { CLIMB_MAP_STYLE_URL, MAP_GROUND, nightLedgerMapStyle } from '../climb/climbMapStyle';
import '../../styles/portal-climb-detail.css';

setWorkerUrl(workerUrl);
export interface ClimbDiscoveryCamera {
  setView: (point: [number, number], zoom: number, options: { animate: boolean; originalEvent?: MouseEvent }) => void;
}
interface ClimbDiscoveryMapProps {
  climbs: Climb[];
  selectedClimbId: string | null;
  hoveredClimbId: string | null;
  fitKey: string | null;
  focus: { climbId: string; nonce: number } | null;
  onSelectClimb: (climbId: string) => void;
  onClearSelection: () => void;
  onHoverClimb: (climbId: string | null) => void;
  onSettledBounds: (bbox: string) => void;
  onViewportChange: (bbox: string) => void;
  onMapReady: (map: ClimbDiscoveryCamera | null) => void;
}
const longitudeFirst = ([lat, lng]: number[]): [number, number] => [lng, lat];
function mapBoundsQuery(map: VectorMap): string {
  const bounds = map.getBounds();
  return [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].map(value => formatFixed(value, 5)).join(',');
}
// Measure the room's actual opaque overlays, including a reflowed search
// control and the phone sheet, instead of guessing from viewport width.
function fitPadding(container: HTMLElement) {
  const box = container.getBoundingClientRect();
  const room = container.closest('.climbs-room');
  const rect = (selector: string) => {
    const element = room?.querySelector<HTMLElement>(selector);
    return element?.getClientRects().length ? element.getBoundingClientRect() : null;
  };
  const column = rect('.climbs-room__column');
  const controls = rect('.climbs-room__controls');
  const card = rect('.climbs-room__card-layer');
  const navigation = rect('.maplibregl-ctrl-group');
  const mobile = window.matchMedia('(max-width: 767px)').matches;
  return {
    left: !mobile && column ? Math.max(24, column.right - box.left + 24) : 24,
    right: 24,
    top: controls ? Math.max(24, controls.bottom - box.top + 24) : 24,
    bottom: Math.max(24, ...[mobile ? column : null, card, navigation].filter((r): r is DOMRect => r !== null).map(r => box.bottom - r.top + 24)),
  };
}

export default function ClimbDiscoveryMap(props: ClimbDiscoveryMapProps) {
  const { climbs, selectedClimbId, hoveredClimbId, fitKey, focus } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<VectorMap | null>(null);
  const callbacksRef = useRef(props);
  callbacksRef.current = props;
  const settlingRef = useRef(false);
  const fittedViewRef = useRef(true);
  const fittedKeyRef = useRef<string | null>(null);
  const focusedNonceRef = useRef(0);
  const [mapReady, setMapReady] = useState(false);
  const [groundReady, setGroundReady] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const controller = new AbortController();
    let disposed = false;
    const map = new VectorMap({ container, center: [-75.23, 40.03], zoom: 12, maxZoom: 19, minZoom: 3,
      style: { version: 8, sources: {}, layers: [{ id: 'ground', type: 'background', paint: { 'background-color': MAP_GROUND.paper } }] },
      attributionControl: false,
      pitchWithRotate: false, dragRotate: false, touchPitch: false,
    });
    mapRef.current = map;
    map.touchZoomRotate.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), 'bottom-right');
    let userMove = false;
    map.on('movestart', event => { userMove = Boolean(event.originalEvent); if (userMove) fittedViewRef.current = false; });
    map.on('dragstart', event => { if (event.originalEvent) userMove = true; });
    map.on('zoomstart', event => { if (event.originalEvent) userMove = true; });
    const settled = () => {
      const bbox = mapBoundsQuery(map);
      if (settlingRef.current) { settlingRef.current = false; callbacksRef.current.onSettledBounds(bbox); }
      else if (userMove) callbacksRef.current.onViewportChange(bbox);
      userMove = false;
    };
    map.on('moveend', settled);
    map.on('click', () => callbacksRef.current.onClearSelection());
    map.on('load', () => {
      if (disposed) return;
      setMapReady(true);
      callbacksRef.current.onMapReady({ setView: (point, zoom, options) => map.easeTo({ center: longitudeFirst(point), zoom, duration: options.animate ? settleDuration() : 0, easing: settleEasing, padding: { top: 0, bottom: 0, left: 0, right: 0 } }, { originalEvent: options.originalEvent }) });
      callbacksRef.current.onSettledBounds(mapBoundsQuery(map));
    });
    void fetch(CLIMB_MAP_STYLE_URL, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error('Map unavailable'); return response.json() as Promise<StyleSpecification>; })
      .then(style => { if (!disposed) { map.setStyle(nightLedgerMapStyle(style)); map.once('idle', () => { if (!disposed) setGroundReady(true); }); } })
      .catch(() => { /* Keep the canon navigable when the geographic provider is absent. */ });
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(container);
    const dispose = () => {
      if (disposed) return;
      disposed = true; controller.abort(); observer.disconnect(); callbacksRef.current.onMapReady(null); map.remove(); mapRef.current = null;
    };
    // A document navigation need not unmount React. Cancel the map's requests
    // before the browser discards the document; keep a cached page restorable.
    const pageHide = (event: PageTransitionEvent) => { if (!event.persisted) dispose(); };
    window.addEventListener('pagehide', pageHide);
    return () => { window.removeEventListener('pagehide', pageHide); dispose(); };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (!map || !container || !mapReady) return;
    // Preserve the index's thin lines, generous hit targets and hover/click
    // semantics. The vector camera projects the same trusted canon geometry.
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.classList.add('climb-discovery-canon');
    const update: Array<() => void> = [];
    const everything: number[][] = [];
    const ink = getComputedStyle(container);
    const color = { faint: ink.getPropertyValue('--br-ink-faint').trim(), held: ink.getPropertyValue('--portal-public-terrain').trim(), start: ink.getPropertyValue('--br-ink').trim() };
    const add = (tag: 'path' | 'circle', attributes: Record<string, string | number>, points: number[][]) => {
      const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
      svg.append(element);
      update.push(() => {
        const projected = points.map(point => map.project(longitudeFirst(point)));
        if (tag === 'path') element.setAttribute('d', projected.map((p, index) => `${index ? 'L' : 'M'}${formatFixed(p.x, 2)},${formatFixed(p.y, 2)}`).join(' '));
        else { element.setAttribute('cx', String(projected[0].x)); element.setAttribute('cy', String(projected[0].y)); }
      });
      return element;
    };
    const interactive = (element: SVGElement, climb: Climb) => {
      element.setAttribute('data-climb-id', climb.id);
      element.style.pointerEvents = 'stroke';
      element.addEventListener('click', event => { event.stopPropagation(); callbacksRef.current.onSelectClimb(climb.id); });
      element.addEventListener('mouseenter', () => callbacksRef.current.onHoverClimb(climb.id));
      element.addEventListener('mouseleave', event => {
        // React has already entered the destination row during mouseout.
        // Do not clear that new hover from the old imperative SVG target.
        if (!element.isConnected || (event.relatedTarget as Element | null)?.closest?.('[data-climb-id]')) return;
        if (callbacksRef.current.hoveredClimbId === climb.id) callbacksRef.current.onHoverClimb(null);
      });
    };
    for (const climb of [...climbs].sort((a, b) => Number(a.id === selectedClimbId || a.id === hoveredClimbId) - Number(b.id === selectedClimbId || b.id === hoveredClimbId))) {
      const point = climbMapPoint(climb);
      if (!point) continue;
      const segments = climbRouteSegments(climb);
      const lit = climb.id === selectedClimbId || climb.id === hoveredClimbId;
      const classes = (base: string) => [base, climb.id === selectedClimbId ? `${base}--selected` : '', climb.id === hoveredClimbId ? `${base}--hovered` : ''].filter(Boolean).join(' ');
      const lineElements: SVGElement[] = [];
      if (segments.length) {
        for (const segment of segments) {
          everything.push(...segment);
          if (lit) lineElements.push(add('path', { class: 'climb-discovery-casing', fill: 'none', stroke: MAP_GROUND.paper, 'stroke-width': 7, 'stroke-opacity': .6 }, segment));
          lineElements.push(add('path', { class: 'climb-discovery-line', fill: 'none', stroke: lit ? color.held : color.faint, 'stroke-width': lit ? 2.5 : 1.6, 'stroke-opacity': lit ? 1 : .8 }, segment));
          const route = add('path', { class: classes('climb-discovery-route'), fill: 'none', stroke: color.faint, 'stroke-width': 12, 'stroke-opacity': 0 }, segment);
          lineElements.push(route);
          interactive(route, climb);
        }
        if (lit) lineElements.push(add('circle', { class: 'climb-discovery-start', r: 3, fill: color.start }, [segments[0][0]]));
      } else everything.push(point);
      {
        const marker = add('circle', { class: classes('climb-discovery-marker'), r: lit ? 4 : 3, stroke: color.faint, 'stroke-width': 14, 'stroke-opacity': 0, fill: lit ? color.start : color.faint, 'fill-opacity': lit ? 1 : .8 }, [point]);
        interactive(marker, climb);
        marker.style.pointerEvents = 'all';
        update.push(() => {
          const projected = segments.flat().map(p => map.project(longitudeFirst(p)));
          const small = !projected.length || Math.max(
            Math.max(...projected.map(p => p.x)) - Math.min(...projected.map(p => p.x)),
            Math.max(...projected.map(p => p.y)) - Math.min(...projected.map(p => p.y)),
          ) < 12;
          if (small && !marker.isConnected) svg.append(marker);
          else if (!small) marker.remove();
          lineElements.forEach(element => { element.style.display = small ? 'none' : ''; });
        });
      }
    }
    const draw = () => update.forEach(project => project());
    container.append(svg);
    map.on('move', draw);
    map.on('resize', draw);
    if (fitKey !== null && fitKey !== fittedKeyRef.current && everything.length) {
      fittedKeyRef.current = fitKey;
      fittedViewRef.current = true;
      const bounds = new LngLatBounds();
      everything.forEach(point => bounds.extend(longitudeFirst(point)));
      settlingRef.current = true;
      map.fitBounds(bounds, { padding: fitPadding(container), maxZoom: 14, duration: 0 });
      if (settlingRef.current) { settlingRef.current = false; callbacksRef.current.onSettledBounds(mapBoundsQuery(map)); }
    }
    const refit = () => {
      if (!fittedViewRef.current) return;
      const focused = callbacksRef.current.focus && callbacksRef.current.selectedClimbId === callbacksRef.current.focus.climbId
        ? climbs.find(climb => climb.id === callbacksRef.current.focus?.climbId) : null;
      const points = focused ? climbRouteCoordinates(focused) : everything;
      const anchor = focused ? climbMapPoint(focused) : null;
      const target = points.length ? points : anchor ? [anchor] : [];
      if (!target.length) return;
      const bounds = new LngLatBounds();
      target.forEach(point => bounds.extend(longitudeFirst(point)));
      settlingRef.current = true;
      map.fitBounds(bounds, { padding: fitPadding(container), maxZoom: focused ? 15 : 14, duration: 0 });
    };
    // The first observer delivery is already covered by the fit above. Later
    // changes include drawer animation, text reflow, and viewport resizing.
    let measured = '';
    const observer = new ResizeObserver(() => {
      const padding = JSON.stringify([fitPadding(container), container.clientWidth, container.clientHeight]);
      if (measured && measured !== padding) refit();
      measured = padding;
    });
    observer.observe(container);
    container.closest('.climbs-room')?.querySelectorAll('.climbs-room__column, .climbs-room__controls, .climbs-room__card-layer').forEach(element => observer.observe(element));
    draw();
    return () => { observer.disconnect(); map.off('move', draw); map.off('resize', draw); svg.remove(); };
  }, [climbs, fitKey, hoveredClimbId, mapReady, selectedClimbId]);

  useEffect(() => {
    const map = mapRef.current;
    const container = containerRef.current;
    if (!map || !container || !mapReady || !focus || focus.nonce === focusedNonceRef.current) return;
    const climb = climbs.find(item => item.id === focus.climbId);
    if (!climb) return;
    focusedNonceRef.current = focus.nonce;
    fittedViewRef.current = true;
    const points = climbRouteCoordinates(climb);
    const point = climbMapPoint(climb);
    if (!points.length && !point) return;
    const bounds = new LngLatBounds();
    (points.length ? points : [point!]).forEach(p => bounds.extend(longitudeFirst(p)));
    settlingRef.current = true;
    map.fitBounds(bounds, { padding: fitPadding(container), maxZoom: 15, duration: settleDuration(), easing: settleEasing });
  }, [climbs, focus, mapReady]);

  return <div ref={containerRef} className="climb-discovery__map-canvas" aria-label="Climb discovery map" data-ground-ready={groundReady}>
    <div className="climb-discovery-map-attribution" style={{ color: MAP_GROUND.label }}><MapAttribution /></div>
  </div>;
}
