import { useRef, useEffect, memo, useMemo } from 'react';
import {
  formatDistanceMeters,
  formatElevationTenths,
  formatGradientBasisPoints,
} from '@/lib/format';

type Coordinate = { lat: number; lon: number; ele?: number };

type ClimbVisualProps = {
  /** Decoded polyline coordinates */
  coordinates: Coordinate[];
  /** Elevation gain in tenths of meters (consistent with climb/vault vert_m) */
  vertM: number | string | null;
  /** Distance in meters */
  distanceM: number | string | null;
  /** Gradient in basis points (consistent with climb/vault avg_gradient_pct) */
  avgGradientPct: number | string | null;
  /** Terrain classification if available */
  terrain?: string | null;
};

/**
 * Detects whether the user prefers dark mode via matchMedia.
 * Falls back to false if matchMedia is unavailable.
 */
function usePrefersDark(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    return false;
  }
}

/**
 * Canvas-based route polyline renderer for climb detail pages.
 * Retina-aware, theme-aware, with start/end dots.
 */
const RouteCanvas = memo(function RouteCanvas({ coordinates }: { coordinates: Coordinate[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDark = usePrefersDark();

  const bounds = useMemo(() => {
    if (coordinates.length < 2) return null;
    let minLat = Infinity, maxLat = -Infinity;
    let minLon = Infinity, maxLon = -Infinity;
    for (const c of coordinates) {
      if (c.lat < minLat) minLat = c.lat;
      if (c.lat > maxLat) maxLat = c.lat;
      if (c.lon < minLon) minLon = c.lon;
      if (c.lon > maxLon) maxLon = c.lon;
    }
    return { minLat, maxLat, minLon, maxLon };
  }, [coordinates]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || !bounds || coordinates.length < 2) return;

    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = rect.width;
    const h = rect.height;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.scale(dpr, dpr);

    // Background
    ctx.fillStyle = isDark ? '#111318' : '#f7f9fc';
    ctx.fillRect(0, 0, w, h);

    // Subtle grid
    ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)';
    ctx.lineWidth = 1;
    const gridSize = 32;
    for (let x = 0; x < w; x += gridSize) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += gridSize) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Project GPS to canvas
    const padding = 20;
    const drawW = w - padding * 2;
    const drawH = h - padding * 2;

    const latRange = bounds.maxLat - bounds.minLat || 0.001;
    const lonRange = bounds.maxLon - bounds.minLon || 0.001;

    const midLat = (bounds.minLat + bounds.maxLat) / 2;
    const cosLat = Math.cos((midLat * Math.PI) / 180);
    const adjustedLonRange = lonRange * cosLat;

    const scaleX = drawW / adjustedLonRange;
    const scaleY = drawH / latRange;
    const scale = Math.min(scaleX, scaleY);

    const projectedW = adjustedLonRange * scale;
    const projectedH = latRange * scale;
    const offsetX = padding + (drawW - projectedW) / 2;
    const offsetY = padding + (drawH - projectedH) / 2;

    const toCanvas = (lat: number, lon: number): [number, number] => {
      const x = offsetX + (lon - bounds.minLon) * cosLat * scale;
      const y = offsetY + (bounds.maxLat - lat) * scale;
      return [x, y];
    };

    // Draw route
    ctx.beginPath();
    const [startX, startY] = toCanvas(coordinates[0].lat, coordinates[0].lon);
    ctx.moveTo(startX, startY);

    const step = Math.max(1, Math.floor(coordinates.length / 400));
    for (let i = step; i < coordinates.length; i += step) {
      const [x, y] = toCanvas(coordinates[i].lat, coordinates[i].lon);
      ctx.lineTo(x, y);
    }
    const last = coordinates[coordinates.length - 1];
    const [lastX, lastY] = toCanvas(last.lat, last.lon);
    ctx.lineTo(lastX, lastY);

    ctx.strokeStyle = isDark ? '#82bbff' : '#1d6fe8';
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.stroke();

    // Start dot (green)
    ctx.beginPath();
    ctx.arc(startX, startY, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#22c55e';
    ctx.fill();
    ctx.strokeStyle = isDark ? '#111318' : '#f7f9fc';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // End dot (red/orange)
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#ef4444';
    ctx.fill();
    ctx.strokeStyle = isDark ? '#111318' : '#f7f9fc';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }, [coordinates, bounds, isDark]);

  if (coordinates.length < 2) return null;

  return (
    <div ref={containerRef} className="climb-visual__map">
      <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height: '100%' }} />
    </div>
  );
});

/**
 * Canvas-based mini elevation profile.
 * Draws a filled area chart of elevation along the route.
 */
const ElevationProfile = memo(function ElevationProfile({ coordinates }: { coordinates: Coordinate[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDark = usePrefersDark();

  const elevations = useMemo(() => {
    return coordinates
      .filter((c) => c.ele !== undefined && c.ele !== null && Number.isFinite(c.ele))
      .map((c) => c.ele as number);
  }, [coordinates]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || elevations.length < 2) return;

    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = rect.width;
    const h = rect.height;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.scale(dpr, dpr);

    // Background
    ctx.fillStyle = isDark ? '#111318' : '#f7f9fc';
    ctx.fillRect(0, 0, w, h);

    const padding = { top: 8, right: 8, bottom: 8, left: 8 };
    const drawW = w - padding.left - padding.right;
    const drawH = h - padding.top - padding.bottom;

    const minEle = Math.min(...elevations);
    const maxEle = Math.max(...elevations);
    const eleRange = maxEle - minEle || 1;

    // Sample for performance
    const step = Math.max(1, Math.floor(elevations.length / 300));
    const sampled: number[] = [];
    for (let i = 0; i < elevations.length; i += step) {
      sampled.push(elevations[i]);
    }
    if (sampled[sampled.length - 1] !== elevations[elevations.length - 1]) {
      sampled.push(elevations[elevations.length - 1]);
    }

    const toX = (i: number) => padding.left + (i / (sampled.length - 1)) * drawW;
    const toY = (ele: number) => padding.top + drawH - ((ele - minEle) / eleRange) * drawH;

    // Filled area
    ctx.beginPath();
    ctx.moveTo(toX(0), toY(sampled[0]));
    for (let i = 1; i < sampled.length; i++) {
      ctx.lineTo(toX(i), toY(sampled[i]));
    }
    ctx.lineTo(toX(sampled.length - 1), padding.top + drawH);
    ctx.lineTo(toX(0), padding.top + drawH);
    ctx.closePath();

    const gradient = ctx.createLinearGradient(0, padding.top, 0, padding.top + drawH);
    if (isDark) {
      gradient.addColorStop(0, 'rgba(130, 187, 255, 0.25)');
      gradient.addColorStop(1, 'rgba(130, 187, 255, 0.03)');
    } else {
      gradient.addColorStop(0, 'rgba(29, 111, 232, 0.18)');
      gradient.addColorStop(1, 'rgba(29, 111, 232, 0.02)');
    }
    ctx.fillStyle = gradient;
    ctx.fill();

    // Line on top
    ctx.beginPath();
    ctx.moveTo(toX(0), toY(sampled[0]));
    for (let i = 1; i < sampled.length; i++) {
      ctx.lineTo(toX(i), toY(sampled[i]));
    }
    ctx.strokeStyle = isDark ? '#82bbff' : '#1d6fe8';
    ctx.lineWidth = 1.5;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // Min/max labels
    ctx.font = `600 10px ${getComputedStyle(document.body).getPropertyValue('--font-mono').trim() || 'monospace'}`;
    ctx.fillStyle = isDark ? '#a0a8b8' : '#566478';
    ctx.textAlign = 'left';
    ctx.fillText(`${Math.round(maxEle)}m`, padding.left + 2, padding.top + 10);
    ctx.fillText(`${Math.round(minEle)}m`, padding.left + 2, padding.top + drawH - 2);
  }, [elevations, isDark]);

  if (elevations.length < 2) return null;

  return (
    <div ref={containerRef} className="climb-visual__profile">
      <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height: '100%' }} />
    </div>
  );
});

/**
 * Trait card for NFT-style property display.
 */
function TraitCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="trait-card">
      <span className="trait-card__label">{label}</span>
      <strong className="trait-card__value">{value}</strong>
    </div>
  );
}

/**
 * Decodes a polyline_json string into coordinate objects.
 * Supports encoded Google polyline strings plus raw JSON arrays in the two
 * formats currently seen in the indexer: { lat, lon, ele? } and [lat, lon, ele?].
 */
export function decodePolylineJson(raw: unknown): Coordinate[] {
  if (!raw) return [];

  if (Array.isArray(raw)) {
    return raw
      .map(coordinateFromPolylinePoint)
      .filter((point): point is Coordinate => point !== null);
  }

  // If it's a JSON string, try parsing
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        return decodePolylineJson(parsed);
      }
    } catch {
      // Not JSON — try Google encoded polyline
      return decodeGooglePolyline(raw);
    }
  }

  return [];
}

function coordinateFromPolylinePoint(point: unknown): Coordinate | null {
  if (!point) return null;

  if (Array.isArray(point)) {
    const lat = toFiniteNumber(point[0]);
    const lon = toFiniteNumber(point[1]);
    const ele = toFiniteNumber(point[2]);
    return normalizeCoordinate(lat, lon, ele);
  }

  if (typeof point === 'object') {
    const record = point as Record<string, unknown>;
    const lat = toFiniteNumber(record.lat);
    const lon = toFiniteNumber(record.lon ?? record.lng);
    const ele = toFiniteNumber(record.ele ?? record.altitude ?? record.elevation);
    return normalizeCoordinate(lat, lon, ele);
  }

  return null;
}

function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function normalizeCoordinate(
  lat: number | null,
  lon: number | null,
  ele: number | null
): Coordinate | null {
  if (lat === null || lon === null) return null;
  if (lat === 0 && lon === 0) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return {
    lat,
    lon,
    ele: ele ?? undefined,
  };
}

/**
 * Decode Google encoded polyline format.
 * Returns lat/lon pairs (no elevation).
 */
function decodeGooglePolyline(encoded: string): Coordinate[] {
  const coords: Coordinate[] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    let shift = 0;
    let result = 0;
    let byte: number;

    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lat += result & 1 ? ~(result >> 1) : result >> 1;

    shift = 0;
    result = 0;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20);
    lng += result & 1 ? ~(result >> 1) : result >> 1;

    const latVal = lat / 1e5;
    const lngVal = lng / 1e5;
    if (latVal !== 0 || lngVal !== 0) {
      coords.push({ lat: latVal, lon: lngVal });
    }
  }

  return coords;
}

/**
 * Full climb visual panel: route map, elevation profile, and NFT-style trait cards.
 */
export default function ClimbVisual({
  coordinates,
  vertM,
  distanceM,
  avgGradientPct,
  terrain,
}: ClimbVisualProps) {
  const hasMap = coordinates.length >= 2;
  const hasElevation = coordinates.some((c) => c.ele !== undefined && c.ele !== null);

  if (!hasMap) return null;

  return (
    <div className="climb-visual">
      <div className="climb-visual__panels">
        <RouteCanvas coordinates={coordinates} />
        {hasElevation ? <ElevationProfile coordinates={coordinates} /> : null}
      </div>
      <div className="climb-visual__traits">
        <TraitCard label="Elevation" value={formatElevationTenths(vertM)} />
        <TraitCard label="Distance" value={formatDistanceMeters(distanceM)} />
        <TraitCard label="Avg Gradient" value={formatGradientBasisPoints(avgGradientPct)} />
        {terrain ? <TraitCard label="Terrain" value={terrain} /> : null}
      </div>
    </div>
  );
}
