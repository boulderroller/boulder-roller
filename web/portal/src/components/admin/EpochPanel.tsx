import { useState, useEffect, useCallback } from 'react';
import { PlayCircle } from 'lucide-react';

import { api } from '../../lib/api';
import type { EpochStatusResponse } from '../../lib/api';
import { formatInteger } from '../../lib/formatters';
import {
  PortalMetric,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
  PortalTruthPill,
} from '../portal/PortalSpine';

export default function EpochPanel() {
  const [status, setStatus] = useState<EpochStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [processResult, setProcessResult] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.getEpochStatus();
      setStatus(res);
      setError(null);
    } catch {
      setError('Failed to load epoch status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleProcess = async () => {
    setProcessing(true);
    setProcessResult(null);
    try {
      const res = await api.processEpoch();
      setProcessResult(
        res.transitioned
          ? `Epoch transitioned. ${formatInteger(res.processed)} distributions processed.`
          : `${formatInteger(res.processed)} distributions processed (no transition needed).`
      );
      await fetchStatus();
    } catch {
      setProcessResult('Failed to process epoch.');
    } finally {
      setProcessing(false);
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

  return (
    <PortalPanel className="admin-v2-epoch-panel">
      <PortalPanelHeader
        title="Epoch Status"
        meta={status?.epochNeedsTransition ? <PortalTruthPill tone="warning">Transition</PortalTruthPill> : 'Current'}
      />
      <PortalPanelBody>
        {error ? <div className="admin-v2-inline-alert admin-v2-inline-alert--danger">{error}</div> : null}

        {status ? (
          <div className="admin-v2-system-stack">
            <div className="admin-v2-metric-grid admin-v2-metric-grid--three">
              <PortalMetric value={formatInteger(status.currentEpoch)} label="Current Epoch" />
              <PortalMetric value={formatInteger(status.storedEpoch)} label="Stored Epoch" />
              <PortalMetric value={formatInteger(status.recentlyCompleted)} label="Recent Completions" />
            </div>

            <div className="admin-v2-fact-list">
              <div>
                <span>Pending Distributions</span>
                <strong>{formatInteger(status.pendingDistributions)}</strong>
              </div>
              {status.pendingDungTotal > 0 ? (
                <div>
                  <span>Pending DUNG</span>
                  <strong>{formatInteger(status.pendingDungTotal)}</strong>
                </div>
              ) : null}
            </div>

            <button
              type="button"
              onClick={handleProcess}
              disabled={processing}
              className="portal-action-button admin-v2-full-button"
            >
              <PlayCircle size={14} aria-hidden="true" />
              {processing ? 'Processing' : 'Process Epoch'}
            </button>

            {processResult ? (
              <div className="admin-v2-inline-alert admin-v2-inline-alert--success">{processResult}</div>
            ) : null}
          </div>
        ) : null}
      </PortalPanelBody>
    </PortalPanel>
  );
}
