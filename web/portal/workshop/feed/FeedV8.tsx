import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Heart, MessageCircle, RotateCcw } from 'lucide-react';
import { FeedV6Map } from './FeedV6Map';
import { FeedV2Avatar as Avatar } from './FeedV2Context';
import { PersonalContext, WorldContext } from './FeedV8Context';
import { FeedV8Results } from './FeedV8Results';
import { climbBand } from './feedV2Model';
import { type FeedV8Scenario,riderForEntry } from './feedV8Model';
import {RiderLink,RiderProvider} from './FeedV8Riders';
import {pageAfter} from './feedV6Model';
import {v5Collection} from './feedV5Model';
import {FeedV8Link as RideLink,V8Navigation} from './FeedV8Navigation';
import type { Climb } from '../scenario';
import { summarize, timeLabel, distanceLabel, type Scenario } from '../scenario';
import { type FeedEntry, type FeedComment, visibleEntries } from './feedModel';
import '../candidate-v12.css';
import './feed-v3.css';
import './feed-v4.css';
import './feed-v5.css';
import './feed-v6.css';
import './feed-v8.css';
type State = 'ready' | 'loading' | 'empty' | 'error';
type SocialState = {
    liked: boolean;
    comments: FeedComment[];
    expanded: boolean;
    draft: string;
    editing: boolean;
};
const localSocial = new Map<string, SocialState>();
const localCommentAuthors=new Map<string,string>();
const scrollSessions = new Map<string,{scroll:number;limit:number}>();
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
    return <svg className="f3-relief" viewBox="0 0 700 48" preserveAspectRatio="none" role="img" aria-label="Ride elevation">{band && <rect data-climb-band x={band.from*700} y="0" width={(band.to-band.from)*700} height="48" fill={active ? "#91a77c55" : "#91a77c30"}/>} {runs.map((points, k) => { if (points.at(-1)!.d <= points[0].d)
        return null; const step = Math.max(1, Math.floor(points.length / 320)), path = points.filter((_, i) => i % step === 0 || i === points.length - 1).map((p, i) => `${i ? 'L' : 'M'}${x(p.d)},${(44 - (p.elevation! - min) / span * 36).toFixed(1)}`).join(' '); return <g key={k}><path d={`${path} L${x(points.at(-1)!.d)},48 L${x(points[0].d)},48 Z`} fill="#dce1d2"/><path d={path} fill="none" stroke="#9fa98f" strokeWidth=".8" vectorEffect="non-scaling-stroke"/></g>; })}</svg>;
}
function FeedMap({ entry, climb, active }: { entry: FeedEntry; climb?: Climb; active: boolean }) {
    return <div className="f3-map"><FeedV6Map scenario={entry.ride} climb={climb} active={active}/><RideLink className="f5-map-link" entry={entry}><span className="sr-only">View ride: {entry.ride.ride.title}</span></RideLink><div className="f3-attribution">© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></div></div>;
}
function FeedCard({ entry, pending, viewer, scenario }: {
    active?: boolean;
    scenario: FeedV8Scenario;
    entry: FeedEntry;
    pending: boolean;
    viewer: string;
}) {
    const [hovered, setHovered] = useState<string|null>(null), [focused, setFocused] = useState<string|null>(null);
    const active = hovered !== null || focused !== null;
    const name = entry.ride.ride.rider?.displayName ?? 'Rider', totals = useMemo(() => summarize(entry.ride.ride.samples), [entry]);
    const [social, setSocial] = useState<SocialState>(() => localSocial.get(`${scenario.id}:${entry.id}`) ?? { liked: false, comments: entry.comments, expanded: false, draft: '', editing: false });
    const commentInput = useRef<HTMLTextAreaElement>(null), commentTrigger = useRef<HTMLButtonElement>(null);
    const update = (patch: Partial<SocialState>) => setSocial(current => { const next = { ...current, ...patch }; localSocial.set(`${scenario.id}:${entry.id}`, next); return next; });
    useEffect(() => { if (social.editing)
        commentInput.current?.focus({preventScroll:true}); }, [social.editing]);
    const close = () => { update({ editing: false }); commentTrigger.current?.focus({preventScroll:true}); };
    const comments = social.expanded ? social.comments : social.comments.slice(-2);
    const leading = useMemo(()=>v5Collection(entry,scenario).visible[0]?.climb,[entry,scenario]);
    const featured = entry.ride.climbs.find(c=>c.id===(hovered??focused)) ?? leading ?? entry.ride.climbs[0];
    return <article className="f3-card" data-entry={entry.id} aria-busy={pending} aria-label={`${name}: ${entry.ride.ride.title}`}>
  <header className="f3-card-identity"><RiderLink className="f8-identity-link" label={name} rider={riderForEntry(scenario,entry.id)}><Avatar name={name} portrait={entry.ride.ride.rider?.avatarDataUrl}/></RiderLink><div><RiderLink rider={riderForEntry(scenario,entry.id)}><strong>{name}</strong></RiderLink><p><time dateTime={entry.ride.ride.startedAt}>{new Date(entry.ride.ride.startedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' })}</time><span> · </span>{entry.ride.ride.location}</p></div></header>
  <div className="f3-card-copy">{entry.companions.length > 0 && <div className="f3-companions"><span className="f3-companion-avatars">{entry.companions.slice(0,3).map((n,i)=><RiderLink key={`${n}:${i}`} label={n} rider={scenario.workshopV7?.riders.find(r=>r.companionKeys.includes(`${entry.id}:${i}`))}><Avatar name={n}/></RiderLink>)}</span><span>With {entry.companions.map((n,i)=><span key={`${n}:${i}`}>{i>0?(i===entry.companions.length-1?" and ":", "):""}<RiderLink rider={scenario.workshopV7?.riders.find(r=>r.companionKeys.includes(`${entry.id}:${i}`))}>{n}</RiderLink></span>)}</span></div>}<h2><RideLink entry={entry}>{entry.ride.ride.title}</RideLink></h2>{entry.description && <p className="f3-description">{entry.description}</p>}
   <dl className="f3-stats" data-pending={pending}><div><dt>Distance</dt><dd>{pending ? '—' : distanceLabel(totals.distance)}<small>km</small></dd></div><div><dt>Elevation</dt><dd>{pending ? '—' : totals.gain === null ? '—' : Math.round(totals.gain).toLocaleString()}<small>m</small></dd></div><div><dt>Elapsed time</dt><dd>{pending ? '—' : timeLabel(totals.duration)}</dd></div></dl>
  </div>
  <div className="f3-terrain" data-active={active}><FeedMap entry={entry} climb={featured} active={active}/><Relief scenario={entry.ride} climb={featured} active={active}/>
  </div>
  <FeedV8Results entry={entry} scenario={scenario} pending={pending} onHover={setHovered} onFocus={id=>{if(id)setHovered(null);setFocused(id);}}/>
  <footer className="f3-social"><span className="f3-social-count">{entry.kudos + Number(social.liked) > 0 && <>{entry.kudos + Number(social.liked)} kudos</>}{social.comments.length > 0 && <button onClick={() => update({ expanded: !social.expanded })}>{social.comments.length} {social.comments.length === 1 ? 'comment' : 'comments'}</button>}</span><div><button disabled={pending} aria-label={social.liked ? 'Remove kudos' : 'Give kudos'} aria-pressed={social.liked} onClick={() => update({ liked: !social.liked })}><Heart size={18} fill={social.liked ? 'currentColor' : 'none'}/></button><button ref={commentTrigger} disabled={pending} aria-label="Add comment" aria-expanded={social.editing} onClick={() => update({ editing: !social.editing })}><MessageCircle size={18}/></button></div></footer>
  {social.comments.length > 0 && <div className="f3-comments" data-pending={pending}>{comments.map(c => <div key={c.id}><RiderLink label={c.name} rider={scenario.workshopV7?.riders.find(r=>r.commentKeys.includes(`${entry.id}:${c.id}`))??scenario.workshopV7?.riders.find(r=>r.id===localCommentAuthors.get(`${scenario.id}:${entry.id}:${c.id}`))}><Avatar name={c.name}/></RiderLink><p><RiderLink rider={scenario.workshopV7?.riders.find(r=>r.commentKeys.includes(`${entry.id}:${c.id}`))??scenario.workshopV7?.riders.find(r=>r.id===localCommentAuthors.get(`${scenario.id}:${entry.id}:${c.id}`))}><strong>{c.name}</strong></RiderLink><span>{c.text}</span></p></div>)}{social.comments.length > 2 && <button onClick={() => update({ expanded: !social.expanded })}>{social.expanded ? 'Show fewer comments' : `View all ${social.comments.length} comments`}</button>}</div>}
  {social.editing && <form className="f3-comment-form" onSubmit={e => { e.preventDefault(); const text = social.draft.trim(); if (text) {
        const id=crypto.randomUUID(),author=scenario.workshopV7?.riders.find(r=>r.viewer);if(author)localCommentAuthors.set(`${scenario.id}:${entry.id}:${id}`,author.id);
        update({ comments: [...social.comments, { id, name: viewer, text }], draft: '', editing: false, expanded: true });
        commentTrigger.current?.focus({preventScroll:true});
    } }} onKeyDown={e => { if (e.key === 'Escape') {
        e.preventDefault();
        close();
    } }}><label className="sr-only" htmlFor={`comment-${entry.id}`}>Comment on {entry.ride.ride.title}</label><textarea disabled={pending} ref={commentInput} id={`comment-${entry.id}`} value={social.draft} rows={2} maxLength={1000} onChange={e => update({ draft: e.target.value })} placeholder="Add a comment"/><div><button type="button" onClick={close}>Cancel</button><button type="submit" disabled={pending || !social.draft.trim()}>Comment</button></div></form>}
 </article>;
}
export function FeedV8({ scenario, filter, state, active=true, onFilter, onRecover, riderId, onRider }: {
    active?: boolean;
    riderId?: string|null;
    onRider?: (id:string|null)=>void;
    scenario: FeedV8Scenario;
    filter: string;
    state: State;
    onFilter: (filter: string) => void;
    onRecover: () => void;
}) {
    const hasPersonal = !!scenario.workshopV3?.personal, personalLabel = 'Your riding';
    const hasWorld = !!scenario.workshopV3?.world;
    const [mobileContext, setMobileContext] = useState<'personal'|'world'|null>(null);
    const entries = useMemo(()=>visibleEntries(scenario,filter),[scenario,filter]), pending=state==='loading';
    const sessionKey=`${scenario.id}:${filter}`,saved=scrollSessions.get(sessionKey);
    const [listLimit,setListLimit]=useState(saved?.limit??8),[loadingMore,setLoadingMore]=useState(false),sentinel=useRef<HTMLDivElement>(null),loading=useRef(false);
    const save=()=>scrollSessions.set(sessionKey,{scroll:window.scrollY,limit:listLimit});
    useEffect(()=>{if(!active)return;const previous=scrollSessions.get(sessionKey);setListLimit(previous?.limit??8);const id=requestAnimationFrame(()=>window.scrollTo({top:previous?.scroll??0,behavior:'instant'}));return()=>cancelAnimationFrame(id);},[sessionKey,active]);
    const more=()=>{if(loading.current||listLimit>=entries.length||pending)return;loading.current=true;setLoadingMore(true);const page=pageAfter(entries,listLimit?entries[Math.min(listLimit,entries.length)-1].id:null,8);void Promise.resolve(page).then(next=>{setListLimit(n=>n+next.items.length);setLoadingMore(false);loading.current=false;});};
    useEffect(()=>{if(!sentinel.current||pending||!active)return;const observer=new IntersectionObserver(rows=>{if(rows[0].isIntersecting)more();},{rootMargin:'500px'});observer.observe(sentinel.current);return()=>observer.disconnect();},[listLimit,entries,pending,active]);
    useEffect(()=>{const capture=()=>{if(active&&document.documentElement.clientHeight>0&&(!window.frameElement||window.frameElement.getClientRects().length>0))save();};window.addEventListener('scroll',capture,{passive:true});return()=>window.removeEventListener('scroll',capture);},[sessionKey,listLimit,active]);
    return <V8Navigation.Provider value={{scenarioId:scenario.id,filter,beforeNavigate:save}}><RiderProvider scenario={scenario} filter={filter} riderId={riderId} onRider={onRider}><div className="f3-page f4-page f5-page f6-page f8-page" data-scenario={scenario.id} data-personal={hasPersonal} data-world={hasWorld} data-state={state}><header className="f3-shell"><strong>Boulder Roller</strong><span>Feed</span><RiderLink label={scenario.viewer} rider={scenario.workshopV7?.riders.find(r=>r.viewer)}><Avatar name={scenario.viewer}/></RiderLink></header><main className="f3-layout">
  {hasPersonal&&<aside className="f3-left" aria-label="Personal" hidden={state === 'error' || state === 'empty'}><PersonalContext scenario={scenario} pending={pending}/></aside>}
  <section className="f3-stream" aria-label="Ride feed"><div className="f3-stream-heading"><h1>Feed</h1><div role="group" aria-label="Feed filter"><button aria-pressed={filter === 'everyone'} onClick={() => {save();onFilter('everyone');}}>Everyone</button><button aria-pressed={filter === 'following'} onClick={() => {save();onFilter('following');}}>Following</button></div></div>
   {state !== 'empty' && state !== 'error' && (hasPersonal || hasWorld) && <div className="f3-mobile-context"><div>{hasPersonal && <button className="f3-personal-toggle" aria-expanded={mobileContext==='personal'} onClick={()=>setMobileContext(v=>v==='personal'?null:'personal')}>{personalLabel} <ChevronRight size={13}/></button>}{hasWorld && <button aria-expanded={mobileContext==='world'} onClick={()=>setMobileContext(v=>v==='world'?null:'world')}>Boulder Roller <ChevronRight size={13}/></button>}</div>{mobileContext && <section aria-label={mobileContext==='personal'?'Personal summary':'World summary'}>{mobileContext==='personal'?<PersonalContext scenario={scenario} pending={pending}/>:<WorldContext scenario={scenario} pending={pending}/>}</section>}</div>}
   {state === 'error' || state === 'empty' || entries.length === 0 ? <div className="f3-empty"><h2>{state === 'error' ? 'Feed unavailable' : 'No rides yet'}</h2><p>{state === 'error' ? 'The feed could not be loaded.' : filter === 'following' ? 'Rides from people you follow will appear here.' : 'Rides will appear here.'}</p><button onClick={state === 'ready' ? () => onFilter('everyone') : onRecover}>{state === 'error' ? <><RotateCcw size={14}/>Try again</> : 'Show rides'}</button></div> : <>{entries.slice(0, listLimit).map(e => <FeedCard key={`${scenario.id}:${e.id}`} entry={e} pending={pending} viewer={scenario.viewer} scenario={scenario}/>)}<div className="f6-continuation" ref={sentinel} aria-live="polite">{entries.length>listLimit?<button className="f3-load" disabled={loadingMore||pending} onClick={more}>{loadingMore?'Loading rides…':'More rides'}</button>:entries.length>8?<span>You’re up to date with these rides.</span>:null}</div></>}
  </section>
  {hasWorld&&<aside className="f3-right" aria-label="World" hidden={state === 'error' || state === 'empty'}><WorldContext scenario={scenario} pending={pending}/></aside>}
 </main></div></RiderProvider></V8Navigation.Provider>;
}
