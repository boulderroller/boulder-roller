import './map-attribution.css';
import type { GeographicData } from '../../lib/api';

export const OPEN_DATA_URL = 'https://docs.boulderroller.xyz/open-data';

export default function GeographyCredit({ data }: { data?: GeographicData | null }) {
  const elevation = data?.sources.filter(source => source.licenseId !== 'ODbL-1.0') ?? [];
  return <div className="geography-credit">
    <span>Climb geography: <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>.</span>{' '}
    {elevation.map(source => <span key={source.assetId}>Elevation: {source.notices.map(notice => <a key={notice.id} href={source.licenseUrl}>{notice.text}</a>)}</span>)}{' '}
    <a href={data?.manifestUrl ?? OPEN_DATA_URL}>Data and sources</a>
  </div>;
}
