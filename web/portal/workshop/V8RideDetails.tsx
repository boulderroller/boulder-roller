import { useMemo } from 'react';
import { ArrowUpRight, ChevronDown } from 'lucide-react';
import { rideFileStats } from './v8Metrics';
import { V8CalAmount } from './V8Economics';
import { channelValue, type AnalysisSample } from './v3Model';
import type { ExampleEconomics } from './v8Example';

export function V8RideDetails({ points, source, economics, pending, onEconomics }: { points: AnalysisSample[]; source: string | null; economics: ExampleEconomics | null; pending: boolean; onEconomics: () => void }) {
  const stats = useMemo(() => rideFileStats(points), [points]);
  const fields = [
    { label: 'Max speed', value: stats.maxSpeed === null ? null : `${channelValue(stats.maxSpeed, 'speed')} km/h` },
    { label: 'Max power', value: stats.maxPower === null ? null : `${Math.round(stats.maxPower).toLocaleString()} W` },
    { label: 'Work', value: stats.workKj === null ? null : `${Math.round(stats.workKj).toLocaleString()} kJ` },
  ].filter(field => field.value !== null);
  if (!fields.length && !source && !economics) return null;
  return <details className="v8-ride-details"><summary><span className="v8-show-more">Show more</span><span className="v8-show-less">Show less</span><ChevronDown size={12}/></summary><div className="v8-ride-details-body">
    <dl>{fields.map(field => <div key={field.label}><dt>{field.label}</dt><dd><span className="v8-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{field.value}</span></span></dd></div>)}{source && <div><dt>Source</dt><dd>{source}</dd></div>}</dl>
    {economics && <section className="v8-summary-cal" aria-label="Illustrative Ride CAL"><header><span>Ride CAL</span><span className="v8-example-label">Illustrative economics</span></header><div><V8CalAmount value={economics.riderCal} pending={pending}/><button onClick={onEconomics}>CAL & tribute<ArrowUpRight size={12}/></button></div></section>}
  </div></details>;
}
