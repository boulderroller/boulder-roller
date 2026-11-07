import { useCallback, useEffect, useState } from 'react';
import { api, type NotificationPreferences } from '../../lib/api';
import { Switch } from '../ui/switch';

/*
 * Alerts — the four notification switches, on the Settings rail (Tim-ratified
 * 2026-09-03 with the consequence ledger: preferences live on the avatar
 * sheet, not on a reading surface). Each switch saves as it flips.
 */

type PreferenceKey = 'leaderboardUpdates' | 'payoutAlerts' | 'socialActivity' | 'systemAnnouncements';

const ALERTS: Array<{ key: PreferenceKey; label: string; description: string }> = [
  { key: 'leaderboardUpdates', label: 'Rank moves', description: 'New entries, rank changes, KOM, and Local Legend updates' },
  { key: 'payoutAlerts', label: 'Vault payouts', description: 'Backer DUNG, legend DUNG, and weekly vault clears' },
  { key: 'socialActivity', label: 'Rider activity', description: 'Follows, comments, and kudos' },
  { key: 'systemAnnouncements', label: 'Ride updates', description: 'Ride status, verification, and platform updates' },
];

export function AlertSwitches({ headingId }: { headingId: string }) {
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<PreferenceKey | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPreferences(await api.getNotificationPreferences());
    } catch (error) {
      console.error('Failed to fetch notification preferences:', error);
      setPreferences(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (key: PreferenceKey, checked: boolean) => {
    if (!preferences) return;
    setSaving(key);
    const updated = { ...preferences, [key]: checked };
    setPreferences(updated);
    try {
      await api.updateNotificationPreferences(updated);
    } catch (error) {
      console.error('Failed to save preference:', error);
      setPreferences((previous) => (previous ? { ...previous, [key]: !checked } : previous));
    } finally {
      setSaving(null);
    }
  };

  const meta = loading ? 'Loading' : saving ? 'Saving' : preferences ? 'Saved' : null;

  return (
    <>
      <div className="settings-sheet__head">
        <h2 id={headingId} className="settings-sheet__eyebrow">Alerts</h2>
        {meta ? <span className="settings-sheet__meta">{meta}</span> : null}
      </div>
      {loading ? (
        <div className="settings-room__deferred">Loading alerts</div>
      ) : !preferences ? (
        <div className="settings-row">
          <span className="settings-row__sub">Could not load alerts</span>
          <button type="button" className="settings-row__retry" onClick={() => { void load(); }}>
            Try again
          </button>
        </div>
      ) : (
        ALERTS.map(({ key, label, description }) => (
          <div key={key} className="settings-row settings-row--switch">
            <span className="settings-row__copy">
              <span className="settings-row__label settings-row__label--ink">{label}</span>
              <span className="settings-row__sub">{description}</span>
            </span>
            <Switch
              className="settings-row__switch"
              checked={preferences[key] !== false}
              disabled={saving === key}
              aria-label={label}
              onCheckedChange={(checked) => {
                void toggle(key, checked);
              }}
            />
          </div>
        ))
      )}
    </>
  );
}
