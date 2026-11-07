import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUpRight, ChevronRight, Heart, MessageCircle, RotateCcw } from 'lucide-react';
import { FeedV2Map } from './FeedV2Map';
import { FeedV2Avatar as Avatar, FeedV2Link as RideLink, PersonalContext, WorldContext, FeedV2Cal } from './FeedV2Context';
import { climbBand, economicsFor, formatFeedCal, personalTrend, type FeedV2Scenario } from './feedV2Model';
import type { Climb } from '../scenario';
import { summarize, climbResult, timeLabel, distanceLabel, type Scenario } from '../scenario';
import { type FeedEntry, type FeedComment, visibleEntries } from './feedModel';
import '../candidate-v12.css';
import './feed-v2.css';
type State = 'ready' | 'loading' | 'empty' | 'error';
type SocialState = {
    liked: boolean;
    comments: FeedComment[];
    expanded: boolean;
    draft: string;
    editing: boolean;
};
const localSocial = new WeakMap<FeedEntry, SocialState>();
function Relief({ scenario, climb, active }: {
    scenario: Scenario; climb?: Climb; active: boolean;
}) {
    const samples = scenario.ride.samples, first = samples[0], last = samples.at(-1), values = samples.flatMap(p => p.elevation === null ? [] : [p.elevation]);
    if (!first || !last || last.d <= first.d || values.length < 2)
        return null;
    const min = Math.min(...values), span = Math.max(1, Math.max(...values) - min), runs: typeof samples[] = [];
    let run: typeof samples = [];
    samples.forEach((p, i) => { if (p.elevation === null || (i > 0 && p.t - samples[i - 1].t > 30)) {
        if (run.length > 1)
            runs.push(run);
        run = [];
    } if (p.elevation !== null)
        run.push(p); });
    if (run.length > 1)
        runs.push(run);
    const x = (d: number) => ((d - first.d) / (last.d - first.d) * 700).toFixed(1);
    const band = climb ? climbBand(scenario, climb) : null;
    return <svg className="f2-relief" viewBox="0 0 700 48" preserveAspectRatio="none" role="img" aria-label="Ride elevation">{band && <rect data-climb-band x={band.from*700} y="0" width={(band.to-band.from)*700} height="48" fill={active ? "#91a77c55" : "#91a77c30"}/>} {runs.map((points, k) => { if (points.at(-1)!.d <= points[0].d)
        return null; const step = Math.max(1, Math.floor(points.length / 320)), path = points.filter((_, i) => i % step === 0 || i === points.length - 1).map((p, i) => `${i ? 'L' : 'M'}${x(p.d)},${(44 - (p.elevation! - min) / span * 36).toFixed(1)}`).join(' '); return <g key={k}><path d={`${path} L${x(points.at(-1)!.d)},48 L${x(points[0].d)},48 Z`} fill="#dce1d2"/><path d={path} fill="none" stroke="#9fa98f" strokeWidth=".8" vectorEffect="non-scaling-stroke"/></g>; })}</svg>;
}
function FeedMap({ entry, climb, active }: { entry: FeedEntry; climb?: Climb; active: boolean }) {
    return <div className="f2-map"><FeedV2Map scenario={entry.ride} climb={climb} active={active}/><RideLink className="f2-map-link" entry={entry}><span>View ride <ArrowUpRight size={13}/></span><span className="sr-only">{entry.ride.ride.title}</span></RideLink><div className="f2-attribution">© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></div></div>;
}
function FeedCard({ entry, pending, viewer, scenario }: {
    scenario: FeedV2Scenario;
    entry: FeedEntry;
    pending: boolean;
    viewer: string;
}) {
    const [hovered, setHovered] = useState(false), [focused, setFocused] = useState(false), [calOpen, setCalOpen] = useState(false);
    const active = hovered || focused, economics = economicsFor(scenario, entry);
    const name = entry.ride.ride.rider?.displayName ?? 'Rider', totals = useMemo(() => summarize(entry.ride.ride.samples), [entry]);
    const [social, setSocial] = useState<SocialState>(() => localSocial.get(entry) ?? { liked: false, comments: entry.comments, expanded: false, draft: '', editing: false });
    const commentInput = useRef<HTMLTextAreaElement>(null), commentTrigger = useRef<HTMLButtonElement>(null);
    const update = (patch: Partial<SocialState>) => setSocial(current => { const next = { ...current, ...patch }; localSocial.set(entry, next); return next; });
    useEffect(() => { if (social.editing)
        commentInput.current?.focus(); }, [social.editing]);
    const close = () => { update({ editing: false }); commentTrigger.current?.focus(); };
    const comments = social.expanded ? social.comments : social.comments.slice(-2);
    const best = entry.ride.climbs.find(c => (climbResult(entry.ride, c).improvement ?? 0) > 0);
    const featured = best ?? entry.ride.climbs[0], result = featured ? climbResult(entry.ride, featured) : null;
    return <article className="f2-card" data-entry={entry.id} aria-busy={pending} aria-label={`${name}: ${entry.ride.ride.title}`}>
  <header className="f2-card-identity"><Avatar name={name} portrait={entry.ride.ride.rider?.avatarDataUrl}/><div><strong>{name}</strong><p><time dateTime={entry.ride.ride.startedAt}>{new Date(entry.ride.ride.startedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' })}</time><span> · </span>{entry.ride.ride.location}</p></div></header>
  <div className="f2-card-copy">{entry.companions.length > 0 && <div className="f2-companions"><span className="f2-companion-avatars">{entry.companions.slice(0,3).map(n=><Avatar name={n} key={n}/>)}</span><span>With {entry.companions.join(entry.companions.length === 2 ? " and " : ", ")}</span></div>}<h2><RideLink entry={entry}>{entry.ride.ride.title}</RideLink></h2>{entry.description && <p className="f2-description">{entry.description}</p>}
   <dl className="f2-stats" data-pending={pending}><div><dt>Distance</dt><dd>{pending ? '—' : distanceLabel(totals.distance)}<small>km</small></dd></div><div><dt>Elevation</dt><dd>{pending ? '—' : totals.gain === null ? '—' : Math.round(totals.gain).toLocaleString()}<small>m</small></dd></div><div><dt>Elapsed time</dt><dd>{pending ? '—' : timeLabel(totals.duration)}</dd></div></dl>
  </div>
  <div className="f2-terrain" data-active={active}><FeedMap entry={entry} climb={featured} active={active}/><Relief scenario={entry.ride} climb={featured} active={active}/>
  {featured && result && <div className="f2-result" data-pending={pending}><RideLink className="f2-result-link" entry={entry} climb={featured.id} onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>setHovered(false)} onFocus={()=>setFocused(true)} onBlur={()=>setFocused(false)}><span className="f2-result-copy"><strong>{featured.name}</strong><small>{distanceLabel(result.distance)} km{result.gain !== null && ` · ${Math.round(result.gain)} m`}</small></span><span className="f2-result-value"><strong>{timeLabel(result.duration)}</strong><small>{best ? 'New best' : 'Climb time'}</small></span><ChevronRight size={14}/></RideLink></div>}
  </div>
  {economics && <div className="f2-card-cal" data-pending={pending}><button disabled={pending} onClick={()=>setCalOpen(true)}>Ride CAL <span>{formatFeedCal(economics.riderCal.amount)} <small>CAL</small></span><small>{economics.riderCal.state === "pending" ? "Pending" : "Counted"}</small><ChevronRight size={12}/></button></div>}
  {calOpen && economics && !pending && <FeedV2Cal entry={entry} economics={economics} onClose={()=>setCalOpen(false)}/>}
  <footer className="f2-social"><span className="f2-social-count">{entry.kudos + Number(social.liked) > 0 && <>{entry.kudos + Number(social.liked)} kudos</>}{social.comments.length > 0 && <button onClick={() => update({ expanded: !social.expanded })}>{social.comments.length} {social.comments.length === 1 ? 'comment' : 'comments'}</button>}</span><div><button disabled={pending} aria-label={social.liked ? 'Remove kudos' : 'Give kudos'} aria-pressed={social.liked} onClick={() => update({ liked: !social.liked })}><Heart size={18} fill={social.liked ? 'currentColor' : 'none'}/></button><button ref={commentTrigger} disabled={pending} aria-label="Add comment" aria-expanded={social.editing} onClick={() => update({ editing: !social.editing })}><MessageCircle size={18}/></button></div></footer>
  {social.comments.length > 0 && <div className="f2-comments" data-pending={pending}>{comments.map(c => <div key={c.id}><Avatar name={c.name}/><p><strong>{c.name}</strong><span>{c.text}</span></p></div>)}{social.comments.length > 2 && <button onClick={() => update({ expanded: !social.expanded })}>{social.expanded ? 'Show fewer comments' : `View all ${social.comments.length} comments`}</button>}</div>}
  {social.editing && <form className="f2-comment-form" onSubmit={e => { e.preventDefault(); const text = social.draft.trim(); if (text) {
        update({ comments: [...social.comments, { id: crypto.randomUUID(), name: viewer, text }], draft: '', editing: false, expanded: true });
        commentTrigger.current?.focus();
    } }} onKeyDown={e => { if (e.key === 'Escape') {
        e.preventDefault();
        close();
    } }}><label className="sr-only" htmlFor={`comment-${entry.id}`}>Comment on {entry.ride.ride.title}</label><textarea disabled={pending} ref={commentInput} id={`comment-${entry.id}`} value={social.draft} rows={2} maxLength={1000} onChange={e => update({ draft: e.target.value })} placeholder="Add a comment"/><div><button type="button" onClick={close}>Cancel</button><button type="submit" disabled={pending || !social.draft.trim()}>Post comment</button></div></form>}
 </article>;
}
export function FeedV2({ scenario, filter, state, onFilter, onRecover }: {
    scenario: FeedV2Scenario;
    filter: string;
    state: State;
    onFilter: (filter: string) => void;
    onRecover: () => void;
}) {
    const hasPersonal = scenario.entries.some(e => e.owned), personalLabel = personalTrend(scenario) ? 'Your progress' : 'Your rides';
    const world = scenario.workshopV2?.world, hasWorld = !!world && [world.climbsRidden, world.rideCal, world.tributeCal].some(v => v !== undefined);
    const [mobileContext, setMobileContext] = useState<'personal'|'world'|null>(null);
    const entries = visibleEntries(scenario, filter), pending = state === 'loading', [listLimit, setListLimit] = useState(8);
    useEffect(() => setListLimit(8), [scenario, filter]);
    return <div className="f2-page"><header className="f2-shell"><strong>Boulder Roller</strong><span>Feed</span><Avatar name={scenario.viewer}/></header><main className="f2-layout">
  <aside className="f2-left" aria-label="Personal" hidden={state === 'error' || state === 'empty'}><PersonalContext scenario={scenario} pending={pending}/></aside>
  <section className="f2-stream" aria-label="Ride feed"><div className="f2-stream-heading"><h1>Feed</h1><div role="group" aria-label="Feed filter"><button aria-pressed={filter === 'everyone'} onClick={() => onFilter('everyone')}>Everyone</button><button aria-pressed={filter === 'following'} onClick={() => onFilter('following')}>Following</button></div></div>
   {state !== 'empty' && state !== 'error' && (hasPersonal || hasWorld) && <div className="f2-mobile-context"><div>{hasPersonal && <button aria-expanded={mobileContext==='personal'} onClick={()=>setMobileContext(v=>v==='personal'?null:'personal')}>{personalLabel} <ChevronRight size={13}/></button>}{hasWorld && <button aria-expanded={mobileContext==='world'} onClick={()=>setMobileContext(v=>v==='world'?null:'world')}>Boulder Roller <ChevronRight size={13}/></button>}</div>{mobileContext && <section aria-label={mobileContext==='personal'?'Personal summary':'World summary'}>{mobileContext==='personal'?<PersonalContext scenario={scenario} pending={pending}/>:<WorldContext scenario={scenario} pending={pending}/>}</section>}</div>}
   {state === 'error' || state === 'empty' || entries.length === 0 ? <div className="f2-empty"><h2>{state === 'error' ? 'Feed unavailable' : 'No rides yet'}</h2><p>{state === 'error' ? 'The feed could not be loaded.' : filter === 'following' ? 'Rides from people you follow will appear here.' : 'Rides will appear here.'}</p><button onClick={state === 'ready' ? () => onFilter('everyone') : onRecover}>{state === 'error' ? <><RotateCcw size={14}/>Try again</> : 'Show rides'}</button></div> : <>{entries.slice(0, listLimit).map(e => <FeedCard key={`${scenario.id}:${e.id}`} entry={e} pending={pending} viewer={scenario.viewer} scenario={scenario}/>)}{entries.length > listLimit && <button className="f2-load" onClick={() => setListLimit(n => n + 8)}>Show more rides</button>}</>}
  </section>
  <aside className="f2-right" aria-label="World" hidden={state === 'error' || state === 'empty'}><WorldContext scenario={scenario} pending={pending}/></aside>
 </main></div>;
}
