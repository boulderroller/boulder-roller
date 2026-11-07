import { useState, useEffect, useCallback } from 'react';
import { PauseCircle, PlayCircle } from 'lucide-react';

import { api } from '../../lib/api';
import type { AdminControl } from '../../lib/api';
import { formatDate, formatInteger } from '../../lib/formatters';
import { PortalEmptyState, PortalPanel, PortalPanelBody, PortalPanelHeader } from '../portal/PortalSpine';
import { cn } from '../ui/utils';

const CONTROL_LABELS: Record<string, string> = {
  staking_enabled: 'Staking',
  minting_enabled: 'Minting',
  uploads_enabled: 'Uploads',
  withdrawals_enabled: 'Withdrawals',
  maintenance_mode: 'Maintenance Mode',
};

function toBackendControlKey(key: string): string {
  return key.replace(/([A-Z])/g, '_$1').toLowerCase();
}

function controlLabel(key: string): string {
  const backendKey = toBackendControlKey(key);
  return CONTROL_LABELS[backendKey] ?? key;
}

function controlEnabled(value: AdminControl['value']): boolean {
  if (typeof value === 'boolean') return value;
  if (value && typeof value === 'object' && 'enabled' in value) {
    return Boolean((value as { enabled?: unknown }).enabled);
  }
  return Boolean(value);
}

function Toggle({
  checked,
  onChange,
  disabled,
  label,
  tone = 'default',
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label: string;
  tone?: 'default' | 'danger';
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={`${label}: ${checked ? 'enabled' : 'disabled'}`}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'admin-v2-switch',
        checked && 'admin-v2-switch--checked',
        checked && tone === 'danger' && 'admin-v2-switch--danger',
        disabled && 'admin-v2-switch--disabled',
      )}
    >
      <span className="admin-v2-switch__thumb" />
    </button>
  );
}

export default function ControlPanel() {
  const [controls, setControls] = useState<AdminControl[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState<string | null>(null);
  const [pauseReason, setPauseReason] = useState('');

  const fetchControls = useCallback(async () => {
    try {
      const res = await api.getAdminControls();
      setControls(res.controls);
      setError(null);
    } catch {
      setError('Failed to load controls');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchControls();
  }, [fetchControls]);

  const handleToggle = async (key: string, enabled: boolean) => {
    setUpdating(key);
    setControls((prev) => prev.map((control) => (
      control.key === key ? { ...control, value: enabled } : control
    )));

    try {
      await api.updateAdminControl(toBackendControlKey(key), enabled);
    } catch {
      setControls((prev) => prev.map((control) => (
        control.key === key ? { ...control, value: !enabled } : control
      )));
    } finally {
      setUpdating(null);
    }
  };

  const handlePauseAll = async () => {
    const reason = pauseReason.trim() || 'Emergency pause';
    setUpdating('pause_all');
    try {
      await api.emergencyPauseAll(reason);
      await fetchControls();
      setPauseReason('');
    } catch {
      setError('Failed to pause');
    } finally {
      setUpdating(null);
    }
  };

  const handleResumeAll = async () => {
    setUpdating('resume_all');
    try {
      await api.emergencyResumeAll();
      await fetchControls();
    } catch {
      setError('Failed to resume');
    } finally {
      setUpdating(null);
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
    <PortalPanel className="admin-v2-control-panel">
      <PortalPanelHeader title="System Controls" meta={controls.length ? `${formatInteger(controls.length)} flags` : 'Flags'} />
      <PortalPanelBody>
        {error ? <div className="admin-v2-inline-alert admin-v2-inline-alert--danger">{error}</div> : null}

        {controls.length === 0 ? (
          <PortalEmptyState
            className="admin-v2-compact-empty"
            title="No controls reported"
            description="The control endpoint did not return any mutable flags."
          />
        ) : (
          <div className="admin-v2-control-list">
            {controls.map((control) => {
              const label = controlLabel(control.key);
              const enabled = controlEnabled(control.value);
              const isMaintenanceMode = toBackendControlKey(control.key) === 'maintenance_mode';
              return (
                <div key={control.key} className="admin-v2-control-row">
                  <div>
                    <strong>{label}</strong>
                    {control.updatedAt ? (
                      <span>Updated {formatDate(control.updatedAt)}</span>
                    ) : null}
                  </div>
                  <Toggle
                    checked={enabled}
                    onChange={(value) => handleToggle(control.key, value)}
                    disabled={updating !== null}
                    label={label}
                    tone={isMaintenanceMode ? 'danger' : 'default'}
                  />
                </div>
              );
            })}
          </div>
        )}

        <div className="admin-v2-emergency">
          <div className="admin-v2-section-label">Emergency</div>
          <input
            type="text"
            value={pauseReason}
            onChange={(event) => setPauseReason(event.target.value)}
            placeholder="Reason (optional)"
            className="admin-v2-input"
          />
          <div className="admin-v2-button-row">
            <button
              type="button"
              onClick={handlePauseAll}
              disabled={updating !== null}
              className="portal-sort-button admin-v2-danger-action"
            >
              <PauseCircle size={14} aria-hidden="true" />
              {updating === 'pause_all' ? 'Pausing' : 'Pause All'}
            </button>
            <button
              type="button"
              onClick={handleResumeAll}
              disabled={updating !== null}
              className="portal-sort-button admin-v2-success-action"
            >
              <PlayCircle size={14} aria-hidden="true" />
              {updating === 'resume_all' ? 'Resuming' : 'Resume All'}
            </button>
          </div>
        </div>
      </PortalPanelBody>
    </PortalPanel>
  );
}
