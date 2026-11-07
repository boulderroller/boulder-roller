import GeographyCredit from './GeographyCredit';
import type { GeographicData } from '../../lib/api';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { formatFixed, formatMeters, formatNumber, formatPercent, getDistanceUnit } from '../../lib/formatters';

export interface ProfilePoint {
  distanceM: number;
  elevationM: number;
}

// Ratified Climb Room: a single ground tone and five luminance/weight rungs.
const BAND_STEPS = [
  { minPct: 12, varName: '--climb-band-12plus', weight: 3 },
  { minPct: 9, varName: '--climb-band-9', weight: 2.2 },
  { minPct: 6, varName: '--climb-band-6', weight: 2 },
  { minPct: 3, varName: '--climb-band-3', weight: 1.8 },
  { minPct: Number.NEGATIVE_INFINITY, varName: '--climb-band-0', weight: 1.6 },
] as const;
const INK = 'var(--portal-public-ink)';
const MUTED = 'var(--br-ink-muted)';
const FAINT = 'var(--portal-public-ink-faint)';
const SHEET = 'var(--br-card)';
const GROUND = 'var(--climb-profile-ground)';

interface Band {
  x0: number;
  x1: number;
  bins: number;
  gradientPct: number;
  stepIndex: number;
}

function stepIndexFor(gradientPct: number): number {
  const idx = BAND_STEPS.findIndex((s) => gradientPct >= s.minPct);
  return idx === -1 ? BAND_STEPS.length - 1 : idx;
}

function interpolateElevation(points: ProfilePoint[], distanceM: number): number {
  if (distanceM <= points[0].distanceM) return points[0].elevationM;
  for (let i = 1; i < points.length; i += 1) {
    if (points[i].distanceM >= distanceM) {
      const a = points[i - 1];
      const b = points[i];
      const span = b.distanceM - a.distanceM;
      if (span <= 0) return b.elevationM;
      const t = (distanceM - a.distanceM) / span;
      return a.elevationM + t * (b.elevationM - a.elevationM);
    }
  }
  return points[points.length - 1].elevationM;
}

function pickStep(span: number, candidates: number[], maxCount: number): number {
  for (const step of candidates) {
    if (span / step <= maxCount) return step;
  }
  return candidates[candidates.length - 1];
}

// Axis ticks and the scrub readout: whole kilometres above 10, up to two
// decimals below. Numerals go through the shared
// formatter; the unit is the semantic distance unit, appended only where the
// axis names it.
function formatKm(m: number, withUnit: boolean): string {
  const km = m / 1000;
  const text = km === 0 ? '0' : km >= 10 ? formatNumber(km, 0, 0) : formatNumber(km, 2, 0);
  return withUnit ? text + ' ' + getDistanceUnit('metric') : text;
}

// Compact: the face alone — bands, silhouette, baseline — for lists and
// identity strips. Same comparable slope; no furniture, no scrub.
export default function ClimbProfileHero({
  profile,
  compact = false,
  geographicData,
  inspectedDistance,
  onInspect,
}: {
  profile: ProfilePoint[];
  compact?: boolean;
  geographicData?: GeographicData | null;
  inspectedDistance?: number | null;
  onInspect?: (distanceM: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const helpId = useId();
  const [width, setWidth] = useState(640);
  const [localDistance, setLocalDistance] = useState<number | null>(null);
  const scrubD = inspectedDistance === undefined ? localDistance : inspectedDistance;
  const inspect = (distance: number) => {
    setLocalDistance(distance);
    onInspect?.(distance);
  };

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;
    const observer = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const model = useMemo(() => {
    const points = (profile ?? []).filter(
      (p) => Number.isFinite(p.distanceM) && Number.isFinite(p.elevationM),
    );
    if (points.length < 2 || width < (compact ? 80 : 160)
      || points.some((point, index) => index > 0 && point.distanceM <= points[index - 1].distanceM)) return null;
    const phone = width <= 440;
    const margin = compact ? { top: 2, right: 0, bottom: 2, left: 0 }
      : phone ? { top: 22, right: 16, bottom: 26, left: 16 }
        : { top: 26, right: 64, bottom: 30, left: 40 };

    const originM = points[0].distanceM;
    const lengthM = points[points.length - 1].distanceM - originM;
    if (lengthM <= 0) return null;

    const elevations = points.map((p) => p.elevationM);
    const minElev = Math.min(...elevations);
    const maxElev = Math.max(...elevations);
    const elevSpan = Math.max(maxElev - minElev, 1);
    const headroom = elevSpan * 0.06;
    const paddedSpan = elevSpan + headroom;

    const plotW = width - margin.left - margin.right;
    const xScale = plotW / lengthM;
    const plotH = compact ? Math.max(12, Math.min(48, paddedSpan * 2.25 * xScale)) : phone ? 70 : 120;
    const yScale = plotH / paddedSpan;
    const viewH = margin.top + plotH + margin.bottom;
    const baselineY = margin.top + plotH;
    const x = (d: number) => margin.left + (d - originM) * xScale;
    const y = (e: number) => baselineY - (e - minElev) * yScale;

    // Fixed 100 m bands, merging only adjacent equal rungs as on the board.
    const binWidthM = 100;
    const grade = (d0: number, d1: number) =>
      ((interpolateElevation(points, d1) - interpolateElevation(points, d0)) / (d1 - d0)) * 100;
    const bands: Band[] = [];
    for (let d0 = originM; d0 < originM + lengthM - 1e-6; d0 += binWidthM) {
      const d1 = Math.min(d0 + binWidthM, originM + lengthM);
      const gradientPct = grade(d0, d1);
      const stepIndex = stepIndexFor(gradientPct);
      const prev = bands[bands.length - 1];
      if (prev && prev.stepIndex === stepIndex) {
        prev.x1 = d1;
        prev.bins += 1;
        prev.gradientPct = grade(prev.x0, d1);
      } else bands.push({ x0: d0, x1: d1, bins: 1, gradientPct, stepIndex });
    }

    const bandShapes = bands.map((band) => {
      const inner = points.filter((p) => p.distanceM > band.x0 && p.distanceM < band.x1);
      const edge0 = { distanceM: band.x0, elevationM: interpolateElevation(points, band.x0) };
      const edge1 = { distanceM: band.x1, elevationM: interpolateElevation(points, band.x1) };
      const top = [edge0, ...inner, edge1]
        .map((p) => `${formatFixed(x(p.distanceM), 2)} ${formatFixed(y(p.elevationM), 2)}`)
        .join(' L ');
      const widthPx = (band.x1 - band.x0) * xScale;
      // Drop labels where width or clearance cannot hold the board’s base label.
      const midM = (band.x0 + band.x1) / 2;
      const fillPx = baselineY - y(interpolateElevation(points, midM));
      const step = BAND_STEPS[band.stepIndex];
      return {
        d: `M ${top}`,
        stroke: `var(${step.varName})`,
        weight: step.weight,
        label: widthPx >= 44 && fillPx >= 20 ? formatPercent(band.gradientPct, 1) : null,
        labelX: x(midM),
      };
    });

    const silhouette = points
      .map((p, i) => `${i === 0 ? 'M' : 'L'} ${formatFixed(x(p.distanceM), 2)} ${formatFixed(y(p.elevationM), 2)}`)
      .join(' ');

    const separators = bands.slice(1).map((band) => ({
      x: x(band.x0),
      y1: y(interpolateElevation(points, band.x0)),
      y2: baselineY,
    }));

    // Recessive paper furniture: round-elevation gridlines, distance ticks.
    const elevStep = pickStep(elevSpan, [10, 20, 25, 50, 100, 200, 500], 5);
    const gridlines: Array<{ y: number; label: string }> = [];
    for (let e = minElev + elevStep; e <= maxElev; e += elevStep) {
      const gy = y(e);
      if (gy > margin.top + 4 && gy < baselineY - 6) {
        gridlines.push({ y: gy, label: formatMeters(e - minElev, 0) });
      }
    }
    const distStep = pickStep(lengthM, [250, 500, 1000, 2000, 5000], phone ? 4 : 7);
    const ticks: Array<{ x: number; label: string }> = [];
    for (let d = 0; d <= lengthM + 1e-6; d += distStep) {
      ticks.push({ x: x(originM + d), label: formatKm(d, d + distStep > lengthM) });
    }

    const summitIsEnd = points[points.length - 1].elevationM >= points[0].elevationM;
    const summit = summitIsEnd ? points[points.length - 1] : points[0];
    const base = summitIsEnd ? points[0] : points[points.length - 1];

    const scrub = (() => {
      if (scrubD == null) return null;
      const d = Math.min(Math.max(scrubD, originM), originM + lengthM);
      const elev = interpolateElevation(points, d);
      const w0 = Math.max(d - 25, originM);
      const w1 = Math.min(d + 25, originM + lengthM);
      const localPct = w1 > w0 ? grade(w0, w1) : 0;
      const px = x(d);
      return {
        x: px,
        y: y(elev),
        lines: [
          formatKm(d - originM, true),
          formatMeters(elev - minElev, 0),
          formatPercent(localPct, 1),
        ],
      };
    })();

    return {
      margin,
      phone,
      ground: `${silhouette} L ${formatFixed(x(originM + lengthM), 2)} ${formatFixed(baselineY, 2)} L ${formatFixed(x(originM), 2)} ${formatFixed(baselineY, 2)} Z`,
      originM,
      endM: originM + lengthM,
      viewH,
      baselineY,
      plotW,
      bandShapes,
      silhouette,
      separators,
      gridlines,
      ticks,
      summit: { x: x(summit.distanceM), y: y(summit.elevationM), label: formatMeters(maxElev - minElev, 0) },
      base: { x: x(base.distanceM), y: y(base.elevationM), label: formatMeters(base.elevationM - minElev, 0) },
      toDistance: (px: number) => originM + (px - margin.left) / xScale,
      scrub,
    };
  }, [profile, width, scrubD, compact]);

  if (!model && (profile ?? []).length < 2) return null;

  return (
    <div ref={containerRef} className={compact ? undefined : 'climb-profile-inspection'} style={{ width: '100%' }}>
      <GeographyCredit data={geographicData} />
      <div className="climb-profile-inspection__chart">
      {model ? (
        <svg
          viewBox={`0 0 ${width} ${model.viewH}`}
          width={width}
          height={model.viewH}
          role="img"
          aria-label="Elevation profile"
          focusable="false"
          style={{ display: 'block', fontFamily: 'var(--br-font-mono, ui-monospace, monospace)' }}
        >
          {!compact && model.gridlines.map((g, i) => (
            <g key={`grid-${i}`}>
              <line x1={model.margin.left} x2={model.margin.left + model.plotW} y1={g.y} y2={g.y} stroke={FAINT} strokeOpacity="0.28" strokeWidth="1" />
              {!model.phone && <text x={model.margin.left + model.plotW + 8} y={g.y + 4} fontSize="11" fill={MUTED}>{g.label}</text>}
            </g>
          ))}
          <path d={model.ground} fill={GROUND} />
          {model.separators.map((sep, i) => (
            <line key={`sep-${i}`} x1={sep.x} x2={sep.x} y1={sep.y1} y2={sep.y2} stroke={SHEET} strokeWidth="1" />
          ))}
          {!compact && model.bandShapes.map((band, i) =>
            band.label ? (
              <text
                key={`pct-${i}`}
                x={band.labelX}
                y={model.baselineY - 7}
                fontSize="11"
                fontWeight="600"
                textAnchor="middle"
                fill={band.stroke}
              >
                {band.label}
              </text>
            ) : null,
          )}
          {model.bandShapes.map((band, i) => <path key={`band-${i}`} d={band.d} fill="none" stroke={band.stroke} strokeWidth={band.weight} strokeLinejoin="round" strokeLinecap="round" />)}
          <line x1={model.margin.left} x2={model.margin.left + model.plotW} y1={model.baselineY} y2={model.baselineY} stroke={FAINT} strokeWidth="1" />
          {!compact && model.ticks.map((t, i) => (
            <g key={`tick-${i}`}>
              <line x1={t.x} x2={t.x} y1={model.baselineY} y2={model.baselineY + 4} stroke={FAINT} strokeWidth="1" />
              <text x={t.x} y={model.baselineY + 16} fontSize="11" textAnchor="middle" fill={MUTED}>{t.label}</text>
            </g>
          ))}
          {!compact && (
          <text
            x={model.summit.x}
            y={model.summit.y - 8}
            fontSize="11"
            fontWeight="600"
            textAnchor={model.summit.x > model.margin.left + model.plotW * 0.8 ? 'end' : 'middle'}
            fill={INK}
          >
            {model.summit.label}
          </text>
          )}
          {model.scrub ? (
            <g pointerEvents="none">
              <line x1={model.scrub.x} x2={model.scrub.x} y1={model.margin.top - 4} y2={model.baselineY} stroke={INK} strokeWidth="1" strokeOpacity="0.85" />
              <circle cx={model.scrub.x} cy={model.scrub.y} r="3.5" fill={INK} stroke={SHEET} strokeWidth="1.5" />
            </g>
          ) : null}
        </svg>
      ) : null}
      {!compact && model ? (
        <input
          type="range"
          className="climb-profile-inspection__input"
          min={model.originM}
          max={model.endM}
          step="1"
          value={scrubD ?? model.originM}
          aria-label="Position on elevation profile"
          aria-describedby={helpId}
          aria-valuetext={model.scrub ? `${formatMeters(Math.max(0, (scrubD ?? model.originM) - model.originM), 0)}, elevation ${model.scrub.lines[1]}, grade ${model.scrub.lines[2]}` : 'Start of climb'}
          onFocus={() => inspect(scrubD ?? model.originM)}
          onChange={(event) => inspect(Number(event.currentTarget.value))}
          onKeyDown={(event) => {
            if (event.key === 'Home' || event.key === 'End') {
              event.preventDefault();
              inspect(event.key === 'Home' ? model.originM : model.endM);
            }
          }}
          style={{ left: model.margin.left, right: model.margin.right }}
        />
      ) : null}
      </div>
      {!compact && model ? <>
        <output className="climb-profile-inspection__readout" aria-live="off" style={{ left: model.scrub ? Math.min(model.scrub.x + 8, width - 196) : model.margin.left, top: model.margin.top - 6 }}>
          {model.scrub ? `${model.scrub.lines[0]} · ${model.scrub.lines[1]} · ${model.scrub.lines[2]}` : null}
        </output>
        <span id={helpId} className="climb-sr-only">Drag across the profile or use the arrow keys to explore elevation. Home and End select the start and finish.</span>
      </> : null}
    </div>
  );
}
