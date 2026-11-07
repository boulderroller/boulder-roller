import { useEffect, useMemo, useRef, useState } from 'react';
import { formatDate, formatFixed, formatInteger, formatMonth, formatMonthYear, formatWeekday } from '../../lib/formatters';

export interface LoadDay {
  /** The day (local midnight). */
  date: Date;
  value: number | null;
}

export interface LoadFigureProps {
  /** One entry per day of the window, oldest first; a day without a ride carries 0. */
  days: LoadDay[];
  /** Readout and endpoint label. */
  formatValue: (value: number) => string;
  /** Y-axis tick label. */
  formatTick: (value: number) => string;
  height?: number;
  ariaLabel: string;
}

// Paper-grade figure in the ledger: one bar per day, ink for the current week
// and soft for the rest, gridlines recessive, month ticks (week ticks under a
// month), today's value the one labelled endpoint. Cobalt only on the scrub,
// which reads the day out in full. The y axis picks its own top per window.
const INK = 'var(--portal-public-ink, #F1EEE8)';
const SOFT = 'var(--portal-public-ink-soft, #9A9488)';
const MUTED = SOFT;
const FAINT = 'var(--portal-public-line, #4E4B46)';
const SHEET = 'var(--portal-public-paper-soft, #1B1A17)';
const COBALT = 'var(--portal-chrome-accent, #5592E2)';
const MARGIN = { top: 24, right: 16, bottom: 26, left: 60 };
const STEPS = [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000];

function niceScale(max: number): { top: number; step: number } {
  const target = Math.max(max, 1);
  for (const step of STEPS) {
    const ticks = Math.ceil(target / step);
    if (ticks <= 4) return { top: ticks * step, step };
  }
  const step = STEPS[STEPS.length - 1];
  return { top: Math.ceil(target / step) * step, step };
}

export default function LoadFigure({ days, formatValue, formatTick, height = 200, ariaLabel }: LoadFigureProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [scrubX, setScrubX] = useState<number | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const observer = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const model = useMemo(() => {
    const n = days.length;
    if (n === 0 || width < 200) return null;
    const plotW = width - MARGIN.left - MARGIN.right;
    const plotH = height - MARGIN.top - MARGIN.bottom;
    const max = days.reduce((best, day) => Math.max(best, day.value ?? 0), 0);
    const { top, step } = niceScale(max);
    const y = (v: number) => MARGIN.top + plotH - (v / top) * plotH;
    const barW = plotW / n;
    const x = (index: number) => MARGIN.left + index * barW;
    const gridlines: number[] = [];
    for (let v = 0; v <= top; v += step) gridlines.push(v);

    const bars = days
      .map((day, index) => ({ day, index }))
      .filter(({ day }) => day.value !== null && day.value > 0)
      .map(({ day, index }) => ({
        key: day.date.getTime(),
        x: x(index) + 0.4,
        y: y(day.value!),
        w: Math.max(1.2, barW - 0.8),
        h: MARGIN.top + plotH - y(day.value!),
        current: index >= n - 7,
      }));

    const ticks: Array<{ x: number; label: string }> = [];
    days.forEach((day, index) => {
      const date = day.date;
      if (n <= 35) {
        if (date.getDay() === 1) ticks.push({ x: x(index), label: `${formatMonth(date)} ${formatInteger(date.getDate())}` });
      } else if (date.getDate() === 1 && (n <= 200 || date.getMonth() % 2 === 0)) {
        ticks.push({ x: x(index), label: n <= 200 ? formatMonth(date) : formatMonthYear(date) });
      }
    });

    // A month label must fit without colliding with its neighbour on a phone.
    // Keep the data window intact; reduce only the displayed axis labels.
    let lastTickRight = -Infinity;
    const readableTicks = ticks.filter((tick) => {
      const halfWidth = tick.label.length * 3.6; // 12px mono labels.
      if (tick.x - halfWidth < 0 || tick.x + halfWidth > width || tick.x - halfWidth < lastTickRight + 12) return false;
      lastTickRight = tick.x + halfWidth;
      return true;
    });

    const last = days[n - 1];
    const endpoint = last.value !== null && last.value > 0 ? { x: x(n - 1) + barW / 2, y: y(last.value), label: formatValue(last.value) } : null;

    const scrub = (() => {
      if (scrubX == null) return null;
      const index = Math.min(n - 1, Math.max(0, Math.floor((scrubX - MARGIN.left) / barW)));
      const day = days[index];
      if (day.value === null) return null;
      const cx = x(index) + barW / 2;
      const date = day.date;
      return {
        x: cx,
        y: y(day.value!),
        flip: cx > MARGIN.left + plotW * 0.7,
        date: `${formatWeekday(date)} ${formatDate(date)}`,
        value: formatValue(day.value),
      };
    })();

    return { plotW, plotH, y, gridlines, bars, ticks: readableTicks, endpoint, scrub, baselineY: MARGIN.top + plotH };
  }, [days, formatValue, height, scrubX, width]);

  if (!model) {
    return <div ref={ref} style={{ width: '100%' }} />;
  }

  return (
    <div ref={ref} style={{ width: '100%' }}>
      <svg
        viewBox={`0 0 ${formatFixed(width, 0)} ${formatFixed(height, 0)}`}
        width={width}
        height={height}
        role="img"
        aria-label={ariaLabel}
        style={{ display: 'block', fontFamily: 'var(--br-font-mono, ui-monospace, monospace)' }}
        onPointerMove={(e) => setScrubX(e.clientX - e.currentTarget.getBoundingClientRect().left)}
        onPointerLeave={() => setScrubX(null)}
      >
        {model.gridlines.map((v) => (
          <g key={v}>
            <line x1={MARGIN.left} x2={MARGIN.left + model.plotW} y1={model.y(v)} y2={model.y(v)} stroke={FAINT} strokeOpacity="0.45" strokeWidth="1" />
            <text x={MARGIN.left - 8} y={model.y(v) + 3.5} fontSize="12" textAnchor="end" fill={MUTED}>{formatTick(v)}</text>
          </g>
        ))}
        <line x1={MARGIN.left} x2={MARGIN.left + model.plotW} y1={model.baselineY} y2={model.baselineY} stroke={FAINT} strokeWidth="1" />
        {model.bars.map((bar) => (
          <rect key={bar.key} x={bar.x} y={bar.y} width={bar.w} height={bar.h} fill={bar.current ? INK : SOFT} />
        ))}
        {model.ticks.map((tick) => (
          <g key={`${tick.label}-${formatFixed(tick.x, 0)}`}>
            <line x1={tick.x} x2={tick.x} y1={model.baselineY} y2={model.baselineY + 4} stroke={FAINT} strokeWidth="1" />
            <text x={tick.x} y={model.baselineY + 16} fontSize="12" textAnchor="middle" fill={MUTED}>{tick.label}</text>
          </g>
        ))}
        {model.endpoint ? (
          <g>
            <circle cx={model.endpoint.x} cy={model.endpoint.y} r="3" fill={INK} stroke={SHEET} strokeWidth="1.5" />
            <text x={model.endpoint.x - 6} y={model.endpoint.y - 6} fontSize="12" fontWeight="600" textAnchor="end" fill={INK}>{model.endpoint.label}</text>
          </g>
        ) : null}
        {model.scrub ? (
          <g pointerEvents="none">
            <line x1={model.scrub.x} x2={model.scrub.x} y1={MARGIN.top - 6} y2={model.baselineY} stroke={COBALT} strokeWidth="1" />
            <circle cx={model.scrub.x} cy={model.scrub.y} r="3.5" fill={COBALT} stroke={SHEET} strokeWidth="1.5" />
            <text
              x={model.scrub.flip ? model.scrub.x - 8 : model.scrub.x + 8}
              y={MARGIN.top - 8}
              fontSize="12"
              textAnchor={model.scrub.flip ? 'end' : 'start'}
              fill={INK}
            >
              <tspan fill={MUTED}>{model.scrub.date}</tspan>
              <tspan fontWeight="600" dx="6">{model.scrub.value}</tspan>
            </text>
          </g>
        ) : null}
      </svg>
    </div>
  );
}
