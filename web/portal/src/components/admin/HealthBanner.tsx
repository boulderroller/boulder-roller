import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, ShieldAlert } from 'lucide-react';
import type { PlatformOverview } from '../../lib/api';
import { PortalPanel, PortalPanelBody } from '../portal/PortalSpine';
import { ABSENT_VALUE, formatInteger } from '../../lib/formatters';

type HealthStatus = 'healthy' | 'warning' | 'critical';

function deriveHealth(data: PlatformOverview | null): HealthStatus {
  if (!data) return 'critical';
  const s = data.healthStatus?.toUpperCase();
  if (s === 'CRITICAL') return 'critical';
  if (s === 'WARNING') return 'warning';
  return 'healthy';
}

const STATUS_CONFIG: Record<HealthStatus, { label: string; icon: typeof CheckCircle2 }> = {
  healthy: { label: 'Healthy', icon: CheckCircle2 },
  warning: { label: 'Warning', icon: AlertTriangle },
  critical: { label: 'Critical', icon: ShieldAlert },
};

interface HealthBannerProps {
  data: PlatformOverview | null;
  status: ReactNode;
}

export default function HealthBanner({ data, status }: HealthBannerProps) {
  const health = deriveHealth(data);
  const cfg = STATUS_CONFIG[health];
  const StatusIcon = cfg.icon;

  const riders = data?.users?.total == null ? ABSENT_VALUE : formatInteger(data.users.total);
  const climbs = data?.climbs?.total == null ? ABSENT_VALUE : formatInteger(data.climbs.total);
  const epoch = data?.epoch?.currentEpoch == null ? ABSENT_VALUE : formatInteger(data.epoch.currentEpoch);
  const pending = data?.epoch?.pendingDistributions ?? 0;

  return (
    <PortalPanel className={`admin-v2-health admin-v2-health--${health}`}>
      <PortalPanelBody className="admin-v2-health__body">
        <div className="admin-v2-health__status">
          <StatusIcon size={16} aria-hidden="true" />
          <span>Platform: {cfg.label}</span>
          {status}
        </div>
        <div className="admin-v2-health__facts">
          <span>{riders} riders</span>
          <span>{climbs} climbs</span>
          <span>
            Epoch {epoch}{pending > 0 ? ` (${formatInteger(pending)} pending)` : ''}
          </span>
        </div>
      </PortalPanelBody>
    </PortalPanel>
  );
}
