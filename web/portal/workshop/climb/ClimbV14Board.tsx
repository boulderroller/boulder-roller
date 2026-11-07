import {useState,type ReactNode} from 'react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {effortDate,type ClimbInspection} from './climbV5Model';
import {ordinal} from './climbV7Model';
import {v8Power} from './climbV8Model';
import type {ClimbV9Study} from './climbV9Model';
import {resultTime} from './climbV6Model';
import {boardComplete,boardGap,boardLeader,boardRows,plural,podiumRows,powerColumn,v14Effort,v14Ride,type BoardView,type V14BoardRow} from './climbV14Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
export {boardRows} from './climbV14Model';
const viewLabel=(v:BoardView)=>v==='overall'?'Overall':'Power verified';
const Unit=({children}:{children:ReactNode})=><>{' '}<span className="c14-unit">{children}</span></>;
/** A whole-second time keeps an invisible tenths slot, so m:ss lines up on the colon in the Time column. */
const Time=({value}:{value:string})=><>{value}{!value.includes('.')&&<span className="c14-tenths" aria-hidden="true">.0</span>}</>;
export function ClimbV14Board({data,study,state,legend}:{data:ClimbInspection;study:ClimbV9Study;state:string;legend?:{name:ReactNode;basis:ReactNode}}){
 const [view,setView]=useState<BoardView>('overall'),[explain,setExplain]=useState(false);
 const rows=boardRows(data,study,state,view),leader=boardLeader(rows),complete=boardComplete(rows);
 const power=(r:V14BoardRow)=>r.href?v8Power(data.recordings,study.climbId,r.href):null;
 const withPower=powerColumn(rows.map(power));
 const cells=(r:V14BoardRow)=>{
  const watts=power(r),gap=boardGap(r.duration,leader);
  const name=r.riderHref?<Link href={r.riderHref}>{r.name}</Link>:<span>{r.name}</span>;
  const date=r.date?(r.href?<Link href={v14Ride(r.href)} label={`Open ${r.name}'s ride from ${effortDate(r.date)}`}><time dateTime={r.date}>{effortDate(r.date)}</time></Link>:<time dateTime={r.date}>{effortDate(r.date)}</time>):null;
  const label=resultTime(r.duration),aligned=<Time value={label}/>;
  const time=r.href?<Link href={v14Effort(r.href)} label={`Analyze ${r.name}'s effort, ${label}`}>{label}</Link>:<span>{label}</span>;
  const column=r.href?<Link href={v14Effort(r.href)} label={`Analyze ${r.name}'s effort, ${label}`}>{aligned}</Link>:<span>{aligned}</span>;
  const gapNode=r.rank===1?'Fastest':gap===null?null:<>+{gap}<Unit>s</Unit></>;
  const watt=watts===null?null:<>{Math.round(watts)}<Unit>W avg</Unit></>;
  return {watts,watt,name,date,time,column,gapNode,you:r.current?<small className="c14-you">You</small>:null};
 };
 const podium=podiumRows(rows);
 const head=<tr><th scope="col">Place</th><th scope="col">Rider</th><th scope="col">Date</th><th scope="col" className="c14-num">Time</th>{withPower&&<th scope="col" className="c14-num">Avg power</th>}<th scope="col" className="c14-num">Gap to fastest</th></tr>;
 return <section className="c14-section c14-leaderboard" id="c14-leaderboard" aria-labelledby="c14-leaderboard-title">
  <header className="c14-section-head c14-board-head"><h2 id="c14-leaderboard-title">Leaderboard</h2><span className="c14-rule"/><div className="c14-board-controls"><div className="c14-segmented" role="group" aria-label="Leaderboard view">{(['overall','qualified'] as const).map(v=><button key={v} aria-pressed={view===v} onClick={()=>setView(v)}>{viewLabel(v)}</button>)}</div><span>All time</span><button className="c14-help" aria-label="About leaderboard views" aria-expanded={explain} onClick={()=>setExplain(!explain)}>?</button></div></header>
  {explain&&<div className="c14-card c14-explanation"><strong>{viewLabel(view)}</strong><p>{view==='overall'?'Each rider’s fastest ascent. Power is shown where its recording is available.':'Each rider’s fastest ascent with verified power data. Ranked by time; these places are separate from Overall.'}</p></div>}
  {state==='loading'?<>
   <div className="c14-podium" aria-hidden="true">{[0,1,2].map(i=><div key={i} className="c14-card c14-tile c14-tile-loading"><span className="c14-bone c14-bone-mark"/><span className="c14-bone" style={{width:96}}/><span className="c14-bone c14-bone-wide" style={{width:120}}/></div>)}</div>
   <div className="c14-card c14-board" aria-label="Loading leaderboard"><table className="c14-table"><thead><tr><th scope="col">Place</th><th scope="col">Rider</th><th scope="col">Date</th><th scope="col" className="c14-num">Time</th><th scope="col" className="c14-num">Gap to fastest</th></tr></thead><tbody>{[0,1,2,3,4].map(i=><tr key={i} className="c14-row-loading"><td colSpan={5}><span className="c14-bone" style={{width:'40%'}}/></td></tr>)}</tbody></table></div>
  </>:!rows.length?<div className="c14-card c14-empty"><h3>{view==='qualified'?(study.candidate9?'No power-verified times yet':'Power-verified leaderboard unavailable'):state==='empty'||study.emptyLeaderboard||data.board?'No times yet':'Leaderboard unavailable'}</h3>{view==='overall'&&(state==='empty'||study.emptyLeaderboard)&&<p>Ride it to set the first time.</p>}</div>:<>
   {podium.length>0&&<div className="c14-podium" data-count={podium.length}>{podium.map(r=>{const c=cells(r);return <article key={r.id} className="c14-card c14-tile" data-current={r.current}>
    <div className="c14-tile-head"><RankMark rank={r.rank} size={40}/><div className="c14-tile-who"><strong>{c.name}{c.you}</strong><span>{ordinal(r.rank)}{c.date&&<><i> · </i>{c.date}</>}</span></div></div>
    <div className="c14-tile-result"><strong>{c.time}</strong><span>{c.watt&&<>{c.watt}<i> · </i></>}{c.gapNode}</span></div>
   </article>;})}</div>}
   <div className="c14-card c14-board">
    <table className="c14-table" data-power={withPower}><colgroup><col className="c14-col-place"/><col className="c14-col-rider"/><col/><col className="c14-col-time"/>{withPower&&<col className="c14-col-power"/>}<col className="c14-col-gap"/></colgroup><thead>{head}</thead><tbody>{rows.map(r=>{const c=cells(r);
     return <tr key={r.id} data-current={r.current}><td><div className="c14-place"><RankMark rank={r.rank} size={24}/><span>{ordinal(r.rank)}</span></div></td><th scope="row"><div className="c14-rider">{c.name}{c.you}{!withPower&&c.watt&&<span className="c14-rider-basis">{c.watt}</span>}</div></th><td className="c14-date">{c.date}</td><td className="c14-num c14-time">{c.column}</td>{withPower&&<td className="c14-num c14-power">{c.watts!==null&&<>{Math.round(c.watts)}<Unit>W</Unit></>}</td>}<td className="c14-num c14-gap">{c.gapNode}</td></tr>;
    })}</tbody></table>
    <ol className="c14-board-list" aria-label={`${viewLabel(view)} leaderboard`}>{rows.map(r=>{const c=cells(r);return <li key={r.id} data-current={r.current}><RankMark rank={r.rank} size={20}/><strong className="c14-list-name">{c.name}{c.you}</strong><strong className="c14-list-time">{c.column}</strong><span className="c14-list-basis">{ordinal(r.rank)}{c.date&&<><i> · </i>{c.date}</>}{c.watt&&<><i> · </i>{c.watt}</>}</span><span className="c14-list-gap">{c.gapNode}</span></li>;})}</ol>
    <footer className="c14-table-foot"><span>{complete&&plural(rows.length,'rider')}{complete&&view==='qualified'&&<i> · </i>}{view==='qualified'&&'power-verified efforts'}</span>{legend&&<span className="c14-foot-legend"><span className="c14-foot-label">Local Legend</span> {legend.name}<i> · </i>{legend.basis}</span>}{data.board?.asOf&&<time dateTime={data.board.asOf}>As of {effortDate(data.board.asOf)}</time>}</footer>
   </div>
  </>}
 </section>;
}
