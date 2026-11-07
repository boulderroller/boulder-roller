import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import { timeLabel, type Climb } from './scenario';
import { CHANNELS, channelSummary, channelValue, nearestIndex, normalizeRange, thinRun, traceRuns, type AnalysisSample, type Axis, type Channel, type SampleRange } from './v3Model';

export function V3Charts({ points, domainPoints = points, channels, axis = 'distance', scrub, onScrub, onRange, onRangePreview, highlight, climbs = [], onClimb, pending = false, height = 76, overview = false }: {
  points: AnalysisSample[]; domainPoints?: AnalysisSample[]; channels: Channel[]; axis?: Axis;
  scrub: number | null; onScrub: (index: number | null) => void;
  onRange?: (range: SampleRange) => void; onRangePreview?: (range: SampleRange | null) => void;
  highlight?: SampleRange | null; climbs?: Climb[]; onClimb?: (id: string) => void;
  pending?: boolean; height?: number; overview?: boolean;
}) {
  const [plot, setPlot] = useState<HTMLDivElement | null>(null), [width, setWidth] = useState(800);
  const drag = useRef<{ x: number; index: number; moved: boolean } | null>(null), [brush, setBrush] = useState<SampleRange | null>(null);
  useEffect(() => { if (!plot) return; const observer = new ResizeObserver(entries => setWidth(Math.max(1, entries[0].contentRect.width))); observer.observe(plot); return () => observer.disconnect(); }, [plot]);
  const visible = useMemo(() => channels.filter(key => points.some(p => p[key] != null)), [channels.join(','), points]);
  const first = points[0], last = points.at(-1)!, key = axis === 'time' ? 't' : 'd';
  const start = first[key], extent = Math.max(last[key] - start, .001), pad = 8, bottom = height - 8, top = 13;
  const x = (p: AnalysisSample) => pad + (p[key] - start) / extent * (width - pad * 2);
  const inspected = scrub === null ? null : points.find(p => p.index === scrub) ?? null;
  const models = useMemo(() => visible.map(channel => {
    const stats = channelSummary(points, channel), domain = channelSummary(domainPoints, channel);
    const low = channel === 'heartRate' || channel === 'elevation' ? Math.floor((domain.min ?? 0) / 10) * 10 : channel === 'grade' ? Math.min(0, Math.floor(domain.min ?? 0)) : 0;
    const high = Math.max(low + (channel === 'elevation' ? 20 : 1), domain.max ?? 1);
    return { channel, stats, low, high, runs: traceRuns(points, channel).map(run => thinRun(run, channel, Math.max(120, Math.floor(width)))) };
  }), [points, domainPoints, visible.join(','), width]);
  const locate = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect(), ratio = Math.max(0, Math.min(1, ((event.clientX - rect.left) / rect.width * width - pad) / (width - pad * 2)));
    return points[nearestIndex(points, start + ratio * extent, axis)];
  };
  const pointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0 || pending) return;
    const point = locate(event); onScrub(point.index);
    drag.current = { x: event.clientX, index: point.index, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const pointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (pending) return;
    const point = locate(event); onScrub(point.index);
    if (onRange && drag.current && Math.abs(event.clientX - drag.current.x) > 6) {
      drag.current.moved = true;
      const range = normalizeRange(Math.max(last.index + 1, point.index + 1), drag.current.index, point.index);
      setBrush(range); onRangePreview?.(range);
    }
  };
  const pointerUp = (event: PointerEvent<SVGSVGElement>) => {
    const gesture = drag.current; drag.current = null;
    if (gesture?.moved && onRange) onRange(normalizeRange(last.index + 1, gesture.index, locate(event).index));
    else if (gesture && onClimb) { const p = locate(event), climb = climbs.find(c => p.t >= c.start && p.t <= c.end); if (climb) onClimb(climb.id); }
    setBrush(null); onRangePreview?.(null);
  };
  const activeRange = brush ?? highlight;
  const rangeStart = activeRange ? points.find(p => p.index === activeRange.startIndex) : undefined;
  const rangeEnd = activeRange ? points.find(p => p.index === activeRange.endIndex) : undefined;
  if (!visible.length) return <p className="v3-no-measurements">No measurements in this stretch.</p>;
  return <div className={`v3-charts ${overview ? 'v3-context-chart' : ''}`} data-pending={pending || undefined} aria-busy={pending}>
    {models.map(({ channel, stats, low, high, runs }, rowIndex) => {
      const config = CHANNELS[channel], y = (value: number) => bottom - (value - low) / (high - low) * (bottom - top);
      const actual = inspected?.[channel], value = inspected ? actual : stats.average;
      return <div className="v3-chart-row" key={channel} style={{ '--chart-color': config.color } as CSSProperties}>
        <div className="v3-chart-label"><strong>{config.label}</strong><span>{channel === 'grade' ? '100 m window' : `Avg ${pending ? '—' : channelValue(stats.average, channel)}${overview ? ` ${config.unit}` : ''}`}</span>{!overview && channel !== 'grade' && <span>Max {pending ? '—' : channelValue(stats.max, channel)}</span>}</div>
        <div className="v3-plot" ref={rowIndex === 0 ? setPlot : undefined}>
          <svg viewBox={`0 0 ${width} ${height}`} height={height} width="100%" role="slider" tabIndex={pending ? -1 : 0} aria-label={`Inspect ${config.label.toLowerCase()}`} aria-valuemin={first.index} aria-valuemax={last.index} aria-valuenow={inspected?.index ?? first.index} aria-valuetext={inspected ? `${(inspected.d / 1000).toFixed(2)} km, ${timeLabel(inspected.t)}, ${channelValue(actual, channel)} ${config.unit}` : 'Use arrow keys to inspect the measurements'}
            onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={() => { drag.current = null; setBrush(null); onRangePreview?.(null); }}
            onKeyDown={event => {
              if (pending || !['ArrowLeft', 'ArrowRight', 'Home', 'End', 'Escape'].includes(event.key)) return;
              event.preventDefault();
              if (event.key === 'Escape') { onScrub(null); return; }
              const index = inspected ? points.findIndex(p => p.index === inspected.index) : 0;
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1 : Math.max(0, Math.min(points.length - 1, index + (event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 10 : 1)));
              onScrub(points[next].index);
            }}>
            {[0, .5, 1].map(fraction => <line key={fraction} x1={pad} x2={width - pad} y1={top + (bottom - top) * fraction} y2={top + (bottom - top) * fraction} className="v3-chart-grid" />)}
            {climbs.map(climb => {
              const a = points.find(p => p.t === climb.start), b = points.find(p => p.t === climb.end);
              return a && b ? <rect key={climb.id} x={x(a)} width={Math.max(1, x(b) - x(a))} y={top} height={bottom - top} className="v3-chart-climb" /> : null;
            })}
            {!pending && runs.map((run, i) => {
              const path = run.map((p, j) => `${j ? 'L' : 'M'}${x(p).toFixed(2)},${y(p[channel]!).toFixed(2)}`).join('');
              return <g key={i}>{run.length > 1 && channel === 'elevation' && <path className="v3-chart-area" d={`${path}L${x(run.at(-1)!).toFixed(2)},${bottom}L${x(run[0]).toFixed(2)},${bottom}Z`} />}<path className="v3-chart-line" d={path} />{run.length === 1 && <circle cx={x(run[0])} cy={y(run[0][channel]!)} r={1.3} fill={config.color} />}</g>;
            })}
            {!pending && stats.average !== null && channel !== 'elevation' && <line x1={pad} x2={width - pad} y1={y(stats.average)} y2={y(stats.average)} className="v3-chart-average" />}
            {rangeStart && rangeEnd && <rect x={x(rangeStart)} width={Math.max(1, x(rangeEnd) - x(rangeStart))} y={top} height={bottom - top} className="v3-chart-selection" />}
            {inspected && !pending && <><line x1={x(inspected)} x2={x(inspected)} y1={top} y2={bottom} className="v3-chart-cursor" />{actual != null && <circle cx={x(inspected)} cy={y(actual)} r={3} fill={config.color} stroke="#fff" strokeWidth={1.5} />}</>}
            <text x={pad + 2} y={10} className="v3-chart-bound">{channelValue(high, channel)}</text>
            <text x={pad + 2} y={bottom - 3} className="v3-chart-bound">{channelValue(low, channel)}</text>
          </svg>
        </div>
        <div className="v3-chart-readout"><strong>{pending ? '—' : channelValue(value, channel)}</strong><span>{config.unit}</span></div>
      </div>;
    })}
    <div className="v3-chart-axis"><span>{axis === 'distance' ? 'Distance' : 'Elapsed time'}</span><svg viewBox={`0 0 ${width} 23`} height={23} width="100%" aria-hidden="true">{[0, .25, .5, .75, 1].map((fraction, i) => <text key={i} x={pad + fraction * (width - pad * 2)} y={15} textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}>{axis === 'time' ? timeLabel(start + extent * fraction) : `${((start + extent * fraction) / 1000).toFixed(extent < 3000 ? 2 : 1)}`}</text>)}</svg><span>{axis === 'distance' ? 'km' : ''}</span></div>
  </div>;
}
