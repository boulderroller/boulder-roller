import type { Climb, Sample } from './scenario';

export type Axis = 'distance' | 'time';
export type Channel = 'elevation' | 'power' | 'speed' | 'cadence' | 'heartRate' | 'grade';
export type SampleRange = { startIndex: number; endIndex: number };
export type MapFocus = SampleRange & { kind: 'climb' | 'range' };
export type AnalysisSample = Sample & { index: number; speed: number | null; cadence: number | null; heartRate: number | null; grade: number | null; speedDerived: boolean };

export const CHANNELS: Record<Channel, { label: string; unit: string; color: string; factor: number; decimals: number }> = {
  elevation: { label: 'Elevation', unit: 'm', color: '#768b71', factor: 1, decimals: 0 },
  speed: { label: 'Speed', unit: 'km/h', color: '#447da2', factor: 3.6, decimals: 1 },
  power: { label: 'Power', unit: 'W', color: '#7860aa', factor: 1, decimals: 0 },
  heartRate: { label: 'Heart rate', unit: 'bpm', color: '#b34f68', factor: 1, decimals: 0 },
  cadence: { label: 'Cadence', unit: 'rpm', color: '#34877f', factor: 1, decimals: 0 },
  grade: { label: 'Grade', unit: '%', color: '#a47f39', factor: 1, decimals: 1 },
};

export function normalizeRange(count: number, a: number, b: number): SampleRange {
  const clamp = (n: number) => Math.max(0, Math.min(count - 1, Math.round(n)));
  let startIndex = clamp(Math.min(a, b)), endIndex = clamp(Math.max(a, b));
  if (startIndex === endIndex) { if (endIndex < count - 1) endIndex++; else startIndex = Math.max(0, startIndex - 1); }
  return { startIndex, endIndex };
}

export function rangeForClimb(samples: Sample[], climb: Climb | undefined): SampleRange | null {
  return climb ? { startIndex: samples.findIndex(p => p.t === climb.start), endIndex: samples.findIndex(p => p.t === climb.end) } : null;
}

/** The returned position is local to this array; callers retain each sample's global index. */
export function nearestIndex(samples: Sample[], value: number, axis: Axis): number {
  const key = axis === 'time' ? 't' : 'd';
  let lo = 0, hi = samples.length - 1;
  while (lo < hi) { const mid = Math.floor((lo + hi) / 2); if (samples[mid][key] < value) lo = mid + 1; else hi = mid; }
  return lo > 0 && Math.abs(samples[lo - 1][key] - value) <= Math.abs(samples[lo][key] - value) ? lo - 1 : lo;
}

/** Net rise over a centered 100m window. Short or discontinuous windows abstain. */
function withGrade(samples: AnalysisSample[]): AnalysisSample[] {
  const breaks: number[] = []; let count = 0;
  for (let i = 0; i < samples.length; i++) {
    if (samples[i].elevation === null || (i > 0 && samples[i].t - samples[i - 1].t > 30)) count++;
    breaks.push(count);
  }
  return samples.map(p => {
    const a = nearestIndex(samples, p.d - 50, 'distance'), b = nearestIndex(samples, p.d + 50, 'distance');
    const first = samples[a], last = samples[b], distance = last.d - first.d;
    const valid = p.elevation !== null && first.elevation !== null && last.elevation !== null && distance >= 50 && breaks[b] === breaks[a];
    return { ...p, grade: valid ? (last.elevation! - first.elevation!) / distance * 100 : null };
  });
}

export function analysisSamples(samples: Sample[]): AnalysisSample[] {
  return withGrade(samples.map((p, index) => {
    const next = samples[index + 1], dt = next ? next.t - p.t : 0;
    const fallback = p.speed == null && next && dt > 0 && dt <= 30;
    return { ...p, index, speed: p.speed ?? (fallback ? (next.d - p.d) / dt : null), speedDerived: !!fallback, cadence: p.cadence ?? null, heartRate: p.heartRate ?? null, grade: null };
  }));
}

export function scopedSamples(samples: AnalysisSample[], range: SampleRange | null): AnalysisSample[] {
  if (!range) return samples;
  const scoped = samples.slice(range.startIndex, range.endIndex + 1);
  const last = scoped.at(-1);
  // A forward-derived speed needs the next sample, which is outside this scope.
  if (last?.speedDerived) scoped[scoped.length - 1] = { ...last, speed: null };
  return withGrade(scoped);
}

/** Means include real zeros and exclude intervals over 30s. Elapsed time remains independent. */
export function channelSummary(samples: AnalysisSample[], channel: Channel) {
  let total = 0, coverage = 0, min = Infinity, max = -Infinity;
  samples.forEach((p, i) => {
    const value = p[channel];
    if (value == null) return;
    min = Math.min(min, value); max = Math.max(max, value);
    const dt = samples[i + 1] ? samples[i + 1].t - p.t : 0;
    if (dt > 0 && dt <= 30) { total += value * dt; coverage += dt; }
  });
  return { average: coverage ? total / coverage : null, min: min === Infinity ? null : min, max: max === -Infinity ? null : max, coverage };
}

export function traceRuns(samples: AnalysisSample[], channel: Channel): AnalysisSample[][] {
  const runs: AnalysisSample[][] = []; let run: AnalysisSample[] = [];
  for (const p of samples) {
    if (p[channel] == null || (run.length > 0 && p.t - run.at(-1)!.t > 30)) { if (run.length) runs.push(run); run = []; }
    if (p[channel] != null) run.push(p);
  }
  if (run.length) runs.push(run);
  return runs;
}

/** Keep both extrema in each bucket, in their original order, so brief efforts survive. */
export function thinRun(run: AnalysisSample[], channel: Channel, columns = 600): AnalysisSample[] {
  if (run.length <= columns * 2) return run;
  const result = new Set<number>([0, run.length - 1]), size = Math.ceil(run.length / columns);
  for (let start = 0; start < run.length; start += size) {
    let lo = start, hi = start;
    for (let i = start + 1; i < Math.min(run.length, start + size); i++) {
      if (run[i][channel]! < run[lo][channel]!) lo = i;
      if (run[i][channel]! > run[hi][channel]!) hi = i;
    }
    result.add(lo); result.add(hi);
  }
  return [...result].sort((a, b) => a - b).map(i => run[i]);
}

export function channelValue(value: number | null | undefined, channel: Channel): string {
  return value == null ? '—' : (value * CHANNELS[channel].factor).toLocaleString('en-US', { minimumFractionDigits: CHANNELS[channel].decimals, maximumFractionDigits: CHANNELS[channel].decimals });
}
