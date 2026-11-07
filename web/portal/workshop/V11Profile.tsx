import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { timeLabel } from './scenario';
import { channelSummary, nearestIndex, thinRun, traceRuns, type AnalysisSample, type Axis, type SampleRange } from './v3Model';
import { boundSelection, resizeSelection, translateSelection } from './v11Selection';

type Gesture = { pointerId: number; kind: 'new' | 'move' | 'start' | 'end'; clientX: number; clientY: number; value: number; index: number; original: SampleRange | null; moved: boolean; cancelled: boolean };
export function V11Profile({ samples, subject, selection, draft, axis, cursor, onHover, onDraft, onSelect, onClearSelection }: {
  samples: AnalysisSample[]; subject: SampleRange; selection: SampleRange | null; draft: SampleRange | null; axis: Axis; cursor: number | null;
  onHover: (index: number | null) => void; onDraft: (range: SampleRange | null) => void; onSelect: (range: SampleRange) => void; onClearSelection: () => void;
}) {
  const host = useRef<HTMLDivElement>(null), gesture = useRef<Gesture | null>(null), [width, setWidth] = useState(800), [keyboard, setKeyboard] = useState(false);
  const points = useMemo(() => samples.slice(subject.startIndex, subject.endIndex + 1), [samples, subject.startIndex, subject.endIndex]);
  const key = axis === 'time' ? 't' : 'd', first = points[0], last = points.at(-1)!, extent = Math.max(.001, last[key] - first[key]);
  const stats = useMemo(() => channelSummary(points, 'elevation'), [points]), low = Math.floor((stats.min ?? 0) / 25) * 25, high = Math.max(low + 25, Math.ceil((stats.max ?? 0) / 25) * 25);
  const runs = useMemo(() => traceRuns(points, 'elevation').map(run => thinRun(run, 'elevation', Math.max(120, Math.round(width)))), [points, width]);
  useEffect(() => { if (!host.current) return; const observer = new ResizeObserver(([entry]) => setWidth(Math.max(40, entry.contentRect.width))); observer.observe(host.current); return () => observer.disconnect(); }, []);
  useEffect(() => { gesture.current = null; onDraft(null); }, [subject.startIndex, subject.endIndex, samples]);
  const x = (p: AnalysisSample) => 10 + (p[key] - first[key]) / extent * (width - 20), y = (n: number) => 100 - (n - low) / (high - low) * 82;
  const active = draft ?? selection, a = active ? samples[active.startIndex] : null, b = active ? samples[active.endIndex] : null;
  const inspected = cursor === null ? null : points.find(p => p.index === cursor) ?? null;
  const valueAt = (event: PointerEvent<HTMLElement | SVGElement>) => {
    const rect = host.current!.getBoundingClientRect();
    return first[key] + Math.max(0, Math.min(1, ((event.clientX - rect.left) / rect.width * width - 10) / (width - 20))) * extent;
  };
  const pointAt = (value: number) => points[nearestIndex(points, value, axis)];
  const begin = (event: PointerEvent<HTMLElement | SVGElement>, kind: Gesture['kind']) => {
    if (event.button !== 0 || !event.isPrimary || gesture.current) return;
    event.stopPropagation(); setKeyboard(false);
    const value = valueAt(event);
    gesture.current = { pointerId: event.pointerId, kind, clientX: event.clientX, clientY: event.clientY, value, index: pointAt(value).index, original: selection, moved: false, cancelled: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (gesture.current && event.pointerId !== gesture.current.pointerId) return;
    const value = valueAt(event), point = pointAt(value), g = gesture.current;
    if (!g) { onHover(point.index); return; }
    if (event.pointerType === 'touch' && !g.moved && Math.abs(event.clientY - g.clientY) > Math.abs(event.clientX - g.clientX) + 5) g.cancelled = true;
    if (g.cancelled || Math.abs(event.clientX - g.clientX) < (g.kind === 'new' ? 6 : 2)) return;
    if (!g.moved) onHover(null);
    g.moved = true;
    const next = g.kind === 'new' || !g.original ? boundSelection(subject, g.index, point.index)
      : g.kind === 'move' ? translateSelection(samples, subject, g.original, value - g.value, axis)
      : resizeSelection(subject, g.original, g.kind, point.index);
    onDraft(next); onHover(point.index);
  };
  const end = (event: PointerEvent<HTMLDivElement>) => {
    if (gesture.current && event.pointerId !== gesture.current.pointerId) return;
    const g = gesture.current; gesture.current = null;
    if (g && !g.cancelled) {
      const value = valueAt(event), point = pointAt(value);
      if (g.moved) {
        const next = g.kind === 'new' || !g.original ? boundSelection(subject, g.index, point.index)
          : g.kind === 'move' ? translateSelection(samples, subject, g.original, value - g.value, axis)
          : resizeSelection(subject, g.original, g.kind, point.index);
        onSelect(next);
      } else if (g.original !== null) onClearSelection();
      else if (g.kind === 'new' || g.kind === 'move') onHover(point.index);
    }
    onDraft(null);
  };
  return <div className="v11-profile" data-keyboard={keyboard || undefined}>
    <div className="v11-profile-scale"><strong>Elevation</strong><span>{stats.max === null ? '—' : `${Math.round(high)} m`}</span><span>{stats.min === null ? '—' : `${Math.round(low)} m`}</span></div>
    <div className="v11-profile-plot" ref={host} onPointerMove={move} onPointerUp={end} onPointerCancel={event => { if (gesture.current && event.pointerId !== gesture.current.pointerId) return; gesture.current = null; onDraft(null); onHover(null); }} onPointerLeave={() => { if (!gesture.current) onHover(null); }}>
      <svg viewBox={`0 0 ${width} 127`} width="100%" height={127} role="slider" tabIndex={0} aria-label="Inspect elevation profile" aria-valuemin={first.index} aria-valuemax={last.index} aria-valuenow={inspected?.index ?? first.index} aria-valuetext={inspected ? `${(inspected.d / 1000).toFixed(2)} kilometers, ${timeLabel(inspected.t)}, ${inspected.elevation === null ? 'elevation unavailable' : `${Math.round(inspected.elevation)} meters elevation`}` : 'Drag to select an interval or use arrow keys to inspect'} onPointerDown={e => begin(e, 'new')} onBlur={() => { setKeyboard(false); onHover(null); }}
        onKeyDown={e => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Enter', 'Escape'].includes(e.key)) return;
          e.preventDefault(); setKeyboard(true);
          if (e.key === 'Escape') { const dragging = gesture.current !== null; gesture.current = null; onDraft(null); onHover(null); if (!dragging) onClearSelection(); return; }
          const index = inspected?.index ?? subject.startIndex;
          if (e.key === 'Enter') { onHover(index); return; }
          const next = e.key === 'Home' ? subject.startIndex : e.key === 'End' ? subject.endIndex : Math.max(subject.startIndex, Math.min(subject.endIndex, index + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 10 : 1)));
          onHover(next);
        }}>
        {[18, 59, 100].map(line => <line key={line} x1={10} x2={width - 10} y1={line} y2={line} className="v11-profile-grid" />)}
        {stats.max === null && <text x={width / 2} y={76} textAnchor="middle" className="v11-profile-axis">Elevation unavailable</text>}
        {runs.map((run, i) => {
          const d = run.map((p, j) => `${j ? 'L' : 'M'}${x(p).toFixed(1)},${y(p.elevation!).toFixed(1)}`).join('');
          return <g key={i}>{run.length > 1 && <path d={`${d}L${x(run.at(-1)!).toFixed(1)},100L${x(run[0]).toFixed(1)},100Z`} className="v11-relief" />}<path d={d} className="v11-relief-edge" /></g>;
        })}
        {a && b && <><rect x={10} y={18} width={Math.max(0, x(a) - 10)} height={82} className="v11-profile-outside" /><rect x={x(b)} y={18} width={Math.max(0, width - 10 - x(b))} height={82} className="v11-profile-outside" /><rect x={x(a)} y={18} width={Math.max(1, x(b) - x(a))} height={82} className="v11-profile-brush" onPointerDown={e => begin(e, 'move')} /></>}
        {inspected && <line x1={x(inspected)} x2={x(inspected)} y1={12} y2={100} className="v11-cursor-line" />}
        {[0, .25, .5, .75, 1].map((f, i) => <text key={i} x={10 + (width - 20) * f} y={119} textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'} className="v11-profile-axis">{axis === 'time' ? timeLabel(first[key] + extent * f) : `${((first[key] + extent * f) / 1000).toFixed(extent < 3000 ? 2 : 1)}`}</text>)}
      </svg>
      {a && b && active && (['start', 'end'] as const).map(edge => {
        const p = edge === 'start' ? a : b;
        return <button key={edge} type="button" className={`v11-range-edge v11-handle-${edge}`} style={{ left: `${x(p) / width * 100}%` }} role="slider" aria-label={`Selection ${edge}`} aria-orientation="horizontal" aria-valuemin={edge === 'start' ? subject.startIndex : active.startIndex + 1} aria-valuemax={edge === 'start' ? active.endIndex - 1 : subject.endIndex} aria-valuenow={p.index} aria-valuetext={`${(p.d / 1000).toFixed(2)} kilometers, ${timeLabel(p.t)}`} onPointerDown={e => begin(e, edge)}
          onKeyDown={e => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(e.key)) return;
            e.preventDefault();
            if (e.key === 'Escape') { const dragging = gesture.current !== null; gesture.current = null; onDraft(null); if (!dragging) { host.current?.querySelector('svg')?.focus(); onClearSelection(); } return; }
            const index = e.key === 'Home' ? subject.startIndex : e.key === 'End' ? subject.endIndex : p.index + (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 10 : 1);
            onSelect(resizeSelection(subject, active, edge, index));
          }} />;
      })}
    </div>
    <div className="v11-profile-reading"><span>At cursor</span><strong>{inspected?.elevation == null ? '—' : Math.round(inspected.elevation)}</strong><small>m</small></div>
  </div>;
}
