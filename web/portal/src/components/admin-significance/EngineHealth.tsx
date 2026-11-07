import { useMemo } from 'react';

import type { DriftSummary, PipelineStats, SignificanceOverview } from '../../lib/api';
import { formatFixed, formatInteger } from '../../lib/formatters';
import { PortalPanel, PortalPanelBody, PortalPanelHeader, PortalTruthPill } from '../portal/PortalSpine';
import { cn } from '../ui/utils';

interface EngineHealthProps {
  overview: SignificanceOverview;
  pipelineStats: PipelineStats | null;
  driftSummary?: DriftSummary | null;
}

type HealthLevel = 'healthy' | 'degraded' | 'broken';

interface HealthBullet {
  text: string;
  level: HealthLevel;
}

function terrainLabel(meanXi: number): string {
  if (meanXi > 0.1) return 'mountainous';
  if (meanXi > -0.05) return 'rolling';
  return 'flat';
}

function assessHealth(
  overview: SignificanceOverview,
  pipelineStats: PipelineStats | null,
  driftSummary?: DriftSummary | null,
): { bullets: HealthBullet[]; overallLevel: HealthLevel } {
  const bullets: HealthBullet[] = [];
  const terrainCells = overview.terrainCells;
  const climbScores = overview.climbScores;
  const gpdParams = overview.gpdParams;

  if (terrainCells.total === 0) {
    bullets.push({
      text: 'No terrain cells fitted. Bootstrap terrain from ride data to begin scoring.',
      level: 'broken',
    });
  } else if (terrainCells.total < 5) {
    bullets.push({
      text: `Early bootstrap: ${formatInteger(terrainCells.total)} cell${terrainCells.total === 1 ? '' : 's'} fitted. Scoring is empirical -- need more cells for geographic coverage.`,
      level: 'degraded',
    });
  }

  if (terrainCells.total > 0 && terrainCells.diagPassCount === 0) {
    bullets.push({
      text: 'No cells pass tail diagnostics yet. This is expected with limited data (need k >= 12 exceedances per cell).',
      level: 'degraded',
    });
  }

  if (climbScores.unscored > 0) {
    bullets.push({
      text: `${formatInteger(climbScores.unscored)} climb${climbScores.unscored === 1 ? '' : 's'} awaiting scoring. Run backfill to score against existing terrain cells.`,
      level: 'degraded',
    });
  }

  if (climbScores.scored > 2 && climbScores.gHistogram.length > 0) {
    const totalCount = climbScores.gHistogram.reduce((sum, bin) => sum + bin.count, 0);
    if (totalCount > 0) {
      const mean = climbScores.gHistogram.reduce((sum, bin) => sum + bin.bin * bin.count, 0) / totalCount;
      const variance = climbScores.gHistogram.reduce((sum, bin) => sum + bin.count * (bin.bin - mean) ** 2, 0) / totalCount;
      const stdDev = Math.sqrt(variance);
      if (stdDev < 0.05) {
        bullets.push({
          text: `Warning: scores are tightly clustered (std dev ${formatFixed(stdDev, 3)}). Model may not discriminate well.`,
          level: 'degraded',
        });
      }
    }
  }

  if (gpdParams.xiStats.mean !== undefined && terrainCells.total > 0) {
    bullets.push({
      text: `Terrain profile: ${terrainLabel(gpdParams.xiStats.mean)} based on mean xi=${formatFixed(gpdParams.xiStats.mean, 3)}`,
      level: 'healthy',
    });
  }

  if (pipelineStats) {
    const { climbsDetected, climbsWithPersistence, climbsInTerrainCell } = pipelineStats;
    if (climbsWithPersistence > 0 && climbsInTerrainCell === 0) {
      bullets.push({
        text: `${formatInteger(climbsWithPersistence)} climbs have persistence but none map to a terrain cell. Bootstrap needed.`,
        level: 'broken',
      });
    } else if (climbsDetected > 0 && climbsWithPersistence === 0) {
      bullets.push({
        text: `${formatInteger(climbsDetected)} climbs detected but none have persistence values. Check climb detector output.`,
        level: 'broken',
      });
    }
  }

  if (driftSummary) {
    if (driftSummary.driftedCells > 0) {
      bullets.push({
        text: `Parameter drift: ${formatInteger(driftSummary.driftedCells)} cell${driftSummary.driftedCells === 1 ? '' : 's'} drifted in last bootstrap (score impact > 0.05). Re-score stale climbs.`,
        level: 'degraded',
      });
    }
    if (driftSummary.staleClimbs > 0) {
      bullets.push({
        text: `${formatInteger(driftSummary.staleClimbs)} stale climb${driftSummary.staleClimbs === 1 ? '' : 's'} need re-scoring after parameter drift.`,
        level: 'degraded',
      });
    }
  }

  let overallLevel: HealthLevel = 'healthy';
  if (bullets.some((bullet) => bullet.level === 'broken')) {
    overallLevel = 'broken';
  } else if (bullets.some((bullet) => bullet.level === 'degraded')) {
    overallLevel = 'degraded';
  }

  if (bullets.length === 0 || (bullets.length === 1 && bullets[0].level === 'healthy')) {
    if (terrainCells.total > 0 && climbScores.scored > 0) {
      bullets.unshift({
        text: `Engine healthy: ${formatInteger(terrainCells.total)} cells, ${formatInteger(climbScores.scored)} climbs scored, ${formatInteger(terrainCells.diagPassCount)} diagnostics passing.`,
        level: 'healthy',
      });
    }
  }

  return { bullets, overallLevel };
}

function healthTone(level: HealthLevel): 'verified' | 'muted' | 'warning' {
  if (level === 'healthy') return 'verified';
  if (level === 'degraded') return 'muted';
  return 'warning';
}

export default function EngineHealth({ overview, pipelineStats, driftSummary }: EngineHealthProps) {
  const { bullets, overallLevel } = useMemo(
    () => assessHealth(overview, pipelineStats, driftSummary),
    [overview, pipelineStats, driftSummary],
  );

  return (
    <PortalPanel className={cn('admin-v2-engine-health', `admin-v2-engine-health--${overallLevel}`)}>
      <PortalPanelHeader
        title="Engine Health"
        meta={<PortalTruthPill tone={healthTone(overallLevel)}>{overallLevel}</PortalTruthPill>}
      />
      <PortalPanelBody>
        <ul className="admin-v2-engine-health__list">
          {bullets.map((bullet) => (
            <li key={bullet.text} className={cn('admin-v2-engine-health__item', `admin-v2-engine-health__item--${bullet.level}`)}>
              <span aria-hidden="true" />
              <strong>{bullet.text}</strong>
            </li>
          ))}
        </ul>
      </PortalPanelBody>
    </PortalPanel>
  );
}
