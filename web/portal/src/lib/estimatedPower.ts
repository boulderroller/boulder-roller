import type { GpsPoint, StreamResponse } from './api';

const STANDARD_RIDER_MASS_KG = 75;
const STANDARD_BIKE_MASS_KG = 8;
const GRAVITY_MPS2 = 9.80665;
const AIR_DENSITY_KG_M3 = 1.225;
const CYCLING_CDA_M2 = 0.32;
const ROLLING_RESISTANCE = 0.005;
const DRIVETRAIN_EFFICIENCY = 0.975;
const MAX_ESTIMATED_POWER_W = 1400;
const MAX_SPEED_MPS = 32;
const MIN_MOVING_SPEED_MPS = 0.8;
const GRADE_WINDOW_M = 55;

function signedSteadyStatePower(speed: number, grade: number, cda = CYCLING_CDA_M2, crr = ROLLING_RESISTANCE): number {
  const angle = Math.atan(grade);
  return ((STANDARD_RIDER_MASS_KG + STANDARD_BIKE_MASS_KG) * GRAVITY_MPS2
    * (Math.sin(angle) + crr * Math.cos(angle)) * speed
    + 0.5 * AIR_DENSITY_KG_M3 * cda * speed ** 3) / DRIVETRAIN_EFFICIENCY;
}

/** Same canonical-profile estimator as backend climb_effort_metrics. */
export function estimateClimbPower(distanceM: number, netGainM: number, timeS: number) {
  const speed = distanceM / timeS;
  const grade = netGainM / distanceM;
  return {
    watts: Math.max(0, signedSteadyStatePower(speed, grade)),
    rangeW: [Math.max(0, signedSteadyStatePower(speed, grade, 0.28, 0.004)),
      Math.max(0, signedSteadyStatePower(speed, grade, 0.36, 0.006))],
  };
}

type EstimatedMotion = {
  timestamp: string;
  dt: number;
  speedMps: number;
  grade: number;
  accelerationMps2: number;
};

type EstimatedPowerInput = {
  rideId?: string;
  points: GpsPoint[];
  speedStream?: StreamResponse | null;
  rideDurationS?: number | null;
};

export function hasTelemetryStreamData(stream?: StreamResponse | null): boolean {
  return (stream?.values ?? []).filter((value) => Number.isFinite(value)).length > 1;
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function parseTimestampSeconds(timestamp?: string): number | null {
  if (!timestamp) return null;
  const ms = Date.parse(timestamp);
  return Number.isFinite(ms) ? ms / 1000 : null;
}

function haversineDistanceM(a: GpsPoint, b: GpsPoint): number {
  const toRad = (degrees: number) => (degrees * Math.PI) / 180;
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);
  const deltaLat = toRad(b.latitude - a.latitude);
  const deltaLon = toRad(b.longitude - a.longitude);
  const sinLat = Math.sin(deltaLat / 2);
  const sinLon = Math.sin(deltaLon / 2);
  const h = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon;
  return 6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(Math.max(0, 1 - h)));
}

function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

function medianSmoothSeries(values: number[], radius: number): number[] {
  if (values.length <= 2 || radius <= 0) return values;
  return values.map((_, index) => {
    const start = Math.max(0, index - radius);
    const end = Math.min(values.length, index + radius + 1);
    return median(values.slice(start, end).filter((value) => Number.isFinite(value)));
  });
}

function exponentialSmoothSeries(values: number[], alpha: number): number[] {
  if (!values.length) return values;
  const smoothed: number[] = [];
  let previous = Number.isFinite(values[0]) ? values[0] : 0;
  values.forEach((value) => {
    const target = Number.isFinite(value) ? value : previous;
    previous += (target - previous) * alpha;
    smoothed.push(previous);
  });
  return smoothed;
}

function fillMissingElevation(values: Array<number | null>): Array<number | null> {
  const forward: Array<number | null> = [];
  let last: number | null = null;
  values.forEach((value, index) => {
    if (typeof value === 'number' && Number.isFinite(value)) last = value;
    forward[index] = last;
  });

  const backward: Array<number | null> = [];
  last = null;
  for (let index = values.length - 1; index >= 0; index -= 1) {
    const value = values[index];
    if (typeof value === 'number' && Number.isFinite(value)) last = value;
    backward[index] = last;
  }

  return values.map((value, index) => {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const before = forward[index];
    const after = backward[index];
    if (before !== null && after !== null) return (before + after) / 2;
    return before ?? after ?? null;
  });
}

function streamValueAtGpsIndex(stream: StreamResponse | null | undefined, index: number, gpsPointCount: number): number | null {
  const values = stream?.values ?? [];
  if (values.length === 0 || gpsPointCount <= 0) return null;
  const streamIndex = gpsPointCount > 1
    ? Math.round((index / (gpsPointCount - 1)) * (values.length - 1))
    : 0;
  const value = values[clampNumber(streamIndex, 0, values.length - 1)];
  return Number.isFinite(value) && value >= 0 ? value : null;
}

function distanceBetweenPoints(prev: GpsPoint, point: GpsPoint): number {
  const trackDistance =
    typeof point.distanceM === 'number' &&
    typeof prev.distanceM === 'number' &&
    Number.isFinite(point.distanceM) &&
    Number.isFinite(prev.distanceM) &&
    point.distanceM >= prev.distanceM
      ? point.distanceM - prev.distanceM
      : null;

  if (trackDistance !== null) return trackDistance;
  return haversineDistanceM(prev, point);
}

function buildTimeDeltas(points: GpsPoint[], rideDurationS?: number | null): number[] {
  const fallbackDt = typeof rideDurationS === 'number' && rideDurationS > 0
    ? rideDurationS / Math.max(1, points.length - 1)
    : 1;

  return points.map((point, index) => {
    if (index === 0) return fallbackDt;
    const previous = points[index - 1];
    const currentTime = parseTimestampSeconds(point.timestamp);
    const prevTime = parseTimestampSeconds(previous.timestamp);
    if (currentTime !== null && prevTime !== null && currentTime > prevTime) {
      return clampNumber(currentTime - prevTime, 0.25, 900);
    }
    return fallbackDt;
  });
}

function buildDistanceSeries(points: GpsPoint[]): { deltas: number[]; cumulative: number[] } {
  const deltas: number[] = [];
  const cumulative: number[] = [];
  let total = 0;

  points.forEach((point, index) => {
    if (index === 0) {
      deltas.push(0);
      cumulative.push(0);
      return;
    }

    const distance = Math.max(0, distanceBetweenPoints(points[index - 1], point));
    total += distance;
    deltas.push(distance);
    cumulative.push(total);
  });

  return { deltas, cumulative };
}

function buildSpeedSeries(
  points: GpsPoint[],
  deltas: number[],
  dts: number[],
  speedStream?: StreamResponse | null,
): number[] {
  const raw = points.map((_, index) => {
    const streamSpeed = streamValueAtGpsIndex(speedStream, index, points.length);
    const gpsSpeed = index > 0 && dts[index] > 0 ? deltas[index] / dts[index] : 0;
    const speed = typeof streamSpeed === 'number' && streamSpeed > 0 ? streamSpeed : gpsSpeed;
    return clampNumber(speed, 0, MAX_SPEED_MPS);
  });

  return exponentialSmoothSeries(medianSmoothSeries(raw, 1), 0.42);
}

function buildGradeSeries(points: GpsPoint[], cumulativeDistance: number[]): number[] {
  const rawElevations = points.map((point) =>
    typeof point.elevationM === 'number' && Number.isFinite(point.elevationM) ? point.elevationM : null,
  );
  const elevations = fillMissingElevation(rawElevations);
  if (elevations.every((value) => value === null)) return points.map(() => 0);

  const rawGrades = points.map((_, index) => {
    const currentElevation = elevations[index];
    if (currentElevation === null) return 0;

    let left = index;
    while (left > 0 && cumulativeDistance[index] - cumulativeDistance[left] < GRADE_WINDOW_M) {
      left -= 1;
    }

    let right = index;
    while (right < points.length - 1 && cumulativeDistance[right] - cumulativeDistance[index] < GRADE_WINDOW_M) {
      right += 1;
    }

    const leftElevation = elevations[left];
    const rightElevation = elevations[right];
    const span = cumulativeDistance[right] - cumulativeDistance[left];
    if (leftElevation === null || rightElevation === null || span < 10) return 0;
    return clampNumber((rightElevation - leftElevation) / span, -0.2, 0.2);
  });

  return exponentialSmoothSeries(medianSmoothSeries(rawGrades, 2), 0.36);
}

function buildMotionSeries(input: EstimatedPowerInput): EstimatedMotion[] {
  const { points, speedStream, rideDurationS } = input;
  const dts = buildTimeDeltas(points, rideDurationS);
  const { deltas, cumulative } = buildDistanceSeries(points);
  const speeds = buildSpeedSeries(points, deltas, dts, speedStream);
  const grades = buildGradeSeries(points, cumulative);

  return points.map((point, index) => {
    const dt = dts[index];
    const acceleration = index > 0 && dt > 0
      ? clampNumber((speeds[index] - speeds[index - 1]) / dt, -2.6, 1.8)
      : 0;

    return {
      timestamp: point.timestamp,
      dt,
      speedMps: speeds[index],
      grade: grades[index],
      accelerationMps2: acceleration,
    };
  });
}

function estimateRawPower(motion: EstimatedMotion, totalMassKg: number): number {
  const { speedMps, grade, accelerationMps2 } = motion;
  if (speedMps < MIN_MOVING_SPEED_MPS) return 0;

  const angle = Math.atan(grade);
  const rollingPower = totalMassKg * GRAVITY_MPS2 * ROLLING_RESISTANCE * Math.cos(angle) * speedMps;
  const accelerationPower = accelerationMps2 > 0.06
    ? totalMassKg * accelerationMps2 * speedMps * 0.82
    : 0;

  let riderPower = signedSteadyStatePower(speedMps, grade) * DRIVETRAIN_EFFICIENCY + accelerationPower;
  if (grade < -0.012 && accelerationMps2 <= 0.08) {
    const descentCeiling = rollingPower * (grade < -0.04 ? 0.35 : 0.65);
    riderPower = Math.min(riderPower, descentCeiling);
  }

  return clampNumber(Math.max(0, riderPower / DRIVETRAIN_EFFICIENCY), 0, MAX_ESTIMATED_POWER_W);
}

function smoothPowerLine(rawValues: number[], motions: EstimatedMotion[]): number[] {
  if (!rawValues.length) return rawValues;
  const targets = medianSmoothSeries(rawValues, 1);
  const firstTarget = targets.find((value) => Number.isFinite(value)) ?? 0;
  let previous = firstTarget;

  return targets.map((target, index) => {
    const dt = clampNumber(motions[index]?.dt ?? 1, 0.5, 6);
    const maxRise = 150 * dt + 60;
    const maxFall = 210 * dt + 80;
    const limitedTarget = previous + clampNumber(target - previous, -maxFall, maxRise);
    const alpha = limitedTarget >= previous ? 0.44 : 0.34;
    previous += (limitedTarget - previous) * alpha;

    if (target === 0 && previous < 24) previous = 0;
    return Math.round(clampNumber(previous, 0, MAX_ESTIMATED_POWER_W));
  });
}

export function buildEstimatedPowerStream(input: EstimatedPowerInput): StreamResponse | null {
  const { rideId, points } = input;
  if (points.length < 2) return null;

  const totalMassKg = STANDARD_RIDER_MASS_KG + STANDARD_BIKE_MASS_KG;
  const motions = buildMotionSeries(input);
  const rawValues = motions.map((motion) => estimateRawPower(motion, totalMassKg));
  const values = smoothPowerLine(rawValues, motions);
  const usableValues = values.filter((value) => Number.isFinite(value));
  if (usableValues.length <= 1 || usableValues.every((value) => value === 0)) return null;

  return {
    id: null,
    rideId: rideId ?? '',
    streamType: 'estimated_power',
    timestamps: motions.map((motion) => motion.timestamp),
    values,
    sampleCount: values.length,
    minValue: Math.min(...usableValues),
    maxValue: Math.max(...usableValues),
    avgValue: usableValues.reduce((sum, value) => sum + value, 0) / usableValues.length,
  };
}
