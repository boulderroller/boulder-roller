import { Users, Mountain, Activity, Zap, TrendingUp, Award } from 'lucide-react';
import KpiCard from './KpiCard';
import AdminActivityFeed from './ActivityFeed';
import QuickActions from './QuickActions';
import type { PlatformOverview, AdminActivityFeedItem } from '../../lib/api';
import { ABSENT_VALUE, formatInteger, formatPercent } from '../../lib/formatters';
import { formatCompactBaseUnits, isPositiveBaseUnits } from '../../lib/tokenAmounts';

interface OverviewTabProps {
  overview: PlatformOverview | null;
  activityFeed: AdminActivityFeedItem[];
  isLoading: boolean;
}

export default function OverviewTab({ overview, activityFeed, isLoading }: OverviewTabProps) {
  if (isLoading || !overview) {
    return (
      <div className="admin-v2-overview">
        <div className="admin-v2-overview__kpis">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="admin-v2-overview-skeleton" />
          ))}
        </div>
        <AdminActivityFeed items={[]} isLoading />
      </div>
    );
  }

  return (
    <div className="admin-v2-overview">
      <div className="admin-v2-overview__kpis">
        <KpiCard
          icon={Users}
          label="Total Riders"
          value={formatInteger(overview.users.total)}
          context={overview.users.new7d > 0 ? `+${formatInteger(overview.users.new7d)} this week` : undefined}
        />
        <KpiCard
          icon={Mountain}
          label="Total Climbs"
          value={formatInteger(overview.climbs.total)}
          context={overview.climbs.scored > 0 ? `${formatPercent(overview.climbs.pctScored, 0)} scored` : undefined}
        />
        <KpiCard
          icon={Activity}
          label="Total Rides"
          value={formatInteger(overview.rides.total)}
          context={overview.rides.thisWeek > 0 ? `+${formatInteger(overview.rides.thisWeek)} this week` : undefined}
        />
        <KpiCard
          icon={Zap}
          label="DUNG Circulating"
          value={overview.supply.circulatingSupplyBaseUnits == null
            ? ABSENT_VALUE
            : formatCompactBaseUnits(overview.supply.circulatingSupplyBaseUnits, 9)}
          context={isPositiveBaseUnits(overview.supply.totalMintedBaseUnits)
            ? `${formatCompactBaseUnits(overview.supply.totalMintedBaseUnits, 9)} minted`
            : undefined}
        />
        <KpiCard
          icon={TrendingUp}
          label="Active Vaults"
          value={formatInteger(overview.vaults.total)}
          context={overview.vaults.totalCompletions > 0 ? `${formatInteger(overview.vaults.totalCompletions)} completions` : undefined}
        />
        <KpiCard
          icon={Award}
          label="Current Epoch"
          value={formatInteger(overview.epoch.currentEpoch)}
          context={overview.epoch.epochNeedsTransition ? 'Needs transition' : overview.epoch.pendingDistributions > 0 ? `${formatInteger(overview.epoch.pendingDistributions)} pending` : 'Up to date'}
        />
      </div>

      <div className="admin-v2-overview__content">
        <div className="admin-v2-overview__activity">
          <AdminActivityFeed items={activityFeed} />
        </div>
        <QuickActions />
      </div>
    </div>
  );
}
