import {useCallback,useMemo,useState,type CSSProperties,type ReactNode} from 'react';
import {ArrowUpRight,RotateCcw,X} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Avatar,FeedV2Dialog} from '../feed/FeedV2Context';
import {distanceLabel,timeLabel} from '../scenario';
import {gradeLabel} from '../v13Grade';
import {selectedTerrain,type ClimbStudy,type ClimbViewer} from './climbModel';
import {climbV4MapHref} from './climbV4Navigation';
import {effortDate} from './climbV5Model';
import {inspectV7,ordinal} from './climbV7Model';
import {v8Power} from './climbV8Model';
import {v9Study} from './climbV9Model';
import {climbMeasurements,elevationLabel} from './climbV12Measurements';
import {boardRows,heroFitPadding,plural,stripCells,v14Effort,v14Ride,type StripCell} from './climbV14Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
import {ClimbV14Map} from './ClimbV14Map';
import {ClimbV14Profile} from './ClimbV14Profile';
import {ClimbV14Board} from './ClimbV14Board';
import {ClimbV14Vault} from './ClimbV14Vault';
import {ClimbV14History} from './ClimbV14History';
import {ClimbV14Shell,ClimbV14SignIn} from './ClimbV14Shell';
import {v9RiderHref} from '../feed/feedV9Model';
import './climb-v14.css';
const feedHref='/?surface=feed&variant=feed-v9&scenario=mixed&filter=everyone';
const Unit=({children}:{children:ReactNode})=><>{' '}<span className="c14-unit">{children}</span></>;
/** A unit that closes up on its figure, as Standard writes 1.2%. */
const Tight=({children}:{children:ReactNode})=><span className="c14-unit">{children}</span>;
function Stat({label,value,basis,rank}:{label:string;value:ReactNode;basis?:ReactNode;rank?:boolean}){return <dl className="c14-stat"><dt>{label}</dt><dd className={rank?'c14-stat-value c14-stat-rank':'c14-stat-value'}>{value}</dd>{basis&&<dd className="c14-basis">{basis}</dd>}</dl>;}
const phone=()=>typeof window!=='undefined'&&window.matchMedia('(max-width:700px)').matches;
export function ClimbV14({study:input,viewer,state,onRecover}:{study:ClimbStudy;viewer:ClimbViewer;state:'ready'|'loading'|'empty'|'error';onRecover:()=>void}){
 const study=v9Study(input),data=useMemo(()=>inspectV7(study,viewer),[study,viewer]),terrain=data.terrain!;
 const [index,setIndex]=useState<number|null>(null),[range,setRange]=useState<[number,number]|null>(null),[expandedMap,setExpandedMap]=useState(false),[signIn,setSignIn]=useState(false);
 const selected=selectedTerrain(terrain.profile,range),personal=state==='ready'?data.personal:undefined,economy=state==='ready'?study.candidate7?.economy:undefined;
 const best=personal?.rows.find(r=>r.duration===personal.best),bestPower=best?.href?v8Power(data.recordings,study.climbId,best.href):null,exploreHref=climbV4MapHref(study,viewer),legend=economy?.legend;
 const dimensions=useMemo(()=>climbMeasurements(terrain),[terrain]);
 const overall=useMemo(()=>state==='ready'?boardRows(data,study,state,'overall'):[],[data,study,state]);
 const fitPadding=useCallback((w:number,h:number)=>heroFitPadding(w,h,phone()),[]);
 const active=index===null?null:terrain.profile[index];
 const viewerName=data.viewerRider?.name;
 const account=viewer==='signed-out'?<ClimbV14SignIn onClick={()=>setSignIn(true)}/>:personal?<Link className="c14-account" href={personal.riderHref} label={`Open ${personal.name}'s profile`}><FeedV2Avatar name={personal.name}/><span>{personal.name}</span></Link>:viewerName?<span className="c14-account"><FeedV2Avatar name={viewerName}/><span>{viewerName}</span></span>:null;
 const cells=state==='ready'?stripCells({viewer,personal,overall,legend:legend&&study.feed?legend:undefined,economy}):[];
 const current=viewer==='rider'?overall.find(r=>r.current):undefined,place=personal?.rank??current?.rank;
 const legendFact=legend&&study.feed?{name:<Link href={v9RiderHref(study.feed,legend.riderId)}>{legend.name}</Link>,basis:<>{legend.completions} completions<i> · </i>Term ends {effortDate(legend.termEnd,true)}</>}:undefined;
 const cell=(kind:StripCell)=>{switch(kind){
  case 'best':return <Stat key={kind} label="Personal best" value={best?.href?<Link href={v14Effort(best.href)} label={`Analyze your personal best, ${timeLabel(personal!.best)}`}>{timeLabel(personal!.best)}</Link>:timeLabel(personal!.best)} basis={best&&<>{best.href?<Link href={v14Ride(best.href)} label={`Open ride from ${effortDate(best.date)}`}><time dateTime={best.date}>{effortDate(best.date)}</time></Link>:<time dateTime={best.date}>{effortDate(best.date)}</time>}{bestPower!==null&&<><i> · </i>{Math.round(bestPower)} W avg</>}</>}/>;
  case 'overall':return <Stat key={kind} label="Overall" rank value={<><RankMark rank={place!} size={24}/>{ordinal(place!)}</>} basis={personal?<a href="#c14-history">{plural(personal.rows.length,'effort')}</a>:current?.date&&<time dateTime={current.date}>{effortDate(current.date)}</time>}/>;
  case 'legend':return <Stat key={kind} label="Local Legend" value={legendFact!.name} basis={legendFact!.basis}/>;
 }};
 const footer=study.id==='live-geography'&&<footer className="c14-footer"><span>Elevation: USGS</span><a href="https://docs.boulderroller.xyz/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/manifest.json" target="_blank" rel="noreferrer">Data and sources</a></footer>;
 return <div className="c14-page" data-scenario={study.id} data-viewer={viewer} data-state={state}>
  <ClimbV14Shell name={state==='error'?undefined:terrain.name} exploreHref={exploreHref} feedHref={feedHref} account={account}>
   <main className="c14-sheet" id="top" aria-busy={state==='loading'}>
    {state==='error'?<section className="c14-card c14-unavailable"><h1>Climb unavailable</h1><p>The climb could not be loaded.</p><div className="c14-card-actions"><button className="c14-button" onClick={onRecover}><RotateCcw aria-hidden="true"/>Try again</button></div></section>:<>
     <section className="c14-card c14-hero" data-expanded={expandedMap} aria-label="Climb terrain">
      <div className="c14-hero-art">
       <ClimbV14Map discovery={terrain} index={index} onInspect={setIndex} range={range} onClear={()=>setRange(null)} fitPadding={fitPadding}><button className="c14-map-size" onClick={()=>setExpandedMap(!expandedMap)} aria-expanded={expandedMap}>{expandedMap?'Compact map':'Expand map'}</button></ClimbV14Map>
       <div className="c14-hero-scrim" aria-hidden="true"/>
       <header className="c14-hero-copy">{terrain.locality&&<p className="c14-kicker">{terrain.locality}</p>}<h1 data-long={terrain.name.length>24}>{terrain.name}</h1>
        <dl className="c14-hero-stats" aria-label="Climb statistics"><div><dt>Distance</dt><dd>{distanceLabel(terrain.length)}<Unit>km</Unit></dd></div><div><dt title="Total uphill elevation change in this climb’s supplied profile">Elevation gain</dt><dd>{elevationLabel(dimensions.gain)}<Unit>m</Unit></dd></div><div><dt title="Finish minus start elevation, divided by climb distance">Avg grade</dt><dd>{dimensions.grade.toFixed(1)}<Tight>%</Tight></dd></div></dl>
       </header>
      </div>
      <div className="c14-elevation" role="group" aria-label="Elevation">
       <div className="c14-elevation-head"><span className="c14-kicker">Elevation</span><output aria-live="polite">{active&&<>{distanceLabel(active.d)}<Unit>km</Unit><i> · </i>{elevationLabel(active.elevation)}<Unit>m</Unit></>}</output>
        <dl className="c14-elev-facts" aria-label="Climb elevations"><div><dt>Lowest elev</dt><dd>{elevationLabel(dimensions.min)}<Unit>m</Unit></dd></div><div><dt>Highest elev</dt><dd>{elevationLabel(dimensions.max)}<Unit>m</Unit></dd></div><div><dt title="Highest minus lowest elevation on this climb">Elev difference</dt><dd>{elevationLabel(dimensions.difference)}<Unit>m</Unit></dd></div></dl></div>
       <ClimbV14Profile {...{terrain,index,range}} onIndex={setIndex} onRange={r=>setRange(selectedTerrain(terrain.profile,r)?r:null)}/>
       {selected&&<div className="c14-selection" role="status"><span>Selection</span><strong>{distanceLabel(selected.distance)}<Unit>km</Unit></strong><strong>{gradeLabel(selected.grade)}<Tight>%</Tight><Unit>avg grade</Unit></strong><button className="c14-icon-button" aria-label="Clear selection" onClick={()=>setRange(null)}><X/></button></div>}
      </div>
     </section>
     {state==='loading'&&viewer==='rider'?<div className="c14-card c14-strip" style={{'--cells':3} as CSSProperties} aria-label="Loading your results">{[0,1,2].map(i=><div key={i} className="c14-stat c14-stat-loading"><span className="c14-bone" style={{width:64,height:12}}/><span className="c14-bone" style={{width:96,height:20}}/></div>)}</div>
      :cells.length>0&&<div className="c14-card c14-strip" data-odd={cells.length%2===1} style={{'--cells':cells.length} as CSSProperties}>{cells.map(cell)}</div>}
     <ClimbV14Board key={`${study.id}:${state}`} {...{data,study,state}} legend={economy&&!cells.includes('legend')?legendFact:undefined}/>
     {economy&&<ClimbV14Vault economy={economy} viewer={viewer} name={terrain.name} onSignIn={()=>setSignIn(true)}/>}
     {personal?<ClimbV14History personal={personal}/>:state!=='loading'&&!current&&<section className="c14-section" aria-labelledby="c14-history-title"><header className="c14-section-head"><h2 id="c14-history-title">Your history</h2><span className="c14-rule"/></header><div className="c14-card c14-efforts-empty"><h3>Your efforts</h3><p>{viewer==='signed-out'?'Sign in to see your history.':'No effort history on this climb.'}</p>{viewer==='signed-out'&&<div className="c14-card-actions"><button className="c14-button" onClick={()=>setSignIn(true)}>Sign in</button></div>}</div></section>}
    </>}
    {footer}
   </main>
  </ClimbV14Shell>
  {signIn&&<FeedV2Dialog title="Sign in" onClose={()=>setSignIn(false)}><div className="c14-detail"><h3>Your climbs, rides and history</h3><p>Sign in to Boulder Roller to see your own results and position.</p><a href="https://app.boulderroller.xyz" target="_blank" rel="noreferrer">Open Boulder Roller<ArrowUpRight aria-hidden="true"/></a></div></FeedV2Dialog>}
 </div>;
}
