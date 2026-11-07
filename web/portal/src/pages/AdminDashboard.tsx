import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Database,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  Zap,
} from 'lucide-react';
import { useAdminCheck } from '../hooks/useAdminCheck';
import { api } from '../lib/api';
import type { AdminActivityFeedItem, PlatformOverview } from '../lib/api';
import { ABSENT_VALUE, formatInteger } from '../lib/formatters';
import HealthBanner from '../components/admin/HealthBanner';
import OverviewTab from '../components/admin/OverviewTab';
import EconomyTab from '../components/admin/EconomyTab';
import SystemTab from '../components/admin/SystemTab';
import {
  PortalEmptyState,
  PortalFrame,
  PortalMetric,
  PortalPage,
  PortalPanel,
  PortalPanelBody,
  PortalStack,
  PortalTruthPill,
} from '../components/portal/PortalSpine';
import { cn } from '../components/ui/utils';

const POLL_INTERVAL_MS = 60_000;
const ScoringTab = lazy(() => import('../components/admin/ScoringTab'));
const ModerationTab = lazy(() => import('../components/admin/ModerationTab'));

const ADMIN_TABS = [
  { id: 'overview', label: 'Overview', icon: Activity },
  { id: 'economy', label: 'Economy', icon: Zap },
  { id: 'scoring', label: 'Scoring', icon: Database },
  { id: 'moderation', label: 'Moderation', icon: ShieldAlert },
  { id: 'system', label: 'System', icon: ShieldCheck },
];

export default function AdminDashboard() {
  const { isAdmin, isLoading: isAdminLoading } = useAdminCheck();

  const [activeTab, setActiveTab] = useState('overview');
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [activityFeed, setActivityFeed] = useState<AdminActivityFeedItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [ov, feed] = await Promise.all([
        api.getPlatformOverview(),
        api.getAdminActivityFeed(20),
      ]);
      setOverview(ov);
      setActivityFeed(feed.items ?? []);
    } catch {
      // Keep stale data on error.
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    void fetchData();
    const timer = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isAdmin, fetchData]);

  const healthLabel = overview?.healthStatus?.toUpperCase() ?? (isLoading ? 'LOADING' : 'UNKNOWN');
  const activeTabConfig = ADMIN_TABS.find((tab) => tab.id === activeTab) ?? ADMIN_TABS[0];

  if (isAdminLoading) {
    return (
      <PortalPage className="admin-v2-state">
        <PortalFrame>
          <PortalPanel>
            <PortalEmptyState
              icon={<Loader2 className="settings-v2-inline-spin" size={22} aria-hidden="true" />}
              title="Verifying access"
              description="Checking admin privileges before opening the command center."
            />
          </PortalPanel>
        </PortalFrame>
      </PortalPage>
    );
  }

  if (!isAdmin) {
    return (
      <PortalPage className="admin-v2-state">
        <PortalFrame>
          <PortalPanel>
            <PortalEmptyState
              icon={<ShieldOff size={24} aria-hidden="true" />}
              title="Access denied"
              description="This area requires admin privileges."
            />
          </PortalPanel>
        </PortalFrame>
      </PortalPage>
    );
  }

  return (
    <PortalPage className="admin-v2-page" aria-busy={isLoading} aria-live="polite">
      <PortalFrame>
        <PortalStack className="portal-stack--loose">
          <PortalPanel>
            <PortalPanelBody className="portal-page-hero admin-v2-hero">
              <div className="portal-page-hero__copy">
                <h1 className="portal-page-hero__title">Admin</h1>
                <div className="portal-page-hero__pending">
                  {activeTabConfig.label} / Live admin controls
                </div>
              </div>

              <div className="portal-metric-row admin-v2-hero__metrics" aria-label="Admin overview">
                <PortalMetric value={overview?.users?.total == null ? ABSENT_VALUE : formatInteger(overview.users.total)} label="Riders" />
                <PortalMetric value={overview?.rides?.total == null ? ABSENT_VALUE : formatInteger(overview.rides.total)} label="Rides" />
                <PortalMetric value={overview?.epoch?.currentEpoch == null ? ABSENT_VALUE : formatInteger(overview.epoch.currentEpoch)} label="Epoch" />
              </div>
            </PortalPanelBody>
          </PortalPanel>

          <HealthBanner
            data={overview}
            status={(
              <PortalTruthPill tone={healthLabel === 'HEALTHY' ? 'verified' : healthLabel === 'LOADING' ? 'muted' : 'warning'}>
                {healthLabel}
              </PortalTruthPill>
            )}
          />

          <PortalPanel className="admin-v2-tabs-panel">
            <PortalPanelBody className="admin-v2-tabs">
              {ADMIN_TABS.map((tab) => {
                const isActive = activeTab === tab.id;
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    className={cn('admin-v2-tab-button', isActive && 'admin-v2-tab-button--active')}
                    onClick={() => setActiveTab(tab.id)}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    <Icon size={15} aria-hidden="true" />
                    {tab.label}
                  </button>
                );
              })}
            </PortalPanelBody>
          </PortalPanel>

          {activeTab === 'overview' && (
            <OverviewTab overview={overview} activityFeed={activityFeed} isLoading={isLoading} />
          )}

          {activeTab === 'economy' && (
            <EconomyTab overview={overview} />
          )}

          {activeTab === 'scoring' && (
            <Suspense
              fallback={(
                <PortalPanel>
                  <PortalEmptyState
                    icon={<Loader2 className="settings-v2-inline-spin" size={20} aria-hidden="true" />}
                    title="Loading scoring tools"
                  />
                </PortalPanel>
              )}
            >
              <ScoringTab />
            </Suspense>
          )}

          {activeTab === 'moderation' && (
            <Suspense
              fallback={(
                <PortalPanel>
                  <PortalEmptyState
                    icon={<Loader2 className="settings-v2-inline-spin" size={20} aria-hidden="true" />}
                    title="Loading moderation queue"
                  />
                </PortalPanel>
              )}
            >
              <ModerationTab />
            </Suspense>
          )}

          {activeTab === 'system' && (
            <SystemTab />
          )}
        </PortalStack>
      </PortalFrame>
    </PortalPage>
  );
}
