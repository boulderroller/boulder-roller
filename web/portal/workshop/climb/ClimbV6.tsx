import {useMemo,useState,type MouseEvent,type ReactNode} from 'react';
import {ArrowUpRight,ChevronRight,Compass,Layers,RotateCcw,X} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Avatar,FeedV2Dialog} from '../feed/FeedV2Context';
import {distanceLabel,timeLabel} from '../scenario';
import {gradeLabel} from '../v13Grade';
import {inspectClimb,selectedTerrain,type ClimbStudy,type ClimbViewer} from './climbModel';
import {climbV3EffortHref} from './climbV3Navigation';
import {ClimbMap} from './ClimbMap';
import {ClimbV4Profile} from './ClimbV4Profile';
import {climbV4MapHref} from './climbV4Navigation';
import './climb-v4.css';
import './climb-v6.css';
import {ClimbV6Data} from './ClimbV6Data';
import {effortDate as date} from './climbV5Model';
const feedHref='/?surface=feed&variant=feed-v9&scenario=mixed&filter=everyone';
function open(e:MouseEvent<HTMLAnchorElement>,href:string){if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();window.parent.postMessage({type:'climb-open',href},location.origin);}
function Link({href,children,className,label}:{href:string;children:ReactNode;className?:string;label?:string}){return <a className={className} aria-label={label} href={href} target="_top" onClick={e=>open(e,href)}>{children}</a>;}
function effort(href:string){const p=new URLSearchParams(climbV3EffortHref(href).slice(2));p.set('climbOriginVariant','climb-v6');return `/?${p}`;}
function RankPiece({rank,size,pending}:{rank:number;size:number;pending:boolean}){return pending?<span className="c4-rank-loading" style={{width:size,height:size}} aria-hidden="true"><i/></span>:<RankMark rank={rank} size={size}/>;}
export function ClimbV6({study,viewer,state,onRecover}:{study:ClimbStudy;viewer:ClimbViewer;state:'ready'|'loading'|'empty'|'error';onRecover:()=>void}){
 const data=useMemo(()=>inspectClimb(study,viewer),[study,viewer]),terrain=data.terrain!;
 const [index,setIndex]=useState<number|null>(null),[range,setRange]=useState<[number,number]|null>(null),[expandedMap,setExpandedMap]=useState(false),[detail,setDetail]=useState<'position'|'sign-in'|number|null>(null);
 const selected=selectedTerrain(terrain.profile,range),pending=state==='loading',empty=state==='empty';
 const rows=empty?[]:data.board?.rows??[],personal=empty?undefined:data.personal;
 const leaders=rows.filter(r=>r.rank<=3);
 const best=personal?.rows.find(r=>r.duration===personal.best);
 const dimensions=useMemo(()=>{let min=Infinity,max=-Infinity,gain=0;for(let i=0;i<terrain.profile.length;i++){const p=terrain.profile[i];min=Math.min(min,p.elevation);max=Math.max(max,p.elevation);if(i)gain+=Math.max(0,p.elevation-terrain.profile[i-1].elevation);}const rise=terrain.profile.at(-1)!.elevation-terrain.profile[0].elevation;return {min,max,rise,gain,grade:rise/terrain.length*100};},[terrain]);
 const metric=(value:ReactNode)=>pending?<span className="c4-loading-value"><span aria-hidden="true">{value}</span></span>:value;
 const exploreHref=climbV4MapHref(study,viewer);
 return <div className="c4-page c6-page" data-scenario={study.id} data-viewer={viewer} data-state={state}>
  <header className="c4-shell"><div><Link className="c4-brand" href={feedHref}>Boulder Roller</Link><nav aria-label="Main navigation"><Link href={feedHref}>Feed</Link><a href={exploreHref??'http://localhost:4320/?surface=map&variant=map-v2&scenario=area'} target="_top">Map</a></nav><div className="c4-account">{viewer==='signed-out'?<button onClick={()=>setDetail('sign-in')}>Sign in</button>:personal?<Link href={personal.riderHref} label={`Open ${personal.name}'s profile`}><FeedV2Avatar name={personal.name}/></Link>:<FeedV2Avatar name={data.viewerRider?.name??'Rider'}/>}</div></div></header>
  <main className="c4-object" aria-busy={pending}>
   <div className="c4-page-actions">{exploreHref&&state!=='error'&&<a href={exploreHref} target="_top"><Compass size={15}/>Explore climbs</a>}</div>
   {state==='error'?<section className="c4-unavailable"><h1>Climb unavailable</h1><p>The climb could not be loaded.</p><button onClick={onRecover}><RotateCcw size={14}/>Try again</button></section>:<div className="c4-composition">
    <header className="c4-identity"><h1>{terrain.name}</h1>{terrain.locality&&<p>{terrain.locality}</p>}
     <dl className="c4-stat-plate"><div><dt>Distance</dt><dd>{distanceLabel(terrain.length)}<small>km</small></dd></div><div><dt>Elevation gain</dt><dd>{Math.round(dimensions.gain)}<small>m</small></dd></div><div><dt>Avg grade</dt><dd>{gradeLabel(dimensions.grade)}<small>%</small></dd></div><div><dt>Lowest elevation</dt><dd>{Math.round(dimensions.min)}<small>m</small></dd></div><div><dt>Highest elevation</dt><dd>{Math.round(dimensions.max)}<small>m</small></dd></div><div><dt>Elevation difference</dt><dd>{Math.round(dimensions.rise)}<small>m</small></dd></div></dl>
    </header>
    <section className="c4-terrain" aria-label="Climb terrain"><div className="c4-map" data-expanded={expandedMap}><ClimbMap discovery={terrain} index={index} onInspect={setIndex} range={range} onClear={()=>setRange(null)}/><button className="c4-map-size" onClick={()=>setExpandedMap(!expandedMap)} aria-expanded={expandedMap}>{expandedMap?'Compact map':'Expand map'}</button></div><ClimbV4Profile {...{terrain,index,range}} onIndex={setIndex} onRange={r=>setRange(selectedTerrain(terrain.profile,r)?r:null)}/><div className="c4-selection-space">{selected&&<div className="c4-selection" role="status"><span>Selection</span><strong>{distanceLabel(selected.distance)} <small>km</small></strong><strong>{gradeLabel(selected.grade)}<small>% avg grade</small></strong><button aria-label="Clear selection" onClick={()=>setRange(null)}><X size={14}/></button></div>}</div></section>
    <aside inert={pending?'' as unknown as boolean:undefined} className="c4-context">
     {personal?<section className="c4-personal"><header><Link href={personal.riderHref}><FeedV2Avatar name={personal.name}/><span><strong>{personal.name}</strong><small>Your history on this climb</small></span></Link></header><div className="c4-personal-result"><div className="c4-best"><h2>All-time PR</h2>{best?.href?<Link className="c4-best-time" label={`Analyze your personal best, ${timeLabel(personal.best)}`} href={effort(best.href)}>{metric(timeLabel(personal.best))}<ArrowUpRight size={16}/></Link>:<strong className="c4-best-time">{metric(timeLabel(personal.best))}</strong>}{best&&<time dateTime={best.date}>{date(best.date)}</time>}</div>{personal.rank&&<div className="c4-personal-rank"><RankPiece rank={personal.rank} size={72} pending={pending}/><span>Overall</span></div>}</div><a className="c4-history-jump" href="#c6-history"><span>{personal.rows.length} efforts</span><span>Your history<ChevronRight size={12}/></span></a></section>:<section className="c4-first-visit"><h2>Your history</h2><p>{viewer==='signed-out'?'Sign in to see your efforts on this climb.':'No effort history available.'}</p>{viewer==='signed-out'&&<button onClick={()=>setDetail('sign-in')}>Sign in<ChevronRight size={14}/></button>}</section>}
     {leaders.length>0&&<section className="c4-leaders"><header><h2>Leading times</h2><span>All time</span></header><ol>{leaders.map(r=><li key={r.id}><RankPiece rank={r.rank} size={60} pending={pending}/><div><span className="c4-leader-name">{r.riderHref?<Link href={r.riderHref}>{r.name}</Link>:r.name}</span><div className="c6-leader-result">{r.href?<Link className="c4-leader-time" href={effort(r.href)} label={`Analyze ${r.name}'s effort, ${timeLabel(r.duration)}`}>{metric(timeLabel(r.duration))}<ArrowUpRight size={13}/></Link>:<strong className="c4-leader-time">{metric(timeLabel(r.duration))}</strong>}<small>{r.rank===1?'Fastest':`#${r.rank} overall`}</small></div></div></li>)}</ol></section>}
     {data.vault&&<section className="c4-vault"><header><h2>Vault</h2><Layers size={15}/></header><span>Your deposited CAL</span><strong>{metric(data.vault.depositedCal.toLocaleString())}<small>CAL</small></strong><div><span>Settlement</span><span>Waiting</span></div><button onClick={()=>setDetail('position')}>View position<ChevronRight size={14}/></button></section>}
    </aside>
    <ClimbV6Data key={state} data={data} state={state} emptyLeaderboard={!!study.emptyLeaderboard} effortHref={effort}/>
   </div>}
   <footer className="c4-source"><span>© OpenStreetMap contributors</span>{study.id==='live-geography'&&<><span>Elevation: USGS</span><a href="https://docs.boulderroller.xyz/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/manifest.json" target="_blank" rel="noreferrer">Data and sources</a></>}</footer>
  </main>
  {detail!==null&&<FeedV2Dialog title={detail==='position'?'Your position':detail==='sign-in'?'Sign in':'Your effort'} onClose={()=>setDetail(null)}><div className="c4-detail"><span>{terrain.name}</span>{detail==='position'&&data.vault?<><strong className="c4-detail-value">{data.vault.depositedCal.toLocaleString()} <small>CAL</small></strong><p>Deposited</p><dl><div><dt>Settlement</dt><dd>Waiting</dd></div></dl></>:detail==='sign-in'?<><h3>Your climbs, rides and history</h3><p>Sign in to Boulder Roller to see your own results.</p><a href="https://app.boulderroller.xyz" target="_blank" rel="noreferrer">Open Boulder Roller<ArrowUpRight size={14}/></a></>:typeof detail==='number'&&personal?<><strong className="c4-detail-value">{timeLabel(personal.rows[detail].duration)}</strong><p>{date(personal.rows[detail].date)}</p>{personal.rows[detail].duration===personal.best&&<div className="c4-detail-best">Personal best</div>}{personal.rows[detail].href&&<Link href={effort(personal.rows[detail].href!)}>Analyze effort<ArrowUpRight size={13}/></Link>}</>:null}</div></FeedV2Dialog>}
 </div>;
}
