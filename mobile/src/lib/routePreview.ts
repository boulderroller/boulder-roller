export interface RoutePreviewPoint {
  x: number;
  y: number;
}

export interface RoutePreviewBounds {
  minLat: number;
  minLon: number;
  maxLat: number;
  maxLon: number;
}

export interface RoutePreview {
  contractVersion: 'route_preview.v1';
  source: string;
  points: RoutePreviewPoint[];
  segments?: RoutePreviewPoint[][];
  pointCount: number;
  bounds?: RoutePreviewBounds | null;
  placeLabel?: string | null;
  fallbackReason?: string | null;
  privacy?: {
    redactedGps?: boolean;
    [key: string]: unknown;
  };
}

interface RawGpsPoint {
  latitude?: number | null;
  longitude?: number | null;
}

const MAX_ROUTE_PREVIEW_POINTS = 48;

function finiteCoordinate(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function sampleSegments(points: Array<[number, number]>): Array<Array<[number, number]>> {
  if (points.length <= MAX_ROUTE_PREVIEW_POINTS) return [points];

  const edges = points.slice(0, -1).map((point, index) => [point, points[index + 1]]);
  const targetEdges = Math.min(edges.length, Math.floor(MAX_ROUTE_PREVIEW_POINTS / 2));
  if (targetEdges <= 1) return edges.slice(0, 1);
  const stride = (edges.length - 1) / (targetEdges - 1);
  return Array.from({ length: targetEdges }, (_unused, index) => edges[Math.round(index * stride)]);
}

export function buildRoutePreviewFromGps(
  points: RawGpsPoint[],
  options: {
    source: string;
    placeLabel?: string | null;
    redactedGps?: boolean;
  },
): RoutePreview | null {
  if (!points.length) return null;

  const coords = points.flatMap((point): Array<[number, number]> => {
    const lat = finiteCoordinate(point.latitude);
    const lon = finiteCoordinate(point.longitude);
    if (lat == null || lon == null) return [];
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return [];
    return [[lat, lon]];
  });

  if (coords.length < 2) {
    return {
      contractVersion: 'route_preview.v1',
      source: options.source,
      points: [],
      pointCount: 0,
      placeLabel: options.placeLabel ?? null,
      fallbackReason: points.length >= 2 ? 'privacy_redacted' : 'missing_gps',
      privacy: { redactedGps: Boolean(options.redactedGps) },
    };
  }

  const lats = coords.map(([lat]) => lat);
  const lons = coords.map(([_lat, lon]) => lon);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const latSpan = Math.max(maxLat - minLat, 0.00001);
  const lonSpan = Math.max(maxLon - minLon, 0.00001);

  const normalizedSegments = sampleSegments(coords).map((segment) => (
    segment.map(([lat, lon]) => ({
      x: Number(((lon - minLon) / lonSpan).toFixed(12)),
      y: Number((1 - ((lat - minLat) / latSpan)).toFixed(12)),
    }))
  ));

  return {
    contractVersion: 'route_preview.v1',
    source: options.source,
    points: normalizedSegments.length === 1 ? normalizedSegments[0] : [],
    segments: normalizedSegments,
    pointCount: coords.length,
    bounds: {
      minLat: Number(minLat.toFixed(9)),
      minLon: Number(minLon.toFixed(9)),
      maxLat: Number(maxLat.toFixed(9)),
      maxLon: Number(maxLon.toFixed(9)),
    },
    placeLabel: options.placeLabel ?? null,
    fallbackReason: null,
    privacy: { redactedGps: Boolean(options.redactedGps) },
  };
}
