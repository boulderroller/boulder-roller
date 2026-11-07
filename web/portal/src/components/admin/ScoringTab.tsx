import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import { Database, RefreshCw, RotateCcw, ShieldCheck, X, Zap } from 'lucide-react';

import { api } from '../../lib/api';
import type {
  DriftSummary,
  PipelineStats,
  ReviewCategory,
  ReviewStatus,
  SignificanceClimb,
  SignificanceOverview,
  TerrainCell,
} from '../../lib/api';
import {
  ABSENT_VALUE,
  formatDate,
  formatFixed,
  formatInteger,
  formatKilometers,
  formatMeters,
  formatPercent,
  formatSignificanceScore,
} from '../../lib/formatters';
import EngineHealth from '../admin-significance/EngineHealth';
import PipelineFunnel from '../admin-significance/PipelineFunnel';
import ScoringTrace from '../admin-significance/ScoringTrace';
import {
  PortalEmptyState,
  PortalMetric,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
  PortalTruthPill,
} from '../portal/PortalSpine';
import { cn } from '../ui/utils';

const TerrainMap = lazy(() => import('../admin-significance/TerrainMap'));
const GpdFitChart = lazy(() => import('../admin-significance/GpdFitChart'));
const ElevationProfile = lazy(() => import('../admin-significance/ElevationProfile'));

const TIER_NAMES = ['Empirical', 'Low', 'Moderate', 'Full'] as const;
const SORT_OPTIONS = [
  ['g_desc', 'G Score'],
  ['percentile_desc', 'Percentile'],
  ['return_period_desc', 'Return Period'],
  ['vert_desc', 'Vert'],
  ['persistence_desc', 'Persistence'],
] as const;

const REVIEW_CATEGORIES: ReviewCategory[] = [
  'noise',
  'too_short',
  'duplicate',
  'sensor_error',
  'misattributed',
  'borderline',
  'other',
];

type ScoreTone = 'base' | 'steady' | 'strong' | 'elite';
type HealthTone = 'success' | 'warning' | 'danger' | 'muted';

function tierName(tier: number): string {
  return TIER_NAMES[tier] ?? `Tier ${formatInteger(tier)}`;
}

function scoreTone(score: number): ScoreTone {
  if (score >= 0.7) return 'elite';
  if (score >= 0.4) return 'strong';
  if (score >= 0.15) return 'steady';
  return 'base';
}

function reviewLabel(status: ReviewStatus): string {
  if (!status) return 'unreviewed';
  return status.replace('_', ' ');
}

function reviewTone(status: ReviewStatus): 'verified' | 'muted' | 'warning' {
  if (status === 'confirmed' || status === 'auto_confirmed') return 'verified';
  if (status === 'false_positive' || status === 'disputed') return 'warning';
  return 'muted';
}

function healthToneClass(tone: HealthTone): string {
  return `admin-v2-health-bullet--${tone}`;
}

function ReviewDot({ status }: { status: ReviewStatus }) {
  if (!status) return null;

  return (
    <span
      className={cn('admin-v2-review-dot', `admin-v2-review-dot--${status}`)}
      title={reviewLabel(status)}
      aria-label={reviewLabel(status)}
    >
      {status === 'false_positive' ? <span>FP</span> : null}
    </span>
  );
}

function TierDots({ tier, size = 'regular' }: { tier: number; size?: 'regular' | 'compact' }) {
  const clampedTier = Math.min(Math.max(Math.round(tier), 0), 3);

  return (
    <span className={cn('admin-v2-tier-dots', `admin-v2-tier-dots--tier-${clampedTier}`, `admin-v2-tier-dots--${size}`)} title={tierName(clampedTier)}>
      <span className="admin-v2-tier-dots__grid" aria-hidden="true">
        {[0, 1, 2, 3].map((dot) => (
          <span
            key={dot}
            className={cn('admin-v2-tier-dots__dot', dot <= clampedTier && 'admin-v2-tier-dots__dot--active')}
          />
        ))}
      </span>
      <span className="admin-v2-tier-dots__label">{tierName(clampedTier)}</span>
    </span>
  );
}

function LazyCardFallback({ label }: { label: string }) {
  return (
    <PortalPanel>
      <PortalPanelBody>
        <div className="admin-v2-loading-panel" aria-label={`Loading ${label}`}>
          <span />
          <strong />
          <em />
        </div>
      </PortalPanelBody>
    </PortalPanel>
  );
}

function ReviewActions({
  climb,
  onReviewComplete,
}: {
  climb: SignificanceClimb;
  onReviewComplete: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [category, setCategory] = useState<ReviewCategory>('other');

  const doReview = async (verdict: 'confirmed' | 'false_positive' | 'disputed') => {
    setLoading(true);
    setMessage(null);
    try {
      const result = await api.reviewClimb(climb.id, {
        verdict,
        reason: reason || undefined,
        category: verdict === 'false_positive' ? category : undefined,
      });
      setMessage(`${result.verdict} (was: ${result.previousStatus ?? 'unreviewed'})`);
      onReviewComplete();
    } catch (err) {
      setMessage(`Error: ${err instanceof Error ? err.message : 'unknown'}`);
    } finally {
      setLoading(false);
    }
  };

  const doRevert = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const result = await api.revertClimbReview(climb.id);
      setMessage(`Reverted from ${result.previousStatus ?? 'unknown'}`);
      onReviewComplete();
    } catch (err) {
      setMessage(`Error: ${err instanceof Error ? err.message : 'unknown'}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <PortalPanel>
      <PortalPanelHeader
        title="Review Actions"
        meta={reviewLabel(climb.reviewStatus)}
      />
      <PortalPanelBody className="admin-v2-scoring-review">
        {climb.reviewStatus ? (
          <div className="admin-v2-inline-alert admin-v2-inline-alert--warning">
            <div>
              <strong>Current status</strong>
              <span>
                {reviewLabel(climb.reviewStatus)}
                {climb.reviewedAt ? ` / ${formatDate(climb.reviewedAt)}` : ''}
              </span>
            </div>
          </div>
        ) : null}

        <div className="admin-v2-scoring-review__fields">
          <input
            type="text"
            placeholder="Reason (optional)"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="admin-v2-input"
          />
          <select
            value={category}
            onChange={(event) => setCategory(event.target.value as ReviewCategory)}
            className="admin-v2-input admin-v2-select"
            aria-label="False positive category"
          >
            {REVIEW_CATEGORIES.map((value) => (
              <option key={value} value={value}>
                {value.replace('_', ' ')}
              </option>
            ))}
          </select>
        </div>

        <div className="admin-v2-button-row">
          <button
            type="button"
            onClick={() => doReview('confirmed')}
            disabled={loading}
            className="portal-action-button admin-v2-success-action"
          >
            Confirm
          </button>
          <button
            type="button"
            onClick={() => doReview('false_positive')}
            disabled={loading}
            className="portal-sort-button admin-v2-danger-action"
          >
            False Positive
          </button>
          <button
            type="button"
            onClick={() => doReview('disputed')}
            disabled={loading}
            className="portal-sort-button admin-v2-warning-action"
          >
            Dispute
          </button>
          {climb.reviewStatus ? (
            <button
              type="button"
              onClick={doRevert}
              disabled={loading}
              className="portal-sort-button"
            >
              <RotateCcw size={14} aria-hidden="true" />
              Revert
            </button>
          ) : null}
        </div>

        {message ? (
          <div className={cn('admin-v2-inline-alert', message.startsWith('Error') ? 'admin-v2-inline-alert--danger' : 'admin-v2-inline-alert--success')}>
            {message}
          </div>
        ) : null}
      </PortalPanelBody>
    </PortalPanel>
  );
}

function ScoreSummary({ climb }: { climb: SignificanceClimb }) {
  return (
    <PortalPanel>
      <PortalPanelHeader
        title="Score Summary"
        meta={climb.significanceCellH3 ? `Cell ${climb.significanceCellH3}` : 'No cell'}
      />
      <PortalPanelBody>
        <div className="admin-v2-score-summary-grid">
          <PortalMetric
            value={<span className={cn('admin-v2-score-value', `admin-v2-score-value--${scoreTone(climb.significanceG)}`)}>{formatSignificanceScore(climb.significanceG)}</span>}
            label="G Score"
          />
          <PortalMetric value={formatPercent(climb.significancePercentile)} label="Percentile" />
          <PortalMetric value={`~${formatInteger(climb.significanceReturnPeriod)}`} label="Return" />
          <div className="admin-v2-score-summary-grid__tier">
            <span>Tier</span>
            <TierDots tier={climb.significanceConfidenceTier} />
          </div>
        </div>
      </PortalPanelBody>
    </PortalPanel>
  );
}

function ClimbDrawer({
  climb,
  onClose,
  onReviewComplete,
}: {
  climb: SignificanceClimb;
  onClose: () => void;
  onReviewComplete: () => void;
}) {
  return (
    <>
      <button
        type="button"
        className="admin-v2-scoring-backdrop"
        aria-label="Close climb detail"
        onClick={onClose}
      />
      <aside className="admin-v2-scoring-drawer" aria-label="Climb scoring detail">
        <header className="admin-v2-scoring-drawer__header">
          <div className="admin-v2-scoring-drawer__title">
            <div>
              <ReviewDot status={climb.reviewStatus} />
              <strong>{climb.roadName || 'Unnamed climb'}</strong>
              <PortalTruthPill tone={reviewTone(climb.reviewStatus)}>
                {reviewLabel(climb.reviewStatus)}
              </PortalTruthPill>
            </div>
            <span>
              {formatMeters(climb.vertM)} vert
              {climb.avgGradientPct != null ? ` / ${formatPercent(climb.avgGradientPct)} grade` : ''}
              {climb.distanceM != null ? ` / ${formatKilometers(climb.distanceM / 1000)}` : ''}
            </span>
          </div>
          <button
            type="button"
            className="portal-sort-button admin-v2-scoring-drawer__close"
            onClick={onClose}
            aria-label="Close climb detail"
            title="Close climb detail"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </header>

        <div className="admin-v2-scoring-drawer__body">
          <ScoreSummary climb={climb} />

          <Suspense fallback={<LazyCardFallback label="elevation profile" />}>
            <ElevationProfile climbId={climb.id} onClose={onClose} />
          </Suspense>

          <ScoringTrace climbId={climb.id} onClose={onClose} />

          {climb.significanceCellH3 ? (
            <Suspense fallback={<LazyCardFallback label="fit chart" />}>
              <GpdFitChart h3Index={climb.significanceCellH3} />
            </Suspense>
          ) : null}

          <ReviewActions climb={climb} onReviewComplete={onReviewComplete} />
        </div>
      </aside>
    </>
  );
}

function ScoreHealthSummary({ overview }: { overview: SignificanceOverview }) {
  const climbScores = overview.climbScores;
  const terrainCells = overview.terrainCells;

  const scoredPct = climbScores.total > 0 ? Math.round((climbScores.scored / climbScores.total) * 100) : 0;
  const diagPassPct = terrainCells.total > 0 ? Math.round((terrainCells.diagPassCount / terrainCells.total) * 100) : 0;
  const highTierCount = (terrainCells.byConfidenceTier['2'] ?? 0) + (terrainCells.byConfidenceTier['3'] ?? 0);
  const highTierPct = terrainCells.total > 0 ? Math.round((highTierCount / terrainCells.total) * 100) : 0;

  const bullets: { text: string; tone: HealthTone }[] = [];

  if (climbScores.total === 0) {
    bullets.push({ text: 'No climbs detected yet. Upload rides to populate.', tone: 'muted' });
  } else {
    bullets.push({
      text: `${formatPercent(scoredPct, 0)} of climbs scored (${formatInteger(climbScores.scored)} of ${formatInteger(climbScores.total)})`,
      tone: scoredPct >= 90 ? 'success' : scoredPct >= 50 ? 'warning' : 'danger',
    });
  }

  if (terrainCells.total > 0) {
    bullets.push({
      text: `${formatPercent(diagPassPct, 0)} terrain cells passing diagnostics`,
      tone: diagPassPct >= 80 ? 'success' : diagPassPct >= 50 ? 'warning' : 'danger',
    });
    bullets.push({
      text: `${formatPercent(highTierPct, 0)} high-confidence coverage (Moderate + Full tier)`,
      tone: highTierPct >= 50 ? 'success' : highTierPct >= 20 ? 'warning' : 'muted',
    });
  }

  if (climbScores.unscored > 0) {
    bullets.push({
      text: `${formatInteger(climbScores.unscored)} climbs awaiting scoring`,
      tone: 'warning',
    });
  }

  return (
    <PortalPanel>
      <PortalPanelHeader title="Score Health" meta="Plain English" />
      <PortalPanelBody>
        <div className="admin-v2-health-bullets">
          {bullets.map((bullet) => (
            <div key={bullet.text} className={cn('admin-v2-health-bullet', healthToneClass(bullet.tone))}>
              <span aria-hidden="true" />
              <strong>{bullet.text}</strong>
            </div>
          ))}
        </div>
      </PortalPanelBody>
    </PortalPanel>
  );
}

export default function ScoringTab() {
  const [overview, setOverview] = useState<SignificanceOverview | null>(null);
  const [climbs, setClimbs] = useState<SignificanceClimb[]>([]);
  const [climbsTotal, setClimbsTotal] = useState(0);
  const [cells, setCells] = useState<TerrainCell[]>([]);
  const [pipelineStats, setPipelineStats] = useState<PipelineStats | null>(null);
  const [driftSummary, setDriftSummary] = useState<DriftSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [climbSort, setClimbSort] = useState('g_desc');
  const [drawerClimb, setDrawerClimb] = useState<SignificanceClimb | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [ov, cl, ce, ps, ds] = await Promise.all([
        api.getSignificanceOverview(),
        api.getSignificanceClimbs({ limit: 50, sort: climbSort }),
        api.getSignificanceCells({ limit: 200 }),
        api.getPipelineStats().catch(() => null),
        api.getDriftSummary().catch(() => null),
      ]);
      setOverview(ov);
      setClimbs(cl.climbs);
      setClimbsTotal(cl.total);
      setCells(ce.cells);
      setPipelineStats(ps);
      setDriftSummary(ds);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [climbSort]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const uniqueClimbs = useMemo(() => {
    const grouped = new Map<string, { climb: SignificanceClimb; count: number }>();
    for (const climb of climbs) {
      const key = `${formatFixed(climb.vertM, 0)}-${formatFixed(climb.persistenceM ?? climb.vertM, 0)}`;
      const existing = grouped.get(key);
      if (!existing) {
        grouped.set(key, { climb, count: 1 });
      } else {
        existing.count += 1;
        const hasName = climb.roadName && climb.roadName !== '';
        const existingHasName = existing.climb.roadName && existing.climb.roadName !== '';
        if ((!existingHasName && hasName) || (hasName === existingHasName && climb.significanceG > existing.climb.significanceG)) {
          existing.climb = climb;
        }
      }
    }
    return Array.from(grouped.values()).slice(0, 20);
  }, [climbs]);

  const handleBootstrap = async () => {
    setActionLoading(true);
    setActionMsg(null);
    try {
      const result = await api.triggerTerrainBootstrap();
      setActionMsg(result.message);
      void fetchData();
    } catch (err) {
      setActionMsg(`Error: ${err instanceof Error ? err.message : 'unknown'}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleBackfill = async () => {
    setActionLoading(true);
    setActionMsg(null);
    try {
      const result = await api.backfillScores({ limit: 100 });
      setActionMsg(`Backfill: ${formatInteger(result.scored)} scored, ${formatInteger(result.noTerrainData)} no terrain data (of ${formatInteger(result.processed)} processed)`);
      void fetchData();
    } catch (err) {
      setActionMsg(`Error: ${err instanceof Error ? err.message : 'unknown'}`);
    } finally {
      setActionLoading(false);
    }
  };

  const handleAutoConfirm = async () => {
    setActionLoading(true);
    setActionMsg(null);
    try {
      const result = await api.autoConfirmClimbs({ minG: 0.4, minPersistence: 20, minConfidenceTier: 2 });
      setActionMsg(`Auto-confirm: ${formatInteger(result.confirmed)} confirmed of ${formatInteger(result.candidates)} candidates`);
      void fetchData();
    } catch (err) {
      setActionMsg(`Error: ${err instanceof Error ? err.message : 'unknown'}`);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="admin-v2-tab-surface">
        <PortalPanel>
          <PortalPanelBody>
            <div className="admin-v2-loading-panel" aria-label="Loading scoring data">
              <span />
              <strong />
              <em />
            </div>
          </PortalPanelBody>
        </PortalPanel>
      </div>
    );
  }

  if (error) {
    return (
      <div className="admin-v2-tab-surface">
        <PortalPanel>
          <PortalPanelHeader title="Scoring unavailable" meta="Retry available" />
          <PortalPanelBody className="admin-v2-system-stack">
            <div className="admin-v2-inline-alert admin-v2-inline-alert--danger">
              {error}
            </div>
            <div className="admin-v2-button-row">
              <button type="button" className="portal-sort-button" onClick={fetchData}>
                <RefreshCw size={14} aria-hidden="true" />
                Retry
              </button>
            </div>
          </PortalPanelBody>
        </PortalPanel>
      </div>
    );
  }

  if (!overview) return null;

  const climbScores = overview.climbScores;

  return (
    <div className="admin-v2-tab-surface">
      <div className="admin-v2-panel-grid admin-v2-panel-grid--two admin-v2-scoring-health-grid">
        <EngineHealth overview={overview} pipelineStats={pipelineStats} driftSummary={driftSummary} />
        <PipelineFunnel stats={pipelineStats} />
      </div>

      <ScoreHealthSummary overview={overview} />

      <PortalPanel>
        <PortalPanelHeader title="Scoring Commands" meta="Terrain and review jobs" />
        <PortalPanelBody className="admin-v2-scoring-command-body">
          <div className="admin-v2-button-row">
            <button
              type="button"
              onClick={handleBootstrap}
              disabled={actionLoading}
              className="portal-action-button"
            >
              <Database size={14} aria-hidden="true" />
              Bootstrap Terrain
            </button>
            <button
              type="button"
              onClick={handleBackfill}
              disabled={actionLoading}
              className="portal-sort-button"
            >
              <Zap size={14} aria-hidden="true" />
              Backfill ({formatInteger(climbScores.unscored)})
            </button>
            <button
              type="button"
              onClick={handleAutoConfirm}
              disabled={actionLoading}
              className="portal-sort-button admin-v2-success-action"
            >
              <ShieldCheck size={14} aria-hidden="true" />
              Auto-Confirm
            </button>
            <button
              type="button"
              onClick={fetchData}
              disabled={loading}
              className="portal-sort-button"
            >
              <RefreshCw size={14} aria-hidden="true" />
              Refresh
            </button>
          </div>

          {actionMsg ? (
            <div className={cn('admin-v2-inline-alert', actionMsg.startsWith('Error') ? 'admin-v2-inline-alert--danger' : 'admin-v2-inline-alert--success')}>
              {actionMsg}
            </div>
          ) : null}
        </PortalPanelBody>
      </PortalPanel>

      <PortalPanel className="admin-v2-terrain-map-panel">
        <PortalPanelHeader title="Terrain Map" meta={`${formatInteger(cells.length)} cells / ${formatInteger(uniqueClimbs.length)} climbs`} />
        <PortalPanelBody>
          <div className="admin-v2-terrain-map-shell">
            <Suspense fallback={<LazyCardFallback label="terrain map" />}>
              <TerrainMap
                cells={cells}
                climbs={uniqueClimbs.map((entry) => entry.climb)}
                selectedClimb={drawerClimb}
                selectedCell={null}
                onSelectClimb={(climb) => setDrawerClimb(climb)}
                onSelectCell={() => {}}
              />
            </Suspense>
          </div>
        </PortalPanelBody>
      </PortalPanel>

      <PortalPanel>
        <PortalPanelHeader
          title="Top Climbs"
          meta={`${formatInteger(uniqueClimbs.length)} shown / ${formatInteger(climbsTotal)} total`}
        >
          <select
            value={climbSort}
            onChange={(event) => setClimbSort(event.target.value)}
            className="admin-v2-input admin-v2-select admin-v2-scoring-sort"
            aria-label="Sort climbs"
          >
            {SORT_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </PortalPanelHeader>
        <PortalPanelBody>
          {uniqueClimbs.length === 0 ? (
            <PortalEmptyState
              className="admin-v2-compact-empty"
              icon={<Database size={20} aria-hidden="true" />}
              title="No scored climbs yet"
              description="Bootstrap terrain cells first."
            />
          ) : (
            <div className="admin-v2-scoring-table">
              <div className="admin-v2-scoring-table__head" aria-hidden="true">
                {['Name', 'Vert', 'Grade', 'G Score', 'Pctile', 'Return', 'Tier'].map((heading) => (
                  <span key={heading}>{heading}</span>
                ))}
              </div>

              {uniqueClimbs.map(({ climb, count }) => (
                <button
                  key={climb.id}
                  type="button"
                  className={cn('admin-v2-scoring-table__row', drawerClimb?.id === climb.id && 'admin-v2-scoring-table__row--selected')}
                  onClick={() => setDrawerClimb(climb)}
                >
                  <span className="admin-v2-scoring-table__name">
                    <ReviewDot status={climb.reviewStatus} />
                    <strong>{climb.roadName || 'Unnamed climb'}</strong>
                    {count > 1 ? <em>x{formatInteger(count)}</em> : null}
                  </span>
                  <span>{formatMeters(climb.vertM)}</span>
                  <span>{climb.avgGradientPct != null ? formatPercent(climb.avgGradientPct) : ABSENT_VALUE}</span>
                  <span className={cn('admin-v2-score-value', `admin-v2-score-value--${scoreTone(climb.significanceG)}`)}>
                    {formatSignificanceScore(climb.significanceG)}
                  </span>
                  <span>{formatPercent(climb.significancePercentile)}</span>
                  <span>~{formatInteger(climb.significanceReturnPeriod)}</span>
                  <TierDots tier={climb.significanceConfidenceTier} size="compact" />
                </button>
              ))}
            </div>
          )}
        </PortalPanelBody>
      </PortalPanel>

      {drawerClimb ? (
        <ClimbDrawer
          climb={drawerClimb}
          onClose={() => setDrawerClimb(null)}
          onReviewComplete={fetchData}
        />
      ) : null}
    </div>
  );
}
