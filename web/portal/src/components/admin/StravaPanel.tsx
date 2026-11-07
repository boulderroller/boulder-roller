import { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, Radio, RefreshCw, Unplug } from 'lucide-react';

import { api } from '../../lib/api';
import type { StravaAdminHealth } from '../../lib/api';
import {
  ABSENT_VALUE,
  formatDateTime,
  formatIdentifier,
  formatInteger,
  formatPercent as formatPercentage,
  formatSecondsLabel,
} from '../../lib/formatters';
import {
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
  PortalTruthPill,
} from '../portal/PortalSpine';
import { cn } from '../ui/utils';

const POLL_INTERVAL_MS = 60_000;

function Stat({
  label,
  value,
  context,
}: {
  label: string;
  value: string | number;
  context?: string;
}) {
  return (
    <div className="admin-v2-stat">
      <span>{label}</span>
      <strong>{value}</strong>
      {context ? <em>{context}</em> : null}
    </div>
  );
}

function formatPercent(usage: number, limit: number): string {
  if (!Number.isFinite(usage) || !Number.isFinite(limit) || limit <= 0) return ABSENT_VALUE;
  return formatPercentage((usage / limit) * 100, 0);
}

function healthTone(status: string): 'verified' | 'warning' {
  return status === 'HEALTHY' ? 'verified' : 'warning';
}

function integrationSummary(data: StravaAdminHealth): string {
  if (!data.stateVerified) return 'Cutover state unavailable';
  if (data.integrationMode === 'file_import_only') {
    return data.subscription.active || data.connections.activeCount > 0
      ? 'File-import cutover incomplete'
      : 'File imports only · Strava sync retired';
  }
  return data.subscription.active
    ? `Subscription ${formatIdentifier(data.subscription.subscriptionId)}`
    : 'No active subscription';
}

export default function StravaPanel() {
  const [data, setData] = useState<StravaAdminHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<'subscribe' | 'delete' | 'refresh' | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const snapshot = await api.getAdminStravaHealth();
      setData(snapshot);
      setError(null);
    } catch {
      setData(null);
      setError('Failed to load Strava health');
    } finally {
      setLoading(false);
      setActionLoading((current) => (current === 'refresh' ? null : current));
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const timer = setInterval(fetchHealth, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchHealth]);

  const handleRefresh = async () => {
    setActionLoading('refresh');
    await fetchHealth();
  };

  const handleSubscribe = async () => {
    setActionLoading('subscribe');
    try {
      await api.createAdminStravaSubscription();
      await fetchHealth();
    } catch {
      setError('Failed to register Strava webhook');
      setActionLoading(null);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Delete the active Strava webhook subscription?')) return;
    setActionLoading('delete');
    try {
      await api.deleteAdminStravaSubscription();
      await fetchHealth();
    } catch {
      setError('Failed to delete Strava webhook');
      setActionLoading(null);
    }
  };

  if (loading) {
    return (
      <PortalPanel>
        <PortalPanelBody className="admin-v2-loading-panel">
          <span />
          <strong />
          <em />
        </PortalPanelBody>
      </PortalPanel>
    );
  }

  const healthStatus = data?.healthStatus?.toUpperCase() ?? 'CRITICAL';
  const fileImportOnly = data?.integrationMode === 'file_import_only';
  const stateVerified = data?.stateVerified === true;
  const quota15 = data ? formatPercent(data.rateLimits.usage15min, data.rateLimits.limit15min) : ABSENT_VALUE;
  const quotaDaily = data ? formatPercent(data.rateLimits.usageDaily, data.rateLimits.limitDaily) : ABSENT_VALUE;

  return (
    <PortalPanel className="admin-v2-strava-panel">
      <PortalPanelHeader
        title="Strava Integration"
        meta={<PortalTruthPill tone={healthTone(healthStatus)}>{healthStatus}</PortalTruthPill>}
      >
        <button
          type="button"
          onClick={handleRefresh}
          disabled={actionLoading !== null}
          className="portal-sort-button admin-v2-compact-button"
        >
          <RefreshCw className={cn('admin-v2-button-icon', actionLoading === 'refresh' && 'admin-v2-icon-spin')} aria-hidden="true" />
          Refresh
        </button>
      </PortalPanelHeader>

      <PortalPanelBody className="admin-v2-system-stack">
        {data ? (
          <div className="admin-v2-strava-status">
            <span className={cn('portal-status-dot', `admin-v2-status-dot--${healthStatus.toLowerCase()}`)} aria-hidden="true" />
            <strong>{integrationSummary(data)}</strong>
          </div>
        ) : null}

        {error ? <div className="admin-v2-inline-alert admin-v2-inline-alert--danger">{error}</div> : null}

        {data ? (
          <>
            <div className="admin-v2-stat-grid">
              <Stat
                label="Active Grants"
                value={stateVerified ? formatInteger(data.connections.activeCount) : 'Unavailable'}
                context={stateVerified
                  ? `${formatInteger(data.connections.recentSync24h)} synced in 24h`
                  : 'Database state not verified'}
              />
              <Stat
                label="15m Quota"
                value={`${formatInteger(data.rateLimits.usage15min)}/${formatInteger(data.rateLimits.limit15min)}`}
                context={`${quota15} used`}
              />
              <Stat
                label="Daily Quota"
                value={`${formatInteger(data.rateLimits.usageDaily)}/${formatInteger(data.rateLimits.limitDaily)}`}
                context={`${quotaDaily} used`}
              />
              <Stat
                label="Backfill"
                value={stateVerified ? formatInteger(data.backfill.inProgress ?? 0) : 'Unavailable'}
                context={stateVerified
                  ? `${formatInteger(data.backfill.complete ?? 0)} complete`
                  : 'Database state not verified'}
              />
            </div>

            <div className="admin-v2-detail-grid">
              <div>
                <div className="admin-v2-section-label">
                  <Radio size={13} aria-hidden="true" />
                  Subscription
                </div>
                <dl>
                  <div>
                    <dt>Callback</dt>
                    <dd className={cn('admin-v2-detail-grid__value', (data.subscription.callbackUrl || data.webhookCallbackUrl) ? 'admin-v2-detail-grid__value--mono' : 'admin-v2-detail-grid__value--sans')}>
                      {data.subscription.callbackUrl || data.webhookCallbackUrl || 'Not configured'}
                    </dd>
                  </div>
                  <div>
                    <dt>Redirect</dt>
                    <dd className={cn('admin-v2-detail-grid__value', data.redirectUri ? 'admin-v2-detail-grid__value--mono' : 'admin-v2-detail-grid__value--sans')}>
                      {data.redirectUri || 'Not configured'}
                    </dd>
                  </div>
                  <div>
                    <dt>Created</dt>
                    <dd className={cn(
                      'admin-v2-detail-grid__value',
                      stateVerified && data.subscription.createdAt
                        ? 'admin-v2-detail-grid__value--mono'
                        : 'admin-v2-detail-grid__value--sans',
                    )}>
                      {stateVerified ? formatDateTime(data.subscription.createdAt) : 'Unavailable'}
                    </dd>
                  </div>
                  <div>
                    <dt>Last Webhook</dt>
                    <dd className={cn(
                      'admin-v2-detail-grid__value',
                      stateVerified && data.connections.lastWebhookAt
                        ? 'admin-v2-detail-grid__value--mono'
                        : 'admin-v2-detail-grid__value--sans',
                    )}>
                      {stateVerified ? formatDateTime(data.connections.lastWebhookAt) : 'Unavailable'}
                    </dd>
                  </div>
                </dl>
              </div>

              <div>
                <div className="admin-v2-section-label">
                  <Activity size={13} aria-hidden="true" />
                  Runtime
                </div>
                <dl>
                  <div><dt>Limiter Storage</dt><dd className="admin-v2-detail-grid__value admin-v2-detail-grid__value--mono">{data.rateLimits.storage}</dd></div>
                  <div><dt>Redis Shared State</dt><dd className="admin-v2-detail-grid__value admin-v2-detail-grid__value--sans">{data.rateLimits.redisAvailable ? 'Yes' : 'No'}</dd></div>
                  <div><dt>15m Reset In</dt><dd className="admin-v2-detail-grid__value admin-v2-detail-grid__value--mono">{formatSecondsLabel(data.rateLimits.resetInSeconds15min)}</dd></div>
                  <div><dt>Stale Syncs 7d</dt><dd className="admin-v2-detail-grid__value admin-v2-detail-grid__value--mono">{stateVerified ? formatInteger(data.connections.staleSync7d) : 'Unavailable'}</dd></div>
                </dl>
              </div>
            </div>

            {fileImportOnly ? (
              <div className="admin-v2-strava-status">
                <Unplug size={14} aria-hidden="true" />
                <strong>OAuth, webhook ingest, backfill, and re-subscription are disabled server-side.</strong>
              </div>
            ) : !stateVerified ? (
              <div className="admin-v2-strava-status">
                <AlertTriangle size={14} aria-hidden="true" />
                <strong>Subscription actions are unavailable until state can be verified.</strong>
              </div>
            ) : (
              <div className="admin-v2-button-row">
                {data.subscription.active ? (
                  <button
                    type="button"
                    onClick={handleDelete}
                    disabled={actionLoading !== null}
                    className="portal-sort-button admin-v2-danger-action"
                  >
                    <Unplug size={14} aria-hidden="true" />
                    {actionLoading === 'delete' ? 'Deleting' : 'Delete Webhook'}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleSubscribe}
                    disabled={actionLoading !== null || !data.enabled}
                    className="portal-action-button"
                  >
                    {actionLoading === 'subscribe' ? 'Registering' : 'Register Webhook'}
                  </button>
                )}
              </div>
            )}

            {data.alerts.length > 0 ? (
              <div className="admin-v2-inline-alert admin-v2-inline-alert--warning">
                <AlertTriangle size={14} aria-hidden="true" />
                <div>
                  {data.alerts.map((alert) => (
                    <span key={alert}>{alert}</span>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="admin-v2-snapshot">Snapshot: {formatDateTime(data.generatedAt)}</div>
          </>
        ) : null}
      </PortalPanelBody>
    </PortalPanel>
  );
}
