import { useEffect, useMemo, useRef, useState } from 'react';
import { formatInteger } from '../../lib/formatters';

export interface RidingDay {
  date: string;
  value: number | null;
  rides: number;
}

export interface ConsistencyHeatmapProps {
  days: RidingDay[];
  endDate: string;
  weeks?: number;
  /** Formats a cell value for the readout (e.g. moving time). */
  formatValue: (value: number) => string;
  /**
   * A calendar window: the grid runs from the week of `startDate` to the week
   * of `endDate` (weeks is then derived), days after `today` stay unpainted.
   */
  startDate?: string;
  today?: string;
  /** `quantile` shades by the rider's own days; `presence` says only whether they rode. */
  read?: 'quantile' | 'presence';
}

// Rhythm as luminance: the sheet for a day off (Tim-ratified 2026-09-01 —
// outlines read as clutter), then card → faint → muted → soft → ink by
// quantile of the rider's own days. Cobalt only on hover.
const RUNGS = ['#2A2825', '#4E4B46', '#6A6660', '#9A9488', '#F1EEE8'];
const SHEET = 'var(--portal-public-paper-soft, #1B1A17)';
const MUTED = 'var(--portal-public-ink-soft, #9A9488)';
const COBALT = 'var(--portal-chrome-accent, #5592E2)';
const MAX_CELL = 12;
const MIN_CELL = 6;
const GAP = 3;
const LEFT = 22;
const TOP = 20;
const RIGHT = 24;
const PRESENCE_RUNG = 3;
const DOW = ['M', '', 'W', '', 'F', '', 'S'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export default function ConsistencyHeatmap({
  days,
  endDate,
  weeks: weeksProp = 26,
  formatValue,
  startDate,
  today,
  read = 'quantile',
}: ConsistencyHeatmapProps) {
  const [hover, setHover] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [boxWidth, setBoxWidth] = useState<number | null>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return undefined;
    const observer = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setBoxWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const model = useMemo(() => {
    const byDate = new Map(days.map((d) => [d.date, d]));
    const end = new Date(`${endDate}T00:00:00Z`);
    const paintedThrough = today ? new Date(`${today}T00:00:00Z`) : end;
    // Grid ends on the week containing endDate; Monday-first columns. A
    // calendar window starts on the week containing startDate instead of
    // counting weeks back from the end.
    const endDow = (end.getUTCDay() + 6) % 7;
    const gridEnd = new Date(end);
    gridEnd.setUTCDate(end.getUTCDate() + (6 - endDow));
    let gridStart: Date;
    let weeks = weeksProp;
    let first: Date | null = null;
    if (startDate) {
      first = new Date(`${startDate}T00:00:00Z`);
      const startDow = (first.getUTCDay() + 6) % 7;
      gridStart = new Date(first);
      gridStart.setUTCDate(first.getUTCDate() - startDow);
      weeks = Math.max(1, Math.round((gridEnd.getTime() - gridStart.getTime()) / 86_400_000 + 1) / 7);
    } else {
      gridStart = new Date(gridEnd);
      gridStart.setUTCDate(gridEnd.getUTCDate() - weeks * 7 + 1);
    }
    // Keep the newest riding weeks in view instead of scrolling from the oldest.
    const capacity = boxWidth ? Math.max(1, Math.floor((boxWidth - LEFT - RIGHT) / (MIN_CELL + GAP))) : weeks;
    if (weeks > capacity) {
      weeks = Math.min(weeks, capacity, boxWidth && boxWidth < 500 ? 26 : capacity);
      const last = paintedThrough < end ? paintedThrough : end;
      gridEnd.setTime(last.getTime());
      gridEnd.setUTCDate(last.getUTCDate() + 6 - (last.getUTCDay() + 6) % 7);
      gridStart = new Date(gridEnd);
      gridStart.setUTCDate(gridEnd.getUTCDate() - weeks * 7 + 1);
    }
    const fitted = boxWidth ? Math.floor((boxWidth - LEFT - RIGHT) / weeks) - GAP : MAX_CELL;
    const cell = Math.max(MIN_CELL, Math.min(MAX_CELL, fitted));
    const values = days.map((d) => d.value).filter((v): v is number => v != null && v > 0).sort((a, b) => a - b);
    const quantile = (q: number) => (values.length ? values[Math.min(values.length - 1, Math.floor(q * values.length))] : 0);
    const cuts = [quantile(0.2), quantile(0.4), quantile(0.6), quantile(0.8)];
    const rung = (v: number) => (v <= 0 ? -1 : read === 'presence' ? PRESENCE_RUNG : cuts.filter((c) => v > c).length);

    const cells: Array<{ x: number; y: number; date: string; day: RidingDay | null; future: boolean; rung: number }> = [];
    const monthLabels: Array<{ x: number; label: string }> = [];
    let lastMonth = -1;
    for (let w = 0; w < weeks; w += 1) {
      for (let d = 0; d < 7; d += 1) {
        const date = new Date(gridStart);
        date.setUTCDate(gridStart.getUTCDate() + w * 7 + d);
        const iso = isoDay(date);
        const day = byDate.get(iso) ?? null;
        const future = date > paintedThrough || date > end || (first !== null && date < first);
        cells.push({ x: LEFT + w * (cell + GAP), y: TOP + d * (cell + GAP), date: iso, day, future, rung: day?.value != null ? rung(day.value) : day?.rides ? 0 : -1 });
        if (d === 0 && date.getUTCMonth() !== lastMonth && (first === null || date >= first || w === 0)) {
          // A calendar window's leading days belong to the year before: no label for them.
          const leading = first !== null && date < first;
          if (!leading) {
            lastMonth = date.getUTCMonth();
            if (w === 0 || date.getUTCDate() <= 7) monthLabels.push({ x: LEFT + w * (cell + GAP), label: MONTHS[lastMonth] });
          }
        }
      }
    }
    const width = LEFT + weeks * (cell + GAP) + RIGHT;
    const height = TOP + 7 * (cell + GAP) + 4;
    const active = days.filter((d) => (d.rides > 0 || (d.value ?? 0) > 0)).length;
    let streak = 0;
    for (let i = 0; ; i += 1) {
      const date = new Date(end);
      date.setUTCDate(end.getUTCDate() - i);
      const day = byDate.get(isoDay(date));
      if (day && (day.rides > 0 || (day.value ?? 0) > 0)) streak += 1;
      else if (i > 0 || !day) break;
      if (i > weeks * 7) break;
    }
    return { cells, monthLabels, width, height, active, streak, cell };
  }, [boxWidth, days, endDate, read, startDate, today, weeksProp]);

  const hovered = hover ? model.cells.find((c) => c.date === hover) : null;
  const selectable = model.cells.filter((cell) => !cell.future);
  const selectedIndex = Math.max(0, hover ? selectable.findIndex((cell) => cell.date === hover) : selectable.length - 1);
  const selected = selectable[selectedIndex];
  const dayText = (cell: typeof selected) => cell ? `${cell.date} · ${cell.day ? cell.day.value == null ? '' : formatValue(cell.day.value) : 'rest'}${cell.day?.rides ? ` · ${formatInteger(cell.day.rides)} ${cell.day.rides === 1 ? 'ride' : 'rides'}` : ''}` : '';
  const selectDay = (index: number) => {
    const cell = selectable[Math.max(0, Math.min(selectable.length - 1, index))];
    if (!cell) return;
    setHover(cell.date);
  };

  return (
    <div className="training-chart" style={{ width: '100%' }}>
      <div ref={boxRef} style={{ width: '100%', overflowX: 'hidden' }}>
      <svg
        viewBox={`0 0 ${model.width} ${model.height}`}
        width={model.width}
        height={model.height}
        role="slider"
        tabIndex={0}
        aria-label="Riding consistency day"
        aria-valuemin={0}
        aria-valuemax={Math.max(0, selectable.length - 1)}
        aria-valuenow={selectedIndex}
        aria-valuetext={dayText(selected)}
        onFocus={() => selectDay(selectedIndex)}
        onKeyDown={(event) => {
          if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          selectDay(event.key === 'Home' ? 0 : event.key === 'End' ? selectable.length - 1 : selectedIndex + (event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? -1 : 1));
        }}
        style={{ display: 'block', fontFamily: 'var(--br-font-mono, ui-monospace, monospace)' }}
        onPointerLeave={() => setHover(null)}
      >
        {model.monthLabels.map((m) => (
          <text key={`${m.label}-${m.x}`} x={m.x} y={11} fontSize="12" fill={MUTED}>{m.label}</text>
        ))}
        {DOW.map((label, i) => (label ? (
          <text key={label + i} x={LEFT - 8} y={TOP + i * (model.cell + GAP) + model.cell - 2} fontSize="12" textAnchor="end" fill={MUTED}>{label}</text>
        ) : null))}
        {model.cells.map((c) => (
          <rect
            key={c.date}
            x={c.x}
            y={c.y}
            width={model.cell}
            height={model.cell}
            rx={2}
            fill={c.future ? 'transparent' : c.rung >= 0 ? RUNGS[c.rung] : SHEET}
            stroke={!c.future && hover === c.date ? COBALT : 'transparent'}
            strokeWidth={1.5}
            onPointerEnter={() => setHover(c.future ? null : c.date)}
            onPointerDown={() => setHover(c.future ? null : c.date)}
          />
        ))}
      </svg>
      </div>
      <p className="training-chart__readout">{hovered ? dayText(hovered) : '\u00a0'}</p>
    </div>
  );
}

export function heatmapSummary(days: RidingDay[], endDate: string, weeks: number) {
  const byDate = new Map(days.map((d) => [d.date, d]));
  const end = new Date(`${endDate}T00:00:00Z`);
  let streak = 0;
  for (let i = 0; i <= weeks * 7; i += 1) {
    const date = new Date(end);
    date.setUTCDate(end.getUTCDate() - i);
    const day = byDate.get(date.toISOString().slice(0, 10));
    if (day && (day.rides > 0 || (day.value ?? 0) > 0)) streak += 1;
    else if (i > 0) break;
  }
  return { activeDays: days.filter((d) => (d.rides > 0 || (d.value ?? 0) > 0)).length, streak };
}
