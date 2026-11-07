import type { Climb, RoutePreviewBounds } from './api';

type ClimbPoint = [number, number];

function isFiniteCoordinate(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function validBounds(bounds: RoutePreviewBounds | null | undefined): bounds is RoutePreviewBounds {
  return Boolean(
    bounds
    && isFiniteCoordinate(bounds.minLat)
    && isFiniteCoordinate(bounds.minLon)
    && isFiniteCoordinate(bounds.maxLat)
    && isFiniteCoordinate(bounds.maxLon)
    && bounds.maxLat >= bounds.minLat
    && bounds.maxLon >= bounds.minLon
    && bounds.minLat >= -90 && bounds.maxLat <= 90
    && bounds.minLon >= -180 && bounds.maxLon <= 180,
  );
}

export function climbMapPoint(climb: Climb): ClimbPoint | null {
  const previewBounds = climb.routePreview?.bounds;
  if (validBounds(previewBounds)) {
    return [
      (previewBounds.minLat + previewBounds.maxLat) / 2,
      (previewBounds.minLon + previewBounds.maxLon) / 2,
    ];
  }

  if (
    !isFiniteCoordinate(climb.startLat)
    || !isFiniteCoordinate(climb.startLon)
    || !isFiniteCoordinate(climb.endLat)
    || !isFiniteCoordinate(climb.endLon)
  ) {
    return null;
  }

  return [
    (climb.startLat + climb.endLat) / 2,
    (climb.startLon + climb.endLon) / 2,
  ];
}

function projectPoints(points: { x: number; y: number }[], bounds: RoutePreviewBounds): ClimbPoint[] {
  const latSpan = bounds.maxLat - bounds.minLat;
  const lonSpan = bounds.maxLon - bounds.minLon;
  return points
    .filter((point) => (
      Number.isFinite(point.x)
      && Number.isFinite(point.y)
      && point.x >= 0
      && point.x <= 1
      && point.y >= 0
      && point.y <= 1
    ))
    .map((point) => [
      bounds.maxLat - (point.y * latSpan),
      bounds.minLon + (point.x * lonSpan),
    ]);
}

/** The climb's centerline as drawable segments; empty when the preview is not a trusted source. */
export function climbRouteSegments(climb: Climb): ClimbPoint[][] {
  const preview = climb.routePreview;
  const bounds = preview?.bounds;
  const trustedSource = preview?.source === 'canon_centerline' || preview?.source === 'climb_polyline';
  if (!trustedSource || preview?.fallbackReason || !validBounds(bounds)) return [];

  const segments = preview?.segments && preview.segments.length > 0
    ? preview.segments
    : preview?.points && preview.points.length >= 2
      ? [preview.points]
      : [];
  return segments.flatMap((segment) => {
    const runs: { x: number; y: number }[][] = [[]];
    for (const point of segment) {
      if (!Number.isFinite(point.x) || !Number.isFinite(point.y) || point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1) {
        if (runs[runs.length - 1].length) runs.push([]);
      } else runs[runs.length - 1].push(point);
    }
    return runs.filter((run) => run.length >= 2).map((run) => projectPoints(run, bounds));
  });
}

export function climbRouteCoordinates(climb: Climb): ClimbPoint[] {
  return climbRouteSegments(climb).flat();
}
