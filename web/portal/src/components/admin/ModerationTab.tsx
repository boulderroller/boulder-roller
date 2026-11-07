import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Flag, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';

import { api, type SocialReport } from '../../lib/api';
import { formatDateTime, formatInteger } from '../../lib/formatters';
import { getPublicRiderDisplayName, getPublicRiderPath } from '../../lib/riderIdentity';
import {
  PortalEmptyState,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
  PortalTruthPill,
} from '../portal/PortalSpine';
import { cn } from '../ui/utils';

type ReportStatusFilter = 'open' | 'reviewing' | 'resolved' | 'dismissed' | 'all';
type ReportResolutionStatus = 'open' | 'reviewing' | 'resolved' | 'dismissed';
type ReportResolutionAction = 'review_started' | 'leave_visible' | 'hide' | 'remove' | 'unsupported';

const FILTERS: ReportStatusFilter[] = ['open', 'reviewing', 'resolved', 'dismissed', 'all'];

function reporterRider(report: SocialReport) {
  return {
    id: report.reporter?.id ?? report.reporterId,
    username: report.reporter?.username,
    displayName: report.reporter?.displayName,
  };
}

function reporterLabel(report: SocialReport): string {
  return getPublicRiderDisplayName(reporterRider(report));
}

function formatReportDate(value?: string | null): string {
  if (!value) return 'pending';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'pending';
  return formatDateTime(date);
}

function targetPresentation(report: SocialReport): { label: string; path: string | null; riderPath?: string } {
  if (report.targetType === 'user') {
    const riderPath = getPublicRiderPath({ id: report.targetId });
    return { label: 'Reported rider', path: riderPath, riderPath };
  }

  if (report.targetType === 'ride') {
    return { label: `Ride ${report.targetId.slice(0, 8)}`, path: `/activities/${encodeURIComponent(report.targetId)}` };
  }

  return { label: `Comment ${report.targetId.slice(0, 8)}`, path: null };
}

function statusTone(status: SocialReport['status']): 'verified' | 'muted' | 'warning' {
  if (status === 'resolved') return 'verified';
  if (status === 'dismissed') return 'muted';
  return 'warning';
}

export default function ModerationTab() {
  const [filter, setFilter] = useState<ReportStatusFilter>('open');
  const [reports, setReports] = useState<SocialReport[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [busyReportId, setBusyReportId] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    try {
      setIsLoading(true);
      const response = await api.getModerationReports({
        status: filter === 'all' ? undefined : filter,
        limit: 50,
      });
      setReports(response.reports ?? []);
    } catch {
      toast.error('FAILED TO LOAD REPORTS');
    } finally {
      setIsLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const resolveReport = useCallback(async (
    reportId: string,
    status: ReportResolutionStatus,
    action?: ReportResolutionAction,
    resolutionNote?: string,
  ) => {
    try {
      setBusyReportId(reportId);
      const updated = await api.resolveModerationReport(reportId, status, resolutionNote, action);
      setReports((current) => current.map((report) => report.id === reportId ? updated : report));
      toast.success(status === 'reviewing' ? 'REPORT CLAIMED' : 'REPORT UPDATED');
    } catch {
      toast.error('FAILED TO UPDATE REPORT');
    } finally {
      setBusyReportId(null);
    }
  }, []);

  return (
    <div className="admin-v2-tab-surface">
      <PortalPanel className="admin-v2-moderation-panel">
        <PortalPanelHeader
          title="Moderation Queue"
          meta={isLoading ? 'Loading' : `${formatInteger(reports.length)} reports`}
        >
          <button
            type="button"
            className="portal-sort-button admin-v2-compact-button"
            onClick={loadReports}
            disabled={isLoading}
          >
            <RefreshCw className={cn('admin-v2-button-icon', isLoading && 'admin-v2-icon-spin')} aria-hidden="true" />
            Refresh
          </button>
        </PortalPanelHeader>

        <PortalPanelBody className="admin-v2-moderation-body">
          <div className="admin-v2-moderation-toolbar">
            <div>
              <strong>Reported rides, comments, and riders</strong>
              <span>Live moderation queue</span>
            </div>

            <div className="admin-v2-filter-row" role="tablist" aria-label="Moderation report status">
              {FILTERS.map((status) => {
                const active = filter === status;
                return (
                  <button
                    key={status}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    className={cn('portal-sort-button admin-v2-filter-button', active && 'admin-v2-filter-button--active')}
                    onClick={() => setFilter(status)}
                  >
                    {status}
                  </button>
                );
              })}
            </div>
          </div>

          {isLoading ? (
            <div className="admin-v2-loading-panel">
              <span />
              <strong />
              <em />
            </div>
          ) : reports.length === 0 ? (
            <PortalEmptyState
              className="admin-v2-compact-empty"
              icon={<Flag size={20} aria-hidden="true" />}
              title="No reports in this queue"
            />
          ) : (
            <div className="admin-v2-report-list">
              {reports.map((report) => (
                <ReportRow
                  key={report.id}
                  report={report}
                  busy={busyReportId === report.id}
                  onResolve={resolveReport}
                />
              ))}
            </div>
          )}
        </PortalPanelBody>
      </PortalPanel>
    </div>
  );
}

function ReportRow({
  report,
  busy,
  onResolve,
}: {
  report: SocialReport;
  busy: boolean;
  onResolve: (
    reportId: string,
    status: ReportResolutionStatus,
    action?: ReportResolutionAction,
    resolutionNote?: string,
  ) => void;
}) {
  const reporterPath = getPublicRiderPath(reporterRider(report));
  const target = targetPresentation(report);

  return (
    <div className="admin-v2-report-row">
      <div className="admin-v2-report-row__icon" aria-hidden="true">
        <Flag size={16} />
      </div>

      <div className="admin-v2-report-row__content">
        <div className="admin-v2-report-row__heading">
          {target.path ? (
            <Link
              to={target.path}
              className="admin-v2-report-row__target"
              data-rider-path={target.riderPath}
            >
              <strong>{target.label}</strong>
            </Link>
          ) : (
            <strong>{target.label}</strong>
          )}
          <PortalTruthPill tone={statusTone(report.status)}>{report.status}</PortalTruthPill>
        </div>

        <div className="admin-v2-report-row__meta">
          {report.reason} by{' '}
          <Link
            to={reporterPath}
            className="admin-v2-report-row__reporter"
            data-rider-path={reporterPath}
          >
            {reporterLabel(report)}
          </Link>
          {' '}/ {formatReportDate(report.createdAt)}
        </div>

        {report.details ? (
          <p>{report.details}</p>
        ) : null}

        {report.resolutionNote ? (
          <p>Resolution: {report.resolutionNote}</p>
        ) : null}

        {report.reporterOutcome ? (
          <p>Reporter outcome: {report.reporterOutcome}</p>
        ) : null}

        {report.resolutionAction ? (
          <div className="admin-v2-report-row__action">
            Action: {report.resolutionAction}
            {report.actionHistory?.[0]?.actionStatus ? ` (${report.actionHistory[0].actionStatus})` : ''}
          </div>
        ) : null}
      </div>

      <div className="admin-v2-report-row__actions">
        {report.status === 'open' ? (
          <button
            type="button"
            className="portal-sort-button"
            disabled={busy}
            onClick={() => onResolve(report.id, 'reviewing', 'review_started')}
          >
            Reviewing
          </button>
        ) : null}
        {report.status !== 'resolved' ? (
          <button
            type="button"
            className="portal-action-button"
            disabled={busy}
            onClick={() => onResolve(report.id, 'resolved', 'leave_visible', 'Resolved in moderation queue')}
          >
            Resolve
          </button>
        ) : null}
        {report.status !== 'resolved' ? (
          <button
            type="button"
            className="portal-sort-button"
            disabled={busy}
            onClick={() => onResolve(report.id, 'resolved', 'hide', 'Content hidden by moderation')}
          >
            Hide
          </button>
        ) : null}
        {report.status !== 'resolved' ? (
          <button
            type="button"
            className="portal-sort-button admin-v2-danger-action"
            disabled={busy}
            onClick={() => onResolve(report.id, 'resolved', 'remove', 'Content removed by moderation')}
          >
            Remove
          </button>
        ) : null}
        {report.status !== 'dismissed' ? (
          <button
            type="button"
            className="portal-sort-button admin-v2-danger-action"
            disabled={busy}
            onClick={() => onResolve(report.id, 'dismissed', 'leave_visible', 'Dismissed in moderation queue')}
          >
            Dismiss
          </button>
        ) : null}
      </div>
    </div>
  );
}
