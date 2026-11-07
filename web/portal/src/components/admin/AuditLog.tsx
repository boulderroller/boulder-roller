import { useState, useEffect } from 'react';
import { ScrollText } from 'lucide-react';

import { api } from '../../lib/api';
import type { AuditLogEntry } from '../../lib/api';
import { ABSENT_VALUE, formatDateTime, formatInteger } from '../../lib/formatters';
import { PortalEmptyState, PortalPanel, PortalPanelBody, PortalPanelHeader } from '../portal/PortalSpine';

function truncateWallet(wallet: string): string {
  if (wallet.length <= 10) return wallet;
  return `${wallet.slice(0, 4)}...${wallet.slice(-4)}`;
}

export default function AuditLog() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.getAuditLog(20);
        setEntries(res.entries);
        setError(null);
      } catch (err: unknown) {
        if (err && typeof err === 'object' && 'statusCode' in err && (err as { statusCode: number }).statusCode === 404) {
          setError(null);
          setEntries([]);
        } else {
          setError('Failed to load audit log');
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

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

  return (
    <PortalPanel className="admin-v2-audit-panel">
      <PortalPanelHeader title="Audit Log" meta={entries.length ? `${formatInteger(entries.length)} entries` : 'Quiet'} />
      <PortalPanelBody>
        {error ? <div className="admin-v2-inline-alert admin-v2-inline-alert--danger">{error}</div> : null}

        {entries.length === 0 && !error ? (
          <PortalEmptyState
            className="admin-v2-compact-empty"
            icon={<ScrollText size={20} aria-hidden="true" />}
            title="No audit entries"
          />
        ) : null}

        {entries.length > 0 ? (
          <div className="admin-v2-table">
            <div className="admin-v2-table__head">
              <span>Action</span>
              <span>Admin</span>
              <span>When</span>
            </div>

            {entries.map((entry) => (
              <div key={entry.id} className="admin-v2-table__row">
                <div>
                  <strong>{entry.action}</strong>
                  {entry.targetType ? <span>{entry.targetType}</span> : null}
                </div>
                <span>{entry.userId ? truncateWallet(entry.userId) : ABSENT_VALUE}</span>
                <time>{formatDateTime(entry.createdAt)}</time>
              </div>
            ))}
          </div>
        ) : null}
      </PortalPanelBody>
    </PortalPanel>
  );
}
