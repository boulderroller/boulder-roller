import { ArrowUpRight } from 'lucide-react';
import { useMemo, useState } from 'react';
import { climbResult, distanceLabel, integer, timeLabel, type Scenario } from './scenario';
import type { ExampleCal, ExampleEconomics } from './v12Example';
import { V12Relief } from './V12Relief';

export function V12CalAmount({ value, pending = false }: { value: ExampleCal; pending?: boolean }) {
 return <span className="v12-cal-amount"><span className="v12-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{value.amount}<small>CAL</small></span></span><span className="v12-cal-state">{pending?'Loading':value.state==='pending'?'Pending':'Counted'}</span></span>;
}
export function V12Economics({scenario,economics,pending,onVault,vaultHref}:{scenario:Scenario;economics:ExampleEconomics;pending:boolean;onVault:(id:string)=>void;vaultHref:(id:string)=>string}) {
 const [hover,setHover]=useState<string|null>(null);
 const climbs=useMemo(()=>economics.tributes.flatMap(t=>{const climb=scenario.climbs.find(c=>c.id===t.climbId);if(!climb)return[];const points=scenario.ride.samples.filter(p=>p.t>=climb.start&&p.t<=climb.end);return[{...t,points,result:climbResult(scenario,climb)}];}),[scenario,economics]);
 const start=scenario.ride.samples[0].d,extent=Math.max(1,scenario.ride.samples.at(-1)!.d-start);
 return <section className="v12-economics-room" aria-label="CAL and tribute">
  <header className="v12-cal-heading"><div><h2>Ride CAL</h2><p>{scenario.ride.rider?.displayName??'Rider'} receives the full Ride CAL.</p></div><V12CalAmount value={economics.riderCal} pending={pending}/></header>
  <div className="v12-tribute-terrain"><span>Climb tribute</span><V12Relief points={scenario.ride.samples} highlight={hover?(()=>{const c=climbs.find(c=>c.climbId===hover);return c?{start:c.points[0].d,end:c.points.at(-1)!.d}:null;})():null}/><svg className="v12-tribute-connections" viewBox="0 0 900 65" preserveAspectRatio="none" aria-hidden="true">{climbs.map((c,i)=>{const x=((c.points[0].d+c.points.at(-1)!.d)/2-start)/extent*900,target=(i+.5)/climbs.length*900;return <path key={c.climbId} data-active={hover===c.climbId||undefined} d={`M${x},0 C${x},38 ${target},25 ${target},65`}/>;})}</svg><div className="v12-tribute-pin-row">{climbs.map(c=><span key={c.climbId} data-active={hover===c.climbId||undefined} style={{left:`${((c.points[0].d+c.points.at(-1)!.d)/2-start)/extent*100}%`}}/>)}</div></div>
  <div className="v12-vault-destinations">{climbs.map(c=><a key={c.climbId} href={vaultHref(c.climbId)} target="_top" className="v12-vault-destination" data-active={hover===c.climbId||undefined} onMouseEnter={()=>setHover(c.climbId)} onMouseLeave={()=>setHover(null)} onFocus={()=>setHover(c.climbId)} onBlur={()=>setHover(null)} onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onVault(c.climbId);}}><div className="v12-destination-heading"><span>Vault</span><ArrowUpRight size={14}/></div><h3>{c.climbName}</h3><V12Relief points={c.points}/><div className="v12-destination-detail"><span>{distanceLabel(c.result.distance)} km{c.result.gain!==null&&` · ${integer(c.result.gain)} m`}<small>{pending?'—':timeLabel(c.result.duration)} · This ride</small></span><V12CalAmount value={c.cal} pending={pending}/></div></a>)}</div>
  <details className="v12-measurement-details"><summary>About CAL</summary><p>Ride CAL follows the ride’s TSS. Tribute follows the measured effort within each eligible climb and goes to that climb’s Vault separately. Tribute does not reduce the rider’s CAL.</p><p>Amounts and destinations in this workshop are example data. CAL is not a measurement of dietary calories.</p></details>
 </section>;
}
