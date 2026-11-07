import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import { timeLabel } from './scenario';
import { CHANNELS, channelSummary, channelValue, nearestIndex, type AnalysisSample, type Axis, type Channel, type SampleRange } from './v3Model';
import { displayTraces } from './v11Model';
import { boundSelection } from './v11Selection';

const colors: Record<Channel, string> = { elevation: '#808285', speed: '#184898', power: '#613393', heartRate: '#C22032', cadence: '#007A61', grade: '#997323' };
export function V11Charts({ points, channels, axis, cursor, draft, selected, onHover, onDraft, onSelect, onClearSelection, pending = false, compact = false }: {
  points: AnalysisSample[]; channels: Channel[]; axis: Axis; cursor: number | null; draft: SampleRange | null; selected?: boolean;
  onHover: (index: number | null) => void;
  onDraft?: (range: SampleRange | null) => void; onSelect?: (range: SampleRange) => void; onClearSelection?: () => void; pending?: boolean; compact?: boolean;
}) {
  const [plot, setPlot] = useState<HTMLDivElement | null>(null), [width, setWidth] = useState(800), [keyboard, setKeyboard] = useState<string | null>(null);
  const keyboardStart = useRef<number | null>(null);
  const gesture = useRef<{ pointerId: number; x: number; y: number; index: number; moved: boolean; cancelled: boolean } | null>(null);
  useEffect(() => { if (!plot) return; const observer = new ResizeObserver(([entry]) => setWidth(Math.max(40, entry.contentRect.width))); observer.observe(plot); return () => observer.disconnect(); }, [plot]);
  useEffect(() => { gesture.current = null; }, [points]);
  const first = points[0], last = points.at(-1)!, key = axis === 'time' ? 't' : 'd', extent = Math.max(.001, last[key] - first[key]);
  const subject = { startIndex: first.index, endIndex: last.index };
  const inspected = cursor === null ? null : points.find(p => p.index === cursor) ?? null;
  const models = useMemo(() => channels.filter(c => points.some(p => p[c] !== null)).map(channel => {
    const stats = channelSummary(points, channel), factor = CHANNELS[channel].factor;
    const step = channel === 'power' ? 100 : channel === 'elevation' ? 25 : channel === 'grade' ? 2 : 10;
    const low = channel === 'elevation' || channel === 'heartRate' || channel === 'grade' ? Math.floor((stats.min ?? 0) * factor / step) * step / factor : 0;
    const high = Math.max(low + step / factor, Math.ceil((stats.max ?? 0) * factor / step) * step / factor);
    return { channel, stats, low, high, ...displayTraces(points, channel, axis, width - 20) };
  }), [points, channels.join(','), width, axis]);
  const ticks = width < 420 ? [0, .5, 1] : [0, .25, .5, .75, 1];
  const positionX = (position: number) => 10 + (position - first[key]) / extent * (width - 20);
  const x = (p: AnalysisSample) => positionX(p[key]);
  const locate = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect(), ratio = Math.max(0, Math.min(1, ((event.clientX - rect.left) / rect.width * width - 10) / (width - 20)));
    return points[nearestIndex(points, first[key] + ratio * extent, axis)];
  };
  const down = (event: PointerEvent<SVGSVGElement>) => {
    if (pending || event.button !== 0 || !event.isPrimary || gesture.current) return;
    setKeyboard(null); keyboardStart.current = null; onDraft?.(null); const p = locate(event);
    gesture.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, index: p.index, moved: false, cancelled: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const move = (event: PointerEvent<SVGSVGElement>) => {
    if (pending || (gesture.current && event.pointerId !== gesture.current.pointerId)) return;
    const p = locate(event), g = gesture.current;
    if (g && event.pointerType === 'touch' && !g.moved && Math.abs(event.clientY - g.y) > Math.abs(event.clientX - g.x) + 5) g.cancelled = true;
    if (g?.cancelled) return;
    if (g && onSelect && Math.abs(event.clientX - g.x) > 6) {
      if (!g.moved) onHover(null);
      g.moved = true; onDraft?.(boundSelection(subject, g.index, p.index));
    }
    onHover(p.index);
  };
  const up = (event: PointerEvent<SVGSVGElement>) => {
    if (gesture.current && event.pointerId !== gesture.current.pointerId) return;
    const g = gesture.current; gesture.current = null;
    if (g && !g.cancelled) {
      const p = locate(event);
      if (g.moved && onSelect) onSelect(boundSelection(subject, g.index, p.index));
      else if (selected) onClearSelection?.(); else onHover(p.index);
    }
    onDraft?.(null);
  };
  const brushStart = draft ? points.find(p => p.index === draft.startIndex) : null, brushEnd = draft ? points.find(p => p.index === draft.endIndex) : null;
  if (!models.length) return <div className="v11-no-data">No measurements in this interval.</div>;
  return <div className={`v11-charts ${compact ? 'v11-charts-compact' : ''}`} aria-busy={pending}>
    <div className="v11-chart-ruler"><span>Measurement</span><svg viewBox={`0 0 ${width} 29`} height={29} width="100%" aria-hidden="true">{ticks.map((f, i) => <text key={i} x={10 + (width - 20) * f} y={19} textAnchor={i === 0 ? 'start' : i === ticks.length - 1 ? 'end' : 'middle'}>{axis === 'time' ? timeLabel(first[key] + extent * f) : `${((first[key] + extent * f) / 1000).toFixed(extent < 3000 ? 2 : 1)} km`}</text>)}</svg><span>{cursor !== null && !inspected ? 'Outside interval' : 'At cursor'}</span></div>
    <div className="v11-chart-stack">
    {models.map(({ channel, stats, low, high, runs, averaged }, row) => {
      const height = compact ? 128 : channel === 'power' ? 108 : 90, top = 18, bottom = height - 12;
      const y = (n: number) => bottom - (n - low) / (high - low) * (bottom - top);
      const actual = inspected?.[channel];
      return <div className="v11-trace" data-averaged={averaged || undefined} data-keyboard={keyboard === channel || undefined} key={channel} style={{ '--trace-color': colors[channel] } as CSSProperties}>
        <div className="v11-trace-label"><strong>{CHANNELS[channel].label}</strong><span>Avg <b>{pending ? '—' : channelValue(stats.average, channel)}</b></span><span>Max <b>{pending ? '—' : channelValue(stats.max, channel)}</b></span></div>
        <div className="v11-trace-plot" ref={row === 0 ? setPlot : undefined}>
          <svg role="slider" aria-label={`Inspect ${CHANNELS[channel].label.toLowerCase()}`} aria-valuemin={first.index} aria-valuemax={last.index} aria-valuenow={inspected?.index ?? first.index} aria-valuetext={inspected && !pending ? `${(inspected.d / 1000).toFixed(2)} kilometers, ${timeLabel(inspected.t)}, ${channelValue(actual, channel)} ${CHANNELS[channel].unit}` : 'Arrow keys inspect; Shift and arrows select; Enter applies; Escape returns'} tabIndex={pending ? -1 : 0} viewBox={`0 0 ${width} ${height}`} height={height} width="100%"
            onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={event => { if (gesture.current && event.pointerId !== gesture.current.pointerId) return; gesture.current = null; onDraft?.(null); onHover(null); }} onPointerLeave={() => { if (!gesture.current) onHover(null); }} onBlur={() => { setKeyboard(null); onHover(null); if (!gesture.current) { keyboardStart.current = null; onDraft?.(null); } }}
            onKeyDown={event => {
              if (pending || !['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Enter', 'Escape'].includes(event.key)) return;
              event.preventDefault(); setKeyboard(channel);
              if (event.key === 'Escape') { const dragging = gesture.current !== null || keyboardStart.current !== null; gesture.current = null; keyboardStart.current = null; onDraft?.(null); onHover(null); if (!dragging) onClearSelection?.(); return; }
              const index = inspected ? points.findIndex(p => p.index === inspected.index) : 0;
              if (event.key === 'Enter') { if (keyboardStart.current !== null && draft) { onSelect?.(draft); onDraft?.(null); keyboardStart.current = null; } else onHover(points[index].index); return; }
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1 : Math.max(0, Math.min(points.length - 1, index + (event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 10 : 1)));
              if (event.shiftKey) { keyboardStart.current ??= points[index].index; onDraft?.(boundSelection(subject, keyboardStart.current, points[next].index)); } else { keyboardStart.current = null; onDraft?.(null); }
              onHover(points[next].index);
            }}>
            {[0, .5, 1].map(f => <line key={f} x1={10} x2={width - 10} y1={top + (bottom - top) * f} y2={top + (bottom - top) * f} className="v11-chart-grid" />)}
            {!pending && runs.map((run, i) => {
              const d = run.map((p, j) => `${j ? 'L' : 'M'}${positionX(p.position).toFixed(1)},${y(p.value).toFixed(1)}`).join('');
              return <g className="v11-chart-drawing" key={`${first.index}-${last.index}-${axis}-${i}`}>{channel === 'elevation' && run.length > 1 && <path className="v11-chart-area" d={`${d}L${positionX(run.at(-1)!.position).toFixed(1)},${bottom}L${positionX(run[0].position).toFixed(1)},${bottom}Z`} />}<path className="v11-chart-line" d={d} />{run.length === 1 && <circle cx={positionX(run[0].position)} cy={y(run[0].value)} r={1.5} fill={colors[channel]} />}</g>;
            })}
            {!pending && stats.average !== null && channel !== 'elevation' && <line x1={10} x2={width - 10} y1={y(stats.average)} y2={y(stats.average)} className="v11-chart-mean" />}
            {inspected && !pending && <><line x1={x(inspected)} x2={x(inspected)} y1={0} y2={height} className="v11-cursor-line" />{actual != null && <circle cx={x(inspected)} cy={y(actual)} r={3} fill={colors[channel]} stroke="#fff" strokeWidth={1.5} />}</>}
            <text x={12} y={13} className="v11-chart-bound">{channelValue(high, channel)}</text><text x={12} y={bottom - 3} className="v11-chart-bound">{channelValue(low, channel)}</text>
          </svg>
        </div>
        <div className="v11-trace-value"><strong>{pending || !inspected ? '—' : channelValue(actual, channel)}</strong><span>{CHANNELS[channel].unit}</span></div>
      </div>;
    })}
    {brushStart && brushEnd && <div className="v11-stack-brush" aria-hidden="true" style={{ left: `calc(var(--v11-label, 100px) + ${x(brushStart)}px)`, width: Math.max(1, x(brushEnd) - x(brushStart)) }}/>}
    </div>
  </div>;
}
