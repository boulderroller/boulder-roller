import { useState, useEffect, useMemo } from 'react';
import { X } from 'lucide-react';
import { api } from '../../lib/api';
import type { ElevationProfileData } from '../../lib/api';
import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceArea,
} from 'recharts';
import { PORTAL_CSS_COLORS } from '../../lib/portalPalette';
import {
  ABSENT_VALUE,
  formatFixed,
  formatInteger,
  formatKilometers,
  formatMeters,
  formatSecondsLabel,
  formatSignificanceScore,
  formatSpeed,
  formatWatts,
} from '../../lib/formatters';

const CHART_COLORS = {
  border: PORTAL_CSS_COLORS.border,
  grid: PORTAL_CSS_COLORS.divider,
  muted: 'currentColor',
  boundary: PORTAL_CSS_COLORS.terrain,
  elevation: PORTAL_CSS_COLORS.terrain,
  smoothed: PORTAL_CSS_COLORS.reward,
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

const BOUNDARY_LABEL = {
  fontSize: 12,
  fontFamily: 'var(--br-font-mono)',
  fill: CHART_COLORS.boundary,
} as const;

type ScoreTone = 'high' | 'medium' | 'low' | 'muted';

function gScoreTone(g: number | null): ScoreTone {
  if (g === null) return 'muted';
  if (g >= 0.7) return 'high';
  if (g >= 0.4) return 'medium';
  if (g >= 0.15) return 'low';
  return 'muted';
}

function fmtNum(v: number | null | undefined, decimals = 1): string {
  if (v === null || v === undefined) return ABSENT_VALUE;
  return formatFixed(v, decimals);
}

function ProfileTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: Record<string, unknown>; dataKey?: string }>;
}) {
  if (!active || !payload?.length) return null;

  const point = payload[0].payload;
  const t = point.t as number;
  const raw = point.elevation as number | undefined;
  const smoothed = point.smoothed as number | undefined;
  const power = point.powerW as number | null | undefined;
  const speed = point.speedMps as number | null | undefined;

  return (
    <div className="admin-v2-elevation-tooltip">
      <strong>t={formatSecondsLabel(t)}</strong>
      {raw !== undefined ? <span>Raw: {formatMeters(raw, 1)}</span> : null}
      {smoothed !== undefined ? <em>SMA(5): {formatMeters(smoothed, 1)}</em> : null}
      {power !== null && power !== undefined ? <span>Power: {formatWatts(power)}</span> : null}
      {speed !== null && speed !== undefined ? (
        <span>Speed: {formatSpeed(speed, 'metric')}</span>
      ) : null}
    </div>
  );
}

interface ElevationProfileProps {
  climbId: string;
  onClose: () => void;
}

export default function ElevationProfile({ climbId, onClose }: ElevationProfileProps) {
  const [data, setData] = useState<ElevationProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getClimbElevationProfile(climbId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load profile');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [climbId]);

  const chartData = useMemo(() => {
    if (!data || !data.profile.samples.length) return [];

    return data.profile.samples.map((s, i) => ({
      t: s.t,
      elevation: s.elevationM,
      smoothed: data.profile.smoothed[i] ?? s.elevationM,
      powerW: s.powerW,
      speedMps: s.speedMps,
    }));
  }, [data]);

  const yDomain = useMemo(() => {
    if (!chartData.length) return [0, 100];
    const elevations = chartData.map((d) => d.elevation);
    const min = Math.floor(Math.min(...elevations) - 5);
    const max = Math.ceil(Math.max(...elevations) + 10);
    return [min, max];
  }, [chartData]);

  const { activePairs, filteredPairs } = useMemo(() => {
    if (!data) return { activePairs: [], filteredPairs: [] };
    const active = data.persistence.pairs.filter((p) => p.aboveNoiseGate);
    const filtered = data.persistence.pairs.filter((p) => !p.aboveNoiseGate);
    return { activePairs: active, filteredPairs: filtered };
  }, [data]);

  if (loading) {
    return (
      <div className="admin-v2-elevation-state admin-v2-elevation-state--loading">
        <span aria-hidden="true" />
        <strong>Loading elevation profile...</strong>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="admin-v2-elevation-state admin-v2-elevation-state--error">
        <strong>{error ?? 'No profile data'}</strong>
      </div>
    );
  }

  const { climb } = data;
  const scoreTone = gScoreTone(climb.significanceG);

  return (
    <section
      className="admin-v2-elevation-profile"
      aria-label={`Elevation profile for ${climb.roadName || 'unnamed climb'}`}
    >
      <header className="admin-v2-elevation-profile__header">
        <div className="admin-v2-elevation-profile__title">
          <div>
            <strong>Elevation Profile</strong>
            {climb.significanceG !== null ? (
              <span data-tone={scoreTone}>G {formatSignificanceScore(climb.significanceG)}</span>
            ) : null}
          </div>
          <h3>{climb.roadName || 'Unnamed climb'}</h3>
          <p>
            {formatMeters(climb.vertM)} vert
            {climb.distanceM ? ` | ${formatKilometers(climb.distanceM / 1000)}` : ''}
            {climb.persistenceM ? ` | ${formatMeters(climb.persistenceM, 1)} persistence` : ''}
          </p>
        </div>

        <button
          type="button"
          className="portal-sort-button admin-v2-elevation-profile__close"
          onClick={onClose}
          aria-label="Close elevation profile"
          title="Close elevation profile"
        >
          <X size={14} aria-hidden="true" />
        </button>
      </header>

      {chartData.length > 0 ? (
        <div className="admin-v2-elevation-profile__chart">
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart
              data={chartData}
              margin={{ top: 20, right: 24, bottom: 24, left: 12 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis
                dataKey="t"
                type="number"
                domain={['dataMin', 'dataMax']}
                tick={AXIS_TICK}
                stroke={CHART_COLORS.border}
                tickFormatter={(v: number) => formatSecondsLabel(v)}
                label={{
                  value: 'Time offset (s)',
                  position: 'bottom',
                  offset: -2,
                  style: AXIS_LABEL,
                }}
              />
              <YAxis
                domain={yDomain}
                tick={AXIS_TICK}
                stroke={CHART_COLORS.border}
                width={56}
                tickFormatter={(v: number) => formatMeters(v)}
                label={{
                  value: 'Elevation (m)',
                  angle: -90,
                  position: 'insideLeft',
                  offset: 4,
                  style: AXIS_LABEL,
                }}
              />
              <Tooltip content={<ProfileTooltip />} />
              <ReferenceArea
                x1={climb.startOffsetS}
                x2={climb.endOffsetS}
                fill={CHART_COLORS.boundary}
                fillOpacity={0.09}
              />
              <ReferenceLine
                x={climb.startOffsetS}
                stroke={CHART_COLORS.boundary}
                strokeDasharray="4 4"
                strokeWidth={1}
                label={{
                  value: 'start',
                  position: 'top',
                  style: BOUNDARY_LABEL,
                }}
              />
              <ReferenceLine
                x={climb.endOffsetS}
                stroke={CHART_COLORS.boundary}
                strokeDasharray="4 4"
                strokeWidth={1}
                label={{
                  value: 'end',
                  position: 'top',
                  style: BOUNDARY_LABEL,
                }}
              />
              <Area
                dataKey="elevation"
                type="monotone"
                fill={CHART_COLORS.elevation}
                stroke={CHART_COLORS.elevation}
                strokeWidth={1}
                fillOpacity={0.14}
                name="Raw elevation"
                dot={false}
                isAnimationActive={false}
              />
              <Line
                dataKey="smoothed"
                type="monotone"
                stroke={CHART_COLORS.smoothed}
                strokeWidth={2}
                dot={false}
                name="SMA(5)"
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="admin-v2-elevation-profile__empty">
          <strong>No elevation samples available</strong>
        </div>
      )}

      {data.persistence.pairs.length > 0 ? (
        <section className="admin-v2-elevation-profile__pairs" aria-label="Persistence pairs">
          <header>
            <strong>Persistence Pairs</strong>
            <span>{formatInteger(activePairs.length)} above gate, {formatInteger(filteredPairs.length)} filtered</span>
          </header>
          <p>noise gate: {formatMeters(data.persistence.noiseGateM)}</p>
          <ol>
            {activePairs.map((p, i) => (
              <li key={`active-${i}`} data-status="active">
                <span aria-hidden="true" />
                <strong>{formatMeters(p.birthElev, 1)} &rarr; {formatMeters(p.deathElev, 1)}</strong>
                <b>+{formatMeters(p.persistenceM, 1)}</b>
                <small>idx {formatInteger(p.birthIdx)}&rarr;{formatInteger(p.deathIdx)}</small>
              </li>
            ))}
            {filteredPairs.slice(0, 5).map((p, i) => (
              <li key={`filtered-${i}`} data-status="filtered">
                <span aria-hidden="true" />
                <strong>{formatMeters(p.birthElev, 1)} &rarr; {formatMeters(p.deathElev, 1)}</strong>
                <b>+{formatMeters(p.persistenceM, 1)}</b>
                <small>Filtered</small>
              </li>
            ))}
          </ol>
          {filteredPairs.length > 5 ? (
            <small>+{formatInteger(filteredPairs.length - 5)} more filtered pairs</small>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
