import {useCallback,useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {formatNumber,formatWatts} from '../../src/lib/formatters';
import {Medal} from './marks';
import {IconButton,Segmented} from './Controls';
export type RowPower={kind:'measured'|'estimated';watts:number;wkg:number|null;range?:readonly [number,number]};
export type LeaderboardEntry={id:string;name:string;rank:number;time:string;gap?:string;current?:boolean;verified?:boolean;profileHref?:string;effortHref?:string;power?:RowPower|null};
export type BoardQuery={tab:string;period:string};
export type BoardLoad=(query:BoardQuery,signal:AbortSignal)=>Promise<LeaderboardEntry[]>;
const defaultPeriods=[{value:'all-time',label:'All time'}];
const tabs=[{value:'overall',label:'Overall'},{value:'qualified',label:'Power verified'}];
export function boardQuery(search:string,periods:readonly {value:string}[]=[{value:'all-time'}]):BoardQuery {
 const p=new URLSearchParams(search);return {tab:p.get('tab')==='qualified'?'qualified':'overall',period:periods.some(v=>v.value===p.get('period'))?p.get('period')!:periods[0].value};
}
export function rememberBoardScroll(){history.replaceState({...history.state,v15Scroll:window.scrollY},'',location.href);}
export function PowerCell({power,tone='light'}:{power:RowPower|null|undefined;tone?:'light'|'dark'}) {
 if(!power)return null;
 return <span className="v15-power" data-tone={tone} data-kind={power.kind} role={power.kind==='estimated'&&power.range?'img':undefined} aria-label={power.kind==='estimated'&&power.range?`Estimated ${formatWatts(power.watts)}, ${formatNumber(power.range[0])}–${formatNumber(power.range[1])} W, at a standard rider weight`:undefined}><span className="v15-power-value">{power.kind==='measured'?<svg className="v15-bolt" viewBox="0 0 10 14" aria-hidden="true"><path d="M6.2 0 0 8h3.6L2.8 14 10 5.6H6.2Z"/></svg>:<em aria-hidden="true">≈</em>}{formatNumber(power.watts)}<span className="v15-power-unit">W</span></span>{power.kind==='measured'&&power.wkg!==null&&<span className="v15-wkg">{formatNumber(power.wkg,1,1)} W/kg</span>}{power.kind==='estimated'&&power.range&&<span className="v15-power-range">{formatNumber(power.range[0])}–{formatNumber(power.range[1])} W</span>}</span>;
}
export function LeaderboardRow({entry,pinned=false}:{entry:LeaderboardEntry;pinned?:boolean}) {
 const metal=entry.rank===1?'gold':entry.rank===2?'silver':entry.rank===3?'bronze':'plain';
 return <div role="row" className="v15-board-row" data-row-id={entry.id} data-pinned={pinned} data-metal={metal} data-current={!!entry.current} data-verified={!!entry.verified} data-linked={!!entry.effortHref}>
  <span role="cell" className="v15-board-place"><Medal rank={entry.rank} size={28}/></span>
  <span role="cell" className="v15-board-rider">{entry.profileHref?<a className="v15-rider-link" href={entry.profileHref} target="_top" onClick={rememberBoardScroll}>{entry.name}</a>:entry.name}{entry.current&&<span className="v15-board-you">You</span>}</span>
  <span role="cell" className="v15-board-power" aria-label={entry.power?.kind==='estimated'?`Estimated ${formatWatts(entry.power.watts)}`:undefined}><PowerCell power={entry.power}/></span>
  <span role="cell" className="v15-board-time">{entry.effortHref?<a className="v15-effort-link" href={entry.effortHref} target="_top" onClick={rememberBoardScroll} aria-label={`Analyze ${entry.name}'s effort, ${entry.time}`}>{entry.time}{!entry.time.includes('.')&&<span className="v15-tenths" aria-hidden="true">.0</span>}</a>:<>{entry.time}{!entry.time.includes('.')&&<span className="v15-tenths" aria-hidden="true">.0</span>}</>}</span>
  <span role="cell" className="v15-board-gap">{entry.gap}</span>
 </div>;
}
export function Leaderboard({initialRows,load,signedIn,excerpt,periods=defaultPeriods,state='ready',overallNote,emptyMessage}:{initialRows:LeaderboardEntry[];load?:BoardLoad;signedIn:boolean;excerpt?:number;periods?:readonly {value:string;label:string}[];state?:'ready'|'loading'|'empty'|'error';overallNote?:string;emptyMessage?:(query:BoardQuery)=>ReactNode}) {
 const [query,setQuery]=useState(()=>boardQuery(typeof location==='undefined'?'':location.search,periods)),[rows,setRows]=useState(initialRows),[busy,setBusy]=useState(false),[failed,setFailed]=useState(false),[inView,setInView]=useState(false),[rowsOnScreen,setRowsOnScreen]=useState(false),[explain,setExplain]=useState(false);
 const periodKey=JSON.stringify(periods.map(({value})=>value));
 const list=useRef<HTMLDivElement>(null),pending=useRef<AbortController|null>(null),loader=useRef(load),queryRef=useRef(query);loader.current=load;queryRef.current=query;
 const refresh=useCallback(async()=>{
  if(!loader.current)return;
  pending.current?.abort();const controller=new AbortController();pending.current=controller;setBusy(true);setFailed(false);
  try{const next=await loader.current(queryRef.current,controller.signal);if(!controller.signal.aborted)setRows(next);}catch{if(!controller.signal.aborted)setFailed(true);}finally{if(!controller.signal.aborted)setBusy(false);}
 },[]);
 useEffect(()=>{void refresh();},[query.tab,query.period,refresh]);
 useEffect(()=>{
  const restore=()=>{setQuery(boardQuery(location.search,(JSON.parse(periodKey) as string[]).map(value=>({value}))));requestAnimationFrame(()=>window.scrollTo(0,history.state?.v15Scroll??0));};
  const focus=()=>{if(document.visibilityState==='visible')void refresh();};
  window.addEventListener('focus',focus);window.addEventListener('v15:effort-landed',refresh);window.addEventListener('popstate',restore);window.addEventListener('pagehide',rememberBoardScroll);
  if(Number.isFinite(history.state?.v15Scroll))requestAnimationFrame(()=>window.scrollTo(0,history.state.v15Scroll));
  return()=>{pending.current?.abort();window.removeEventListener('focus',focus);window.removeEventListener('v15:effort-landed',refresh);window.removeEventListener('popstate',restore);window.removeEventListener('pagehide',rememberBoardScroll);};
 },[refresh,periodKey]);
 const change=(next:BoardQuery)=>{rememberBoardScroll();const url=new URL(location.href);url.searchParams.set('tab',next.tab);url.searchParams.set('period',next.period);history.pushState({...history.state},'',url);setQuery(next);};
 const shown=excerpt===undefined?rows:rows.slice(0,excerpt),you=rows.find(r=>r.current);
 useLayoutEffect(()=>{
  const element=list.current;if(!element)return;
  let frame=0;
  const measure=()=>{
   frame=0;const current=element.querySelector('[data-current=true]')?.getBoundingClientRect();
   setInView(!!current&&current.top<innerHeight&&current.bottom>0);
   // The copy waits until real rows sit above its slot, so it never covers the board's tools while the board is only entering.
   const first=element.querySelector('.v15-board-row')?.getBoundingClientRect(),slot=element.closest('.v15-leaderboard')?.querySelector('.v15-board-pin-space')?.getBoundingClientRect().height??0,box=element.getBoundingClientRect();
   setRowsOnScreen(!!first&&first.top<innerHeight-slot&&box.bottom>0);
  };
  const schedule=()=>{if(!frame)frame=requestAnimationFrame(measure);};
  const observer=new ResizeObserver(schedule);observer.observe(element);measure();
  window.addEventListener('scroll',schedule,{passive:true});window.addEventListener('resize',schedule);
  return()=>{cancelAnimationFrame(frame);observer.disconnect();window.removeEventListener('scroll',schedule);window.removeEventListener('resize',schedule);};
 },[rows,excerpt,state,explain]);
 const loading=busy||state==='loading',empty=state==='empty'||(!rows.length&&!loading),error=state==='error'||failed;
 return <div className="v15-leaderboard"><div className="v15-board-tools"><div className="v15-board-tools-left"><Segmented label="Leaderboard view" options={tabs} value={query.tab} onChange={tab=>change({...query,tab})}/><IconButton size="help" label="About leaderboard views" aria-expanded={explain} onClick={()=>setExplain(!explain)}>?</IconButton></div>{periods.length===1?<span>{periods[0].label}</span>:<select className="v15-period" aria-label="Period" value={query.period} onChange={e=>change({...query,period:e.target.value})}>{periods.map(period=><option key={period.value} value={period.value}>{period.label}</option>)}</select>}</div>
  {explain&&<div className="v15-row-message"><p>{query.tab==='overall'?(overallNote??'Each rider’s fastest ascent. Power is shown where its recording is available.'):'Each rider’s fastest ascent with verified power data. Ranked by time; these places are separate from Overall.'}</p></div>}
  {error&&<div className="v15-row-message" role="alert">Leaderboard unavailable</div>}
  {empty?<p className="v15-row-message">{emptyMessage?.(query)??'No times yet'}</p>:<>
   <div role="table" className="v15-board-table" aria-label="Leaderboard" aria-busy={loading}>
    <div role="row" className="v15-board-cols"><span role="columnheader" aria-label="Place">#</span><span role="columnheader">Rider</span><span role="columnheader">Power</span><span role="columnheader">Time</span><span role="columnheader" className="v15-board-gap" aria-label="Gap to fastest"/></div>
    <div ref={list} role="rowgroup" className="v15-board-rows">{shown.map(entry=><LeaderboardRow key={entry.id} entry={entry}/>)}</div>
   </div>
   {you&&<div className="v15-board-pin-space"><div role="table" aria-label="Your leaderboard place" aria-busy={loading} className="v15-board-pin" data-visible={signedIn&&!inView&&rowsOnScreen&&!error} aria-hidden={!(signedIn&&!inView&&rowsOnScreen&&!error)}><div role="rowgroup"><LeaderboardRow entry={you} pinned/></div></div></div>}
  </>}
 </div>;
}
export function ListRow({name,meta,figure,href,current,power,gap}:{name:string;meta?:ReactNode;figure?:ReactNode;href?:string;current?:boolean;power?:RowPower;gap?:ReactNode}) {
 const content=<><span className="v15-list-copy"><span className="v15-list-name">{name}</span>{meta!==undefined&&<span className="v15-list-meta">{meta}</span>}</span>{figure!==undefined&&<span className="v15-list-figure" data-result={power?true:undefined}>{power?<span className="v15-list-result"><PowerCell power={power}/><span className="v15-list-clock">{figure}</span></span>:figure}{gap!==undefined&&<span className="v15-list-gap">{gap}</span>}</span>}</>;
 return href?<a className="v15-list-row" data-current={current||undefined} aria-current={current?'location':undefined} data-lines={meta===undefined?1:2} href={href} target="_top">{content}</a>:<div className="v15-list-row" data-current={current||undefined} data-lines={meta===undefined?1:2}>{content}</div>;
}
export function Table({label,columns,rows}:{label:string;columns:readonly string[];rows:readonly {id:string;cells:ReactNode[];figureColumns?:number[]}[]}) {
 return <div className="v15-table-scroll"><table className="v15-table" aria-label={label}><thead><tr>{columns.map((c,i)=><th scope="col" key={i}>{c}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.id}>{row.cells.map((cell,i)=><td data-figure={row.figureColumns?.includes(i)||undefined} key={i}>{cell}</td>)}</tr>)}</tbody></table></div>;
}
