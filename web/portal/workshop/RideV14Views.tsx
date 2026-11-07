import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { ArrowRight, Bike, SlidersHorizontal, Trophy, X } from 'lucide-react';
import { bestPower, powerEffortRange, type PowerBest } from './v12Model';
import {climbReturnHref,carryClimbOrigin,climbV3Destination} from './climb/climbV3Navigation';
import {climbStudies} from './climb/climbModel';
import './climb/climb-v3-navigation.css';
import { V13Vault } from './V13Vault';
import type { V13Context } from './v13Context';
import { gradeLabel, selectedAverageGrade } from './v13Grade';
import { V12PowerCadence } from './V12PowerCadence';
import { type RideV14Mode as V13Mode, type RideV14Navigation } from './rideV14Navigation';
import { V12Economics } from './V12Economics';
import { v12Economics } from './v12Example';
import { V12PowerDistribution } from './V12PowerDistribution';
import { V12Map } from './V12Map';
import { V12MapFrame } from './V12MapFrame';
import { V12ClimbMarks } from './V12ClimbMarks';
import { V12Profile } from './V12Profile';
import { V12PowerCurve } from './V12PowerCurve';
import { V12Charts } from './V12Charts';
import { climbResult, distanceLabel, integer, summarize, timeLabel, type Rider, type Scenario } from './scenario';
import { analysisSamples, channelSummary, channelValue, nearestIndex, rangeForClimb, scopedSamples, type Axis, type Channel, type MapFocus, type SampleRange } from './v3Model';
import { boundSelection } from './v12Selection';
import './candidate-v13.css';

const dateLabel = (date: string) => new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' });
function RiderIdentity({ rider, children }: { rider: Rider; children: ReactNode }) {
  const [failedPortrait, setFailedPortrait] = useState<string | null>(null);
  const initials = rider.displayName.split(/\s+/).filter(Boolean).map(part => Array.from(part)[0]).filter(Boolean);
  return <div className="v12-rider"><span className="v12-rider-avatar" aria-hidden="true">{rider.avatarDataUrl && failedPortrait !== rider.avatarDataUrl ? <img src={rider.avatarDataUrl} alt="" onError={() => setFailedPortrait(rider.avatarDataUrl!)} /> : `${initials[0] ?? ''}${initials.length > 1 ? initials.at(-1) : ''}`.toLocaleUpperCase()}</span><div className="v12-rider-text"><strong>{rider.displayName}</strong><div>{children}</div></div></div>;
}
function Value({ children, pending }: { children: ReactNode; pending: boolean }) {
  return <span className="v12-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{children}</span></span>;
}
function Figures({ values, pending, className = '' }: { values: { label: string; value: string | null; unit?: string }[]; pending: boolean; className?: string }) {
  return <dl className={`v12-figures ${className}`}>{values.filter(v => v.value !== null).map(v => <div key={v.label}><dt>{v.label}</dt><dd><Value pending={pending}>{v.value}{v.unit && <small>{v.unit}</small>}</Value></dd></div>)}</dl>;
}
export function RideV14Views({ scenario, nav, pending, focusTarget, bundled, owner, context: suppliedContext }: {
  scenario: Scenario; context?:V13Context; bundled: boolean; owner:boolean; nav:RideV14Navigation; pending: boolean; focusTarget: RefObject<HTMLHeadingElement | null>;
}) {
  const feedQuery=new URL(window.parent.location.href).searchParams;
  const climbOriginHref=climbReturnHref(feedQuery);
  const fromClimbV3=!!climbOriginHref&&['climb-v3','climb-v4'].includes(feedQuery.get('climbOriginVariant')??'');
  const context=fromClimbV3&&suppliedContext?{...suppliedContext,climbs:suppliedContext.climbs.map(c=>({...c,leaderboard:c.leaderboard.map(r=>({...r,...(r.href?{href:carryClimbOrigin(r.href,feedQuery)}:{})}))}))}:suppliedContext;
  const climbPageHref=(id:string)=>climbV3Destination(id,feedQuery,climbStudies);
  const vaultHref=(id:string)=>climbPageHref(id)??nav.href({mode:'vault',climbId:id,range:null});
  const backToClimb=()=>{if(climbOriginHref)window.parent.postMessage({type:'workshop-open-climb',href:climbOriginHref},location.origin);};
  const {mode,axis,climbId:selected,range:committed,mapHeight,hidden,effortDuration}=nav.location;
  const setAxis=(axis:Axis)=>nav.visit({axis},false);
  const setHidden=(value:Channel[]|((current:Channel[])=>Channel[]))=>nav.visit({hidden:typeof value==='function'?value(hidden):value},false);

  const economics = useMemo(() => owner ? context?.economics ?? v12Economics(scenario, bundled) : null, [scenario, bundled, context?.economics, owner]);
  const mapVisible = mode === 'analysis' || mode === 'heartRate';
  const [draft,setDraft]=useState<SampleRange|null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [editing, setEditing] = useState(false), [from, setFrom] = useState(''), [to, setTo] = useState(''), [error, setError] = useState('');
  const adjustButton = useRef<HTMLButtonElement>(null), editForm = useRef<HTMLFormElement>(null), previous = useRef(scenario);
  const profileContainer = useRef<HTMLDivElement>(null);
  const samples = useMemo(() => analysisSamples(scenario.ride.samples), [scenario]);
  const climb = scenario.climbs.find(c => c.id === selected);
  const climbRange = useMemo(() => rangeForClimb(samples, climb), [samples, climb]);
  const subject = useMemo(() => ({ startIndex: 0, endIndex: samples.length - 1 }), [samples]);
  const base = useMemo(() => scopedSamples(samples, subject), [samples, subject]);
  const sameContext = previous.current === scenario;
  const selection = sameContext ? committed ?? climbRange : null, preview = sameContext ? draft : null;
  const selectedRange = selection ?? subject, displayRange = preview ?? selectedRange;
  const detail = useMemo(() => selection ? scopedSamples(samples, selection) : base, [samples, base, selection]);
  const displayed = useMemo(() => samples.slice(displayRange.startIndex, displayRange.endIndex + 1), [samples, displayRange.startIndex, displayRange.endIndex]);
  const totals = useMemo(() => summarize(base), [base]), interval = useMemo(() => summarize(displayed), [displayed]);
  const averageGrade=useMemo(()=>selectedAverageGrade(displayed),[displayed]);
  const powerBest=useMemo(()=>effortDuration?bestPower(base,effortDuration):null,[base,effortDuration]);
  const effortBounds=useMemo(()=>powerBest?powerEffortRange(base,powerBest):null,[base,powerBest]);
  const stats = useMemo(() => ({ power: channelSummary(displayed, 'power'), basePower: channelSummary(base, 'power'), speed: channelSummary(base, 'speed'), cadence: channelSummary(base, 'cadence') }), [displayed, base]);
  const available = useMemo(() => (['speed', 'power', 'heartRate', 'cadence'] as Channel[]).filter(c => base.some(p => p[c] != null)), [base]);
  const channels = available.filter(c => !hidden.includes(c));
  const candidateCursor = sameContext ? hover : null;
  const cursor = candidateCursor !== null && candidateCursor >= subject.startIndex && candidateCursor <= subject.endIndex ? candidateCursor : null;
  const point = cursor === null ? null : samples[cursor];
  const outsideSelection = cursor !== null && selection !== null && (cursor < selection.startIndex || cursor > selection.endIndex);
  useEffect(() => {
    if (!sameContext) { setDraft(null); setHover(null); setEditing(false); setError(''); previous.current=scenario; }
    if ((mode==='heartRate'&&!available.includes('heartRate'))||(mode==='power'&&!available.includes('power'))||(mode==='economics'&&!economics)) nav.visit({mode:'analysis',climbId:null,range:null},false);
  }, [scenario, mode, economics, available]);
  useEffect(() => { if (editing) editForm.current?.querySelector('input')?.focus(); }, [editing]);
  useEffect(()=>{setDraft(null);setHover(null);setEditing(false);},[mode,selected,committed]);
  const clearInspection=()=>setHover(null);
  const resetTransient=()=>{setDraft(null);clearInspection();setEditing(false);};
  const navigate=(id:string)=>{resetTransient();nav.visit({mode:'analysis',climbId:selected===id?null:id,range:null,scroll:window.scrollY});};
  const switchMode=(next:V13Mode)=>{if(next===mode)return;resetTransient();nav.visit({mode:next,climbId:null,range:null,scroll:next==='overview'?nav.location.overview?.pageScroll??0:0});};
  const selectRange=(next:SampleRange)=>{resetTransient();nav.visit({mode:mode==='heartRate'?'heartRate':'analysis',climbId:null,range:boundSelection(subject,next.startIndex,next.endIndex)});};
  const clearRange=()=>{
    const root=profileContainer.current?.getRootNode() as Document|ShadowRoot|undefined;
    if(root?.activeElement?.classList.contains('v12-clear-interval'))profileContainer.current?.querySelector<SVGSVGElement>('svg[role="slider"]')?.focus();
    if(root?.activeElement?.classList.contains('v12-summary-clear'))adjustButton.current?.focus();
    resetTransient();if(selected||committed)nav.visit({climbId:null,range:null});
  };
  const openVault=(id:string)=>{const href=climbPageHref(id);if(href){window.parent.postMessage({type:'workshop-open-climb',href},location.origin);return;}resetTransient();nav.visit({mode:'vault',climbId:id,range:null,scroll:0});requestAnimationFrame(()=>focusTarget.current?.focus({preventScroll:true}));};
  const openPowerEffort=(effort:PowerBest)=>{if(pending)return;const bounds=powerEffortRange(base,effort);if(!bounds)return;resetTransient();nav.visit({mode:'analysis',climbId:null,range:{startIndex:bounds.startIndex,endIndex:bounds.endIndex},effortDuration:effort.duration,axis:'time',scroll:0});requestAnimationFrame(()=>focusTarget.current?.focus({preventScroll:true}));};
  const wholeRide=()=>{resetTransient();nav.visit({mode:'overview',climbId:null,range:null,effortDuration:null,scroll:0});};
  const openEffort=()=>{resetTransient();nav.visit({mode:'overview',climbId:selected,range:null,scroll:0});requestAnimationFrame(()=>focusTarget.current?.focus({preventScroll:true}));};
  const returnFromVault=()=>{if(window.parent.history.state?.r14Return)window.parent.history.back();else openEffort();};
  const onHover = (index: number | null) => setHover(index);
  const factor = axis === 'time' ? 60 : 1000, field = axis === 'time' ? 't' : 'd', unit = axis === 'time' ? 'min' : 'km';
  const editRange = () => { setFrom((samples[selectedRange.startIndex][field] / factor).toFixed(3)); setTo((samples[selectedRange.endIndex][field] / factor).toFixed(3)); setError(''); setEditing(true); };
  const closeEditor = () => { setEditing(false); requestAnimationFrame(() => adjustButton.current?.focus()); };
  const applyRange = () => {
    const a = Number(from), b = Number(to), min = samples[subject.startIndex][field] / factor, max = samples[subject.endIndex][field] / factor;
    if (!from.trim() || !to.trim() || !Number.isFinite(a) || !Number.isFinite(b) || a < min - .0005 || b > max + .0005 || b <= a) { setError(`Choose a start before the end, within ${min.toFixed(3)}–${max.toFixed(3)} ${unit}.`); return; }
    selectRange(boundSelection(subject, nearestIndex(samples, a * factor, axis), nearestIndex(samples, b * factor, axis))); closeEditor();
  };
  const focus: MapFocus | null = preview || selection ? { ...displayRange, kind: climb && !committed && !preview ? 'climb' : 'range' } : null;
  const bests = useMemo(() => scenario.climbs.filter(c => (climbResult(scenario, c).improvement ?? 0) > 0), [scenario]);
  return <>{fromClimbV3&&<div className="c3-ride-return"><a href={climbOriginHref!} target="_top" onClick={e=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();backToClimb();}}>← Back to climb</a>{(selected||committed||effortDuration||mode==='vault')&&<button onClick={wholeRide}>Whole ride<ArrowRight size={13}/></button>}</div>}{mode==='vault'&&climb&&<V13Vault scenario={scenario} climb={climb} context={context?.climbs.find(c=>c.climbId===climb.id)} owner={owner} economics={economics} pending={pending} onEffort={openEffort} onReturn={returnFromVault} effortHref={nav.href({mode:'overview',climbId:climb.id,range:null})} focusTarget={focusTarget}/>}<div hidden={mode==='vault'} data-mode={mode} style={{display:'block',padding:0}} className={`v12-layout v12-${mode} v12-analysis v12-ride`} onPointerDown={e => { if (!(e.target as Element).closest('.v12-map, .v12-profile, .v12-charts, .v12-power-room')) clearInspection(); }} onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); clearRange(); } }}>
    <main className="v12-main" aria-busy={pending}>
      <div className="v12-object-bar">{scenario.ride.rider ? <RiderIdentity rider={scenario.ride.rider}><span>Ride</span></RiderIdentity> : <div><Bike size={17} /><span>{scenario.source.kind === 'recorded' ? 'Recorded ride' : 'Illustrative ride'}</span></div>}</div>
      <header className="v12-identity"><div className="v12-title"><p><time dateTime={scenario.ride.startedAt}>{dateLabel(scenario.ride.startedAt)}</time><span> · </span>{scenario.ride.location}</p><h1 ref={mode==='vault'?undefined:focusTarget} tabIndex={-1}>{scenario.ride.title}</h1>{bests.length>0&&<button className="v12-title-best" onClick={()=>navigate(bests[0].id)}><Trophy size={12}/><Value pending={pending}>{bests.length} new {bests.length===1?'best':'bests'}</Value></button>}</div>
        <div className="v12-primary-result"><Figures pending={pending} values={[{ label: 'Distance', value: distanceLabel(totals.distance), unit: 'km' }, { label: 'Elapsed time', value: timeLabel(totals.duration) }, { label: 'Elevation', value: totals.gain === null ? null : integer(totals.gain), unit: 'm' }]} />
          <Figures className="v12-secondary-figures" pending={pending} values={[{ label: 'Avg power', value: stats.basePower.average === null ? null : channelValue(stats.basePower.average, 'power'), unit: 'W' }, { label: 'Avg cadence', value: stats.cadence.average === null ? null : channelValue(stats.cadence.average, 'cadence'), unit: 'rpm' }, { label: 'Avg speed', value: stats.speed.average === null ? null : channelValue(stats.speed.average, 'speed'), unit: 'km/h' }]} />
        </div>
      </header>

      <div className="v12-workspace" hidden={!mapVisible}>
        <div className="v12-geography"><V12MapFrame adjustable height={mapHeight} onHeight={mapHeight=>nav.visit({mapHeight},false)}><V12Map visible={mapVisible} scenario={scenario} focus={focus} cameraKey={`${mode}:${selection?.startIndex ?? subject.startIndex}:${selection?.endIndex ?? subject.endIndex}`} scrub={cursor} onScrub={onHover} onLeave={() => onHover(null)} onSelect={navigate} onClearSelection={clearRange} /></V12MapFrame>
          <div className="v12-elevation-workspace" ref={profileContainer}><div className="v12-profile-heading"><h2>Ride elevation</h2><div className="v12-profile-controls">{selection && <button className="v12-clear-interval" onClick={clearRange} aria-label="Clear selected interval" aria-keyshortcuts="Escape"><X size={13} />Clear</button>}<div className="v12-axis" role="group" aria-label="Horizontal axis"><button aria-pressed={axis === 'distance'} onClick={() => { setAxis('distance'); if (editing) closeEditor(); }}>Distance</button><button aria-pressed={axis === 'time'} onClick={() => { setAxis('time'); if (editing) closeEditor(); }}>Time</button></div></div></div>
            <V12Profile samples={samples} subject={subject} selection={selection} draft={preview} axis={axis} cursor={cursor} onHover={onHover} onDraft={setDraft} onSelect={selectRange} onClearSelection={clearRange} />
            <V12ClimbMarks scenario={scenario} samples={samples} axis={axis} selected={selected} onSelect={navigate}/>
          </div>

        </div>
      </div>
      {(mode === 'analysis' || mode === 'heartRate') && <section className="v12-analysis" aria-label="Ride analysis">
        <div className={`v12-selection-summary ${selection || preview ? 'has-selection' : ''}`} aria-live="polite"><div className="v12-selection-identity"><span>{preview ? 'Selecting' : climb && !committed ? 'Climb' : selection ? powerBest?'Power effort':'Selection' : 'Whole ride'}</span>{climb&&!committed&&!preview?<a className="v12-scope-vault" href={vaultHref(climb.id)} target="_top" onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();openVault(climb.id);}}>{climb.name}<ArrowRight size={13}/></a>:<strong>{powerBest&&!preview?`Best ${powerBest.duration<60?`${powerBest.duration}s`:powerBest.duration%60===0?`${powerBest.duration/60} min`:timeLabel(powerBest.duration)}`:selection||preview?axis==='distance'?`${(displayed[0].d/1000).toFixed(2)}–${(displayed.at(-1)!.d/1000).toFixed(2)} km`:`${timeLabel(displayed[0].t)}–${timeLabel(displayed.at(-1)!.t)}`:scenario.ride.title}</strong>}{!pending&&powerBest&&effortBounds?.expanded&&<small className="v12-effort-boundary">{powerBest.start.toFixed(1)}–{powerBest.end.toFixed(1)} s · {Math.round(powerBest.watts)} W<br/>View includes surrounding recorded samples</small>}</div>
          <Figures pending={pending} className="v12-selection-figures" values={[{ label: 'Distance', value: distanceLabel(interval.distance), unit: 'km' }, { label: 'Elapsed time', value: timeLabel(interval.duration) }, { label: 'Elevation', value: interval.gain === null ? null : integer(interval.gain), unit: 'm' }, ...(selection||preview?[{ label: 'Avg grade', value: gradeLabel(averageGrade), unit: averageGrade===null?undefined:'%' }]:[]), { label: 'Avg power', value: stats.power.average === null ? null : channelValue(stats.power.average, 'power'), unit: 'W' }]} />
          <div className="v12-selection-actions">{powerBest&&<button onClick={()=>{switchMode('power');requestAnimationFrame(()=>(profileContainer.current?.getRootNode() as Document|ShadowRoot|undefined)?.querySelector<SVGSVGElement>('.v12-power-room[aria-label="Power curve"] svg')?.focus());}}>Back to Power</button>}<button ref={adjustButton} onClick={editRange} aria-expanded={editing}><SlidersHorizontal size={14} />{selection ? 'Adjust' : 'Set interval'}</button>{selection && <button className="v12-summary-clear" onClick={clearRange}><X size={14} />Clear selection</button>}</div>
        </div>
        {editing && <form ref={editForm} className="v12-range-editor" onSubmit={e => { e.preventDefault(); applyRange(); }} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); closeEditor(); } }}><div><strong>Adjust interval</strong><span>Within this ride</span></div><label>From ({unit})<input aria-label={`Interval start in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" step="any" value={from} onChange={e => setFrom(e.target.value)} /></label><label>To ({unit})<input aria-label={`Interval end in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" step="any" value={to} onChange={e => setTo(e.target.value)} /></label><button type="submit">Apply</button><button type="button" onClick={closeEditor}>Cancel</button>{error && <p role="alert">{error}</p>}</form>}
        <div className="v12-inspection-bar"><span>{point ? <>{outsideSelection ? 'Outside selected interval' : 'At cursor'}<strong>{(point.d / 1000).toFixed(2)} km</strong><span>{timeLabel(point.t)}</span></> : null}</span></div>
        <V12Charts points={detail} channels={mode === 'heartRate' ? ['heartRate'] : channels} axis={axis} cursor={cursor} draft={preview} selected={!!selection} onHover={onHover} onDraft={setDraft} onSelect={selectRange} onClearSelection={clearRange} pending={pending} />
        <div hidden={mode === 'heartRate'} className="v12-channel-controls" role="group" aria-label="Visible measurements">{available.map(c => <label key={c}><input type="checkbox" checked={!hidden.includes(c)} disabled={!hidden.includes(c) && channels.length === 1} onChange={() => setHidden(current => current.includes(c) ? current.filter(x => x !== c) : [...current, c])} />{c === 'heartRate' ? 'Heart rate' : c[0].toUpperCase() + c.slice(1)}</label>)}</div>
        <details className="v12-measurement-details"><summary>About these measurements</summary><p>Chart averages include measured zeros and use covered time. Recording gaps over 30 seconds stay unconnected and are excluded from averages. Elapsed time includes pauses. The grade trace uses a centered 100 m window. Avg grade uses the selected section’s net elevation change divided by distance. It is unavailable below 50 m, across missing elevation, or across recording gaps over 30 seconds.</p><p>The cursor follows freely. Arrow keys inspect; leaving the chart clears the reading. Hold Shift with arrows to select in the measurement charts, then Enter to apply. A plain click in the map or chart, or Escape, returns to the whole ride. Drag inside the elevation selection to move it, or use its two edges to adjust the interval. Selection boundaries stay on recorded samples. Use Time to move a stationary interval.</p>{!available.includes('heartRate') && <p>Heart rate is not included in this ride.</p>}</details>
      </section>}
      <div hidden={mode!=='power'}><V12PowerCurve points={base} pending={pending} onEffort={openPowerEffort}/><V12PowerDistribution points={base} pending={pending}/>{available.includes('cadence')&&<V12PowerCadence points={base} scenario={scenario} pending={pending}/>}</div>
      {mode === 'economics' && economics && <V12Economics scenario={scenario} economics={economics} pending={pending} onVault={openVault} vaultHref={vaultHref}/>}

    </main>
  </div></>;
}
