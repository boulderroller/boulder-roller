import { useMemo } from 'react';
import { ArrowUpRight, ChevronDown } from 'lucide-react';
import { rideFileStats } from './v9Metrics';
import { V9CalAmount } from './V9Economics';
import { channelValue, type AnalysisSample } from './v3Model';
import type { ExampleEconomics } from './v9Example';

export function V9RideDetails({ points, source, economics, pending, onEconomics, expanded, onExpanded }: { points: AnalysisSample[]; source: string | null; economics: ExampleEconomics | null; pending: boolean; onEconomics: () => void; expanded: boolean; onExpanded: (value: boolean) => void }) {
  const stats = useMemo(() => rideFileStats(points), [points]);
  const fields = [
    { label: 'Max speed', value: stats.maxSpeed === null ? null : `${channelValue(stats.maxSpeed, 'speed')} km/h` },
    { label: 'Max power', value: stats.maxPower === null ? null : `${Math.round(stats.maxPower).toLocaleString()} W` },
    { label: 'Work', value: stats.workKj === null ? null : `${Math.round(stats.workKj).toLocaleString()} kJ` },
  ].filter(field => field.value !== null);
  if (!fields.length && !source && !economics) return null;
  return <div className="v9-ride-details" data-expanded={expanded}><button className="v9-details-toggle" aria-expanded={expanded} aria-controls="v9-extra-details" onClick={() => onExpanded(!expanded)}><span className="v9-show-more">Show more</span><span className="v9-show-less">Show less</span><ChevronDown size={12}/></button><div id="v9-extra-details" className="v9-ride-details-body" hidden={!expanded}>
    <dl>{fields.map(field => <div key={field.label}><dt>{field.label}</dt><dd><span className="v9-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{field.value}</span></span></dd></div>)}{source && <div><dt>Source</dt><dd>{source}</dd></div>}</dl>
    {economics && <section className="v9-summary-cal" aria-label="Ride CAL"><header><span>Ride CAL</span></header><div><V9CalAmount value={economics.riderCal} pending={pending}/><button onClick={onEconomics}>CAL & tribute<ArrowUpRight size={12}/></button></div></section>}
  </div></div>;
}
