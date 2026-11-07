/**
 * VaultPanel - Sidebar panel showing matched/created vaults
 *
 * ONLY shows vaults that exist on this ride - empty when no vaults matched.
 * Climb patterns belong in RideRoomLedger, not here.
 *
 * Design System:
 * - Geist Sans for UI, Geist Mono for data
 * - Portal CSS variables for climb/reward states
 * - Industrial-utilitarian aesthetic
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useFormatters } from '../../hooks/useFormatters';
import { BeetleButton } from '../ui/beetle-button';
import { cn } from '../ui/utils';
import {
  Flag,
  Trophy,
  Crown,
  Coins,
  TrendingUp,
  ChevronRight,
  Gauge,
  Compass,
  ChevronDown,
  Star,
  Sparkles,
} from 'lucide-react';
import { ClimbPattern, SteadyPattern, ExplorationPattern } from '../../lib/api';
import { ABSENT_VALUE, formatInteger, formatTokenAmount } from '../../lib/formatters';

// ============================================================================
// TYPES
// ============================================================================

interface VaultPanelProps {
  /** Climb patterns - we filter to only show those with vaultMatch */
  climbPatterns?: ClimbPattern[];
  /** Optional steady state data */
  steadyPattern?: SteadyPattern | null;
  /** Optional exploration data */
  explorationPattern?: ExplorationPattern | null;
  /** Summary text */
  summary?: string;
  /** Total CAL earned from crossing vaults on this ride */
  totalVaultEarnings?: number;
}

interface VaultMatch {
  id?: string;
  vaultId: number;
  vaultClimbId?: string | null;
  name?: string | null;
  // Real completion-backed facts; the backend only sends fields it can
  // truthfully source from chain-backed projections.
  yourTime?: number | null;
  yourRank?: number | null;
  yourBestTime?: number | null;
  isPR?: boolean | null;
  komTime?: number | null;
  komHolder?: string | null;
}

// ============================================================================
// VAULT CARD
// ============================================================================

interface VaultCardProps {
  vault: VaultMatch;
  climbVertM: number;
  climbGradient: number;
  onNavigate: () => void;
}

function VaultCard({ vault, climbVertM, climbGradient, onNavigate }: VaultCardProps) {
  const {
    elevation: formatElevation,
    percent: formatPercent,
    raceTime: formatRaceTime,
    secondsLabel: formatSecondsLabel,
  } = useFormatters();

  const formatTime = (seconds: number | undefined) => seconds ? formatRaceTime(seconds) : ABSENT_VALUE;

  // Determine border and highlight based on rank
  const isKom = vault.yourRank === 1;
  const isPodium = Boolean(vault.yourRank && vault.yourRank <= 3);
  const isTop10 = Boolean(vault.yourRank && vault.yourRank <= 10);
  const achievementTone = isKom ? 'kom' : isPodium ? 'podium' : vault.isPR ? 'pr' : 'top-10';
  const comparisonIsBetter = Boolean(
    vault.yourBestTime && vault.yourTime && vault.yourTime < vault.yourBestTime,
  );
  const gradientTone = climbGradient >= 8 ? 'danger' : climbGradient >= 5 ? 'reward' : 'default';
  const rankTone = vault.yourRank === 1 ? 'gold' : vault.yourRank && vault.yourRank <= 3 ? 'reward' : 'default';

  return (
    <div
      className={cn(
        'ride-vault-card',
        isKom && 'ride-vault-card--kom',
        !isKom && isPodium && 'ride-vault-card--podium',
      )}
      onClick={onNavigate}
    >
      {/* Celebration banner for achievements */}
      {(isTop10 || vault.isPR) && (
        <div className={cn('ride-vault-card__achievement', `ride-vault-card__achievement--${achievementTone}`)}>
          <div className="ride-vault-card__achievement-main">
            {isKom ? (
              <>
                <Crown size={12} />
                <span className="ride-vault-card__achievement-label">
                  KOM!
                </span>
              </>
            ) : isPodium ? (
              <>
                <Trophy size={12} />
                <span className="ride-vault-card__achievement-label">
                  #{formatInteger(vault.yourRank)}
                </span>
              </>
            ) : isTop10 ? (
              <>
                <Sparkles size={12} />
                <span className="ride-vault-card__achievement-label">
                  Top 10
                </span>
              </>
            ) : null}
          </div>
          {vault.isPR && (
            <div className="ride-vault-card__pr">
              <Star size={10} fill="currentColor" />
              <span className="ride-vault-card__pr-label">
                New PR!
              </span>
              {typeof vault.yourBestTime === 'number' && vault.yourBestTime > 0
                && typeof vault.yourTime === 'number' && vault.yourTime > 0
                && vault.yourBestTime !== vault.yourTime && (
                <span className="ride-vault-card__pr-delta">
                  {vault.yourBestTime > vault.yourTime
                    ? `${formatSecondsLabel(vault.yourBestTime - vault.yourTime)} faster`
                    : `${formatSecondsLabel(vault.yourTime - vault.yourBestTime)} slower`}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* PR comparison when not in top 10 but still beat previous time */}
      {!isTop10 && !vault.isPR
        && typeof vault.yourBestTime === 'number' && vault.yourBestTime > 0
        && typeof vault.yourTime === 'number' && vault.yourTime > 0
        && vault.yourBestTime !== vault.yourTime && (
        <div
          className={cn(
            'ride-vault-card__comparison',
            comparisonIsBetter ? 'ride-vault-card__comparison--better' : 'ride-vault-card__comparison--slower',
          )}
        >
          <span className="ride-vault-card__comparison-text">
            {vault.yourTime < vault.yourBestTime
              ? `${formatSecondsLabel(vault.yourBestTime - vault.yourTime)} faster than your best`
              : `${formatSecondsLabel(vault.yourTime - vault.yourBestTime)} slower than PR`}
          </span>
        </div>
      )}

      {/* Main content */}
      <div className="ride-vault-card__body">
        {/* Header */}
        <div className="ride-vault-card__header">
          <div className="ride-vault-card__identity">
            <div className={cn('ride-vault-card__badge', isKom && 'ride-vault-card__badge--kom')}>
              {isKom ? (
                <Crown size={14} />
              ) : (
                <Trophy size={14} />
              )}
            </div>
            <div className="ride-vault-card__text">
              <div className="ride-vault-card__name">
                {vault.name}
              </div>
            </div>
          </div>
          <ChevronRight className="ride-vault-card__chevron" size={14} />
        </div>

        {/* Stats Grid */}
        <div className="ride-vault-card__metrics">
          <div className="ride-vault-card__metric">
            <div className="ride-vault-card__metric-value">
              {formatElevation(climbVertM)}
            </div>
            <div className="ride-vault-card__metric-label">
              Vert
            </div>
          </div>
          <div className="ride-vault-card__metric">
            <div className={cn('ride-vault-card__metric-value', `ride-vault-card__metric-value--${gradientTone}`)}>
              {formatPercent(climbGradient)}
            </div>
            <div className="ride-vault-card__metric-label">
              Grad
            </div>
          </div>
          <div className="ride-vault-card__metric">
            <div className="ride-vault-card__metric-value ride-vault-card__metric-value--gold ride-vault-card__metric-value--inline">
              <Crown size={9} />
              {formatTime(vault.komTime ?? undefined)}
            </div>
            <div className="ride-vault-card__metric-label">
              KOM
            </div>
          </div>
        </div>

        {/* Your rank on the matched climb vault. */}
        {(vault.yourRank ?? 0) > 0 && (
          <div className="ride-vault-card__position">
            <span className="ride-vault-card__position-label">
              Your place
            </span>
            <div className="ride-vault-card__position-values">
              <span className={cn('ride-vault-card__rank', `ride-vault-card__rank--${rankTone}`)}>
                #{formatInteger(vault.yourRank)}
              </span>
              <span className="ride-vault-card__time">
                {formatTime(vault.yourTime ?? vault.yourBestTime ?? undefined)}
              </span>
              {/* Gap to KOM */}
              {typeof vault.komTime === 'number' && vault.komTime > 0
                && vault.yourRank !== 1
                && typeof vault.yourTime === 'number' && vault.yourTime > 0 && (
                <span className="ride-vault-card__gap">
                  (+{formatTime(vault.yourTime - vault.komTime)})
                </span>
              )}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="ride-vault-card__actions">
          <BeetleButton
            variant="primary"
            size="sm"
            className="ride-vault-card__action"
            onClick={(e) => {
              e.stopPropagation();
              onNavigate();
            }}
          >
            <Coins size={11} />
            Open
          </BeetleButton>
          <BeetleButton
            variant="secondary"
            size="sm"
            className="ride-vault-card__action"
            onClick={(e) => {
              e.stopPropagation();
              onNavigate();
            }}
          >
            <TrendingUp size={11} />
            Details
          </BeetleButton>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// EMPTY STATE - Compact, not wasteful
// ============================================================================

function EmptyVaultState() {
  return (
    <div className="ride-vault-empty">
      <div className="ride-vault-empty__row">
        <Flag size={14} className="ride-vault-empty__icon" aria-hidden="true" />
        <span className="ride-vault-empty__title">
          No vaults on this ride yet
        </span>
      </div>
      <p className="ride-vault-empty__text">
        Open a climb below to start one.
      </p>
    </div>
  );
}

// ============================================================================
// SUPPLEMENTAL PATTERNS (Steady + Exploration)
// ============================================================================

interface SupplementalSectionProps {
  steadyPattern?: SteadyPattern | null;
  explorationPattern?: ExplorationPattern | null;
}

function SupplementalPatterns({ steadyPattern, explorationPattern }: SupplementalSectionProps) {
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    steady: false,
    exploration: false,
  });
  const {
    hoursMinutes: formatHoursMinutes,
    percent: formatPercent,
    watts: formatWatts,
  } = useFormatters();

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => ({ ...prev, [section]: !prev[section] }));
  };

  if (!steadyPattern && !explorationPattern) return null;

  return (
    <div className="ride-vault-supplemental">
      {/* Steady State */}
      {steadyPattern && (
        <div className="ride-vault-supplemental__section">
          <button
            type="button"
            onClick={() => toggleSection('steady')}
            className="ride-vault-supplemental__trigger"
          >
            <div className="ride-vault-supplemental__trigger-main">
              <Gauge size={12} className="ride-vault-supplemental__icon ride-vault-supplemental__icon--steady" aria-hidden="true" />
              <span className="ride-vault-supplemental__title">
                Steady State
              </span>
            </div>
            {expandedSections.steady ? (
              <ChevronDown size={12} className="ride-vault-supplemental__chevron" aria-hidden="true" />
            ) : (
              <ChevronRight size={12} className="ride-vault-supplemental__chevron" aria-hidden="true" />
            )}
          </button>

          {expandedSections.steady && (
            <div className="ride-vault-supplemental__body">
              <div className="ride-vault-supplemental__metrics">
                <div className="ride-vault-supplemental__metric">
                  <div className="ride-vault-supplemental__metric-value">
                    {formatHoursMinutes(steadyPattern.durationS)}
                  </div>
                  <div className="ride-vault-supplemental__metric-label">
                    Duration
                  </div>
                </div>
                {(steadyPattern.avgPowerW ?? 0) > 0 && (
                  <div className="ride-vault-supplemental__metric">
                    <div className="ride-vault-supplemental__metric-value">
                      {formatWatts(steadyPattern.avgPowerW)}
                    </div>
                    <div className="ride-vault-supplemental__metric-label">
                      Avg Power
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Exploration */}
      {explorationPattern && (
        <div className="ride-vault-supplemental__section">
          <button
            type="button"
            onClick={() => toggleSection('exploration')}
            className="ride-vault-supplemental__trigger"
          >
            <div className="ride-vault-supplemental__trigger-main">
              <Compass size={12} className="ride-vault-supplemental__icon ride-vault-supplemental__icon--exploration" aria-hidden="true" />
              <span className="ride-vault-supplemental__title">
                Exploration
              </span>
              {explorationPattern.newTilesWallet > 0 && (
                <span className="ride-vault-supplemental__badge">
                  +{formatInteger(explorationPattern.newTilesWallet)}
                </span>
              )}
            </div>
            {expandedSections.exploration ? (
              <ChevronDown size={12} className="ride-vault-supplemental__chevron" aria-hidden="true" />
            ) : (
              <ChevronRight size={12} className="ride-vault-supplemental__chevron" aria-hidden="true" />
            )}
          </button>

          {expandedSections.exploration && (
            <div className="ride-vault-supplemental__body">
              <div className="ride-vault-supplemental__metrics ride-vault-supplemental__metrics--three">
                <div className="ride-vault-supplemental__metric">
                  <div className="ride-vault-supplemental__metric-value ride-vault-supplemental__metric-value--exploration">
                    {formatInteger(explorationPattern.newTilesWallet)}
                  </div>
                  <div className="ride-vault-supplemental__metric-label">
                    New
                  </div>
                </div>
                <div className="ride-vault-supplemental__metric">
                  <div className="ride-vault-supplemental__metric-value">
                    {formatInteger(explorationPattern.totalTiles)}
                  </div>
                  <div className="ride-vault-supplemental__metric-label">
                    Total
                  </div>
                </div>
                <div className="ride-vault-supplemental__metric">
                  <div
                    className={cn(
                      'ride-vault-supplemental__metric-value',
                      (explorationPattern.discoveryPct ?? 0) > 30 && 'ride-vault-supplemental__metric-value--exploration',
                    )}
                  >
                    {formatPercent(explorationPattern.discoveryPct ?? 0, 0)}
                  </div>
                  <div className="ride-vault-supplemental__metric-label">
                    Discovery
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function VaultPanel({
  climbPatterns = [],
  steadyPattern,
  explorationPattern,
  summary,
  totalVaultEarnings,
}: VaultPanelProps) {
  const navigate = useNavigate();

  // Filter to only climbs with vault matches
  const matchedVaults = climbPatterns
    .filter((c) => c.vaultMatch)
    .map((c) => ({
      vault: c.vaultMatch!,
      climbId: c.vaultMatch!.vaultClimbId ?? c.climbId ?? c.segmentId,
      vertM: c.vertM,
      gradient: c.avgGradientPct ?? 0,
    }));

  return (
    <div className="ride-vault-panel">
      {/* Header */}
      <div className="ride-vault-panel__header">
        <div className="ride-vault-panel__title-row">
          <Flag size={12} className="ride-vault-panel__flag" aria-hidden="true" />
          <h3 className="ride-vault-panel__title">
            Vaults
          </h3>
          {matchedVaults.length > 0 && (
            <span className="ride-vault-panel__count">
              {formatInteger(matchedVaults.length)}
            </span>
          )}
        </div>
        {summary && (
          <p className="ride-vault-panel__summary">
            {summary}
          </p>
        )}

        {/* Total earnings from vault completions */}
        {totalVaultEarnings !== undefined && totalVaultEarnings > 0 && matchedVaults.length > 0 && (
          <div className="ride-vault-panel__earnings">
            <div className="ride-vault-panel__earnings-row">
              <span className="ride-vault-panel__earnings-label">
                Vault CAL
              </span>
              <span className="ride-vault-panel__earnings-value">
                +{formatTokenAmount(totalVaultEarnings)}
              </span>
            </div>
            <p className="ride-vault-panel__earnings-note">
              Counted from {formatInteger(matchedVaults.length)} climb vault{matchedVaults.length > 1 ? 's' : ''}
            </p>
          </div>
        )}
      </div>

      {/* Scrollable Content */}
      <div className="ride-vault-panel__content">
        {matchedVaults.length === 0 ? (
          <EmptyVaultState />
        ) : (
          <div className="ride-vault-panel__cards">
            {matchedVaults.map((item, index) => (
              <VaultCard
                key={item.vault.vaultId || index}
                vault={item.vault}
                climbVertM={item.vertM}
                climbGradient={item.gradient}
                onNavigate={() => navigate(
                  item.climbId
                    ? `/climbs/${encodeURIComponent(item.climbId)}`
                    : `/vaults/${item.vault.vaultId}`,
                )}
              />
            ))}
          </div>
        )}

        {/* Supplemental patterns */}
        <SupplementalPatterns
          steadyPattern={steadyPattern}
          explorationPattern={explorationPattern}
        />
      </div>
    </div>
  );
}
