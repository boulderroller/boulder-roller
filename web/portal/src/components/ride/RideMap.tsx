import MapAttribution from '../climb/MapAttribution';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Map,
  Marker,
  LngLatBounds,
  setWorkerUrl,
  type StyleSpecification,
} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Expand, Minus, Plus } from 'lucide-react';
import {
  MAP_GROUND,
  CLIMB_MAP_STYLE_URL,
  nightLedgerMapStyle,
} from '../climb/climbMapStyle';
import type { RoutePreview } from '../../lib/api';
import { groundRouteSegments } from '../profile/groundModel';
import type { RideSample, RideSpan } from './ridePageModel';
setWorkerUrl(workerUrl);
const visible = (p: RideSample) =>
  !p.gps.redacted &&
  Number.isFinite(p.gps.latitude) &&
  Number.isFinite(p.gps.longitude);
function segments(samples: RideSample[]) {
  const runs: number[][][] = [];
  let run: number[][] = [];
  samples.forEach((p) => {
    if (visible(p)) run.push([p.gps.longitude, p.gps.latitude]);
    else {
      if (run.length > 1) runs.push(run);
      run = [];
    }
  });
  if (run.length > 1) runs.push(run);
  return runs;
}
export default function RideMap({
  samples,
  spans,
  scrub,
  fitBox,
  onScrub,
  viewer = 'owner',
  routePreview,
  readOnly = false,
  compact = false,
}: {
  viewer?: 'owner' | 'stranger';
  routePreview?: RoutePreview | null;
  readOnly?: boolean;
  compact?: boolean;
  samples: RideSample[];
  spans: RideSpan[];
  scrub: number | null;
  fitBox: { top: number; bottom: number; left: number; right: number };
  onScrub: (index: number | null) => void;
}) {
  const container = useRef<HTMLDivElement>(null),
    mapRef = useRef<Map | null>(null),
    marker = useRef<Marker | null>(null),
    moved = useRef(false);
  const fitRef = useRef(fitBox);
  fitRef.current = fitBox;
  const [ready, setReady] = useState(false);
  const [groundReady, setGroundReady] = useState(false);
  const routes = useMemo(() => routePreview !== undefined
    ? groundRouteSegments(routePreview).map(run => run.map(([lat, lon]) => [lon, lat]))
    : segments(samples), [samples, routePreview]);
  const canon = useMemo(
    () =>
      spans.flatMap((s) =>
        segments(samples.filter((p) => p.t >= s.start && p.t <= s.end)),
      ),
    [samples, spans],
  );
  const bounds = useMemo(() => {
    const b = new LngLatBounds();
    routes.flat().forEach((p) => b.extend(p as [number, number]));
    return b;
  }, [routes]);
  const padding = () => {
    const h = container.current?.clientHeight ?? 720,
      w = container.current?.clientWidth ?? 1440,
      b = fitRef.current;
    return {
      ...b,
      top: Math.min(b.top, Math.max(0, h - b.bottom - 30)),
      left: Math.min(b.left, Math.max(20, w - b.right - 120)),
    };
  };
  const fit = () => {
    moved.current = false;
    if (!bounds.isEmpty())
      mapRef.current?.fitBounds(bounds, {
        padding: padding(),
        maxZoom: 16,
        duration: 0,
      });
  };
  useEffect(() => {
    if (!moved.current) fit();
  }, [fitBox.top, fitBox.bottom, fitBox.left, fitBox.right]);
  useEffect(() => {
    if (!container.current) return;
    setGroundReady(false);
    let geographyPainted = false;
    const abort = new AbortController();
    const css = getComputedStyle(container.current),
      ink = css.getPropertyValue('--br-ink').trim(),
      cobalt = css.getPropertyValue('--br-terrain').trim();
    const geometry = (coordinates: number[][][]) => ({
      type: 'Feature' as const,
      properties: {},
      geometry: { type: 'MultiLineString' as const, coordinates },
    });
    const style: StyleSpecification = {
      version: 8,
      sources: {
        ride: { type: 'geojson', data: geometry(routes) },
        counted: { type: 'geojson', data: geometry(canon) },
      },
      layers: [
        {
          id: 'ground',
          type: 'background',
          paint: { 'background-color': MAP_GROUND.paper },
        },
        {
          id: 'ride-halo',
          type: 'line',
          source: 'ride',
          paint: { 'line-color': MAP_GROUND.paper, 'line-width': 5.5 },
        },
        {
          id: 'ride-track',
          type: 'line',
          source: 'ride',
          paint: { 'line-color': readOnly && canon.length === 0 ? cobalt : ink, 'line-width': readOnly ? 2.6 : 2.2 },
          layout: { 'line-cap': 'round', 'line-join': 'round' },
        },
        {
          id: 'ride-counted',
          type: 'line',
          source: 'counted',
          paint: { 'line-color': cobalt, 'line-width': 3.2 },
          layout: { 'line-cap': 'round', 'line-join': 'round' },
        },
      ],
    };
    let map: Map;
    try {
      map = new Map({
        container: container.current,
        style,
        attributionControl: false,
        interactive: !readOnly,
        ...(bounds.isEmpty() ? { center: [-75.23, 40.03] as [number, number], zoom: 12 } : { bounds }),
        fitBoundsOptions: { padding: padding(), maxZoom: 16 },
        minZoom: 3,
        maxZoom: 19,
        pitchWithRotate: false,
        dragRotate: false,
        touchPitch: false,
      });
    } catch {
      return;
    }
    mapRef.current = map;
    moved.current = false;
    map.touchZoomRotate.disableRotation();
    map.doubleClickZoom.disable();
    map.getCanvas().setAttribute('aria-label', 'Ride route');
    map.on('mouseout', () => onScrub(null));
    map.on('movestart', (e) => {
      if (e.originalEvent) moved.current = true;
    });
    if (!readOnly) map.on('dblclick', fit);
    let routePainted = false;
    map.on('render', () => {
      // Terrain may still be loading after the rider's route is already drawn.
      if (!routePainted && map.getLayer('ride-track') && map.queryRenderedFeatures({ layers: ['ride-track'] }).length > 0) {
        routePainted = true;
        setReady(true);
      }
      // A feed band never presents a trace on a void while tiles are absent.
      if (readOnly && !geographyPainted && map.queryRenderedFeatures().some(feature => feature.source !== 'ride' && feature.source !== 'counted')) {
        geographyPainted = true;
        setGroundReady(true);
      }
    });
    map.on('mousemove', (e) => {
      if (readOnly) return;
      let best = -1,
        dist = 20;
      samples.forEach((p, i) => {
        if (!visible(p)) return;
        const pixel = map.project([p.gps.longitude, p.gps.latitude]);
        const d = Math.hypot(pixel.x - e.point.x, pixel.y - e.point.y);
        if (d < dist) {
          dist = d;
          best = i;
        }
      });
      onScrub(best >= 0 ? best : null);
    });
    const endpoints: Marker[] = [];
    const first = samples[0],
      last = samples.at(-1);
    (readOnly || viewer === 'stranger' ? [] : [first, last]).forEach((p, i) => {
      if (!p || !visible(p)) return;
      const el = document.createElement('button');
      el.type = 'button';
      el.className = `ride-map-endpoint ${i ? 'ride-map-endpoint--finish' : ''}`;
      const label = i ? 'Finish' : 'Start';
      el.setAttribute('aria-label', label);
      const word = document.createElement('span');
      word.textContent = label;
      el.append(word);
      el.onclick = () => onScrub(i ? samples.length - 1 : 0);
      endpoints.push(
        new Marker({ element: el })
          .setLngLat([p.gps.longitude, p.gps.latitude])
          .addTo(map),
      );
    });
    const labelEndpoints = () => {
      if (endpoints.length !== 2 || !first || !last) return;
      const a = map.project([first.gps.longitude, first.gps.latitude]),
        b = map.project([last.gps.longitude, last.gps.latitude]);
      const together = Math.hypot(a.x - b.x, a.y - b.y) < 28;
      endpoints[0].getElement().querySelector('span')!.textContent = together
        ? 'Start · Finish'
        : 'Start';
      endpoints[1].getElement().querySelector('span')!.hidden = together;
    };
    map.on('move', labelEndpoints);
    labelEndpoints();
    const el = document.createElement('span');
    el.className = 'ride-map-scrub';
    el.hidden = true;
    el.setAttribute('aria-label', 'Position on ride map');
    if (routes[0]?.[0]) marker.current = new Marker({ element: el })
      .setLngLat(routes[0][0] as [number, number])
      .addTo(map);
    void fetch(CLIMB_MAP_STYLE_URL, { signal: abort.signal })
      .then((r) => {
        if (!r.ok) throw Error();
        return r.json();
      })
      .then((s) => {
        if (abort.signal.aborted) return;
        const ground = nightLedgerMapStyle(s, { landNames: !readOnly, quiet: readOnly });
        map.setStyle({
          ...ground,
          sources: { ...ground.sources, ...style.sources },
          layers: [...ground.layers, ...style.layers.slice(1)],
        });
      })
      .catch(() => {});
    const observer = new ResizeObserver(() => {
      map.resize();
      if (!moved.current && !bounds.isEmpty())
        map.fitBounds(bounds, { padding: padding(), maxZoom: 16, duration: 0 });
    });
    observer.observe(container.current);
    let disposed = false;
    const dispose = () => {
      if (disposed) return;
      disposed = true;
      abort.abort();
      observer.disconnect();
      endpoints.forEach((m) => m.remove());
      marker.current?.remove();
      marker.current = null;
      map.remove();
      mapRef.current = null;
    };
    const pageHide = (event: PageTransitionEvent) => { if (!event.persisted) dispose(); };
    window.addEventListener('pagehide', pageHide);
    return () => { window.removeEventListener('pagehide', pageHide); dispose(); };
  }, [routes, canon, bounds, samples, viewer, readOnly]);
  useEffect(() => {
    const m = marker.current,
      p = scrub === null ? null : samples[scrub];
    if (!m) return;
    m.getElement().hidden = !p || !visible(p);
    if (p && visible(p)) m.setLngLat([p.gps.longitude, p.gps.latitude]);
  }, [scrub, samples, ready]);
  return (
    <div
      className="ride-map"
      data-read-only={readOnly}
      data-ground-ready={groundReady}
      data-compact={compact}
      data-route-ready={ready}
      data-route-segments={routes.length}
      data-scrub-index={scrub ?? ''}
    >
      <div className="ride-map-canvas" ref={container} style={readOnly && !groundReady ? { opacity: 0 } : undefined} />
      {!readOnly && <span className="ride-map-north" aria-hidden="true">
        ↑<br />N
      </span>}
      {!readOnly && !bounds.isEmpty() && (
        <div className="ride-map-controls">
          <button aria-label="Fit ride in map" onClick={fit}>
            <Expand size={18} />
          </button>
          <button
            aria-label="Zoom in"
            onClick={() => {
              moved.current = true;
              mapRef.current?.zoomIn();
            }}
          >
            <Plus size={18} />
          </button>
          <button
            aria-label="Zoom out"
            onClick={() => {
              moved.current = true;
              mapRef.current?.zoomOut();
            }}
          >
            <Minus size={18} />
          </button>
        </div>
      )}
      <div className="ride-map-attribution">
        <MapAttribution />
      </div>
    </div>
  );
}
