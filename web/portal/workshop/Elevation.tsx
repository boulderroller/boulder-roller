import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { pathFor, nearest, type RideSample } from '../src/components/ride/rideRoomModel';
import { distanceLabel, integer, type Scenario } from './scenario';

export function Elevation({ scenario, selected, scrub, onScrub, onSelect, detail = false, revision = true, v2 = false, overview = false }: {
  scenario: Scenario; selected: string | null; scrub: number | null; detail?: boolean; revision?: boolean; v2?: boolean; overview?: boolean;
  onScrub: (i: number | null) => void; onSelect: (id: string) => void;
}) {
  const id = useId(), host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1000);
  useEffect(() => { const element = host.current; if (!element) return; const observer = new ResizeObserver(() => setWidth(element.clientWidth)); observer.observe(element); return () => observer.disconnect(); }, []);
  const all = scenario.ride.samples;
  const selectedClimb = scenario.climbs.find(c => c.id === selected);
  const points = useMemo(() => all.map((p, index) => ({ ...p, index })).filter(p => !detail || !selectedClimb || p.t >= selectedClimb.start && p.t <= selectedClimb.end), [all, selectedClimb, detail]);
  const elevations = points.flatMap(p => p.elevation === null ? [] : [p.elevation]);
  const min = elevations.length ? Math.floor(Math.min(...elevations) / 10) * 10 : 0;
  const max = elevations.length ? Math.max(min + 20, Math.ceil(Math.max(...elevations) / 10) * 10) : 20;
  const start = points[0].d, distance = points.at(-1)!.d - start || 1;
  const height = v2 ? overview ? 96 : detail ? width <= 440 ? 144 : 172 : width <= 440 ? 116 : 128 : detail ? 172 : 116;
  const left = 38, right = 18, top = 15, bottom = height - 23;
  const x = (p: { d: number }) => left + (p.d - start) / distance * (width - left - right);
  const y = (v: number) => bottom - (v - min) / (max - min) * (bottom - top);
  const paths = useMemo(() => {
    const runs: (typeof points)[] = []; let run: typeof points = [];
    for (const point of points) {
      if (point.elevation === null || (run.length && point.t - run.at(-1)!.t > 30)) { if (run.length) runs.push(run); run = []; }
      if (point.elevation !== null) run.push(point);
    }
    if (run.length) runs.push(run);
    return runs.map(run => { const line = pathFor(run as unknown as RideSample[], p => p.elevation, x, y, 1500); return { line, area: `${line}L${x(run.at(-1)!)},${bottom}L${x(run[0])},${bottom}Z` }; });
  }, [points, height, width]);
  const candidate = scrub === null ? null : all[scrub];
  const hovered = candidate && candidate.d >= start && candidate.d <= start + distance && (!detail || !selectedClimb || candidate.t >= selectedClimb.start && candidate.t <= selectedClimb.end) ? candidate : null;
  const update = (clientX: number) => {
    const rect = host.current!.getBoundingClientRect();
    const at = Math.max(0, Math.min(1, (clientX - rect.left - left / width * rect.width) / (rect.width * (width - left - right) / width)));
    const local = nearest(points, start + at * distance, p => p.d);
    onScrub(points[local].index);
    return points[local];
  };
  if (!elevations.length) return null;
  return <div className={`elevation ${detail ? 'elevation-detail' : ''}`}>
    <div className="profile-heading"><span>{detail ? 'Climb elevation' : 'Ride elevation'}</span><span className="inspection-readout">{hovered ? `${distanceLabel(detail ? hovered.d - start : hovered.d)} km${hovered.elevation !== null ? ` · ${integer(hovered.elevation)} m` : ''}` : `${integer(min)}–${integer(max)} m`}</span></div>
    <div ref={host} className="profile-interaction" role="slider" tabIndex={0} aria-label={detail ? 'Inspect climb elevation' : 'Inspect ride elevation'} aria-valuemin={0} aria-valuemax={Math.round(distance)} aria-valuenow={Math.round(hovered ? Math.max(0, hovered.d - start) : 0)} aria-valuetext={hovered ? `${distanceLabel(detail ? hovered.d - start : hovered.d)} kilometers${hovered.elevation !== null ? `, ${integer(hovered.elevation)} meters elevation` : ''}` : 'Use arrow keys to inspect the route; Enter opens the climb at this point.'}
      onPointerMove={e => update(e.clientX)} onPointerLeave={() => onScrub(null)}
      onClick={e => { const p = update(e.clientX); const climb = scenario.climbs.find(c => p.t >= c.start && p.t <= c.end); if (climb) onSelect(climb.id); }}
      onKeyDown={e => {
        const step = Math.max(1, Math.floor(points.length / 100));
        const local = hovered ? nearest(points, hovered.d, p => p.d) : 0;
        let index: number | undefined;
        if (e.key === 'ArrowRight') index = Math.min(points.length - 1, local + step);
        if (e.key === 'ArrowLeft') index = Math.max(0, local - step);
        if (e.key === 'Home') index = 0;
        if (e.key === 'End') index = points.length - 1;
        if (index !== undefined) { e.preventDefault(); onScrub(points[index].index); }
        if (e.key === 'Enter' && hovered) { const climb = scenario.climbs.find(c => hovered.t >= c.start && hovered.t <= c.end); if (climb) onSelect(climb.id); }
      }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={v2 ? { height } : undefined} preserveAspectRatio="none" aria-hidden="true">
        <defs><clipPath id={id}><path d={paths.map(p => p.area).join(' ')} /></clipPath></defs>
        {[min, max].map(v => <g key={v}><line x1={left} x2={width - right} y1={y(v)} y2={y(v)} className="profile-grid" /><text x={left - 8} y={y(v) + 3} textAnchor="end">{v}</text></g>)}
        <path d={paths.map(p => p.area).join(' ')} className="profile-land" />
        <path d={paths.map(p => p.line).join(' ')} className="profile-line" />
        {scenario.climbs.filter(c => !detail || c.id === selected).map(c => {
          const a = all.find(p => p.t === c.start)!, b = all.find(p => p.t === c.end)!;
          const tone = selected === null || !revision ? 'profile-climb' : selected === c.id ? 'profile-climb selected' : 'profile-climb quiet';
          if (!revision && selected === c.id) return <g key={c.id}><rect x={x(a)} y={top} width={Math.max(2, x(b) - x(a))} height={bottom - top} clipPath={`url(#${id})`} className="profile-climb selected" />{!detail && <line x1={x(a)} x2={x(a)} y1={bottom + 3} y2={bottom + 7} className="profile-climb-tick" />}</g>;
          if (!revision) return <g key={c.id}><rect x={x(a)} y={top} width={Math.max(2, x(b) - x(a))} height={bottom - top} clipPath={`url(#${id})`} className="profile-climb" />{!detail && <line x1={x(a)} x2={x(a)} y1={bottom + 3} y2={bottom + 7} className="profile-climb-tick" />}</g>;
          return <g key={c.id}><rect x={x(a)} y={top} width={Math.max(2, x(b) - x(a))} height={bottom - top} clipPath={`url(#${id})`} className={tone} /><line x1={x(a)} x2={x(a)} y1={bottom + 3} y2={bottom + 7} className={selected !== null && selected !== c.id ? 'profile-climb-tick quiet' : 'profile-climb-tick'} /></g>;
        })}
        {[0, .25, .5, .75, 1].map(f => <text key={f} x={left + f * (width - left - right)} y={height - 3} textAnchor={f === 0 ? 'start' : f === 1 ? 'end' : 'middle'}>{distanceLabel(distance * f)}{f === 1 ? ' km' : ''}</text>)}
        {hovered && hovered.d >= start && hovered.d <= start + distance && <g><line x1={x(hovered)} x2={x(hovered)} y1={top} y2={bottom} className="profile-cursor" />{hovered.elevation !== null && <circle cx={x(hovered)} cy={y(hovered.elevation)} r="4" className="profile-dot" />}</g>}
      </svg>
    </div>
  </div>;
}
