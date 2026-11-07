import {useMemo,useState} from 'react';
import {Info} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {effortDate,type ClimbInspection} from './climbV5Model';
import {ordinal} from './climbV7Model';
import {v8Power} from './climbV8Model';
import {v9Effort,v9Ride,vaultAttempts,type ClimbV9Study} from './climbV9Model';
import {resultTime} from './climbV6Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
export function ClimbV9Board({data,study,state}:{data:ClimbInspection;study:ClimbV9Study;state:string}){
 const [view,setView]=useState<'overall'|'vault'>('overall'),[explain,setExplain]=useState(false);
 const recordings=useMemo(()=>new Map(data.recordings.map(r=>[r.entry.ride.id,r.entry])),[data.recordings]);
 const overall=data.board?.rows.map(r=>({...r,date:(r.rideId?recordings.get(r.rideId)?.ride.ride.startedAt:undefined)??study.candidate7?.rowDates[r.id]}))??[];
 const qualified=study.candidate9?vaultAttempts(study.candidate9.attempts).map(a=>{const row=overall.find(r=>r.id===a.rowId)!,record=data.recordings.find(r=>r.entry.id===a.entryId);return {...row,id:a.id,rank:a.rank,duration:a.duration,date:a.date,href:record?.href,rideId:record?.entry.ride.id};}):[];
 const rows=state==='empty'?[]:view==='vault'?qualified:overall,fastest=rows[0]?.duration;
 return <section className="c7-board c9-board" id="c7-leaderboard">
  <header className="c7-section-heading c9-board-heading"><h2>Leaderboard</h2><div className="c9-board-views" role="group" aria-label="Leaderboard view">{(['overall','vault'] as const).map(v=><button key={v} aria-pressed={view===v} onClick={()=>setView(v)}>{v==='overall'?'Overall':'Vault'}</button>)}</div><span>All time</span><button className="c9-info" aria-label="About leaderboard views" aria-expanded={explain} onClick={()=>setExplain(!explain)}><Info size={15}/></button></header>
  {explain&&<div className="c9-board-explanation"><strong>{view==='overall'?'Overall':'Vault'}</strong><p>{view==='overall'?'Each rider’s fastest ascent. Power is shown where its recording is available.':'Each rider’s fastest qualifying effort, ordered by ascent time. Vault places are separate from overall places.'}</p></div>}
  {state==='loading'?<div className="c7-skeleton-rows" aria-label="Loading leaderboard">{[0,1,2,3,4].map(i=><div key={i}/>)}</div>:!rows.length?<div className="c7-empty"><h3>{view==='vault'?(study.candidate9?'No qualifying times yet':'Vault leaderboard unavailable'):state==='empty'||study.emptyLeaderboard||data.board?'No times yet':'Leaderboard unavailable'}</h3>{view==='overall'&&(state==='empty'||study.emptyLeaderboard)&&<p>Ride it to set the first time.</p>}</div>:<>
   <table className="c8-table"><thead><tr><th scope="col">{view==='vault'?'Vault place':'Place'}</th><th scope="col">Rider</th><th scope="col" className="c8-date-column">Date</th><th scope="col">Time</th><th scope="col">Avg power</th><th scope="col" className="c8-gap-column">Gap to fastest</th></tr></thead><tbody>{rows.map(r=>{
    const power=r.href?v8Power(data.recordings,study.climbId,r.href):null,gap=fastest===undefined?null:Math.round((r.duration-fastest)*10)/10;
    const dateNode=r.date?(r.href?<Link href={v9Ride(r.href)} label={`Open ${r.name}'s ride from ${effortDate(r.date)}`}><time dateTime={r.date}>{effortDate(r.date)}</time></Link>:<time dateTime={r.date}>{effortDate(r.date)}</time>):null;
    return <tr key={r.id} data-current={r.current}><td>{view==='overall'?<div className="c7-place"><RankMark rank={r.rank} size={42}/><span>{ordinal(r.rank)}</span></div>:<span className="c9-vault-place">{r.rank}<small>{ordinal(r.rank).replace(String(r.rank),'')}</small></span>}</td><th scope="row"><div className="c7-rider-name">{r.riderHref?<Link href={r.riderHref}>{r.name}</Link>:<span>{r.name}</span>}{r.current&&<small>You</small>}</div><span className="c8-mobile-date">{dateNode}</span></th><td className="c8-date-column">{dateNode}</td><td className="c8-time">{r.href?<Link href={v9Effort(r.href)} label={`Analyze ${r.name}'s effort, ${resultTime(r.duration)}`}>{resultTime(r.duration)}</Link>:<span>{resultTime(r.duration)}</span>}</td><td className="c8-power">{power!==null?<><span>{Math.round(power)}</span><small>W</small></>:<span className="c8-absent" aria-label="Power unavailable">—</span>}</td><td className="c8-gap-column c8-gap">{r.rank===1?<span className="c8-fastest">Fastest</span>:gap===null?null:<>+{gap}<small>s</small></>}</td></tr>;
   })}</tbody></table><footer className="c7-table-foot"><span>{rows.length} riders{view==='vault'?' · qualifying efforts':''}</span>{data.board?.asOf&&<time dateTime={data.board.asOf}>As of {effortDate(data.board.asOf)}</time>}</footer>
  </>}
 </section>;
}
