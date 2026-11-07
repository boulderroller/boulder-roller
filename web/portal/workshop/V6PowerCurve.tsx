import { useEffect, useMemo, useRef, useState } from 'react';
import { powerCurve, type PowerBest } from './v6Model';
import { type AnalysisSample } from './v3Model';
import { timeLabel } from './scenario';
const durationLabel = (t: number) => t < 60 ? `${t}s` : t % 60 === 0 ? `${t / 60} min` : timeLabel(t);
export function V6PowerCurve({ points, pending }: { points: AnalysisSample[]; pending: boolean }) {
 const host=useRef<HTMLElement>(null),[width,setWidth]=useState(880);
 useEffect(()=>{if(!host.current)return;const observer=new ResizeObserver(([entry])=>setWidth(Math.max(280,entry.contentRect.width)));observer.observe(host.current);return()=>observer.disconnect();},[]);
 const curve = useMemo(() => powerCurve(points), [points]), [cursor, setCursor] = useState<number | null>(null);
 if (!curve.length) return <section ref={host} className="v6-power-room"><h2>Power curve</h2><p>No continuous power measurements lasting one second in this interval.</p></section>;
 const maximum = Math.max(1, ...curve.map(p=>p.watts)), duration = curve.at(-1)!.duration;
 const height=width<600?240:330, left=width<600?32:48, right=width-16, bottom=height-34;
 const x = (p: PowerBest) => left + Math.log(p.duration) / (Math.log(duration) || 1) * (right-left);
 const y = (p: PowerBest) => bottom - p.watts / maximum * (bottom-22);
 const active = cursor === null ? null : curve[Math.min(cursor,curve.length-1)];
 const anchors = curve.filter(p => [5,15,30,60,300,1200,3600].includes(p.duration));
 return <section ref={host} className="v6-power-room" aria-label="Power curve"><header><div><h2>Power curve</h2><p>Your strongest continuous efforts in this recording interval.</p></div><div className="v6-power-reading" aria-live="polite"><strong>{pending || !active ? '—' : Math.round(active.watts)}<small>W</small></strong><span>{active ? durationLabel(active.duration) : 'Move across the curve'}</span></div></header>
 <svg viewBox={`0 0 ${width} ${height}`} role="slider" tabIndex={pending ? -1 : 0} aria-label="Inspect power curve duration" aria-valuemin={1} aria-valuemax={duration} aria-valuenow={active?.duration ?? 1} aria-valuetext={active && !pending ? `${durationLabel(active.duration)}, ${Math.round(active.watts)} watts` : 'Arrow keys inspect recorded best efforts'} onPointerMove={e => { if(pending)return; const r=e.currentTarget.getBoundingClientRect(), target=Math.exp(Math.max(0,Math.min(1,((e.clientX-r.left)/r.width*width-left)/(right-left)))*Math.log(duration)); setCursor(curve.reduce((best,p,i) => Math.abs(Math.log(p.duration/target))<Math.abs(Math.log(curve[best].duration/target)) ? i : best,0)); }} onPointerLeave={() => setCursor(null)} onBlur={() => setCursor(null)} onKeyDown={e => { if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(e.key))return;e.preventDefault();setCursor(e.key==='Escape'?null:e.key==='Home'?0:e.key==='End'?curve.length-1:Math.max(0,Math.min(curve.length-1,(cursor??0)+(e.key==='ArrowLeft'?-1:1)))); }}>
 {[0,.25,.5,.75,1].map(f => <g key={f}><line x1={left} x2={right} y1={bottom-f*(bottom-22)} y2={bottom-f*(bottom-22)} className="v6-chart-grid"/><text x={left-8} y={bottom+4-f*(bottom-22)} textAnchor="end">{Math.round(maximum*f)}</text></g>)}
 {!pending && <path className="v6-power-line" d={curve.map((p,i)=>`${i?'L':'M'}${x(p)},${y(p)}`).join('')} />}
 {(width<600?[1,30,300,1200]:[1,5,30,60,300,1200,3600]).filter(d=>d<=duration).map(d=><text key={d} x={x({duration:d} as PowerBest)} y={height-9} textAnchor="middle">{durationLabel(d)}</text>)}
 {active && !pending && <><line x1={x(active)} x2={x(active)} y1={22} y2={bottom} className="v6-cursor-line"/><circle cx={x(active)} cy={y(active)} r={4} fill="#613393" stroke="white" strokeWidth={2}/></>}
 </svg><div className="v6-power-window">{active && !pending ? <>Best {durationLabel(active.duration)}: <strong>{timeLabel(active.start)}–{timeLabel(active.end)}</strong> elapsed</> : 'Each point is a best effort over its full duration.'}</div>
 <div className="v6-power-bests">{anchors.map(p=><button key={p.duration} onClick={()=>setCursor(curve.indexOf(p))} onBlur={()=>setCursor(null)} aria-pressed={active?.duration===p.duration}><span>{durationLabel(p.duration)}</span><strong>{pending?'—':Math.round(p.watts)}<small>W</small></strong></button>)}</div>
 <details className="v6-measurement-details"><summary>About this curve</summary><p>Time-weighted power from this recording, including measured zeros. Each effort requires uninterrupted coverage. Missing power and recording gaps over 30 seconds break coverage; unavailable durations are omitted. The final reading has no invented duration. Chart smoothing is never used in this calculation.</p></details></section>;
}
