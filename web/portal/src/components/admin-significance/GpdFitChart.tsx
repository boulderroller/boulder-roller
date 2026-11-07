import { useState, useEffect, useMemo } from 'react';
import { api } from '../../lib/api';
import type { CellFitData } from '../../lib/api';
import {
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import { PORTAL_CSS_COLORS } from '../../lib/portalPalette';
import { formatFixed, formatInteger, formatMeters, formatSignificanceScore } from '../../lib/formatters';

const CHART_COLORS = {
  border: PORTAL_CSS_COLORS.border,
  grid: PORTAL_CSS_COLORS.divider,
  muted: 'currentColor',
  gpd: PORTAL_CSS_COLORS.reward,
  threshold: PORTAL_CSS_COLORS.crown,
} as const;

const AXIS_TICK = {
  fontSize: 12,
  fontFamily: 'var(--br-font-mono)',
  fill: CHART_COLORS.muted,
} as const;

const AXIS_LABEL = {
  fontSize: 12,
  fontFamily: 'var(--br-font-mono)',
  fill: CHART_COLORS.muted,
} as const;

const THRESHOLD_LABEL = {
  fontSize: 12,
  fontFamily: 'var(--br-font-mono)',
  fill: CHART_COLORS.threshold,
} as const;

type ScoreTone = 'high' | 'medium' | 'low' | 'muted';

function gScoreTone(g: number): ScoreTone {
  if (g >= 0.7) return 'high';
  if (g >= 0.4) return 'medium';
  if (g >= 0.15) return 'low';
  return 'muted';
}

function FitTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: Record<string, unknown>; dataKey?: string }>;
}) {
  if (!active || !payload?.length) return null;

  const point = payload[0].payload;

  if (point.roadName !== undefined) {
    const gScore = point.gScore as number;
    return (
      <div className="admin-v2-gpd-fit-tooltip">
        <strong>{(point.roadName as string) || 'Unnamed'}</strong>
        <span>persistence: {formatMeters(point.persistenceM as number, 1)}</span>
        <em data-tone={gScoreTone(gScore)}>G = {formatSignificanceScore(gScore)}</em>
      </div>
    );
  }

  const x = point.x as number | undefined;
  const gpdCdf = point.gpdCdf as number | undefined;
  const empiricalCdf = point.empiricalCdf as number | undefined;

  return (
    <div className="admin-v2-gpd-fit-tooltip">
      <span>persistence: {formatMeters(x, 1)}</span>
      {gpdCdf !== undefined && gpdCdf !== null ? (
        <em data-tone="medium">GPD survival: {formatFixed(1 - gpdCdf, 4)}</em>
      ) : null}
      {empiricalCdf !== undefined && empiricalCdf !== null ? (
        <span>Empirical: {formatFixed(1 - empiricalCdf, 4)}</span>
      ) : null}
    </div>
  );
}

interface GpdFitChartProps {
  h3Index: string;
}

export default function GpdFitChart({ h3Index }: GpdFitChartProps) {
  const [data, setData] = useState<CellFitData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getCellFitData(h3Index)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load fit data');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [h3Index]);

  const chartData = useMemo(() => {
    if (!data) return [];

    return data.fittedCurve.map((point) => ({
      x: point.x,
      gpdSurvival: Math.max(1 - point.gpdCdf, 0.0001),
      empiricalSurvival: point.empiricalCdf !== null ? Math.max(1 - point.empiricalCdf, 0.0001) : null,
      gpdCdf: point.gpdCdf,
      empiricalCdf: point.empiricalCdf,
    }));
  }, [data]);

  if (loading) {
    return (
      <div className="admin-v2-gpd-fit-state admin-v2-gpd-fit-state--loading">
        <span aria-hidden="true" />
        <strong>Loading fit data...</strong>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="admin-v2-gpd-fit-state admin-v2-gpd-fit-state--error">
        <strong>{error ?? 'No fit data'}</strong>
      </div>
    );
  }

  return (
    <section className="admin-v2-gpd-fit" aria-label={`GPD fit for cell ${h3Index}`}>
      <header className="admin-v2-gpd-fit__header">
        <strong>GPD Fit: {h3Index.slice(0, 12)}...</strong>
        <div>
          <span>xi={formatFixed(data.cell.gpdXi, 4)}</span>
          <span>sigma={formatFixed(data.cell.gpdSigma, 2)}</span>
          <span>n={formatInteger(data.persistenceValues.length)}</span>
        </div>
      </header>

      <div className="admin-v2-gpd-fit__chart">
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart
            data={chartData}
            margin={{ top: 20, right: 24, bottom: 24, left: 12 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis
              dataKey="x"
              type="number"
              tick={AXIS_TICK}
              stroke={CHART_COLORS.border}
              label={{
                value: 'Persistence (m)',
                position: 'bottom',
                offset: -2,
                style: AXIS_LABEL,
              }}
            />
            <YAxis
              scale="log"
              domain={[0.001, 1]}
              tick={AXIS_TICK}
              stroke={CHART_COLORS.border}
              width={56}
              tickFormatter={(value: number) => {
                if (value >= 1) return '1';
                if (value >= 0.1) return formatFixed(value, 1);
                if (value >= 0.01) return formatFixed(value, 2);
                return formatFixed(value, 3);
              }}
              label={{
                value: 'Survival',
                angle: -90,
                position: 'insideLeft',
                offset: 4,
                style: AXIS_LABEL,
              }}
            />
            <Tooltip content={<FitTooltip />} />
            <ReferenceLine
              x={data.thresholdM}
              stroke={CHART_COLORS.threshold}
              strokeDasharray="4 4"
              strokeWidth={1}
              label={{
                value: `threshold ${formatMeters(data.thresholdM, 1)}`,
                position: 'top',
                style: THRESHOLD_LABEL,
              }}
            />
            <Scatter
              dataKey="empiricalSurvival"
              fill={CHART_COLORS.muted}
              fillOpacity={0.4}
              r={2}
              name="Empirical"
            />
            <Line
              dataKey="gpdSurvival"
              type="monotone"
              stroke={CHART_COLORS.gpd}
              strokeWidth={2}
              dot={false}
              name="GPD Fit"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {data.climbPositions.length > 0 ? (
        <section className="admin-v2-gpd-fit__climbs" aria-label="Climbs in cell">
          <strong>Climbs in cell ({formatInteger(data.climbPositions.length)})</strong>
          <ol>
            {data.climbPositions.slice(0, 10).map((climb) => (
              <li key={climb.id}>
                <span aria-hidden="true" data-tone={gScoreTone(climb.gScore)} />
                <strong>{climb.roadName || 'Unnamed'}</strong>
                <em>{formatMeters(climb.persistenceM, 1)}</em>
                <b data-tone={gScoreTone(climb.gScore)}>G {formatFixed(climb.gScore, 3)}</b>
              </li>
            ))}
          </ol>
          {data.climbPositions.length > 10 ? (
            <small>+{formatInteger(data.climbPositions.length - 10)} more</small>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
