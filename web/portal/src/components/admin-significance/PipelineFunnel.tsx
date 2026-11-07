import type { PipelineStats } from '../../lib/api';
import { formatInteger, formatPercent, roundToDigits } from '../../lib/formatters';
import {
  PortalEmptyState,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
} from '../portal/PortalSpine';

interface Stage {
  label: string;
  count: number;
}

interface PipelineFunnelProps {
  stats: PipelineStats | null;
}

function buildStages(stats: PipelineStats): Stage[] {
  return [
    { label: 'Detected', count: stats.climbsDetected },
    { label: 'Persistence', count: stats.climbsWithPersistence },
    { label: 'In Cell', count: stats.climbsInTerrainCell },
    { label: 'Scored', count: stats.climbsScored },
  ];
}

export default function PipelineFunnel({ stats }: PipelineFunnelProps) {
  if (!stats || stats.climbsDetected === 0) {
    return (
      <PortalPanel className="admin-v2-pipeline-panel">
        <PortalEmptyState
          className="admin-v2-compact-empty"
          title="No pipeline data yet"
        />
      </PortalPanel>
    );
  }

  const stages = buildStages(stats);
  const maxCount = stages[0].count;
  const dropoffMap = new Map<string, { delta: number; reason: string }>();
  for (const dropoff of stats.dropoffs) {
    dropoffMap.set(dropoff.stage, { delta: dropoff.from - dropoff.to, reason: dropoff.reason });
  }

  return (
    <PortalPanel className="admin-v2-pipeline-panel">
      <PortalPanelHeader title="Scoring Pipeline" meta={`${formatInteger(stats.climbsUnscored)} unscored`} />
      <PortalPanelBody className="admin-v2-pipeline">
        <p className="admin-v2-pipeline__intro">
          Detected climbs move through persistence, terrain-cell assignment, and GPD scoring.
        </p>

        <div className="admin-v2-pipeline__stages" aria-label="Scoring pipeline stages">
          {stages.map((stage, index) => {
            const dropPct = maxCount > 0 ? ((maxCount - stage.count) / maxCount) * 100 : 0;
            const roundedDropPct = roundToDigits(dropPct, 0);
            return (
              <div key={stage.label} className="admin-v2-pipeline__stage">
                <strong>{formatInteger(stage.count)}</strong>
                <span>{stage.label}</span>
                {roundedDropPct > 0
                  ? <em className="admin-v2-pipeline__stage-delta--mono">-{formatPercent(dropPct, 0)}</em>
                  : <em className="admin-v2-pipeline__stage-delta--sans">Start</em>}
                {index < stages.length - 1 ? <i aria-hidden="true" /> : null}
              </div>
            );
          })}
        </div>

        {stats.dropoffs.length > 0 ? (
          <div className="admin-v2-pipeline__dropoffs">
            {['persistence', 'terrain_cell', 'scored'].map((key) => {
              const dropoff = dropoffMap.get(key);
              if (!dropoff || dropoff.delta === 0) return null;
              const isLarge = dropoff.delta > stages[0].count * 0.3;
              return (
                <span key={key} className={isLarge ? 'admin-v2-pipeline__dropoff--critical' : undefined}>
                  <strong>-{formatInteger(dropoff.delta)}</strong>
                  <span>{dropoff.reason}</span>
                </span>
              );
            })}
          </div>
        ) : null}

        {stats.climbsUnscored > 0 ? (
          <div className="admin-v2-inline-alert admin-v2-inline-alert--warning">
            {formatInteger(stats.climbsUnscored)} climbs unscored (awaiting terrain data)
          </div>
        ) : null}
      </PortalPanelBody>
    </PortalPanel>
  );
}
