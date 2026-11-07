import { useEffect, useMemo, useRef, useState } from 'react';
import { formatDurationCompact, formatFixed, formatInteger, formatWatts } from '../../lib/formatters';

export interface PowerCurveSeries {
  durationsS: number[];
  bestW: Array<number | null>;
  sealedW: number | null;
  candidateW: number | null;
  anchorsS?: number[];
}

// Paper-grade figure in the ledger: ink curve on log time, gridlines
// recessive, the Threshold as the one weighted horizontal (sealed pays),
// a candidate as a lighter dashed line (candidate shows), anchors marked
// where the authority read the curve. Cobalt only on the scrub.
const INK = 'var(--portal-public-ink, #F1EEE8)';
const SOFT = 'var(--portal-public-ink-soft, #9A9488)';
const MUTED = SOFT;
const FAINT = 'var(--portal-public-line, #4E4B46)';
const SHEET = 'var(--portal-public-paper-soft, #1B1A17)';
const COBALT = 'var(--portal-chrome-accent, #5592E2)';
const MARGIN = { top: 20, right: 16, bottom: 28, left: 54 };
const X_TICKS: Array<[number, string]> = [[1, '1s'], [5, '5s'], [15, '15s'], [60, '1m'], [300, '5m'], [1200, '20m'], [3600, '1h']];

export default function PowerCurveChart({ series, height = 240 }: { series: PowerCurveSeries; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  const [scrubX, setScrubX] = useState<number | null>(null);
  const [keyboardIndex, setKeyboardIndex] = useState<number | null>(null);

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
    const points = series.durationsS
      .map((d, i) => ({ d, w: series.bestW[i] }))
      .filter((p): p is { d: number; w: number } => p.w != null && Number.isFinite(p.w) && p.d > 0);
    if (points.length < 2 || width < 200) return null;
    const plotW = width - MARGIN.left - MARGIN.right;
    const plotH = height - MARGIN.top - MARGIN.bottom;
    const minD = points[0].d;
    const maxD = points[points.length - 1].d;
    const logMin = Math.log10(minD);
    const logMax = Math.log10(maxD);
    const wValues = points.map((p) => p.w).concat(series.sealedW ?? [], series.candidateW ?? []);
    const maxW = Math.max(...wValues) * 1.08;
    const yStep = maxW > 800 ? 200 : maxW > 400 ? 100 : 50;
    const x = (d: number) => MARGIN.left + ((Math.log10(d) - logMin) / (logMax - logMin)) * plotW;
    const y = (w: number) => MARGIN.top + plotH - (w / maxW) * plotH;
    const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${formatFixed(x(p.d), 2)} ${formatFixed(y(p.w), 2)}`).join(' ');
    const gridlines: number[] = [];
    for (let w = yStep; w < maxW; w += yStep) gridlines.push(w);
    const anchors = (series.anchorsS ?? []).map((d) => points.find((p) => p.d === d)).filter((p): p is { d: number; w: number } => Boolean(p));
    const xTicks = X_TICKS.filter(([d]) => d >= minD && d <= maxD);
    const interpolate = (d: number) => {
      for (let i = 1; i < points.length; i += 1) {
        if (points[i].d >= d) {
          const a = points[i - 1];
          const b = points[i];
          const t = (Math.log10(d) - Math.log10(a.d)) / (Math.log10(b.d) - Math.log10(a.d));
          return a.w + t * (b.w - a.w);
        }
      }
      return points[points.length - 1].w;
    };
    const scrub = (() => {
      if (keyboardIndex !== null) {
        const p = points[Math.min(keyboardIndex, points.length - 1)];
        return { x: x(p.d), y: y(p.w), d: p.d, w: p.w, flip: x(p.d) > MARGIN.left + plotW * 0.7 };
      }
      if (scrubX == null) return null;
      const px = Math.min(Math.max(scrubX, MARGIN.left), MARGIN.left + plotW);
      const d = 10 ** (logMin + ((px - MARGIN.left) / plotW) * (logMax - logMin));
      const w = interpolate(d);
      return { x: px, y: y(w), d, w, flip: px > MARGIN.left + plotW * 0.7 };
    })();
    return { points, plotW, plotH, x, y, path, gridlines, anchors, xTicks, scrub, baselineY: MARGIN.top + plotH };
  }, [series, width, height, scrubX, keyboardIndex]);

  if (!model) {
    return <div ref={ref} style={{ width: '100%' }} />;
  }

  return (
    <div ref={ref} className="training-chart" style={{ width: '100%' }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        role="slider"
        tabIndex={0}
        aria-label="Power curve duration"
        aria-valuemin={model.points[0].d}
        aria-valuemax={model.points[model.points.length - 1].d}
        aria-valuenow={model.scrub?.d ?? model.points[0].d}
        aria-valuetext={`${formatWatts(model.scrub?.w ?? model.points[0].w)} · ${formatDurationCompact(model.scrub?.d ?? model.points[0].d)}`}
        onFocus={() => setKeyboardIndex((index) => index ?? 0)}
        onBlur={() => setKeyboardIndex(null)}
        onKeyDown={(event) => {
          if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const index = keyboardIndex ?? 0;
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? model.points.length - 1 : index + (event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? -1 : 1);
          setKeyboardIndex(Math.max(0, Math.min(model.points.length - 1, next)));
        }}
        style={{ display: 'block', fontFamily: 'var(--br-font-mono, ui-monospace, monospace)' }}
        onPointerMove={(e) => { setKeyboardIndex(null); setScrubX(e.clientX - e.currentTarget.getBoundingClientRect().left); }}
        onPointerDown={(e) => { setKeyboardIndex(null); setScrubX(e.clientX - e.currentTarget.getBoundingClientRect().left); }}
        onPointerLeave={() => setScrubX(null)}
      >
        {model.gridlines.map((w, i) => (
          <g key={w}>
            <line x1={MARGIN.left} x2={MARGIN.left + model.plotW} y1={model.y(w)} y2={model.y(w)} stroke={FAINT} strokeOpacity="0.45" strokeWidth="1" />
            <text x={MARGIN.left - 8} y={model.y(w) + 3.5} fontSize="12" textAnchor="end" fill={MUTED}>
              {i === model.gridlines.length - 1 ? formatWatts(w) : formatInteger(w)}
            </text>
          </g>
        ))}
        <line x1={MARGIN.left} x2={MARGIN.left + model.plotW} y1={model.baselineY} y2={model.baselineY} stroke={FAINT} strokeWidth="1" />
        {model.xTicks.map(([d, label]) => (
          <g key={d}>
            <line x1={model.x(d)} x2={model.x(d)} y1={model.baselineY} y2={model.baselineY + 4} stroke={FAINT} strokeWidth="1" />
            <text x={model.x(d)} y={model.baselineY + 16} fontSize="12" textAnchor="middle" fill={MUTED}>{label}</text>
          </g>
        ))}
        {series.candidateW != null ? (
          <g>
            <line x1={MARGIN.left} x2={MARGIN.left + model.plotW} y1={model.y(series.candidateW)} y2={model.y(series.candidateW)} stroke={SOFT} strokeWidth="1" strokeDasharray="3 4" />
            <text x={MARGIN.left + model.plotW} y={model.y(series.candidateW) - 5} fontSize="12" textAnchor="end" fill={SOFT}>candidate {formatWatts(series.candidateW)}</text>
          </g>
        ) : null}
        {series.sealedW != null ? (
          <g>
            <line x1={MARGIN.left} x2={MARGIN.left + model.plotW} y1={model.y(series.sealedW)} y2={model.y(series.sealedW)} stroke={INK} strokeWidth="1.5" strokeOpacity="0.85" />
            <text x={MARGIN.left + 6} y={model.y(series.sealedW) - 5} fontSize="12" fontWeight="600" fill={INK}>Threshold {formatWatts(series.sealedW)}</text>
          </g>
        ) : null}
        <path d={model.path} fill="none" stroke={INK} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {model.anchors.map((p) => (
          <circle key={p.d} cx={model.x(p.d)} cy={model.y(p.w)} r="3.5" fill={INK} stroke={SHEET} strokeWidth="1.5" />
        ))}
        {model.scrub ? (
          <g pointerEvents="none">
            <line x1={model.scrub.x} x2={model.scrub.x} y1={MARGIN.top - 4} y2={model.baselineY} stroke={COBALT} strokeWidth="1" strokeOpacity="0.85" />
            <circle cx={model.scrub.x} cy={model.scrub.y} r="3.5" fill={COBALT} stroke={SHEET} strokeWidth="1.5" />
            <text x={model.scrub.flip ? model.scrub.x - 8 : model.scrub.x + 8} y={MARGIN.top + 4} fontSize="12" textAnchor={model.scrub.flip ? 'end' : 'start'} fill={INK}>
              <tspan fontWeight="600">{formatWatts(model.scrub.w)}</tspan>
              <tspan fill={SOFT} dx="7">{formatDurationCompact(model.scrub.d)}</tspan>
            </text>
          </g>
        ) : null}
      </svg>
    </div>
  );
}
