import './map-attribution.css';
import type { GeographicData } from '../../lib/api';
import { OPEN_DATA_URL } from './GeographyCredit';

/** The existing CARTO credit is preserved; service entitlement remains unresolved. The
 * pinned Voyager style's license asks for visible OpenMapTiles and CARTO credits. */
export default function MapAttribution({ data }: { data?: GeographicData | null }) {
  return <span className="map-credit-row"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a><a href="https://openmaptiles.org/" target="_blank" rel="noreferrer">© OpenMapTiles</a><a href="https://carto.com/attributions" target="_blank" rel="noreferrer">© CARTO</a><a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noreferrer">Terrain: Mapzen (AWS)</a><details className="map-source-notices" onToggle={event => {
    const details = event.currentTarget;
    const panel = details.querySelector('div');
    if (!details.open || !panel) return;
    panel.style.transform = '';
    const box = panel.getBoundingClientRect();
    const dx = Math.max(12 - box.left, Math.min(0, window.innerWidth - 12 - box.right));
    const dy = Math.max(12 - box.top, Math.min(0, window.innerHeight - 12 - box.bottom));
    panel.style.transform = `translate(${dx}px, ${dy}px)`;
  }}><summary>Data and sources</summary><div>
    <a href={data?.manifestUrl ?? OPEN_DATA_URL}>Open climb data</a>
    <a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md">Terrain sources</a>
    {data?.sources.flatMap(source => source.notices.map(notice => <a key={`${source.assetId}:${notice.id}`} href={source.licenseUrl}>{notice.text}</a>))}
  </div></details></span>;
}
