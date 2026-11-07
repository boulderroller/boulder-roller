import {
  PortalMetric,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
} from '../portal/PortalSpine';
import SupplyGauge from './SupplyGauge';
import type { PlatformOverview } from '../../lib/api';
import { ABSENT_VALUE, formatInteger, formatPercent, formatTokenAmount } from '../../lib/formatters';

interface EconomyTabProps {
  overview: PlatformOverview | null;
}

export default function EconomyTab({ overview }: EconomyTabProps) {
  if (!overview) {
    return (
      <div className="admin-v2-tab-surface">
        {[...Array(3)].map((_, i) => (
          <PortalPanel key={i}>
            <PortalPanelBody className="admin-v2-loading-panel">
              <span />
              <strong />
              <em />
            </PortalPanelBody>
          </PortalPanel>
        ))}
      </div>
    );
  }

  const totalStaked = overview.vaults?.totalStakedCal ?? 0;
  const uniqueStakers = overview.vaults?.uniqueStakers ?? 0;
  const avgStake = uniqueStakers > 0 ? totalStaked / uniqueStakers : 0;
  const emission = overview.emission;
  const currentEpoch = overview.epoch?.currentEpoch ?? 0;

  return (
    <div className="admin-v2-tab-surface">
      <SupplyGauge supply={overview.supply ?? null} />

      <div className="admin-v2-panel-grid admin-v2-panel-grid--two">
        <PortalPanel className="admin-v2-economy-card">
          <PortalPanelHeader title="Vault TVL" meta="Stake" />
          <PortalPanelBody className="admin-v2-metric-grid admin-v2-metric-grid--three">
            <PortalMetric value={formatTokenAmount(totalStaked)} label="Total Staked" />
            <PortalMetric value={formatInteger(uniqueStakers)} label="Unique Stakers" />
            <PortalMetric value={avgStake > 0 ? formatTokenAmount(avgStake) : ABSENT_VALUE} label="Avg Stake" />
          </PortalPanelBody>
        </PortalPanel>

        <PortalPanel className="admin-v2-economy-card">
          <PortalPanelHeader title="Emission Schedule" meta="Epoch" />
          <PortalPanelBody className="admin-v2-metric-grid admin-v2-metric-grid--three">
            <PortalMetric value={formatInteger(currentEpoch)} label="Current Epoch" />
            <PortalMetric
              value={emission ? formatPercent(emission.currentEmissionRateBps / 100) : ABSENT_VALUE}
              label="Emission Rate"
            />
            <PortalMetric value={formatInteger(emission?.totalHalvings ?? 0)} label="Total Halvings" />
          </PortalPanelBody>
        </PortalPanel>
      </div>
    </div>
  );
}
