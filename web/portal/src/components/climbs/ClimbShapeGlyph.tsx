import { useMemo } from 'react';
import { formatFixed } from '../../lib/formatters';

// The climb's own canon profile at glyph size: the shape is the identity,
// so each glyph is normalised to its own length and gain (the trailing
// value on the row carries the size). Fill on the card rung, line in the
// soft gray; the room lights the line cobalt when the climb is lit.

export interface ShapePoint {
  distanceM: number;
  elevationM: number;
}

/** A stretch of the shape, in distance, that counted (a climb that earned). */
export interface ShapeSpan {
  startDistanceM: number;
  endDistanceM: number;
}

const WIDTH = 40;
const HEIGHT = 20;
const HEADROOM = 1;
const FLOOR = 2;

function elevationAt(profile: ShapePoint[], distanceM: number): number {
  if (distanceM <= profile[0].distanceM) return profile[0].elevationM;
  for (let i = 1; i < profile.length; i += 1) {
    if (profile[i].distanceM >= distanceM) {
      const a = profile[i - 1];
      const b = profile[i];
      const span = b.distanceM - a.distanceM;
      if (span <= 0) return b.elevationM;
      return a.elevationM + ((distanceM - a.distanceM) / span) * (b.elevationM - a.elevationM);
    }
  }
  return profile[profile.length - 1].elevationM;
}

export function shapePath(
  profile: ShapePoint[],
  width = WIDTH,
  height = HEIGHT,
  spans: ShapeSpan[] = [],
): { line: string; fill: string; spans: string[] } | null {
  if (profile.length < 2) return null;
  const distances = profile.map((point) => point.distanceM);
  const elevations = profile.map((point) => point.elevationM);
  const maxDistance = Math.max(...distances);
  const minElevation = Math.min(...elevations);
  const elevationSpan = Math.max(...elevations) - minElevation;
  if (!(maxDistance > 0)) return null;

  const plotHeight = height - HEADROOM - FLOOR;
  const place = (point: ShapePoint) => {
    const x = (point.distanceM / maxDistance) * width;
    const rise = elevationSpan > 0 ? ((point.elevationM - minElevation) / elevationSpan) * plotHeight : 0;
    const y = height - FLOOR - rise;
    return `${formatFixed(x, 1)} ${formatFixed(y, 1)}`;
  };
  const line = `M${profile.map(place).join(' L')}`;
  const corner = `${formatFixed(width, 0)} ${formatFixed(height, 0)}`;

  // Counted spans ride the same trace: the span's ends are interpolated onto
  // it so the cobalt stroke starts and stops exactly where the climb did.
  const spanPaths = spans
    .filter((span) => Number.isFinite(span.startDistanceM) && Number.isFinite(span.endDistanceM) && span.endDistanceM > span.startDistanceM)
    .map((span) => {
      const start = Math.max(0, span.startDistanceM);
      const end = Math.min(maxDistance, span.endDistanceM);
      if (end <= start) return null;
      const inside = profile.filter((point) => point.distanceM > start && point.distanceM < end);
      const points: ShapePoint[] = [
        { distanceM: start, elevationM: elevationAt(profile, start) },
        ...inside,
        { distanceM: end, elevationM: elevationAt(profile, end) },
      ];
      return `M${points.map(place).join(' L')}`;
    })
    .filter((path): path is string => Boolean(path));

  return { line, fill: `${line} L${corner} L0 ${formatFixed(height, 0)} Z`, spans: spanPaths };
}

interface ClimbShapeGlyphProps {
  profile: ShapePoint[] | undefined;
  className?: string;
  /** Glyph size; the climb index uses 40×20, the ride log's spine 120×28. */
  width?: number;
  height?: number;
  /** Stretches that counted, stroked cobalt over the trace. */
  spans?: ShapeSpan[];
}

export default function ClimbShapeGlyph({ profile, className, width = WIDTH, height = HEIGHT, spans }: ClimbShapeGlyphProps) {
  const path = useMemo(() => shapePath(profile ?? [], width, height, spans ?? []), [height, profile, spans, width]);
  const classes = ['climb-shape-glyph', className].filter(Boolean).join(' ');
  if (!path) return <span className={`${classes} climb-shape-glyph--absent`} aria-hidden="true" />;
  return (
    <svg
      className={classes}
      width={width}
      height={height}
      viewBox={`0 0 ${formatFixed(width, 0)} ${formatFixed(height, 0)}`}
      aria-hidden="true"
      focusable="false"
    >
      <path className="climb-shape-glyph__fill" d={path.fill} />
      <path className="climb-shape-glyph__line" d={path.line} />
      {path.spans.map((span, index) => (
        <path key={index} className="climb-shape-glyph__span" d={span} />
      ))}
    </svg>
  );
}
