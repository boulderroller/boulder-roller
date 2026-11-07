import { StateRow } from '../portal/FailureSpecies';
import { LoadingRows } from '../loading/LoadingSystem';
import { Slot } from '../loading/Slot';
import { useVault } from '../../hooks/queries';
import { formatInteger } from '../../lib/formatters';

export default function ClimbLegend({ vaultId }: { vaultId: number }) {
  const query = useVault(vaultId);
  const legend = query.data?.localLegend;
  const active = legend && legend.isActive !== false;
  return <section aria-label="Local Legend">
    <div className="profile-eyebrow"><div className="climb-section-heading"><h2>Local Legend</h2></div></div>
    <div className="climb-ledger-card">
      {query.isPending ? <LoadingRows label="Loading" rows={4} /> : query.isError ? <StateRow title="Unavailable" action={<button onClick={() => void query.refetch()}>Try again</button>} /> : active ? <div className="climb-result-row climb-legend-row">
        <span className="climb-legend-avatar" aria-hidden="true" />
        <span className="climb-result-rider"><strong>{legend.isBootstrap ? 'Founder stewardship' : 'Rider'}</strong><small /></span><strong className="climb-result-value">{formatInteger(legend.completionsCount)}<small>Completions</small></strong>
      </div> : <StateRow title="Vacant" />}
    </div>
  </section>;
}
