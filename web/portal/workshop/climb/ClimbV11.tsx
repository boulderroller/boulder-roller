import {useMemo,useState} from 'react';
import {ArrowUpRight,ChevronRight,Compass,RotateCcw,X} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Avatar,FeedV2Dialog} from '../feed/FeedV2Context';
import {distanceLabel,timeLabel} from '../scenario';
import {gradeLabel} from '../v13Grade';
import {selectedTerrain,type ClimbStudy,type ClimbViewer} from './climbModel';
import {ClimbV7Map} from './ClimbV7Map';
import {ClimbV4Profile} from './ClimbV4Profile';
import {climbV4MapHref} from './climbV4Navigation';
import {effortDate} from './climbV5Model';
import {inspectV7,ordinal} from './climbV7Model';
import {v9Study} from './climbV9Model';
import {v11Effort,v11Ride} from './climbV11Model';
import {v8Power} from './climbV8Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
import {ClimbV11Board,ClimbV11History} from './ClimbV11Data';
import {ClimbV11Vault,ClimbV11VaultSummary} from './ClimbV11Vault';
import {v9RiderHref} from '../feed/feedV9Model';
import './climb-v4.css';
import './climb-v7.css';
import './climb-v8.css';
import './climb-v10.css';
import './climb-v11.css';
const feedHref='/?surface=feed&variant=feed-v9&scenario=mixed&filter=everyone';
export function ClimbV11({study:input,viewer,state,onRecover}:{study:ClimbStudy;viewer:ClimbViewer;state:'ready'|'loading'|'empty'|'error';onRecover:()=>void}){
 const study=v9Study(input),data=useMemo(()=>inspectV7(study,viewer),[study,viewer]),terrain=data.terrain!;
 const [index,setIndex]=useState<number|null>(null),[range,setRange]=useState<[number,number]|null>(null),[expandedMap,setExpandedMap]=useState(false),[signIn,setSignIn]=useState(false);
 const selected=selectedTerrain(terrain.profile,range),personal=state==='ready'?data.personal:undefined,economy=state==='ready'?study.candidate7?.economy:undefined;
 const best=personal?.rows.find(r=>r.duration===personal.best),bestPower=best?.href?v8Power(data.recordings,study.climbId,best.href):null,exploreHref=climbV4MapHref(study,viewer),legend=economy?.legend;
 const dimensions=useMemo(()=>{let min=Infinity,max=-Infinity,gain=0;for(let i=0;i<terrain.profile.length;i++){const p=terrain.profile[i];min=Math.min(min,p.elevation);max=Math.max(max,p.elevation);if(i)gain+=Math.max(0,p.elevation-terrain.profile[i-1].elevation);}const rise=terrain.profile.at(-1)!.elevation-terrain.profile[0].elevation;return {min,max,rise,gain,grade:rise/terrain.length*100};},[terrain]);
 return <div className="c4-page c7-page c10-page c11-page" data-scenario={study.id} data-viewer={viewer} data-state={state}>
  <header className="c4-shell"><div><Link className="c4-brand" href={feedHref}>Boulder Roller</Link><nav aria-label="Main navigation"><Link href={feedHref}>Feed</Link><a href={exploreHref??'http://localhost:4320/?surface=map&variant=map-v2&scenario=area'} target="_top">Map</a></nav><div className="c4-account">{viewer==='signed-out'?<button onClick={()=>setSignIn(true)}>Sign in</button>:personal?<Link href={personal.riderHref} label={`Open ${personal.name}'s profile`}><FeedV2Avatar name={personal.name}/></Link>:<FeedV2Avatar name={data.viewerRider?.name??'Rider'}/>}</div></div></header>
  <main className="c7-object" aria-busy={state==='loading'}>
   <div className="c7-page-actions">{exploreHref&&state!=='error'&&<a href={exploreHref} target="_top"><Compass size={14}/>Explore climbs</a>}</div>
   {state==='error'?<section className="c4-unavailable"><h1>Climb unavailable</h1><p>The climb could not be loaded.</p><button onClick={onRecover}><RotateCcw size={14}/>Try again</button></section>:<>
    <div className="c7-composition"><header className="c7-identity"><h1>{terrain.name}</h1>{terrain.locality&&<p>{terrain.locality}</p>}<dl className="c7-stat-plate"><div><dt>Distance</dt><dd>{distanceLabel(terrain.length)}<small>km</small></dd></div><div><dt>Elevation gain</dt><dd>{Math.round(dimensions.gain)}<small>m</small></dd></div><div><dt>Avg grade</dt><dd>{gradeLabel(dimensions.grade)}<small>%</small></dd></div></dl><dl className="c7-stat-secondary"><div><dt>Low</dt><dd>{Math.round(dimensions.min)} m</dd></div><div><dt>High</dt><dd>{Math.round(dimensions.max)} m</dd></div><div><dt>Difference</dt><dd>{Math.round(dimensions.rise)} m</dd></div></dl></header>
     <section className="c7-terrain" aria-label="Climb terrain"><div className="c4-map" data-expanded={expandedMap}><ClimbV7Map discovery={terrain} index={index} onInspect={setIndex} range={range} onClear={()=>setRange(null)}/><button className="c4-map-size" onClick={()=>setExpandedMap(!expandedMap)} aria-expanded={expandedMap}>{expandedMap?'Compact map':'Expand map'}</button></div><ClimbV4Profile {...{terrain,index,range}} onIndex={setIndex} onRange={r=>setRange(selectedTerrain(terrain.profile,r)?r:null)}/>{selected&&<div className="c7-terrain-selection" role="status"><span>Selection</span><strong>{distanceLabel(selected.distance)} <small>km</small></strong><strong>{gradeLabel(selected.grade)}<small>% avg grade</small></strong><button aria-label="Clear selection" onClick={()=>setRange(null)}><X size={14}/></button></div>}</section>
     <aside className="c7-context">{state==='loading'?<div className="c7-context-loading" aria-label="Loading your results"/>:personal?<section className="c7-personal"><header><Link href={personal.riderHref}><FeedV2Avatar name={personal.name}/><strong>{personal.name}</strong></Link></header><div className="c7-personal-result"><div><h2>Personal best</h2>{best?.href?<Link className="c7-personal-time" href={v11Effort(best.href)} label={`Analyze your personal best, ${timeLabel(personal.best)}`}>{timeLabel(personal.best)}<ArrowUpRight size={16}/></Link>:<strong className="c7-personal-time">{timeLabel(personal.best)}</strong>}{best&&<div className="c8-personal-date">{best.href?<Link href={v11Ride(best.href)} label={`Open ride from ${effortDate(best.date)}`}><time dateTime={best.date}>{effortDate(best.date)}</time></Link>:<time dateTime={best.date}>{effortDate(best.date)}</time>}{bestPower!==null&&<span>{Math.round(bestPower)} <small>W avg</small></span>}</div>}</div>{personal.rank&&<div className="c7-personal-place"><RankMark rank={personal.rank} size={66}/><span><strong>{ordinal(personal.rank)}</strong> overall</span></div>}</div><a className="c7-history-link" href="#c7-history"><span>{personal.rows.length} efforts</span><span>Your history<ChevronRight size={14}/></span></a></section>:<section className="c7-personal c7-personal-empty"><h2>Your efforts</h2><p>{viewer==='signed-out'?'Sign in to see your history.':'No effort history on this climb.'}</p>{viewer==='signed-out'&&<button onClick={()=>setSignIn(true)}>Sign in<ArrowUpRight size={14}/></button>}</section>}
      {legend&&study.feed&&<section className="c7-legend"><div><h2>Local Legend</h2><span>{legend.completions} completions</span></div><Link href={v9RiderHref(study.feed,legend.riderId)}><FeedV2Avatar name={legend.name}/><span><strong>{legend.name}</strong><small>Term ends {effortDate(legend.termEnd,true)}</small></span><ArrowUpRight size={13}/></Link></section>}
      {economy&&<ClimbV11VaultSummary economy={economy}/>}
     </aside>
    </div>
    <div className="c7-data"><ClimbV11Board key={`${study.id}:${state}`} {...{data,study,state}}/>{economy&&<ClimbV11Vault economy={economy} viewer={viewer} name={terrain.name} onSignIn={()=>setSignIn(true)}/>}{personal&&<ClimbV11History personal={personal}/>}</div>
   </>}
   <footer className="c4-source"><span>© OpenStreetMap contributors</span>{study.id==='live-geography'&&<><span>Elevation: USGS</span><a href="https://docs.boulderroller.xyz/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/manifest.json" target="_blank" rel="noreferrer">Data and sources</a></>}</footer>
  </main>{signIn&&<FeedV2Dialog title="Sign in" onClose={()=>setSignIn(false)}><div className="c4-detail"><h3>Your climbs, rides and history</h3><p>Sign in to Boulder Roller to see your own results and position.</p><a href="https://app.boulderroller.xyz" target="_blank" rel="noreferrer">Open Boulder Roller<ArrowUpRight size={14}/></a></div></FeedV2Dialog>}
 </div>;
}
