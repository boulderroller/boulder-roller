import type { GpsPoint } from './api';

export function distanceBetweenMeters(a: Pick<GpsPoint, 'latitude' | 'longitude'>, b: Pick<GpsPoint, 'latitude' | 'longitude'>): number {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const earthRadiusM = 6_371_000;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;

  return 2 * earthRadiusM * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

export function buildDistanceSeries(points: GpsPoint[]): number[] {
  const distances: number[] = [];
  let cumulativeDistanceM = 0;
  let previousPoint: GpsPoint | null = null;
  const hasProvidedDistance = points.some((point) => typeof point.distanceM === 'number' && point.distanceM > 0);

  points.forEach((point) => {
    if (hasProvidedDistance) {
      cumulativeDistanceM = point.distanceM ?? cumulativeDistanceM;
    } else if (
      previousPoint &&
      Number.isFinite(previousPoint.latitude) &&
      Number.isFinite(previousPoint.longitude) &&
      Number.isFinite(point.latitude) &&
      Number.isFinite(point.longitude)
    ) {
      cumulativeDistanceM += distanceBetweenMeters(previousPoint, point);
    }

    distances.push(cumulativeDistanceM);
    previousPoint = point;
  });

  return distances;
}

function parseTimestampMs(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '') return null;
  const numeric = Number(raw);
  if (Number.isFinite(numeric)) {
    if (Math.abs(numeric) > 1_000_000_000_000) return numeric;
    if (Math.abs(numeric) > 1_000_000_000) return numeric * 1000;
    return null;
  }

  const parsed = Date.parse(String(raw));
  return Number.isFinite(parsed) ? parsed : null;
}

function numericOffsetSeconds(raw: unknown, firstNumeric?: number): number | null {
  const numeric = Number(raw);
  if (!Number.isFinite(numeric)) return null;
  if (Math.abs(numeric) > 1_000_000_000_000) return firstNumeric === undefined ? 0 : (numeric - firstNumeric) / 1000;
  if (Math.abs(numeric) > 1_000_000_000) return firstNumeric === undefined ? 0 : numeric - firstNumeric;
  return numeric;
}

export function getGpsPointOffsetSeconds(points: GpsPoint[], index: number): number | null {
  const raw = points[index]?.timestamp;
  if (raw === undefined) return null;

  const firstNumeric = points
    .map((point) => Number(point.timestamp))
    .find((value) => Number.isFinite(value));
  const numericOffset = numericOffsetSeconds(raw, firstNumeric);
  if (numericOffset !== null) return numericOffset;

  const firstParsed = points
    .map((point) => parseTimestampMs(point.timestamp))
    .find((value): value is number => value !== null);
  const parsed = parseTimestampMs(raw);
  if (parsed === null || firstParsed === undefined) return null;

  return (parsed - firstParsed) / 1000;
}

export function findGpsIndexForOffset(
  points: GpsPoint[],
  offset?: number,
  fallbackDurationS?: number | null,
): number | undefined {
  if (!points.length || offset === undefined) return undefined;

  let closestIndex = 0;
  let closestDistance = Infinity;
  let foundTimestampOffset = false;
  let maxTimestampOffset = 0;

  points.forEach((_, index) => {
    const timestampOffset = getGpsPointOffsetSeconds(points, index);
    if (!Number.isFinite(timestampOffset)) return;
    foundTimestampOffset = true;
    maxTimestampOffset = Math.max(maxTimestampOffset, timestampOffset as number);
    const distance = Math.abs((timestampOffset as number) - offset);
    if (distance < closestDistance) {
      closestDistance = distance;
      closestIndex = index;
    }
  });

  if (foundTimestampOffset && maxTimestampOffset > 0) return closestIndex;

  if (fallbackDurationS && fallbackDurationS > 0) {
    const progress = Math.max(0, Math.min(1, offset / fallbackDurationS));
    return Math.round(progress * (points.length - 1));
  }

  return foundTimestampOffset ? 0 : undefined;
}

export function calculateGradeAtIndex(points: GpsPoint[], distances: number[], index: number): number | null {
  if (index <= 0 || index >= points.length) return null;
  const currentElevation = points[index]?.elevationM;
  const previousElevation = points[index - 1]?.elevationM;
  if (typeof currentElevation !== 'number' || typeof previousElevation !== 'number') return null;

  const distanceDelta = (distances[index] ?? 0) - (distances[index - 1] ?? 0);
  if (distanceDelta <= 0) return null;

  return ((currentElevation - previousElevation) / distanceDelta) * 100;
}
