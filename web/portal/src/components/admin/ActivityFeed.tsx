import {
  Activity,
  Award,
  Mountain,
  Shield,
  Users,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { AdminActivityFeedItem } from '../../lib/api';
import { formatDateTime, formatInteger } from '../../lib/formatters';
import { PortalPanel, PortalPanelBody, PortalPanelHeader } from '../portal/PortalSpine';

const EVENT_ICON_MAP: Record<string, LucideIcon> = {
  ride_upload: Activity,
  vault_completion: Mountain,
  vault_created: Mountain,
  leaderboard_bump: Award,
  admin_action: Shield,
  user_signup: Users,
};

interface AdminActivityFeedProps {
  items: AdminActivityFeedItem[];
  isLoading?: boolean;
}

export default function AdminActivityFeed({ items, isLoading }: AdminActivityFeedProps) {
  return (
    <PortalPanel>
      <PortalPanelHeader title="Events" meta={isLoading ? 'Loading' : `${formatInteger(items.length)} events`} />
      <PortalPanelBody>
        {isLoading ? (
          <div className="admin-v2-activity-skeleton">
            {[...Array(5)].map((_, i) => (
              <div key={i}>
                <span />
                <strong />
                <em />
              </div>
            ))}
          </div>
        ) : items.length === 0 ? (
          <p className="admin-v2-empty-copy">No recent activity</p>
        ) : (
          <div className="admin-v2-activity-list">
            {items.map((item, idx) => {
              const Icon = EVENT_ICON_MAP[item.eventType] || Activity;
              return (
                <div key={item.id || idx} className="admin-v2-activity-row">
                  <Icon size={15} aria-hidden="true" />
                  <span>{item.detail || item.eventType}</span>
                  <time>{formatDateTime(item.createdAt)}</time>
                </div>
              );
            })}
          </div>
        )}
      </PortalPanelBody>
    </PortalPanel>
  );
}
