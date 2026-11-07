import {useCallback,useMemo,useState,type CSSProperties,type ReactNode} from 'react';
import {ArrowUpRight,RotateCcw} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Avatar,FeedV2Dialog} from '../feed/FeedV2Context';
import {timeLabel} from '../scenario';
import {climbStudies,selectedTerrain,type ClimbStudy,type ClimbViewer} from './climbModel';
import {climbV4MapHref} from './climbV4Navigation';
import {effortDate} from './climbV5Model';
import {inspectV7,ordinal} from './climbV7Model';
import {v8Power} from './climbV8Model';
import {v9Study} from './climbV9Model';
import {climbMeasurements} from './climbV12Measurements';
import {boardLeader,boardRows,heroFitPadding15,overallBasis,plural,railClimbs,stripCells,v15Effort,v15Ride,type Hero,type StripCell} from './climbV15Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
import {ClimbV15Hero,ClimbV15Elevation,ClimbV15MapCard,Unit,type Terrain} from './ClimbV15Hero';
import {ClimbV15Board} from './ClimbV15Board';
import {ClimbV15Vault} from './ClimbV15Vault';
import {ClimbV15History} from './ClimbV15History';
import {ClimbV15Shell,ClimbV15SignIn} from './ClimbV15Shell';
import {v9RiderHref} from '../feed/feedV9Model';
import './climb-v15.css';
const feedHref='/?surface=feed&variant=feed-v9&scenario=mixed&filter=everyone';
function Stat({label,value,basis,rank}:{label:string;value:ReactNode;basis?:ReactNode;rank?:boolean}){return <dl className="c15-stat"><dt>{label}</dt><dd className={rank?'c15-stat-value c15-stat-rank':'c15-stat-value'}>{value}</dd>{basis&&<dd className="c15-basis">{basis}</dd>}</dl>;}
const phone=()=>typeof window!=='undefined'&&window.matchMedia('(max-width:700px)').matches;
/** Candidate V15: V14's grammar with a value range. One dark masthead carries the mood (three directions, `hero`), the olive band frames the console,
 *  and the facts and the podium arrive on the first screen. Sections run Leaderboard, Your history, then the Vault closes the page. */
export function ClimbV15({study:input,viewer,state,hero,onRecover}:{study:ClimbStudy;viewer:ClimbViewer;state:'ready'|'loading'|'empty'|'error';hero:Hero;onRecover:()=>void}){
 const study=v9Study(input),data=useMemo(()=>inspectV7(study,viewer),[study,viewer]),terrain=data.terrain!;
 const [index,setIndex]=useState<number|null>(null),[range,setRange]=useState<[number,number]|null>(null),[expandedMap,setExpandedMap]=useState(false),[signIn,setSignIn]=useState(false);
 const personal=state==='ready'?data.personal:undefined,economy=state==='ready'?study.candidate7?.economy:undefined;
 const best=personal?.rows.find(r=>r.duration===personal.best),bestPower=best?.href?v8Power(data.recordings,study.climbId,best.href):null,exploreHref=climbV4MapHref(study,viewer),legend=economy?.legend;
 const dimensions=useMemo(()=>climbMeasurements(terrain),[terrain]);
 const overall=useMemo(()=>state==='ready'?boardRows(data,study,state,'overall'):[],[data,study,state]),leader=boardLeader(overall);
 const climbs=useMemo(()=>railClimbs(climbStudies,{current:input,viewer,hero,state}),[input,viewer,hero,state]);
 const heroFit=useCallback((w:number,h:number)=>heroFitPadding15(w,h,phone(),hero),[hero]),cardFit=useCallback((w:number,h:number)=>heroFitPadding15(w,h,phone(),'card'),[]);
 const viewerName=data.viewerRider?.name;
 const account=viewer==='signed-out'?<ClimbV15SignIn onClick={()=>setSignIn(true)}/>:personal?<Link className="c15-account" href={personal.riderHref} label={`Open ${personal.name}'s profile`}><FeedV2Avatar name={personal.name}/><span>{personal.name}</span></Link>:viewerName?<span className="c15-account"><FeedV2Avatar name={viewerName}/><span>{viewerName}</span></span>:null;
 const strip=state==='ready'?stripCells({viewer,personal,overall,legend:legend&&study.feed?legend:undefined,economy}):[];
 /** Under A, a lone Overall or Local Legend fact folds away and the elevation takes the row: the rider's place is the highlighted row
  *  directly below, and the legend moves to the board's foot, so nothing the column held is lost. */
 const cells=hero==='a'&&strip.length===1&&strip[0]!=='best'?[]:strip;
 const current=viewer==='rider'?overall.find(r=>r.current):undefined,place=personal?.rank??current?.rank,basis=overallBasis(current,leader);
 const legendFact=legend&&study.feed?{name:<Link href={v9RiderHref(study.feed,legend.riderId)}>{legend.name}</Link>,basis:<>{legend.completions} completions<i> · </i>Term ends {effortDate(legend.termEnd,true)}</>}:undefined;
 const single=cells.length===1;
 const cell=(kind:StripCell)=>{switch(kind){
  case 'best':return <Stat key={kind} label="Personal best" value={best?.href?<Link href={v15Effort(best.href)} label={`Analyze your personal best, ${timeLabel(personal!.best)}`}>{timeLabel(personal!.best)}</Link>:timeLabel(personal!.best)} basis={best&&<>{best.href?<Link href={v15Ride(best.href)} label={`Open ride from ${effortDate(best.date)}`}><time dateTime={best.date}>{effortDate(best.date)}</time></Link>:<time dateTime={best.date}>{effortDate(best.date)}</time>}{bestPower!==null&&<><i> · </i>{Math.round(bestPower)} W avg</>}</>}/>;
  case 'overall':return <Stat key={kind} label="Overall" rank value={<><RankMark rank={place!} size={single?40:24}/>{ordinal(place!)}</>} basis={personal?<a href="#c15-history">{plural(personal.rows.length,'effort')}</a>:basis&&<>{timeLabel(basis.duration)}{basis.gap!==null&&<><i> · </i>{basis.gap===0?'Fastest':<>+{basis.gap}<Unit>s</Unit></>}</>}</>}/>;
  case 'legend':return <Stat key={kind} label="Local Legend" value={legendFact!.name} basis={legendFact!.basis}/>;
 }};
 const t:Terrain={terrain,dimensions,index,onIndex:setIndex,range,onRange:r=>setRange(r&&selectedTerrain(terrain.profile,r)?r:null)};
 const map={expanded:expandedMap,onExpand:()=>setExpandedMap(!expandedMap)};
 const standing=state==='loading'&&viewer==='rider'?<div className="c15-card c15-standing" data-count={3} style={{'--cells':3} as CSSProperties} aria-label="Loading your results">{[0,1,2].map(i=><div key={i} className="c15-stat c15-stat-loading"><span className="c15-bone" style={{width:64,height:12}}/><span className="c15-bone" style={{width:96,height:20}}/></div>)}</div>
  :cells.length>0?<div className="c15-card c15-standing" data-count={cells.length} data-odd={cells.length%2===1} style={{'--cells':cells.length} as CSSProperties}>{cells.map(cell)}</div>:null;
 const sources=study.id==='live-geography'&&<><span>Elevation: USGS</span><a href="https://docs.boulderroller.xyz/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/manifest.json" target="_blank" rel="noreferrer">Data and sources</a></>;
 const footer=<footer className="c15-footer"><span className="c15-footer-mark">Boulder Roller</span><span className="c15-footer-credits"><span>© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></span>{sources}</span></footer>;
 return <div className="c15-page" data-scenario={study.id} data-viewer={viewer} data-state={state} data-hero={hero}>
  <ClimbV15Shell name={state==='error'?undefined:terrain.name} exploreHref={exploreHref} feedHref={feedHref} account={account} climbs={climbs}>
   <main className="c15-sheet" id="top" aria-busy={state==='loading'}>
    {state==='error'?<section className="c15-card c15-unavailable"><h1>Climb unavailable</h1><p>The climb could not be loaded.</p><div className="c15-card-actions"><button className="c15-button" onClick={onRecover}><RotateCcw aria-hidden="true"/>Try again</button></div></section>:<>
     <ClimbV15Hero hero={hero} t={t} map={{...map,fitPadding:heroFit}}/>
     {(hero!=='c'||standing)&&<div className="c15-first" data-hero={hero} data-standing={!!standing}>
      {hero==='a'&&<ClimbV15Elevation t={t}/>}
      {hero==='b'&&<ClimbV15MapCard t={t} map={{...map,fitPadding:cardFit}}/>}
      {standing}
     </div>}
     <ClimbV15Board key={`${study.id}:${state}`} {...{data,study,state}} legend={economy&&!cells.includes('legend')?legendFact:undefined}/>
     {personal?<ClimbV15History personal={personal} fastest={leader?.duration}/>:state!=='loading'&&!current&&<section className="c15-section" aria-labelledby="c15-history-title"><header className="c15-section-head"><h2 id="c15-history-title">Your history</h2><span className="c15-rule"/></header><div className="c15-card c15-efforts-empty"><h3>Your efforts</h3><p>{viewer==='signed-out'?'Sign in to see your history.':'No effort history on this climb.'}</p>{viewer==='signed-out'&&<div className="c15-card-actions"><button className="c15-button" onClick={()=>setSignIn(true)}>Sign in</button></div>}</div></section>}
     {economy&&<ClimbV15Vault economy={economy} viewer={viewer} name={terrain.name} onSignIn={()=>setSignIn(true)}/>}
    </>}
    {footer}
   </main>
  </ClimbV15Shell>
  {signIn&&<FeedV2Dialog title="Sign in" onClose={()=>setSignIn(false)}><div className="c15-detail"><h3>Your climbs, rides and history</h3><p>Sign in to Boulder Roller to see your own results and position.</p><a href="https://app.boulderroller.xyz" target="_blank" rel="noreferrer">Open Boulder Roller<ArrowUpRight aria-hidden="true"/></a></div></FeedV2Dialog>}
 </div>;
}
