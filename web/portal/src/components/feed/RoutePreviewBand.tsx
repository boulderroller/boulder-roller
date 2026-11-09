import { lazy, memo, Suspense, useMemo, type CSSProperties } from 'react';
import type { RoutePreview } from '../../lib/api';
import type { RideSample, RideSpan } from '../ride/ridePageModel';
import { MAP_GROUND } from '../climb/mapGroundPalette';
import '../../styles/portal-ride-page.css';
const RideMap = lazy(() => import('../ride/RideMap'));
const FIT = { top: 22, bottom: 40, left: 22, right: 22 };
const NO_SPANS: RideSpan[] = [];
const NO_SCRUB = () => {};

function RoutePreviewBandImpl({ preview, className }: { preview: RoutePreview | null | undefined; className?: string }) {
  const samples = useMemo(() => {
    const b = preview?.bounds;
    if (!b || ![b.minLat, b.maxLat, b.minLon, b.maxLon].every(Number.isFinite)) return [];
    // The projection owns privacy: never reconnect separate visible runs.
    const runs = preview.segments?.length ? preview.segments : [preview.points ?? []];
    const result: RideSample[] = [];
    runs.forEach((run) => {
      if (result.length) result.push({ ...result[result.length - 1], gps: { latitude: 0, longitude: 0, redacted: true } });
      run.forEach((p) => {
        const valid = Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1;
        result.push({ t: result.length, d: 0, index: result.length, elevation: null, power: null, cadence: null, speed: null, heartRate: null,
          gps: { latitude: b.minLat + (1 - p.y) * Math.max(b.maxLat - b.minLat, 0.00001), longitude: b.minLon + p.x * Math.max(b.maxLon - b.minLon, 0.00001), redacted: !valid } });
      });
    });
    return result;
  }, [preview]);
  if (samples.length < 2) return null;
  return <div className={['feed-route-band', className].filter(Boolean).join(' ')} style={{ '--ride-map-paper': MAP_GROUND.paper, '--ride-map-label': MAP_GROUND.label } as CSSProperties}>
    <Suspense fallback={null}><RideMap samples={samples} spans={NO_SPANS} scrub={null} onScrub={NO_SCRUB} fitBox={FIT} readOnly /></Suspense>
  </div>;
}
export const RoutePreviewBand = memo(RoutePreviewBandImpl);
export default RoutePreviewBand;
