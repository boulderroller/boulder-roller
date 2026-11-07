import { traceRuns, type AnalysisSample, type Axis, type Channel } from './v3Model';

export type DisplayPoint = { position: number; value: number; min: number; max: number };
/** Display only. All axes, summaries and cursor readings continue to use the original samples. */
export function displayTraces(points: AnalysisSample[], channel: Channel, axis: Axis, width: number) {
  const key = axis === 'time' ? 't' : 'd', bins = Math.max(1, Math.floor(width / 2));
  const raw = traceRuns(points, channel), origin = points[0][key], extent = Math.max(.001, points.at(-1)![key] - origin);
  const averaged = points.length > bins * 1.2;
  if (!averaged) return { averaged, runs: raw.map(run => run.map(p => ({ position: p[key], value: p[channel]!, min: p[channel]!, max: p[channel]! }))) };
  const coverage: [AnalysisSample, AnalysisSample][][] = []; let active: [AnalysisSample, AnalysisSample][] | null = null;
  for (let i = 0; i + 1 < points.length; i++) {
    const p = points[i], next = points[i + 1], dt = next.t - p.t;
    if (p[channel] == null || dt <= 0 || dt > 30) { active = null; continue; }
    if (!active) { active = []; coverage.push(active); }
    active.push([p,next]);
  }
  const runs = coverage.map(run => {
    const buckets = new Map<number, { weight: number; sum: number; position: number; min: number; max: number }>();
    for (const [p,next] of run) {
      const dt = next.t - p.t, dx = next[key] - p[key];
      if (dt <= 0 || dt > 30) continue;
      const first = Math.min(bins - 1, Math.floor((p[key] - origin) / extent * bins));
      const last = Math.min(bins - 1, Math.floor((next[key] - origin) / extent * bins));
      for (let b = first; b <= last; b++) {
        const left = Math.max(p[key], origin + b / bins * extent), right = Math.min(next[key], origin + (b + 1) / bins * extent);
        const weight = dx > 0 ? Math.max(0, right - left) / dx * dt : dt;
        if (!weight) continue;
        const position = dx > 0 ? (left + right) / 2 : p[key], value = p[channel]!;
        const old = buckets.get(b) ?? { weight: 0, sum: 0, position: 0, min: value, max: value };
        old.weight += weight; old.sum += value * weight; old.position += position * weight;
        old.min = Math.min(old.min, value); old.max = Math.max(old.max, value); buckets.set(b, old);
      }
    }
    return [...buckets.values()].map(b => ({ position: b.position / b.weight, value: b.sum / b.weight, min: b.min, max: b.max }));
  });
  // A recorded isolated reading remains a dot, without assigning it any duration.
  const covered = new Set(coverage.flat().map(([p]) => p.index));
  for (const run of raw) if (run.length === 1 && !covered.has(run[0].index)) { const p = run[0]; runs.push([{position:p[key],value:p[channel]!,min:p[channel]!,max:p[channel]!}]); }
  return { averaged, runs };
}

export type PowerBest = { duration: number; watts: number; start: number; end: number };
type PowerRun = { times: number[]; energy: number[]; watts: number[] };
function powerRuns(points: AnalysisSample[]) {
  const runs: PowerRun[] = []; let run: PowerRun | null = null;
  for (let i = 0; i + 1 < points.length; i++) {
    const p = points[i], next = points[i + 1], dt = next.t - p.t;
    if (p.power == null || dt <= 0 || dt > 30) { run = null; continue; }
    if (!run) { run = { times: [p.t], energy: [0], watts: [] }; runs.push(run); }
    run.times.push(next.t); run.energy.push(run.energy.at(-1)! + p.power * dt); run.watts.push(p.power);
  }
  return runs;
}
function bestWithin(runs: PowerRun[], duration: number): PowerBest | null {
  if (!(duration > 0)) return null;
  let best: PowerBest | null = null;
  const consider = (start: number, energy: number) => {
    const watts = energy / duration;
    if (!best || watts > best.watts || (watts === best.watts && start < best.start)) best = { duration, watts, start, end: start + duration };
  };
  for (const run of runs) {
    const { times, energy, watts } = run, first = times[0], last = times.at(-1)!;
    if (last - first < duration) continue;
    // Both endpoint families are necessary: extrema can occur between recorded timestamps.
    let endIndex = 0;
    for (let i = 0; i < times.length && times[i] + duration <= last; i++) {
      const end = times[i] + duration;
      while (endIndex + 1 < times.length && times[endIndex + 1] <= end) endIndex++;
      consider(times[i], energy[endIndex] + (watts[endIndex] ?? 0) * (end - times[endIndex]) - energy[i]);
    }
    let startIndex = 0;
    for (let i = 0; i < times.length; i++) {
      const start = times[i] - duration;
      if (start < first) continue;
      while (startIndex + 1 < times.length && times[startIndex + 1] <= start) startIndex++;
      consider(start, energy[i] - energy[startIndex] - (watts[startIndex] ?? 0) * (start - times[startIndex]));
    }
  }
  return best;
}
export const bestPower = (points: AnalysisSample[], duration: number) => bestWithin(powerRuns(points), duration);
export function powerCurve(points: AnalysisSample[]) {
  const runs = powerRuns(points), longest = Math.max(0, ...runs.map(r => r.times.at(-1)! - r.times[0]));
  if (longest < 1) return [];
  const maximum = Math.min(3600, longest);
  const durations = [...new Set([1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600, maximum, ...Array.from({ length: 56 }, (_, i) => Math.round(Math.exp(Math.log(maximum) * i / 55)))])].filter(d => d <= maximum).sort((a,b) => a-b);
  return durations.map(d => bestWithin(runs,d)).filter((p): p is PowerBest => p !== null);
}
