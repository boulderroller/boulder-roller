import type { Climb } from '../../lib/api';
import { useFormatters } from '../../hooks/useFormatters';
import { formatPercent } from '../../lib/formatters';
import '../../styles/portal-climb-detail.css';

export default function ClimbIdentity({ climb, viewer = 'owner' }: { climb: Climb; viewer?: 'owner' | 'stranger' }) {
  const { distance, elevation } = useFormatters();
  return <header className="climb-detail-hero" data-object-layer="climb-identity">
    <div className="climb-detail-hero__copy"><h1 className="climb-detail-hero__title">{climb.name || 'Climb'}</h1>{climb.region && <p className="climb-place">{climb.region}</p>}</div>
    <dl className="climb-summary" aria-label="Climb summary">
      {(viewer === 'owner' || Number.isFinite(climb.lengthM)) && <div><dt>Distance</dt><dd>{distance(climb.lengthM)}</dd></div>}
      {(viewer === 'owner' || Number.isFinite(climb.elevGainM)) && <div><dt>Elevation</dt><dd>{elevation(climb.elevGainM)}</dd></div>}
      {(viewer === 'owner' || Number.isFinite(climb.avgGradientPct)) && <div><dt>Grade</dt><dd>{formatPercent(climb.avgGradientPct)}</dd></div>}
    </dl>
  </header>;
}
