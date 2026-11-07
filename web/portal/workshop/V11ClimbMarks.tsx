import { useEffect, useMemo, useRef, useState } from 'react';
import type { Scenario } from './scenario';
import { rangeForClimb, type AnalysisSample, type Axis } from './v3Model';

export function V11ClimbMarks({ scenario, samples, axis, selected, onSelect }: { scenario: Scenario; samples: AnalysisSample[]; axis: Axis; selected: string | null; onSelect: (id: string) => void }) {
  const host = useRef<HTMLDivElement>(null), [width, setWidth] = useState(600);
  useEffect(() => { if (!host.current) return; const observer = new ResizeObserver(([entry]) => setWidth(Math.max(20, entry.contentRect.width - 20))); observer.observe(host.current); return () => observer.disconnect(); }, []);
  const marks = useMemo(() => {
    const key = axis === 'time' ? 't' : 'd', origin = samples[0][key], extent = Math.max(.001, samples.at(-1)![key] - origin);
    const ends: number[] = [];
    return scenario.climbs.map((climb, index) => {
      const range = rangeForClimb(samples, climb)!;
      const start = (samples[range.startIndex][key] - origin) / extent * width, end = (samples[range.endIndex][key] - origin) / extent * width;
      return { climb, number: index + 1, start, end };
    }).sort((a,b) => a.start - b.start || a.number - b.number).map(mark => {
      const targetWidth = Math.max(28, mark.end - mark.start), left = Math.max(0, Math.min(width - targetWidth, (mark.start + mark.end - targetWidth) / 2));
      let lane = ends.findIndex(end => end + 4 <= left); if (lane < 0) lane = ends.length;
      ends[lane] = left + targetWidth;
      return { ...mark, left, targetWidth, lane };
    });
  }, [scenario, samples, axis, width]);
  if (!marks.length) return null;
  return <div className="v11-climb-track" aria-label="Climbs along the ride"><span>Climbs</span><div ref={host} className="v11-climb-track-plot" style={{ height: (Math.max(...marks.map(m => m.lane)) + 1) * 28 + 8 }}>
    {marks.map(m => <button key={m.climb.id} className="v11-climb-mark" style={{ left: m.left + 10, top: m.lane * 28 + 4, width: m.targetWidth }} aria-label={`${selected === m.climb.id ? 'Return to whole ride from' : 'Analyze'} ${m.climb.name}`} aria-pressed={selected === m.climb.id} onClick={() => onSelect(m.climb.id)}>
      <i aria-hidden="true" style={{ left: m.start - m.left, width: Math.max(2, m.end - m.start) }}/><span className="v11-climb-tooltip">{m.climb.name}</span>
    </button>)}
  </div><span/></div>;
}
