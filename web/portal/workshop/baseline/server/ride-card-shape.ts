import type { RidePresentation, RideMetricBasis } from '../src/lib/api';
import { formatDistance, formatElevation, formatDuration } from '../src/lib/formatters';

// Shared read mapping only. Legacy endpoints retain their permitted totals but
// never acquire a made-up revision, basis, or viewer identity.
export function ridePresentationFacts(ride: {
  id?: string; presentation?: RidePresentation | null;
  distanceM?: number | null; elevationM?: number | null; durationS?: number | null;
}, id: string, viewerProjection: string) {
  const candidate = ride.presentation;
  const basis: RideMetricBasis | undefined = candidate?.metricBasis;
  const presentation = candidate?.id === id && candidate.revision?.trim()
    && basis?.key?.trim() && basis.viewerProjection === viewerProjection
    ? candidate : null;
  const source = ride.id && ride.id !== id ? null : candidate ? presentation : ride;
  return {
    presentation,
    distanceM: finite(source?.distanceM) ? source.distanceM : null,
    elevationM: finite(source?.elevationM) ? source.elevationM : null,
    durationS: finite(source?.durationS) ? source.durationS : null,
  };
}
export function formatRidePresentation(facts: { distanceM: number | null; elevationM: number | null; durationS: number | null },
  format = { distance: (v: number) => formatDistance(v, 'metric'), elevation: (v: number) => formatElevation(v, 'metric'), duration: formatDuration },
) {
  return {
    distance: facts.distanceM === null ? '' : format.distance(facts.distanceM),
    elevation: facts.elevationM === null ? '' : format.elevation(facts.elevationM),
    time: facts.durationS === null ? '' : facts.durationS === 0 ? '0:00' : format.duration(facts.durationS),
  };
}

// Consume only the public compact projection. A gap starts a separate path.
type Point = {distance_m:number;elevation_m:number;break_before?:boolean};
type Span = {start_distance_m:number;end_distance_m:number;pattern_id:string};
const finite = (v:unknown): v is number => typeof v === 'number' && Number.isFinite(v);
export function rideCardShape(profile:unknown, spans:unknown) {
  const runs: Point[][] = [];
  let run: Point[] = [];
  for (const p of Array.isArray(profile) ? profile : []) {
    if (!finite(p?.distance_m) || !finite(p?.elevation_m) || p.distance_m < 0) {
      if (run.length > 1) runs.push(run);
      run = [];
      continue;
    }
    if (p.break_before || (run.length && p.distance_m <= run[run.length-1].distance_m)) {
      if (run.length > 1) runs.push(run);
      run = [];
    }
    run.push(p);
  }
  if (run.length > 1) runs.push(run);
  const points = runs.flat();
  if (!points.length) return {lines:[],fills:[],strokes:[],count:null};
  const maxD = Math.max(...points.map(p=>p.distance_m));
  const minE = Math.min(...points.map(p=>p.elevation_m));
  const range = Math.max(1,...points.map(p=>p.elevation_m-minE));
  const x = (p:Point) => 72 + 1056 * p.distance_m / maxD;
  const y = (p:Point) => 426 - (p.elevation_m-minE)/range*190*.9;
  const path = (ps:Point[]) => ps.map((p,i)=>`${i?'L':'M'} ${x(p).toFixed(1)} ${y(p).toFixed(1)}`).join(' ');
  const validSpans: {span:Span;run:Point[]}[] = [];
  for (const span of Array.isArray(spans) ? spans : []) {
    if (!finite(span?.start_distance_m) || !finite(span?.end_distance_m) || span.end_distance_m <= span.start_distance_m || typeof span.pattern_id !== 'string' || !span.pattern_id) continue;
    const run = runs.find(r=>span.start_distance_m>=r[0].distance_m && span.end_distance_m<=r[r.length-1].distance_m);
    if (run) validSpans.push({span,run});
  }
  const interpolate = (run:Point[],distance:number):Point => {
    const right = run.findIndex(p=>p.distance_m>=distance);
    if (right===0) return run[0];
    const a=run[right-1], b=run[right];
    return {distance_m:distance,elevation_m:a.elevation_m+(b.elevation_m-a.elevation_m)*(distance-a.distance_m)/(b.distance_m-a.distance_m)};
  };
  return {
    lines:runs.map(path),
    fills:runs.map(r=>`M ${x(r[0]).toFixed(1)} 426 ${path(r).replace(/^M /,'L ')} L ${x(r[r.length-1]).toFixed(1)} 426 Z`),
    strokes:validSpans.map(({run,span:s})=>path([interpolate(run,s.start_distance_m),...run.filter(p=>p.distance_m>s.start_distance_m&&p.distance_m<s.end_distance_m),interpolate(run,s.end_distance_m)])),
    count:Array.isArray(spans) ? validSpans.length : null,
  };
}
