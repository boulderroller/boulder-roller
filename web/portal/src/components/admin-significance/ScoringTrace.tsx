import { useState, useEffect, useCallback } from 'react';
import { X } from 'lucide-react';
import { api } from '../../lib/api';
import type { ScoringTrace as ScoringTraceData } from '../../lib/api';
import { ABSENT_VALUE, formatFixed, formatInteger, formatKilometers, formatMeters, formatPercent, formatSignificanceScore } from '../../lib/formatters';

type StepStatus = 'pass' | 'warn' | 'fail';
type ScoreTone = 'high' | 'medium' | 'low' | 'muted';

function gScoreTone(g: number): ScoreTone {
  if (g >= 0.7) return 'high';
  if (g >= 0.4) return 'medium';
  if (g >= 0.15) return 'low';
  return 'muted';
}

function fmtNum(v: number | null | undefined, decimals = 3): string {
  if (v === null || v === undefined) return ABSENT_VALUE;
  return formatFixed(v, decimals);
}

interface StepProps {
  label: string;
  value: string;
  status: StepStatus;
  sublabel?: string;
  isLast?: boolean;
}

function Step({ label, value, status, sublabel, isLast }: StepProps) {
  return (
    <li
      className="admin-v2-scoring-trace__step"
      data-status={status}
      data-last={isLast ? 'true' : undefined}
    >
      <span className="admin-v2-scoring-trace__rail" aria-hidden="true" />
      <div className="admin-v2-scoring-trace__step-body">
        <div>
          <strong>{label}</strong>
          <b>{value}</b>
        </div>
        {sublabel ? <span>{sublabel}</span> : null}
      </div>
    </li>
  );
}

interface ScoringTraceProps {
  climbId: string;
  onClose: () => void;
}

export default function ScoringTrace({ climbId, onClose }: ScoringTraceProps) {
  const [data, setData] = useState<ScoringTraceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTrace = useCallback(() => {
    setLoading(true);
    setError(null);
    api.getClimbScoringTrace(climbId)
      .then((result) => setData(result))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load trace'))
      .finally(() => setLoading(false));
  }, [climbId]);

  useEffect(() => {
    fetchTrace();
  }, [fetchTrace]);

  if (loading) {
    return (
      <div className="admin-v2-scoring-trace-state admin-v2-scoring-trace-state--loading">
        <span aria-hidden="true" />
        <strong>Loading trace...</strong>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="admin-v2-scoring-trace-state admin-v2-scoring-trace-state--error">
        <strong>{error ?? 'No data'}</strong>
        <button type="button" className="portal-sort-button admin-v2-compact-button" onClick={onClose}>
          <X size={14} aria-hidden="true" />
          Close
        </button>
      </div>
    );
  }

  const { climb, trace } = data;
  const capBinding = trace.gCap !== null && trace.gConservative !== null && trace.gCap < trace.gConservative;

  const steps: StepProps[] = [
    {
      label: 'Persistence',
      value: formatMeters(trace.persistenceM, 1),
      status: trace.passedNoiseGate ? 'pass' : 'fail',
      sublabel: `noise gate: ${formatMeters(trace.noiseGateM, 1)} ${trace.passedNoiseGate ? 'PASS' : 'BLOCKED'}`,
    },
    {
      label: 'Cell Lookup',
      value: trace.cellLookup.cellH3
        ? `${trace.cellLookup.cellH3.slice(0, 12)}...`
        : 'none',
      status: trace.cellLookup.cellH3 ? 'pass' : 'fail',
      sublabel: trace.cellLookup.res5Found
        ? 'res-5 primary'
        : trace.cellLookup.res4Fallback
          ? 'res-4 fallback'
          : trace.cellLookup.res5Parent
            ? `parent: ${trace.cellLookup.res5Parent.slice(0, 12)}...`
            : 'no terrain data',
    },
    {
      label: 'Threshold',
      value: trace.thresholdM !== null
        ? formatMeters(trace.thresholdM, 1)
        : ABSENT_VALUE,
      status: trace.thresholdM !== null ? 'pass' : 'fail',
      sublabel: trace.thresholdM !== null
        ? `q=${fmtNum(trace.thresholdQuantile, 2)} | exceedance=${formatMeters(trace.exceedanceM, 1)}`
        : undefined,
    },
    {
      label: 'GPD Fit',
      value: trace.gpdXi !== null
        ? `xi=${fmtNum(trace.gpdXi, 4)}`
        : ABSENT_VALUE,
      status: trace.gpdXi !== null ? 'pass' : 'fail',
      sublabel: trace.gpdXi !== null
        ? `sigma=${fmtNum(trace.gpdSigma, 2)} | xi_ci_hi=${fmtNum(trace.xiCiHi, 4)}`
        : undefined,
    },
    {
      label: 'Survival (point)',
      value: trace.survivalPoint !== null
        ? fmtNum(trace.survivalPoint, 6)
        : ABSENT_VALUE,
      status: trace.survivalPoint !== null ? 'pass' : 'fail',
      sublabel: trace.gPoint !== null
        ? `G_point = ${fmtNum(trace.gPoint, 4)}`
        : undefined,
    },
    {
      label: 'Survival (conservative)',
      value: trace.survivalConservative !== null
        ? fmtNum(trace.survivalConservative, 6)
        : ABSENT_VALUE,
      status: trace.survivalConservative !== null ? 'pass' : 'fail',
      sublabel: trace.gConservative !== null
        ? `G_conservative = ${fmtNum(trace.gConservative, 4)}`
        : undefined,
    },
    {
      label: 'Score Cap',
      value: trace.gCap !== null ? fmtNum(trace.gCap, 4) : ABSENT_VALUE,
      status: capBinding ? 'warn' : 'pass',
      sublabel: capBinding
        ? 'CAP IS BINDING (limited by sample size)'
        : trace.gCap !== null
          ? 'not binding'
          : undefined,
    },
    {
      label: 'Diagnostics',
      value: trace.diagPass === null
        ? ABSENT_VALUE
        : trace.diagPass ? 'PASS' : 'FAIL',
      status: trace.diagPass === null
        ? 'fail'
        : trace.diagPass ? 'pass' : 'warn',
      sublabel: `confidence tier: ${formatInteger(trace.confidenceTier)}`,
    },
  ];

  return (
    <section className="admin-v2-scoring-trace" aria-label={`Scoring trace for ${climb.roadName || 'unnamed climb'}`}>
      <header className="admin-v2-scoring-trace__header">
        <div>
          <h3>{climb.roadName || 'Unnamed climb'}</h3>
          <p>
            {formatMeters(climb.vertM)} vert
            {climb.distanceM ? ` | ${formatKilometers(climb.distanceM / 1000)}` : ''}
            {climb.avgGradientPct ? ` | ${formatPercent(climb.avgGradientPct)}` : ''}
          </p>
        </div>
        <button
          type="button"
          className="portal-sort-button admin-v2-scoring-trace__close"
          onClick={onClose}
          aria-label="Close scoring trace"
          title="Close scoring trace"
        >
          <X size={14} aria-hidden="true" />
        </button>
      </header>

      <ol className="admin-v2-scoring-trace__steps">
        {steps.map((step, i) => (
          <Step key={step.label} {...step} isLast={i === steps.length - 1} />
        ))}
      </ol>

      <section className="admin-v2-scoring-trace__final" data-tone={gScoreTone(trace.gFinal)}>
        <strong>Final Score</strong>
        <b>{formatSignificanceScore(trace.gFinal)}</b>
        <div>
          <span>{formatFixed(trace.percentile, 1)}th pctile</span>
          <span>~{formatInteger(trace.returnPeriod)} return period</span>
        </div>
      </section>
    </section>
  );
}
