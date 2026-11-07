import { useState } from 'react';
import { api } from '../../lib/api';
import { Clock, Database, Loader2, Mountain } from 'lucide-react';
import { toast } from 'sonner';
import { PortalPanel, PortalPanelBody, PortalPanelHeader } from '../portal/PortalSpine';
import { formatInteger } from '../../lib/formatters';

interface ActionButton {
  label: string;
  icon: typeof Mountain;
  action: () => Promise<string>;
}

export default function QuickActions() {
  const [loadingKey, setLoadingKey] = useState<string | null>(null);

  const actions: ActionButton[] = [
    {
      label: 'Bootstrap Terrain',
      icon: Mountain,
      action: async () => {
        const res = await api.triggerTerrainBootstrap();
        return `Fitted ${formatInteger(res.cellsFitted)} cells`;
      },
    },
    {
      label: 'Process Epoch',
      icon: Clock,
      action: async () => {
        const res = await api.processEpoch();
        return res.transitioned ? `Processed ${formatInteger(res.processed)} vaults` : 'No epoch transition needed';
      },
    },
    {
      label: 'Backfill Scores',
      icon: Database,
      action: async () => {
        const res = await api.backfillScores({ dryRun: false });
        return `Scored ${formatInteger(res.scored)} of ${formatInteger(res.processed)} climbs`;
      },
    },
  ];

  const handleAction = async (a: ActionButton) => {
    setLoadingKey(a.label);
    try {
      const msg = await a.action();
      toast.success(msg);
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : 'Action failed');
    } finally {
      setLoadingKey(null);
    }
  };

  return (
    <PortalPanel>
      <PortalPanelHeader title="Quick Actions" meta={loadingKey ? 'Running' : 'Manual'} />
      <PortalPanelBody className="admin-v2-quick-actions">
        {actions.map((a) => {
          const isLoading = loadingKey === a.label;
          const Icon = a.icon;
          return (
            <button
              key={a.label}
              type="button"
              onClick={() => void handleAction(a)}
              disabled={loadingKey !== null}
              className="portal-sort-button admin-v2-quick-action"
            >
              {isLoading ? (
                <Loader2 size={15} className="settings-v2-inline-spin" aria-hidden="true" />
              ) : (
                <Icon size={15} aria-hidden="true" />
              )}
              {a.label}
            </button>
          );
        })}
      </PortalPanelBody>
    </PortalPanel>
  );
}
