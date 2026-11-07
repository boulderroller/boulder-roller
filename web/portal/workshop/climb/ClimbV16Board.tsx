import React,{useState,type ReactNode} from 'react';
import {Medal} from '../marks/Medal';
import {effortDate,type ClimbInspection} from './climbV5Model';
import type {ClimbV9Study} from './climbV9Model';
import {resultTime} from './climbV6Model';
import {boardComplete,boardGap,boardLeader,boardRows,plural,rowPower,powerVerified,v16Effort,type BoardView,type BoardPower} from './climbV16Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
const viewLabel=(v:BoardView)=>v==='overall'?'Overall':'Power verified';
/** Preserve V15's invisible tenths slot: align the colon without inventing precision. */
const Time=({value}:{value:string})=><>{value}{!value.includes('.')&&<span className="c16-tenths" aria-hidden="true">.0</span>}</>;
export function PowerCell({power}:{power:BoardPower|null}){
 if(!power)return null;
 return <span className="c16-watts" data-kind={power.kind}>
  <span className="c16-watts-value">{power.kind==='measured'?<svg className="c16-bolt" viewBox="0 0 10 14" aria-hidden="true"><path d="M6.2 0 0 8h3.6L2.8 14 10 5.6H6.2Z"/></svg>:<em aria-hidden="true">≈</em>}{power.watts}<span className="c16-watts-unit">W</span></span>
  <span className="c16-wkg">{power.kind==='measured'&&power.wkg!==null?`${power.wkg.toFixed(1)} W/kg`:null}</span>
 </span>;
}
/** One accessible row structure at both widths; power and place carry the board. */
export function ClimbV16Board({data,study,state,legend}:{data:ClimbInspection;study:ClimbV9Study;state:string;legend?:{name:ReactNode;basis:ReactNode}}){
 const [view,setView]=useState<BoardView>('overall'),[explain,setExplain]=useState(false);
 const rows=boardRows(data,study,state,view),leader=boardLeader(rows),complete=boardComplete(rows);
 const tools=<div className="c16-board-tools"><div className="c16-board-tools-left"><div className="c16-segmented" role="group" aria-label="Leaderboard view">{(['overall','qualified'] as const).map(v=><button key={v} aria-pressed={view===v} onClick={()=>setView(v)}>{viewLabel(v)}</button>)}</div><button className="c16-help" aria-label="About leaderboard views" aria-expanded={explain} onClick={()=>setExplain(!explain)}>?</button></div><span>All time</span></div>;
 const explanation=explain&&<div className="c16-explanation"><strong>{viewLabel(view)}</strong><p>{view==='overall'?'Each rider’s fastest ascent. Power is shown where its recording is available.':'Each rider’s fastest ascent with verified power data. Ranked by time; these places are separate from Overall.'}</p></div>;
 const heads=<div role="row" className="c16-board-cols"><span role="columnheader" aria-colindex={1} aria-label="Place">#</span><span role="columnheader" aria-colindex={2}>Rider</span><span role="columnheader" aria-colindex={3}>Power</span><span role="columnheader" aria-colindex={4} aria-sort="ascending">Time</span><span role="columnheader" aria-colindex={5} aria-label="Gap to fastest" className="c16-board-gap"/></div>;
 return <section className="c16-section c16-leaderboard" id="c16-leaderboard" aria-labelledby="c16-leaderboard-title">
  <header className="c16-section-head"><h2 id="c16-leaderboard-title">Leaderboard</h2><span className="c16-rule"/>{state==='ready'&&rows.length>0&&data.board?.asOf&&<time dateTime={data.board.asOf}>As of {effortDate(data.board.asOf)}</time>}</header>
  <div className="c16-board">{tools}{explanation}
   {state==='loading'?<div role="table" aria-label="Loading leaderboard" aria-busy="true">{heads}<div role="rowgroup" className="c16-board-rows">{[0,1,2,3,4].map(i=><div role="row" key={i} className="c16-board-row c16-board-loading">{[1,2,3,4,5].map(column=><span role="cell" aria-colindex={column} key={column} className={column===5?'c16-board-gap':undefined}><span className="c16-bone"/></span>)}</div>)}</div></div>
   :!rows.length?<div className="c16-empty"><h3>{view==='qualified'?(study.candidate9?'No power-verified times yet':'Power-verified leaderboard unavailable'):state==='empty'||study.emptyLeaderboard||data.board?'No times yet':'Leaderboard unavailable'}</h3>{view==='overall'&&(state==='empty'||study.emptyLeaderboard)&&<p>Ride it to set the first time.</p>}</div>
   :<><div role="table" aria-label={`${viewLabel(view)} leaderboard`}>{heads}<div role="rowgroup" className="c16-board-rows">{rows.map(r=>{
    const gap=boardGap(r.duration,leader),label=resultTime(r.duration),power=rowPower(data,study,r),metal=r.rank===1?'gold':r.rank===2?'silver':r.rank===3?'bronze':'plain';
    const verified=powerVerified(data,study,r);
    return <div role="row" key={r.id} className="c16-board-row" data-metal={metal} data-current={r.current} data-verified={verified}>
     <span role="cell" aria-colindex={1} className="c16-board-place"><Medal rank={r.rank} size={28}/></span>
     <span role="cell" aria-colindex={2} className="c16-board-rider">{r.riderHref?<Link href={r.riderHref}>{r.name}</Link>:<span>{r.name}</span>}{r.current&&<small className="c16-tag">You</small>}</span>
     <span role="cell" aria-colindex={3} className="c16-board-power" aria-label={power?.kind==='estimated'?`Estimated ${power.watts} W`:undefined}><PowerCell power={power}/></span>
     <span role="cell" aria-colindex={4} className="c16-board-time">{r.href?<Link href={v16Effort(r.href)} label={`Analyze ${r.name}'s effort, ${label}`}><Time value={label}/></Link>:<Time value={label}/>}</span>
     <span role="cell" aria-colindex={5} className="c16-board-gap">{r.rank===1?'Fastest':gap===null?null:<>+{gap} s</>}</span>
    </div>;
   })}</div></div>
   {(complete||view==='qualified'||legend)&&<footer className="c16-table-foot"><span>{complete&&plural(rows.length,'rider')}{complete&&view==='qualified'&&<i> · </i>}{view==='qualified'&&'power-verified efforts'}</span>{legend&&<span className="c16-foot-legend"><span className="c16-foot-label">Local Legend</span> {legend.name}<i> · </i>{legend.basis}</span>}</footer>}</>}
  </div>
 </section>;
}
