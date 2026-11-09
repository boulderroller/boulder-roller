import type {
  TraceReductionDescriptor,
  ClimbPattern,
  GpsPoint,
  StreamResponse,
  TelemetryData,
} from '../../lib/api';
import { buildDistanceSeries } from '../../lib/rideTelemetry';
const stripGeneratedClimbNameSuffix = (value: string) =>
  value
    .trim()
    .replace(/\s+\d{10,13}$/, '')
    .trim();

export type RideSample = {
  t: number;
  d: number;
  elevation: number | null;
  power: number | null;
  cadence: number | null;
  speed: number | null;
  heartRate: number | null;
  gps: GpsPoint;
  index: number;
};
export type RideSpan = {
  id: string;
  name: string;
  start: number;
  end: number;
  pattern: ClimbPattern;
};
export type TimedValue = { t: number; v: number };
export const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
export function seconds(value: string | number): number | null {
  if (typeof value === 'number')
    return finite(value) ? (value > 1e11 ? value / 1000 : value) : null;
  const n = Number(value);
  if (value.trim() && finite(n)) return n > 1e11 ? n / 1000 : n;
  const date = Date.parse(value);
  return finite(date) ? date / 1000 : null;
}
export function timedStream(
  stream: StreamResponse | null | undefined,
  origin: number,
): TimedValue[] {
  if (!stream) return [];
  const points: TimedValue[] = [];
  stream.timestamps.forEach((timestamp, index) => {
    const stamp = seconds(timestamp),
      value = stream.values[index];
    if (stamp === null || !finite(value)) return;
    const t = stamp > 1e8 ? stamp - origin : stamp;
    if (t >= 0 && (!points.length || t > points[points.length - 1].t))
      points.push({ t, v: value });
  });
  return points;
}
export function nearest<T>(
  items: T[],
  value: number,
  axis: (item: T) => number,
): number {
  if (!items.length) return 0;
  let lo = 0,
    hi = items.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (axis(items[mid]) < value) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 &&
    Math.abs(axis(items[lo - 1]) - value) < Math.abs(axis(items[lo]) - value)
    ? lo - 1
    : lo;
}
export function ridePageModel(
  gps: GpsPoint[],
  telemetry: TelemetryData,
  patterns: ClimbPattern[],
  startedAt: string,
) {
  const origin = seconds(gps[0]?.timestamp ?? startedAt) ?? 0;
  const streams = Object.fromEntries(
    ['power', 'cadence', 'speed', 'heartRate'].map((key) => [
      key,
      timedStream(telemetry[key as 'power'], origin),
    ]),
  ) as Record<'power' | 'cadence' | 'speed' | 'heartRate', TimedValue[]>;
  const distances = buildDistanceSeries(
    gps.map((p) => (p.redacted ? { ...p, latitude: NaN, longitude: NaN } : p)),
  );
  const samples: RideSample[] = gps
    .map((point, index) => {
      const stamp = seconds(point.timestamp);
      const t = stamp === null ? NaN : stamp > 1e8 ? stamp - origin : stamp;
      const values = Object.fromEntries(
        Object.entries(streams).map(([key, stream]) => {
          const sample = stream[nearest(stream, t, (p) => p.t)];
          return [
            key,
            sample && Math.abs(sample.t - t) <= 10
              ? sample.v * (key === 'speed' ? 3.6 : 1)
              : null,
          ];
        }),
      );
      return {
        t,
        d: distances[index],
        elevation:
          !point.redacted && finite(point.elevationM) ? point.elevationM : null,
        ...values,
        gps: point,
        index,
      } as RideSample;
    })
    .filter((p) => finite(p.t) && finite(p.d));
  const spans: RideSpan[] = patterns.flatMap((pattern) => {
    // Detection alone never paints a counted climb. Canon identity and traversal bounds are required.
    const id = pattern.vaultMatch?.vaultClimbId || pattern.climbId;
    const start =
      pattern.startOffsetS ??
      pattern.startTimeOffsetS ??
      pattern.matchTrace?.detection?.effortBounds?.[0];
    const end =
      pattern.endOffsetS ??
      pattern.endTimeOffsetS ??
      pattern.matchTrace?.detection?.effortBounds?.[1];
    if (!id || !finite(start) || !finite(end) || end <= start) return [];
    const name = stripGeneratedClimbNameSuffix(
      pattern.vaultMatch?.name || pattern.name || pattern.roadName || '',
    );
    return [{ id, name, start, end, pattern }];
  });
  return { samples, spans, streams };
}
export function pathFor(
  samples: RideSample[],
  value: (p: RideSample) => number | null,
  x: (p: RideSample) => number,
  y: (v: number) => number,
  limit = 1800,
): string {
  // Preserve extrema within each pixel bucket, including gaps, rather than dropping narrow peaks.
  const stride = Math.max(1, Math.ceil(samples.length / limit));
  let path = '',
    connected = false;
  for (let i = 0; i < samples.length; i += stride) {
    const bucket = samples.slice(i, i + stride);
    const valid = bucket.filter((p) => finite(value(p)));
    if (!valid.length) {
      connected = false;
      continue;
    }
    const extrema = [
      valid[0],
      valid.reduce((a, b) => (value(a)! < value(b)! ? a : b)),
      valid.reduce((a, b) => (value(a)! > value(b)! ? a : b)),
      valid[valid.length - 1],
    ];
    [...new Set(extrema)]
      .sort((a, b) => a.t - b.t)
      .forEach((p) => {
        path += `${connected ? 'L' : 'M'}${x(p)},${y(value(p)!)} `;
        connected = true;
      });
    if (valid.length !== bucket.length) connected = false;
  }
  return path;
}
/** Board register: 200 m bins over a whole ride, then a five-point mean;
 * a climb retains its recorded resolution with a nine-point mean. Readouts use
 * this same series. Range statistics and power curves always use raw streams. */
export function instrumentSamples(
  samples: RideSample[],
  scoped: boolean,
  source?: TraceReductionDescriptor | null,
): { samples: RideSample[]; descriptor: TraceReductionDescriptor } {
  const fields = ['power', 'cadence', 'speed', 'heartRate'] as const;
  const runs: RideSample[][] = [];
  samples.forEach((p) => {
    if (!runs.length || p.t - runs.at(-1)!.at(-1)!.t > 30) runs.push([]);
    runs.at(-1)!.push(p);
  });
  const reduced = runs.flatMap((run) => {
    let series = run;
    if (!scoped && run.length > 1) {
      const bins = new Map<number, RideSample[]>();
      run.forEach((p) => {
        const key = Math.floor(p.d / 200);
        if (!bins.has(key)) bins.set(key, []);
        bins.get(key)!.push(p);
      });
      series = [...bins.values()].map((bin) => {
        const middle = { ...bin[Math.floor(bin.length / 2)] };
        fields.forEach((field) => {
          const values = bin.map((p) => p[field]).filter(finite);
          middle[field] = values.length
            ? values.reduce((a, b) => a + b, 0) / values.length
            : null;
        });
        return middle;
      });
      series = [
        { ...series[0], d: run[0].d, t: run[0].t, elevation: run[0].elevation },
        ...series,
        {
          ...series.at(-1)!,
          d: run.at(-1)!.d,
          t: run.at(-1)!.t,
          elevation: run.at(-1)!.elevation,
        },
      ];
    }
    const radius = scoped ? 4 : 2;
    return series.map((p, i) => {
      const result = { ...p };
      fields.forEach((field) => {
        if (p[field] === null) return;
        const values = series
          .slice(Math.max(0, i - radius), i + radius + 1)
          .map((s) => s[field])
          .filter(finite);
        result[field] = values.reduce((a, b) => a + b, 0) / values.length;
      });
      return result;
    });
  });
  return {
    samples: reduced,
    descriptor: {
      source: source?.source ?? '',
      method: scoped ? 'moving-mean' : 'distance-bin-mean+moving-mean',
      binDistanceM: scoped ? null : 200,
      smoothingWindowSamples: scoped ? 9 : 5,
      preservesExtrema: false,
    },
  };
}
