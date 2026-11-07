import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { ArrowUpRight, ChevronRight, Heart, MessageCircle, Mountain, RotateCcw, Users, X } from 'lucide-react';
import { V12Map } from '../V12Map';
import { summarize, climbResult, timeLabel, distanceLabel, type Scenario } from '../scenario';
import { type FeedEntry, type FeedComment, type FeedScenario, rideHref, visibleEntries } from './feedModel';
import '../candidate-v12.css';
import './feed-v1.css';
type State = 'ready' | 'loading' | 'empty' | 'error';
type SocialState = {
    liked: boolean;
    comments: FeedComment[];
    expanded: boolean;
    draft: string;
    editing: boolean;
};
const localSocial = new WeakMap<FeedEntry, SocialState>();
const initials = (name: string) => name.split(/\s+/).slice(0, 2).map(s => s[0]).join('');
const noop = () => { };
function requestRide(event: MouseEvent<HTMLAnchorElement>, href: string) { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
    return; event.preventDefault(); window.parent.postMessage({ type: 'feed-open-ride', href }, location.origin); }
function RideLink({ entry, climb, children, className }: {
    entry: FeedEntry;
    climb?: string;
    children: React.ReactNode;
    className?: string;
}) { const href = rideHref(entry, climb); return <a className={className} href={href} target="_top" onClick={e => requestRide(e, href)}>{children}</a>; }
function Avatar({ name, large = false }: {
    name: string;
    large?: boolean;
}) { return <span className={`f1-avatar ${large ? 'large' : ''}`} aria-hidden="true">{initials(name)}</span>; }
function Relief({ scenario }: {
    scenario: Scenario;
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
    return <svg className="f1-relief" viewBox="0 0 700 48" preserveAspectRatio="none" role="img" aria-label="Ride elevation">{runs.map((points, k) => { if (points.at(-1)!.d <= points[0].d)
        return null; const step = Math.max(1, Math.floor(points.length / 320)), path = points.filter((_, i) => i % step === 0 || i === points.length - 1).map((p, i) => `${i ? 'L' : 'M'}${x(p.d)},${(44 - (p.elevation! - min) / span * 36).toFixed(1)}`).join(' '); return <g key={k}><path d={`${path} L${x(points.at(-1)!.d)},48 L${x(points[0].d)},48 Z`} fill="#dce1d2"/><path d={path} fill="none" stroke="#9fa98f" strokeWidth=".8" vectorEffect="non-scaling-stroke"/></g>; })}</svg>;
}
function FeedMap({ entry }: {
    entry: FeedEntry;
}) {
    const ref = useRef<HTMLDivElement>(null), [visible, setVisible] = useState(false);
    useEffect(() => { const observer = new IntersectionObserver(entries => { if (entries[0].isIntersecting) {
        setVisible(true);
        observer.disconnect();
    } }, { rootMargin: '300px' }); if (ref.current)
        observer.observe(ref.current); return () => observer.disconnect(); }, []);
    const open = (id: string) => window.parent.postMessage({ type: 'feed-open-ride', href: rideHref(entry, id) }, location.origin);
    return <div ref={ref} className="f1-map"><div className="f1-map-art" aria-hidden="true" ref={node => { node?.setAttribute('inert', ''); }}>{visible && <V12Map scenario={entry.ride} focus={null} cameraKey={entry.id} visible scrub={null} onScrub={noop} onSelect={open} onLeave={noop} onClearSelection={noop}/>}</div><RideLink className="f1-map-link" entry={entry}><span>View ride <ArrowUpRight size={13}/></span><span className="sr-only">{entry.ride.ride.title}</span></RideLink></div>;
}
function FeedCard({ entry, pending, viewer }: {
    entry: FeedEntry;
    pending: boolean;
    viewer: string;
}) {
    const name = entry.ride.ride.rider?.displayName ?? 'Rider', totals = summarize(entry.ride.ride.samples);
    const [social, setSocial] = useState<SocialState>(() => localSocial.get(entry) ?? { liked: false, comments: entry.comments, expanded: false, draft: '', editing: false });
    const commentInput = useRef<HTMLTextAreaElement>(null), commentTrigger = useRef<HTMLButtonElement>(null);
    const update = (patch: Partial<SocialState>) => setSocial(current => { const next = { ...current, ...patch }; localSocial.set(entry, next); return next; });
    useEffect(() => { if (social.editing)
        commentInput.current?.focus(); }, [social.editing]);
    const close = () => { update({ editing: false }); commentTrigger.current?.focus(); };
    const comments = social.expanded ? social.comments : social.comments.slice(-2);
    const best = entry.ride.climbs.find(c => (climbResult(entry.ride, c).improvement ?? 0) > 0);
    const featured = best ?? entry.ride.climbs[0], result = featured ? climbResult(entry.ride, featured) : null;
    return <article className="f1-card" data-entry={entry.id} aria-busy={pending} aria-label={`${name}: ${entry.ride.ride.title}`}>
  <header className="f1-card-identity"><Avatar name={name}/><div><strong>{name}</strong><p><time dateTime={entry.ride.ride.startedAt}>{new Date(entry.ride.ride.startedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' })}</time><span> · </span>{entry.ride.ride.location}</p></div>{entry.companions.length > 0 && <span className="f1-group" title={`With ${entry.companions.join(' and ')}`}><Users size={14}/><span>{entry.companions.length + 1}</span></span>}</header>
  <div className="f1-card-copy"><h2><RideLink entry={entry}>{entry.ride.ride.title}</RideLink></h2>{entry.description && <p className="f1-description">{entry.description}</p>}
   <dl className="f1-stats" data-pending={pending}><div><dt>Distance</dt><dd>{pending ? '—' : distanceLabel(totals.distance)}<small>km</small></dd></div><div><dt>Elevation</dt><dd>{pending ? '—' : totals.gain === null ? '—' : Math.round(totals.gain).toLocaleString()}<small>m</small></dd></div><div><dt>Elapsed time</dt><dd>{pending ? '—' : timeLabel(totals.duration)}</dd></div></dl>
  </div>
  <FeedMap entry={entry}/><Relief scenario={entry.ride}/>
  {featured && result && <div className="f1-result" data-pending={pending}><Mountain size={15}/><RideLink entry={entry} climb={featured.id}>{featured.name}<ChevronRight size={13}/></RideLink><span className="f1-result-time">{timeLabel(result.duration)}</span>{best && <span className="f1-best">New best</span>}</div>}
  <footer className="f1-social"><span className="f1-social-count">{entry.kudos + Number(social.liked) > 0 && <>{entry.kudos + Number(social.liked)} kudos</>}{social.comments.length > 0 && <button onClick={() => update({ expanded: !social.expanded })}>{social.comments.length} {social.comments.length === 1 ? 'comment' : 'comments'}</button>}</span><div><button disabled={pending} aria-label={social.liked ? 'Remove kudos' : 'Give kudos'} aria-pressed={social.liked} onClick={() => update({ liked: !social.liked })}><Heart size={18} fill={social.liked ? 'currentColor' : 'none'}/></button><button ref={commentTrigger} disabled={pending} aria-label="Add comment" aria-expanded={social.editing} onClick={() => update({ editing: !social.editing })}><MessageCircle size={18}/></button></div></footer>
  {social.comments.length > 0 && <div className="f1-comments" data-pending={pending}>{comments.map(c => <div key={c.id}><Avatar name={c.name}/><p><strong>{c.name}</strong><span>{c.text}</span></p></div>)}{social.comments.length > 2 && <button onClick={() => update({ expanded: !social.expanded })}>{social.expanded ? 'Show fewer comments' : `View all ${social.comments.length} comments`}</button>}</div>}
  {social.editing && <form className="f1-comment-form" onSubmit={e => { e.preventDefault(); const text = social.draft.trim(); if (text) {
        update({ comments: [...social.comments, { id: crypto.randomUUID(), name: viewer, text }], draft: '', editing: false, expanded: true });
        commentTrigger.current?.focus();
    } }} onKeyDown={e => { if (e.key === 'Escape') {
        e.preventDefault();
        close();
    } }}><label className="sr-only" htmlFor={`comment-${entry.id}`}>Comment on {entry.ride.ride.title}</label><textarea disabled={pending} ref={commentInput} id={`comment-${entry.id}`} value={social.draft} rows={2} maxLength={1000} onChange={e => update({ draft: e.target.value })} placeholder="Add a comment"/><div><button type="button" onClick={close}>Cancel</button><button type="submit" disabled={pending || !social.draft.trim()}>Post comment</button></div></form>}
 </article>;
}
export function FeedV1({ scenario, filter, state, onFilter, onRecover }: {
    scenario: FeedScenario;
    filter: string;
    state: State;
    onFilter: (filter: string) => void;
    onRecover: () => void;
}) {
    const entries = visibleEntries(scenario, filter), pending = state === 'loading', own = scenario.entries.filter(e => e.owned), [listLimit, setListLimit] = useState(8);
    useEffect(() => setListLimit(8), [scenario, filter]);
    return <div className="f1-page"><header className="f1-shell"><strong>Boulder Roller</strong><span>Feed</span><Avatar name={scenario.viewer}/></header><main className="f1-layout">
  <aside className="f1-left" aria-hidden={state === 'error' || state === 'empty'} style={state === 'error' || state === 'empty' ? { visibility: 'hidden' } : undefined}><div className="f1-person"><Avatar name={scenario.viewer} large/><h1>{scenario.viewer}</h1></div>{own.length > 0 && <section className="f1-recent"><h2>Your rides</h2>{own.map(e => <RideLink entry={e} key={e.id}><span>{e.ride.ride.title}<small>{new Date(e.ride.ride.startedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' })}</small></span><ChevronRight size={14}/></RideLink>)}</section>}<p className="f1-rail-brand">Boulder Roller</p></aside>
  <section className="f1-stream" aria-label="Ride feed"><div className="f1-stream-heading"><h1>Feed</h1><div role="group" aria-label="Feed filter"><button aria-pressed={filter === 'everyone'} onClick={() => onFilter('everyone')}>Everyone</button><button aria-pressed={filter === 'following'} onClick={() => onFilter('following')}>Following</button></div></div>
   {state === 'error' || state === 'empty' || entries.length === 0 ? <div className="f1-empty"><h2>{state === 'error' ? 'Feed unavailable' : 'No rides yet'}</h2><p>{state === 'error' ? 'The feed could not be loaded.' : filter === 'following' ? 'Rides from people you follow will appear here.' : 'Rides will appear here.'}</p><button onClick={state === 'ready' ? () => onFilter('everyone') : onRecover}>{state === 'error' ? <><RotateCcw size={14}/>Try again</> : 'Show rides'}</button></div> : <>{entries.slice(0, listLimit).map(e => <FeedCard key={`${scenario.id}:${e.id}`} entry={e} pending={pending} viewer={scenario.viewer}/>)}{entries.length > listLimit && <button className="f1-load" onClick={() => setListLimit(n => n + 8)}>Show more rides</button>}</>}
  </section>
  <aside className="f1-right" aria-hidden={state === 'error' || state === 'empty'} style={state === 'error' || state === 'empty' ? { visibility: 'hidden' } : undefined}><section><h2>Climbs in this feed</h2>{entries.flatMap(e => e.ride.climbs.map(c => ({ entry: e, climb: c }))).filter((x, i, all) => all.findIndex(a => a.climb.id === x.climb.id) === i).slice(0, 4).map(({ entry, climb }) => { const r = climbResult(entry.ride, climb); return <RideLink entry={entry} climb={climb.id} key={climb.id}><Mountain size={16}/><span><strong>{climb.name}</strong><small>{distanceLabel(r.distance)} km <span> · </span>{r.gain === null ? '' : `${Math.round(r.gain)} m`}</small></span><ChevronRight size={13}/></RideLink>; })}</section><p className="f1-quiet-note">{new Set(entries.flatMap(e => e.ride.climbs.map(c => c.id))).size} climbs <span>·</span> {entries.length} rides</p></aside>
 </main></div>;
}
