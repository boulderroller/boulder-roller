import type { AnalysisSample } from './v3Model';

export type PowerBin = { from: number; to: number; seconds: number };
/** A recorded value covers the interval to the next sample, up to 30 seconds. */
function coveredPower(points: AnalysisSample[]) {
  const intervals: { watts: number; seconds: number }[] = [];
  for (let i = 0; i + 1 < points.length; i++) {
    const watts = points[i].power, seconds = points[i + 1].t - points[i].t;
    if (watts !== null && watts !== undefined && Number.isFinite(watts) && watts >= 0 && seconds > 0 && seconds <= 30) intervals.push({ watts, seconds });
  }
  return intervals;
}

export function powerDistribution(points: AnalysisSample[], binWidth = 25): { bins: PowerBin[]; coveredSeconds: number; unavailable?: true } {
  if (!Number.isFinite(binWidth) || binWidth <= 0) throw new Error('Power bin width must be positive.');
  const intervals = coveredPower(points);
  if (!intervals.length) return { bins: [], coveredSeconds: 0 };
  const maximum = intervals.reduce((max, p) => Math.max(max, p.watts), 0);
  const coveredSeconds = intervals.reduce((sum, p) => sum + p.seconds, 0);
  // Keep imported outliers intact, while bounding the display's memory cost.
  const step = Math.max(binWidth, Math.ceil(maximum / 159 / binWidth) * binWidth);
  const count = Math.floor(maximum / step) + 1;
  if (!Number.isFinite(step * count) || count > 160) return { bins: [], coveredSeconds, unavailable: true };
  const bins = Array.from({ length: count }, (_, i) => ({ from: i * step, to: (i + 1) * step, seconds: 0 }));
  for (const p of intervals) bins[Math.floor(p.watts / step)].seconds += p.seconds;
  return { bins, coveredSeconds };
}

export function rideFileStats(points: AnalysisSample[]) {
  const intervals = coveredPower(points);
  const max = (channel: 'power' | 'speed') => points.reduce<number | null>((maximum, p) => p[channel] == null ? maximum : Math.max(maximum ?? 0, p[channel]!), null);
  return {
    maxPower: max('power'), maxSpeed: max('speed'),
    workKj: intervals.length ? intervals.reduce((sum, p) => sum + p.watts * p.seconds, 0) / 1000 : null,
    powerSeconds: intervals.reduce((sum, p) => sum + p.seconds, 0),
  };
}
