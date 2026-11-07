import { useEffect, useMemo, useRef, useState } from 'react';
import { Heart, MessageCircle } from 'lucide-react';
import { FeedV13Map } from './FeedV13Map';
import { FeedV2Avatar as Avatar } from './FeedV2Context';
import { PersonalContext, WorldContext } from './FeedV13Context';
import { FeedV13Results } from './FeedV13Results';
import { type FeedV13Scenario,riderForEntry } from './feedV13Model';
import {RiderLink,RiderProvider} from './FeedV13Riders';
import {pageAfter} from './feedV6Model';
import {v5Collection} from './feedV5Model';
import {FeedV13Link as RideLink,V13Navigation} from './FeedV13Navigation';
import type { Climb } from '../scenario';
import { type FeedEntry, type FeedComment, visibleEntries } from './feedModel';
import {V15Frame} from '../frame/V15Frame';
import {v13RailItems,v13RideFacts,v13OwnRide} from './feedV13Model';
import {Unit} from '../climb/ClimbV15Hero';
import './feed-v13.css';
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
function FeedMap({ entry, climb, active }: { entry: FeedEntry; climb?: Climb; active: boolean }) {
    return <div className="c15-map f13-map" data-ground="light" data-quiet="true"><FeedV13Map scenario={entry.ride} climb={climb} active={active}/><RideLink className="f13-map-link" entry={entry}><span className="sr-only">View ride: {entry.ride.ride.title}</span></RideLink><div className="c15-map-foot"><div className="c15-map-attribution">© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></div></div></div>;
}
function FeedCard({ entry, pending, viewer, scenario }: {
    active?: boolean;
    scenario: FeedV13Scenario;
    entry: FeedEntry;
    pending: boolean;
    viewer: string;
}) {
    const [hovered, setHovered] = useState<string|null>(null), [focused, setFocused] = useState<string|null>(null);
    const active = hovered !== null || focused !== null;
    const name = entry.ride.ride.rider?.displayName ?? 'Rider', facts=useMemo(()=>v13RideFacts(entry.ride),[entry]);
    const [social, setSocial] = useState<SocialState>(() => localSocial.get(`${scenario.id}:${entry.id}`) ?? { liked: false, comments: entry.comments, expanded: false, draft: '', editing: false });
    const commentInput = useRef<HTMLTextAreaElement>(null), commentTrigger = useRef<HTMLButtonElement>(null);
    const update = (patch: Partial<SocialState>) => setSocial(current => { const next = { ...current, ...patch }; localSocial.set(`${scenario.id}:${entry.id}`, next); return next; });
    useEffect(() => { if (social.editing)
        commentInput.current?.focus({preventScroll:true}); }, [social.editing]);
    const close = () => { update({ editing: false }); commentTrigger.current?.focus({preventScroll:true}); };
    const comments = social.expanded ? social.comments : social.comments.slice(-2);
    const leading = useMemo(()=>v5Collection(entry,scenario).visible[0]?.climb,[entry,scenario]);
    const featured = entry.ride.climbs.find(c=>c.id===(hovered??focused)) ?? leading ?? entry.ride.climbs[0];
    return <article className="c15-card f13-card" data-entry={entry.id} data-own={v13OwnRide(scenario,entry)} aria-busy={pending} aria-label={`${name}: ${entry.ride.ride.title}`}>
  <section className="c15-hero" data-hero="a"><div className="c15-hero-art">
   <header className="c15-hero-copy"><div className="c15-hero-title">
    <p className="c15-kicker f13-kicker"><RiderLink className="f13-identity-link" label={name} rider={riderForEntry(scenario,entry.id)}><Avatar name={name} portrait={entry.ride.ride.rider?.avatarDataUrl}/><span>{name}</span></RiderLink><span><time dateTime={entry.ride.ride.startedAt}>{new Date(entry.ride.ride.startedAt).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'America/New_York'})}</time>{entry.ride.ride.location&&<> · {entry.ride.ride.location}</>}</span></p>
    <h2 data-long={entry.ride.ride.title.length>24}><RideLink entry={entry}>{entry.ride.ride.title}</RideLink></h2>
    {entry.companions.length>0&&<div className="f13-companions"><span className="f13-companion-avatars">{entry.companions.slice(0,3).map((n,i)=><RiderLink key={`${n}:${i}`} label={n} rider={scenario.workshopV7?.riders.find(r=>r.companionKeys.includes(`${entry.id}:${i}`))}><Avatar name={n}/></RiderLink>)}</span><span>With {entry.companions.map((n,i)=><span key={`${n}:${i}`}>{i>0?(i===entry.companions.length-1?' and ':', '):''}<RiderLink rider={scenario.workshopV7?.riders.find(r=>r.companionKeys.includes(`${entry.id}:${i}`))}>{n}</RiderLink></span>)}</span></div>}
   </div><dl className="c15-hero-stats">{facts.map(f=><div key={f.label}><dt>{f.label}</dt><dd>{pending?<span className="c15-bone"/>:<>{f.value}{f.unit&&<Unit>{f.unit}</Unit>}</>}</dd></div>)}</dl></header>
   {pending?<div className="c15-map"><span className="c15-bone f13-map-skel"/></div>:<FeedMap entry={entry} climb={featured} active={active}/>}
  </div></section>
  <div className="f13-card-body">
   {entry.description&&<p className="f13-description">{entry.description}</p>}
   <FeedV13Results entry={entry} scenario={scenario} pending={pending} onHover={setHovered} onFocus={id=>{if(id)setHovered(null);setFocused(id);}}/>
  <footer className="f13-social"><span className="f13-social-count">{entry.kudos + Number(social.liked) > 0 && <>{entry.kudos + Number(social.liked)} kudos</>}{social.comments.length > 0 && <button onClick={() => update({ expanded: !social.expanded })}>{social.comments.length} {social.comments.length === 1 ? 'comment' : 'comments'}</button>}</span><div><button disabled={pending} aria-label={social.liked ? 'Remove kudos' : 'Give kudos'} aria-pressed={social.liked} onClick={() => update({ liked: !social.liked })}><Heart size={18} fill={social.liked ? 'currentColor' : 'none'}/></button><button ref={commentTrigger} disabled={pending} aria-label="Add comment" aria-expanded={social.editing} onClick={() => update({ editing: !social.editing })}><MessageCircle size={18}/></button></div></footer>
  {social.comments.length > 0 && <div className="f13-comments" data-pending={pending}>{comments.map(c => <div key={c.id}><RiderLink label={c.name} rider={scenario.workshopV7?.riders.find(r=>r.commentKeys.includes(`${entry.id}:${c.id}`))??scenario.workshopV7?.riders.find(r=>r.id===localCommentAuthors.get(`${scenario.id}:${entry.id}:${c.id}`))}><Avatar name={c.name}/></RiderLink><p><RiderLink rider={scenario.workshopV7?.riders.find(r=>r.commentKeys.includes(`${entry.id}:${c.id}`))??scenario.workshopV7?.riders.find(r=>r.id===localCommentAuthors.get(`${scenario.id}:${entry.id}:${c.id}`))}><strong>{c.name}</strong></RiderLink><span>{c.text}</span></p></div>)}{social.comments.length > 2 && <button onClick={() => update({ expanded: !social.expanded })}>{social.expanded ? 'Show fewer comments' : `View all ${social.comments.length} comments`}</button>}</div>}
  {social.editing && <form className="f13-comment-form" onSubmit={e => { e.preventDefault(); const text = social.draft.trim(); if (text) {
        const id=crypto.randomUUID(),author=scenario.workshopV7?.riders.find(r=>r.viewer);if(author)localCommentAuthors.set(`${scenario.id}:${entry.id}:${id}`,author.id);
        update({ comments: [...social.comments, { id, name: viewer, text }], draft: '', editing: false, expanded: true });
        commentTrigger.current?.focus({preventScroll:true});
    } }} onKeyDown={e => { if (e.key === 'Escape') {
        e.preventDefault();
        close();
    } }}><label className="sr-only" htmlFor={`f13-comment-${entry.id}`}>Comment on {entry.ride.ride.title}</label><textarea disabled={pending} ref={commentInput} id={`f13-comment-${entry.id}`} value={social.draft} rows={2} maxLength={1000} onChange={e => update({ draft: e.target.value })} placeholder="Add a comment"/><div><button type="button" onClick={close}>Cancel</button><button type="submit" disabled={pending || !social.draft.trim()}>Comment</button></div></form>}
  </div>
 </article>;
}
export function FeedV13({scenario,filter,state,active=true,onFilter,onRecover,riderId,onRider}:{active?:boolean;riderId?:string|null;onRider?:(id:string|null)=>void;scenario:FeedV13Scenario;filter:string;state:State;onFilter:(filter:string)=>void;onRecover:()=>void}){
 const hasPersonal=!!scenario.workshopV3?.personal,hasWorld=!!scenario.workshopV3?.world,pending=state==='loading';
 const [mobileContext,setMobileContext]=useState<'personal'|'world'|null>(null),entries=useMemo(()=>visibleEntries(scenario,filter),[scenario,filter]);
 const sessionKey=`${scenario.id}:${filter}`,saved=scrollSessions.get(sessionKey);
 const [listLimit,setListLimit]=useState(saved?.limit??8),[loadingMore,setLoadingMore]=useState(false),sentinel=useRef<HTMLDivElement>(null),loading=useRef(false);
 const save=()=>scrollSessions.set(sessionKey,{scroll:window.scrollY,limit:listLimit});
 useEffect(()=>{if(!active)return;const previous=scrollSessions.get(sessionKey);setListLimit(previous?.limit??8);const id=requestAnimationFrame(()=>window.scrollTo({top:previous?.scroll??0,behavior:'instant'}));return()=>cancelAnimationFrame(id);},[sessionKey,active]);
 const more=()=>{if(loading.current||listLimit>=entries.length||pending)return;loading.current=true;setLoadingMore(true);const page=pageAfter(entries,listLimit?entries[Math.min(listLimit,entries.length)-1].id:null,8);void Promise.resolve(page).then(next=>{setListLimit(n=>n+next.items.length);setLoadingMore(false);loading.current=false;});};
 useEffect(()=>{if(!sentinel.current||pending||!active)return;const observer=new IntersectionObserver(rows=>{if(rows[0].isIntersecting)more();},{rootMargin:'500px'});observer.observe(sentinel.current);return()=>observer.disconnect();},[listLimit,entries,pending,active]);
 useEffect(()=>{const capture=()=>{if(active&&document.documentElement.clientHeight>0&&(!window.frameElement||window.frameElement.getClientRects().length>0))save();};window.addEventListener('scroll',capture,{passive:true});return()=>window.removeEventListener('scroll',capture);},[sessionKey,listLimit,active]);
 const feedItems=[{id:'everyone',label:'Everyone'},{id:'following',label:'Following'}].map(item=>({...item,current:filter===item.id,onSelect:()=>{save();onFilter(item.id);}}));
 const account=<RiderLink className="c15-account" label={scenario.viewer} rider={scenario.workshopV7?.riders.find(r=>r.viewer)}><Avatar name={scenario.viewer} portrait={scenario.entries.find(e=>e.owned)?.ride.ride.rider?.avatarDataUrl}/><span>{scenario.viewer}</span></RiderLink>;
 const contexts=state!=='error'&&state!=='empty';
 const feedHref=`/?${new URLSearchParams({surface:'feed',variant:'feed-v13',scenario:scenario.id,filter})}`;
 const mapItems=v13RailItems(scenario).map(({meta,...item})=>state==='ready'?{...item,meta}:item);
 return <div className="c15-page v15-frame f13-page" data-scenario={scenario.id} data-state={state}><V13Navigation.Provider value={{scenario,filter,beforeNavigate:save}}><RiderProvider scenario={scenario} filter={filter} riderId={riderId} onRider={onRider}>
  <V15Frame section="feed" hrefs={{feed:feedHref,wordmark:feedHref}} feedItems={feedItems} mapItems={mapItems} crumbs={[{label:'Feed'}]} phoneTitle="Feed" account={account}>
   <h1 className="sr-only">Feed</h1>
   <div className="f13-layout" data-context={contexts&&(hasPersonal||hasWorld)}>
    {contexts&&(hasPersonal||hasWorld)&&<div className="f13-mobile-context"><div className="c15-card f13-disclosures">{hasPersonal&&<button aria-expanded={mobileContext==='personal'} onClick={()=>setMobileContext(v=>v==='personal'?null:'personal')}>Your riding <span aria-hidden="true">›</span></button>}{hasWorld&&<button aria-expanded={mobileContext==='world'} onClick={()=>setMobileContext(v=>v==='world'?null:'world')}>Boulder Roller <span aria-hidden="true">›</span></button>}</div>{mobileContext==='personal'&&<PersonalContext scenario={scenario} pending={pending}/>} {mobileContext==='world'&&<WorldContext scenario={scenario} pending={pending}/>}</div>}
    <section className="f13-stream" aria-label="Ride feed">
     {state==='error'||state==='empty'||entries.length===0?<div className="c15-card f13-empty"><h2>{state==='error'?'Feed unavailable':'No rides yet'}</h2><p>{state==='error'?'The feed could not be loaded.':filter==='following'?'Rides from people you follow will appear here.':'Rides will appear here.'}</p><button className="c15-button" onClick={state==='ready'?()=>onFilter('everyone'):onRecover}>{state==='error'?'Try again':'Show rides'}</button></div>:<>{entries.slice(0,listLimit).map(entry=><FeedCard key={`${scenario.id}:${entry.id}`} entry={entry} pending={pending} viewer={scenario.viewer} scenario={scenario}/>)}<div className="f13-continuation" ref={sentinel} aria-live="polite">{entries.length>listLimit?<button className="c15-button" disabled={loadingMore||pending} onClick={more}>{loadingMore?'Loading rides…':'More rides'}</button>:entries.length>8?<span>You’re up to date with these rides.</span>:null}</div></>}
    </section>
    {contexts&&(hasPersonal||hasWorld)&&<aside className="f13-side" aria-label="Your riding and Boulder Roller">{hasPersonal&&<PersonalContext scenario={scenario} pending={pending}/>} {hasWorld&&<WorldContext scenario={scenario} pending={pending}/>}</aside>}
   </div>
  </V15Frame>
 </RiderProvider></V13Navigation.Provider></div>;
}
