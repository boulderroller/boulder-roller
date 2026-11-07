import releases from '../data/open-data.json';
import type { ClimbSummary } from '../types';

const OPEN_DATA = 'https://docs.boulderroller.xyz/open-data';
const index: Record<string, (typeof releases)[keyof typeof releases]> = releases;

export default function GeographicCredit({ climb }: { climb: ClimbSummary }) {
  const receipt = index[climb.id]?.find(row => row.canon_id === climb.canon_id && row.version === climb.version && row.profile.length === climb.canonical_profile.length && row.profile.every((sample,i) => sample.dist_m === climb.canonical_profile[i].dist_m && sample.elev_m === climb.canonical_profile[i].elev_m));
  return <div className="geographic-credit">
    Climb geography: <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>.{' '}
    {receipt?.metadata.sources.filter(source => source.license_id !== 'ODbL-1.0').map(source => <span key={source.asset_id}>Elevation: {source.notices.map(notice => <a key={notice.id} href={source.license_url}>{notice.text}</a>)}</span>)}{' '}
    <a href={receipt?.metadata.manifest_url ?? OPEN_DATA}>Data and sources</a>
  </div>;
}
