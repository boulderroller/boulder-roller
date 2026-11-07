import {useState,type ReactNode} from 'react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {effortDate,type ClimbInspection} from './climbV5Model';
import {ordinal} from './climbV7Model';
import {v8Power} from './climbV8Model';
import type {ClimbV9Study} from './climbV9Model';
import {resultTime} from './climbV6Model';
import {boardComplete,boardGap,boardLeader,boardRows,gapScale,plural,podiumRows,powerColumn,v15Effort,v15Ride,type BoardView,type V14BoardRow} from './climbV15Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
const viewLabel=(v:BoardView)=>v==='overall'?'Overall':'Power verified';
const Unit=({children}:{children:ReactNode})=><>{' '}<span className="c15-unit">{children}</span></>;
/** A whole-second time keeps an invisible tenths slot, so m:ss lines up on the colon in the Time column. */
const Time=({value}:{value:string})=><>{value}{!value.includes('.')&&<span className="c15-tenths" aria-hidden="true">.0</span>}</>;
/** V14's board on Standard's table anatomy: the as-of in the section head, a toolbar row inside the card, and the facts set close together
 *  (place, rider, date, time) so the gap bar takes the free width: the spread of the hill is the table's picture. The leader tile carries an olive line. */
export function ClimbV15Board({data,study,state,legend}:{data:ClimbInspection;study:ClimbV9Study;state:string;legend?:{name:ReactNode;basis:ReactNode}}){
 const [view,setView]=useState<BoardView>('overall'),[explain,setExplain]=useState(false);
 const rows=boardRows(data,study,state,view),leader=boardLeader(rows),complete=boardComplete(rows),scale=gapScale(rows);
 const power=(r:V14BoardRow)=>r.href?v8Power(data.recordings,study.climbId,r.href):null;
 const withPower=powerColumn(rows.map(power));
 const cells=(r:V14BoardRow)=>{
  const watts=power(r),gap=boardGap(r.duration,leader);
  const name=r.riderHref?<Link href={r.riderHref}>{r.name}</Link>:<span>{r.name}</span>;
  const date=r.date?(r.href?<Link href={v15Ride(r.href)} label={`Open ${r.name}'s ride from ${effortDate(r.date)}`}><time dateTime={r.date}>{effortDate(r.date)}</time></Link>:<time dateTime={r.date}>{effortDate(r.date)}</time>):null;
  const label=resultTime(r.duration),aligned=<Time value={label}/>;
  const time=r.href?<Link href={v15Effort(r.href)} label={`Analyze ${r.name}'s effort, ${label}`}>{label}</Link>:<span>{label}</span>;
  const column=r.href?<Link href={v15Effort(r.href)} label={`Analyze ${r.name}'s effort, ${label}`}>{aligned}</Link>:<span>{aligned}</span>;
  const gapNode=r.rank===1?'Fastest':gap===null?null:<>+{gap}<Unit>s</Unit></>;
  const watt=watts===null?null:<>{Math.round(watts)}<Unit>W avg</Unit></>;
  return {watts,watt,name,date,time,column,gap,gapNode,you:r.current?<small className="c15-tag">You</small>:null};
 };
 const podium=podiumRows(rows);
 const tools=<div className="c15-board-tools"><div className="c15-board-tools-left"><div className="c15-segmented" role="group" aria-label="Leaderboard view">{(['overall','qualified'] as const).map(v=><button key={v} aria-pressed={view===v} onClick={()=>setView(v)}>{viewLabel(v)}</button>)}</div><button className="c15-help" aria-label="About leaderboard views" aria-expanded={explain} onClick={()=>setExplain(!explain)}>?</button></div><span>All time</span></div>;
 const explanation=explain&&<div className="c15-explanation"><strong>{viewLabel(view)}</strong><p>{view==='overall'?'Each rider’s fastest ascent. Power is shown where its recording is available.':'Each rider’s fastest ascent with verified power data. Ranked by time; these places are separate from Overall.'}</p></div>;
 const head=<tr><th scope="col">Place</th><th scope="col">Rider</th><th scope="col">Date</th><th scope="col" className="c15-num" aria-sort="ascending">Time</th>{withPower&&<th scope="col" className="c15-num">Avg power</th>}<th scope="col" className="c15-gap-head">Gap to fastest</th></tr>;
 const bar=(r:V14BoardRow,c:ReturnType<typeof cells>)=>scale===null?c.gapNode:<div className="c15-gap"><span className="c15-gap-track" aria-hidden="true">{r.rank===1?<i className="c15-gap-dot"/>:<i className="c15-gap-bar" style={{width:`${scale(r.duration)*100}%`}}/>}</span><span className="c15-gap-figure">{c.gapNode}</span></div>;
 return <section className="c15-section c15-leaderboard" id="c15-leaderboard" aria-labelledby="c15-leaderboard-title">
  <header className="c15-section-head"><h2 id="c15-leaderboard-title">Leaderboard</h2><span className="c15-rule"/>{state==='ready'&&rows.length>0&&data.board?.asOf&&<time dateTime={data.board.asOf}>As of {effortDate(data.board.asOf)}</time>}</header>
  {state==='loading'?<>
   <div className="c15-podium" aria-hidden="true">{[0,1,2].map(i=><div key={i} className="c15-card c15-tile c15-tile-loading"><span className="c15-bone c15-bone-mark"/><span className="c15-bone" style={{width:96}}/><span className="c15-bone c15-bone-wide" style={{width:120}}/></div>)}</div>
   <div className="c15-card c15-board" aria-label="Loading leaderboard">{tools}<table className="c15-table"><thead><tr><th scope="col">Place</th><th scope="col">Rider</th><th scope="col">Date</th><th scope="col" className="c15-num">Time</th><th scope="col" className="c15-gap-head">Gap to fastest</th></tr></thead><tbody>{[0,1,2,3,4].map(i=><tr key={i} className="c15-row-loading"><td colSpan={5}><span className="c15-bone" style={{width:'40%'}}/></td></tr>)}</tbody></table></div>
  </>:<>
   {podium.length>0&&<div className="c15-podium" data-count={podium.length}>{podium.map(r=>{const c=cells(r);return <article key={r.id} className="c15-card c15-tile" data-rank={r.rank} data-current={r.current}>
    <RankMark rank={r.rank} size={56}/><div className="c15-tile-who"><strong>{c.name}{c.you}</strong><span>{ordinal(r.rank)}{c.date&&<><i> · </i>{c.date}</>}</span></div>
    <div className="c15-tile-result"><strong>{c.time}</strong><span>{c.watt&&<>{c.watt}<i> · </i></>}{c.gapNode}</span></div>
   </article>;})}</div>}
   <div className="c15-card c15-board">
    {tools}{explanation}
    {!rows.length?<div className="c15-empty"><h3>{view==='qualified'?(study.candidate9?'No power-verified times yet':'Power-verified leaderboard unavailable'):state==='empty'||study.emptyLeaderboard||data.board?'No times yet':'Leaderboard unavailable'}</h3>{view==='overall'&&(state==='empty'||study.emptyLeaderboard)&&<p>Ride it to set the first time.</p>}</div>:<>
     <table className="c15-table" data-power={withPower}><colgroup><col className="c15-col-place"/><col className="c15-col-rider"/><col className="c15-col-date"/><col className="c15-col-time"/>{withPower&&<col className="c15-col-power"/>}<col className="c15-col-gap"/></colgroup><thead>{head}</thead><tbody>{rows.map(r=>{const c=cells(r);
      return <tr key={r.id} data-current={r.current}><td><div className="c15-place" data-podium={r.rank<=3}><RankMark rank={r.rank} size={24}/><span>{ordinal(r.rank)}</span></div></td><th scope="row"><div className="c15-rider">{c.name}{c.you}{!withPower&&c.watt&&<span className="c15-rider-basis">{c.watt}</span>}</div></th><td className="c15-date">{c.date}</td><td className="c15-num c15-time">{c.column}</td>{withPower&&<td className="c15-num c15-power">{c.watts!==null&&<>{Math.round(c.watts)}<Unit>W</Unit></>}</td>}<td className="c15-gap-cell">{bar(r,c)}</td></tr>;
     })}</tbody></table>
     <ol className="c15-board-list" aria-label={`${viewLabel(view)} leaderboard`}>{rows.map(r=>{const c=cells(r);return <li key={r.id} data-current={r.current}><RankMark rank={r.rank} size={20}/><strong className="c15-list-name">{c.name}{c.you}</strong><strong className="c15-list-time">{c.column}</strong><span className="c15-list-basis">{ordinal(r.rank)}{c.date&&<><i> · </i>{c.date}</>}{c.watt&&<><i> · </i>{c.watt}</>}</span><span className="c15-list-gap">{c.gapNode}</span></li>;})}</ol>
     {(complete||view==='qualified'||legend)&&<footer className="c15-table-foot"><span>{complete&&plural(rows.length,'rider')}{complete&&view==='qualified'&&<i> · </i>}{view==='qualified'&&'power-verified efforts'}</span>{legend&&<span className="c15-foot-legend"><span className="c15-foot-label">Local Legend</span> {legend.name}<i> · </i>{legend.basis}</span>}</footer>}
    </>}
   </div>
  </>}
 </section>;
}
