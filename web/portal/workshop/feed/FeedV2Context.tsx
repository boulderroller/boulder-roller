import { useEffect, useId, useRef, useState, type ReactNode, type MouseEvent } from 'react';
import { ArrowUpRight, ChevronRight, X } from 'lucide-react';
import { V12Economics } from '../V12Economics';
import { V12Relief } from '../V12Relief';
import { climbResult, distanceLabel, timeLabel } from '../scenario';
import { rideHref, type FeedEntry } from './feedModel';
import { personalTrend, formatFeedCal, type FeedEconomics, type FeedV2Scenario, type WorldSummary } from './feedV2Model';

export const shortDate = (date: string) => new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' });
const periodLabel = (world: WorldSummary) => {
  const end = new Date(Date.parse(world.periodEnd) - 1).toISOString();
  const month = (d: string) => new Date(d).toLocaleDateString('en-US', {month:'short', year:'numeric', timeZone:'America/New_York'});
  return `${shortDate(world.periodStart)}–${month(world.periodStart) === month(end) ? shortDate(end).replace(/^\w+ /, '') : shortDate(end)}`;
};
export function openFeedRide(event: MouseEvent<HTMLAnchorElement>, href: string, before?: () => void) {
  if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault(); before?.(); window.parent.postMessage({ type: 'feed-open-ride', href }, location.origin);
}
export function FeedV2Link({ entry, climb, children, className, onFocus, onBlur, onMouseEnter, onMouseLeave }: {
  entry: FeedEntry; climb?: string; children: ReactNode; className?: string;
  onFocus?: () => void; onBlur?: () => void; onMouseEnter?: () => void; onMouseLeave?: () => void;
}) {
  const href = rideHref(entry, climb);
  return <a {...{className,onFocus,onBlur,onMouseEnter,onMouseLeave}} href={href} target="_top" onClick={e => openFeedRide(e, href)}>{children}</a>;
}
export function FeedV2Avatar({ name, large = false, portrait }: { name: string; large?: boolean; portrait?: string }) {
  const [failed, setFailed] = useState(false);
  return <span className={`f2-avatar ${large ? 'large' : ''}`} aria-hidden="true">{portrait && !failed ? <img src={portrait} alt="" onError={() => setFailed(true)}/> : name.split(/\s+/).filter(Boolean).slice(0, 2).map(s => Array.from(s)[0]).join('')}</span>;
}
export function FeedV2Dialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null), label = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    ref.current?.showModal();
    return () => { document.body.style.overflow = overflow; if (trigger?.isConnected) trigger.focus({preventScroll: true}); };
  }, []);
  return <dialog ref={ref} className="f2-dialog" aria-labelledby={label} onCancel={e => { e.preventDefault(); onClose(); }} onClick={e => { if (e.target === e.currentTarget) { const box = e.currentTarget.getBoundingClientRect(); if (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom) onClose(); } }}>
    <header><h2 id={label}>{title}</h2><button aria-label={`Close ${title}`} onClick={onClose}><X size={20}/></button></header>{children}
  </dialog>;
}

type Trend = NonNullable<ReturnType<typeof personalTrend>>;
function TrendChart({ trend }: { trend: Trend }) {
  const [index, setIndex] = useState<number | null>(null), current = trend.points[index ?? trend.points.length - 1];
  const first = Date.parse(trend.points[0].date), last = Date.parse(trend.points.at(-1)!.date), min = Math.min(...trend.points.map(p => p.duration)), max = Math.max(...trend.points.map(p => p.duration));
  const coords = trend.points.map(p => ({ x: 10 + (Date.parse(p.date) - first) / Math.max(1, last - first) * 180, y: 16 + (p.duration - min) / Math.max(12, max - min) * 42 }));
  const path = coords.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ');
  return <div className="f2-trend" onMouseLeave={() => setIndex(null)}>
    <div className="f2-trend-reading"><span>{index === null ? 'Latest effort' : shortDate(current.date)}</span><strong>{timeLabel(current.duration)}</strong></div>
    <svg viewBox="0 0 200 86" role="img" aria-label={`Recent times on ${trend.climb.name}; lower times appear higher`}>
      <path d="M10,16 H190 M10,58 H190" stroke="#e1e5dc" strokeWidth=".7" fill="none"/><path d={path} fill="none" stroke="#788d62" strokeWidth="1.4"/>
      {coords.map((p, i) => <g key={trend.points[i].date}><circle cx={p.x} cy={p.y} r={index === i || (index === null && i === coords.length - 1) ? 4 : 2.7} fill={i === coords.length - 1 ? '#566d40' : '#fff'} stroke="#788d62" strokeWidth="1.2"/><circle cx={p.x} cy={p.y} r="10" fill="transparent" onMouseEnter={() => setIndex(i)}/></g>)}
      <text x="10" y="81">{shortDate(trend.points[0].date)}</text><text x="190" y="81" textAnchor="end">{shortDate(trend.points.at(-1)!.date)}</text>
    </svg>
  </div>;
}
function HistoryDetail({ trend, onClose }: { trend: Trend; onClose: () => void }) {
  const best = Math.min(...trend.points.map(p => p.duration));
  return <FeedV2Dialog title={trend.climb.name} onClose={onClose}><p className="f2-dialog-subtitle">Your effort history</p><div className="f2-history-head"><span>Best time</span><strong>{timeLabel(best)}</strong></div><div className="f2-history-list">{[...trend.points].reverse().map((p, i) => <div key={`${p.date}-${i}`}><span>{shortDate(p.date)}<small>{new Date(p.date).getFullYear()}</small></span><strong>{timeLabel(p.duration)}</strong>{p.current ? <a href={rideHref(trend.entry, trend.climb.id)} target="_top" onClick={e => openFeedRide(e, rideHref(trend.entry, trend.climb.id), onClose)}>Analyze effort <ArrowUpRight size={13}/></a> : <span/>}</div>)}</div></FeedV2Dialog>;
}
export function PersonalContext({ scenario, pending }: { scenario: FeedV2Scenario; pending: boolean }) {
  const trend = personalTrend(scenario), own = scenario.entries.filter(e => e.owned), [history, setHistory] = useState(false);
  const portrait = own.find(e => e.ride.ride.rider?.avatarDataUrl)?.ride.ride.rider?.avatarDataUrl;
  return <><div className="f2-person"><FeedV2Avatar name={scenario.viewer} portrait={portrait} large/><h2>{scenario.viewer}</h2></div>
    {trend && <section className="f2-person-trend" data-pending={pending}><div className="f2-rail-heading"><h2>Your progress</h2></div><strong className="f2-trend-name">{trend.climb.name}</strong><TrendChart trend={trend}/><button className="f2-context-link" disabled={pending} onClick={() => setHistory(true)}>Your effort history <ChevronRight size={14}/></button></section>}
    {own.length > 0 && <section className="f2-recent"><h2>Your rides</h2>{own.slice(0, 3).map(e => <FeedV2Link entry={e} key={e.id}><span>{e.ride.ride.title}<small>{shortDate(e.ride.ride.startedAt)}</small></span><ChevronRight size={14}/></FeedV2Link>)}</section>}
    {history && trend && !pending && <HistoryDetail trend={trend} onClose={() => setHistory(false)}/>}
  </>;
}
const worldRows = (world: WorldSummary) => [
  {label:'Climbs ridden', value:world.climbsRidden, detail:'Distinct climbs with a recorded ride during this period.'},
  {label:'Ride CAL', value:world.rideCal, detail:'CAL counted for riders during this period.'},
  {label:'Climb tribute', value:world.tributeCal, detail:'CAL attributed to climb Vaults during this period, separately from Ride CAL.'},
].filter(r => r.value !== undefined);
export function WorldContext({ scenario, pending }: { scenario: FeedV2Scenario; pending: boolean }) {
  const world = scenario.workshopV2?.world, [detail, setDetail] = useState(false);
  const climbs = scenario.entries.flatMap(e => e.ride.climbs.map(c => ({entry:e, climb:c}))).filter((x, i, all) => all.findIndex(a => a.climb.id === x.climb.id) === i).slice(0, 3);
  return <>{world && worldRows(world).length > 0 && <section className="f2-world-summary" data-pending={pending}><div className="f2-rail-heading"><h2>Boulder Roller</h2><span>{periodLabel(world)}</span></div><dl>{worldRows(world).map(r => <div key={r.label}><dt>{r.label}</dt><dd>{pending ? '—' : formatFeedCal(r.value!)}{r.label !== 'Climbs ridden' && <small>CAL</small>}</dd></div>)}</dl><button className="f2-context-link" disabled={pending} onClick={() => setDetail(true)}>Activity details <ChevronRight size={14}/></button></section>}
    {climbs.length > 0 && <section className="f2-world-climbs"><h2>Climbs in this feed</h2>{climbs.map(({entry,climb}) => { const result = climbResult(entry.ride, climb); return <FeedV2Link entry={entry} climb={climb.id} key={climb.id}><span className="f2-world-climb-copy"><strong>{climb.name}</strong><small>{distanceLabel(result.distance)} km{result.gain !== null && ` · ${Math.round(result.gain)} m`}</small></span><span className="f2-climb-shape"><V12Relief points={entry.ride.ride.samples.filter(p => p.t >= climb.start && p.t <= climb.end)}/></span></FeedV2Link>; })}</section>}
    {detail && world && !pending && <FeedV2Dialog title="Boulder Roller" onClose={() => setDetail(false)}><p className="f2-dialog-subtitle">{shortDate(world.periodStart)}–{shortDate(new Date(Date.parse(world.periodEnd) - 1).toISOString())} · Platform activity</p><dl className="f2-world-detail">{worldRows(world).map(r => <div key={r.label}><dt>{r.label}<small>{r.detail}</small></dt><dd>{formatFeedCal(r.value!)}{r.label !== 'Climbs ridden' && <small>CAL</small>}</dd></div>)}</dl><p className="f2-as-of">Through {new Date(world.asOf).toLocaleString('en-US', {month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:'America/New_York',timeZoneName:'short'})}</p></FeedV2Dialog>}
  </>;
}
export function FeedV2Cal({ entry, economics, onClose }: { entry: FeedEntry; economics: FeedEconomics; onClose: () => void }) {
  const href = (id: string) => { const u = new URL(rideHref(entry, id), location.origin); u.searchParams.set('view', 'vault'); return `${u.pathname}${u.search}`; };
  return <FeedV2Dialog title={entry.ride.ride.title} onClose={onClose}><div className="f2-cal-detail"><V12Economics scenario={entry.ride} economics={economics} pending={false} vaultHref={href} onVault={id => { onClose(); window.parent.postMessage({type:'feed-open-ride',href:href(id)},location.origin); }}/></div></FeedV2Dialog>;
}
