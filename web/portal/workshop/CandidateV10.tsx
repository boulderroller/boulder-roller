import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { ArrowRight, BarChart3, Bike, ChevronRight, Map as MapIcon, Activity, GitBranch, Heart, SlidersHorizontal, Trophy, X } from 'lucide-react';
import { bestPower, powerEffortRange, type PowerBest } from './v10Model';
import { V10Vault } from './V10Vault';
import { V10RideContext } from './V10RideContext';
import { V10PowerCadence } from './V10PowerCadence';
import { useV10Navigation, type V10Mode } from './v10Navigation';
import { V10RideDetails } from './V10RideDetails';
import { V10Economics } from './V10Economics';
import { v10Economics } from './v10Example';
import { V10PowerDistribution } from './V10PowerDistribution';
import { V10Map } from './V10Map';
import { V10MapFrame } from './V10MapFrame';
import { V10ClimbMarks } from './V10ClimbMarks';
import { V10Profile } from './V10Profile';
import { V10PowerCurve } from './V10PowerCurve';
import { V10Social } from './V10Social';
import { V10Charts } from './V10Charts';
import { climbResult, distanceLabel, integer, summarize, timeLabel, type Rider, type Scenario } from './scenario';
import { analysisSamples, channelSummary, channelValue, nearestIndex, rangeForClimb, scopedSamples, type Axis, type Channel, type MapFocus, type SampleRange } from './v3Model';
import { boundSelection } from './v10Selection';
import './candidate-v10.css';

const dateLabel = (date: string) => new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' });
function RiderIdentity({ rider, children }: { rider: Rider; children: ReactNode }) {
  const [failedPortrait, setFailedPortrait] = useState<string | null>(null);
  const initials = rider.displayName.split(/\s+/).filter(Boolean).map(part => Array.from(part)[0]).filter(Boolean);
  return <div className="v10-rider"><span className="v10-rider-avatar" aria-hidden="true">{rider.avatarDataUrl && failedPortrait !== rider.avatarDataUrl ? <img src={rider.avatarDataUrl} alt="" onError={() => setFailedPortrait(rider.avatarDataUrl!)} /> : `${initials[0] ?? ''}${initials.length > 1 ? initials.at(-1) : ''}`.toLocaleUpperCase()}</span><div className="v10-rider-text"><strong>{rider.displayName}</strong><div>{children}</div></div></div>;
}
function Value({ children, pending }: { children: ReactNode; pending: boolean }) {
  return <span className="v10-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{children}</span></span>;
}
function Figures({ values, pending, className = '' }: { values: { label: string; value: string | null; unit?: string }[]; pending: boolean; className?: string }) {
  return <dl className={`v10-figures ${className}`}>{values.filter(v => v.value !== null).map(v => <div key={v.label}><dt>{v.label}</dt><dd><Value pending={pending}>{v.value}{v.unit && <small>{v.unit}</small>}</Value></dd></div>)}</dl>;
}
function Results({ scenario, selected, pending, onSelect }: { scenario: Scenario; selected: string | null; pending: boolean; onSelect: (id: string) => void }) {
  const rows = scenario.climbs.map((climb, i) => ({ climb, number: i + 1, result: climbResult(scenario, climb) })).filter(row => row.climb.id !== selected);
  if (!rows.length) return null;
  return <section className="v10-results" aria-label={selected ? 'Other climbs on this ride' : 'Climbs on this ride'}><header><h2>{selected ? 'Other climbs' : 'Climbs on this ride'}</h2><span>{rows.length}</span></header>
    {rows.map(({ climb, number, result }) => <button className="v10-result-row" key={climb.id} onClick={() => onSelect(climb.id)} aria-label={`Open ${climb.name}, ${distanceLabel(result.distance)} kilometers${pending ? ', results loading' : `, ${timeLabel(result.duration)} elapsed${result.power === null ? '' : `, ${integer(result.power)} watts`}`}`}>
      <span className="v10-result-name"><i>{number}</i><strong>{climb.name}</strong><ChevronRight size={14} /></span>
      <span className="v10-result-dimensions">{distanceLabel(result.distance)} km{result.gain !== null && <> · {integer(result.gain)} m</>}{result.grade !== null && <> · {result.grade.toFixed(1)}%</>}</span>
      <span className="v10-result-performance"><strong><Value pending={pending}>{timeLabel(result.duration)}</Value></strong>{result.power !== null && <span><Value pending={pending}>{integer(result.power)} <small>W</small></Value></span>}{(result.improvement ?? 0) > 0 && <span className="v10-best"><Value pending={pending}><Trophy size={12} />New best</Value></span>}</span>
    </button>)}
  </section>;
}

export function CandidateV10({ scenario, onSelect, onBack, pending, focusTarget, bundled, owner }: {
  scenario: Scenario; bundled: boolean; owner:boolean; selected: string | null; onSelect: (id: string) => void; onBack: () => void; pending: boolean; focusTarget: RefObject<HTMLHeadingElement | null>;
}) {
  const nav=useV10Navigation(scenario);
  const {mode,axis,climbId:selected,range:committed,mapHeight,expanded,hidden,effortDuration}=nav.location;
  const setAxis=(axis:Axis)=>nav.visit({axis},false);
  const setHidden=(value:Channel[]|((current:Channel[])=>Channel[]))=>nav.visit({hidden:typeof value==='function'?value(hidden):value},false);
  useEffect(()=>{if(selected)onSelect(selected);else onBack();},[selected]);

  const economics = useMemo(() => v10Economics(scenario, bundled), [scenario, bundled]);
  const mapVisible = mode === 'overview' || mode === 'analysis' || mode === 'heartRate';
  const [menuHost,setMenuHost]=useState<HTMLDivElement|null>(null);
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
  const navigate=(id:string)=>{resetTransient();nav.visit({mode:'analysis',climbId:mode==='analysis'&&selected===id?null:id,range:null,scroll:mode==='analysis'?window.scrollY:0});};
  const switchMode=(next:V10Mode)=>{if(next===mode)return;resetTransient();nav.visit({mode:next,climbId:null,range:null,scroll:0});};
  const selectRange=(next:SampleRange)=>{resetTransient();nav.visit({mode:mode==='heartRate'?'heartRate':'analysis',climbId:null,range:boundSelection(subject,next.startIndex,next.endIndex)});};
  const clearRange=()=>{
    if(document.activeElement?.classList.contains('v10-clear-interval'))profileContainer.current?.querySelector<SVGSVGElement>('svg[role="slider"]')?.focus();
    if(document.activeElement?.classList.contains('v10-summary-clear'))adjustButton.current?.focus();
    resetTransient();if(selected||committed)nav.visit({climbId:null,range:null});
  };
  const openVault=(id:string)=>{resetTransient();nav.visit({mode:'vault',climbId:id,range:null,scroll:0});requestAnimationFrame(()=>focusTarget.current?.focus({preventScroll:true}));};
  const openPowerEffort=(effort:PowerBest)=>{if(pending)return;const bounds=powerEffortRange(base,effort);if(!bounds)return;resetTransient();nav.visit({mode:'analysis',climbId:null,range:{startIndex:bounds.startIndex,endIndex:bounds.endIndex},effortDuration:effort.duration,axis:'time',scroll:0});requestAnimationFrame(()=>focusTarget.current?.focus({preventScroll:true}));};
  const openEffort=()=>{resetTransient();nav.visit({mode:'analysis',climbId:selected,range:null,scroll:0});requestAnimationFrame(()=>focusTarget.current?.focus({preventScroll:true}));};
  const returnFromVault=()=>{if(window.parent.history.state?.v10Return)window.parent.history.back();else openEffort();};
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
  return <>{mode==='vault'&&climb&&<V10Vault scenario={scenario} climb={climb} economics={economics} pending={pending} onEffort={openEffort} onReturn={returnFromVault} effortHref={nav.href({mode:'analysis',climbId:climb.id,range:null})} focusTarget={focusTarget}/>}<div hidden={mode==='vault'} className={`v10-layout v10-${mode} ${mode !== 'overview' ? 'v10-analysis' : ''} v10-ride`} onPointerDown={e => { if (!(e.target as Element).closest('.v10-map, .v10-profile, .v10-charts, .v10-power-room')) clearInspection(); }} onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); clearRange(); } }}>
    <aside className="v10-sidebar"><div className="v10-section-links"><nav aria-label="Ride sections"><button aria-current={mode === 'overview' ? 'page' : undefined} onClick={() => switchMode('overview')}><MapIcon size={17} />Overview</button><button aria-current={mode === 'analysis' ? 'page' : undefined} onClick={() => switchMode('analysis')}><BarChart3 size={17} />Analysis</button></nav>
      <nav className="v10-sidebar-tools" aria-label="Recorded analysis">{available.includes('power') && <button aria-current={mode === 'power' ? 'page' : undefined} onClick={() => switchMode('power')}><Activity size={17}/>Power</button>}{available.includes('heartRate') && <button aria-current={mode === 'heartRate' ? 'page' : undefined} onClick={() => switchMode('heartRate')}><Heart size={17}/>Heart rate</button>}{economics && <button aria-current={mode === 'economics' ? 'page' : undefined} onClick={() => switchMode('economics')}><GitBranch size={17}/>CAL & tribute</button>}</nav>
      </div><div className="v10-owner-slot" ref={setMenuHost}/>
    </aside>
    <main className="v10-main" aria-busy={pending}>
      <div className="v10-object-bar">{scenario.ride.rider ? <RiderIdentity rider={scenario.ride.rider}><span>Ride</span></RiderIdentity> : <div><Bike size={17} /><span>{scenario.source.kind === 'recorded' ? 'Recorded ride' : 'Illustrative ride'}</span></div>}<div className="v10-object-actions"><V10Social key={scenario.id} ride={scenario.ride}/></div></div>
      <header className={`v10-identity ${expanded?'details-open':''}`}><div className="v10-title"><p><time dateTime={scenario.ride.startedAt}>{dateLabel(scenario.ride.startedAt)}</time><span> · </span>{scenario.ride.location}</p><h1 ref={mode==='vault'?undefined:focusTarget} tabIndex={-1}>{scenario.ride.title}</h1>{bests.length>0&&<button className="v10-title-best" onClick={()=>navigate(bests[0].id)}><Trophy size={12}/><Value pending={pending}>{bests.length} new {bests.length===1?'best':'bests'}</Value></button>}<V10RideContext visible={mode==='overview'} key={`${scenario.id}:${scenario.ride.startedAt}`} bundled={bundled} group={scenario.source.history==='illustrative'} owner={owner} menuHost={menuHost}/></div>
        <div className="v10-primary-result"><Figures pending={pending} values={[{ label: 'Distance', value: distanceLabel(totals.distance), unit: 'km' }, { label: 'Elapsed time', value: timeLabel(totals.duration) }, { label: 'Elevation', value: totals.gain === null ? null : integer(totals.gain), unit: 'm' }]} />
          <Figures className="v10-secondary-figures" pending={pending} values={[{ label: 'Avg power', value: stats.basePower.average === null ? null : channelValue(stats.basePower.average, 'power'), unit: 'W' }, { label: 'Avg cadence', value: stats.cadence.average === null ? null : channelValue(stats.cadence.average, 'cadence'), unit: 'rpm' }, { label: 'Avg speed', value: stats.speed.average === null ? null : channelValue(stats.speed.average, 'speed'), unit: 'km/h' }]} />
          {mode === 'overview' && <V10RideDetails points={base} source={bundled ? 'FIT recording' : null} economics={economics} pending={pending} onEconomics={() => switchMode('economics')} expanded={expanded} onExpanded={expanded=>nav.visit({expanded},false)}/>}
        </div>
      </header>

      <div className="v10-workspace" hidden={!mapVisible}>
        <div className="v10-geography"><V10MapFrame adjustable={mode !== 'overview'} height={mapHeight} onHeight={mapHeight=>nav.visit({mapHeight},false)}><V10Map visible={mapVisible} scenario={scenario} focus={focus} cameraKey={`${mode}:${selection?.startIndex ?? subject.startIndex}:${selection?.endIndex ?? subject.endIndex}`} scrub={cursor} onScrub={onHover} onLeave={() => onHover(null)} onSelect={navigate} onClearSelection={clearRange} /></V10MapFrame>
          <div className="v10-elevation-workspace" ref={profileContainer}><div className="v10-profile-heading"><h2>Ride elevation</h2><div className="v10-profile-controls">{selection && <button className="v10-clear-interval" onClick={clearRange} aria-label="Clear selected interval" aria-keyshortcuts="Escape"><X size={13} />Clear</button>}<div className="v10-axis" role="group" aria-label="Horizontal axis"><button aria-pressed={axis === 'distance'} onClick={() => { setAxis('distance'); if (editing) closeEditor(); }}>Distance</button><button aria-pressed={axis === 'time'} onClick={() => { setAxis('time'); if (editing) closeEditor(); }}>Time</button></div></div></div>
            <V10Profile samples={samples} subject={subject} selection={selection} draft={preview} axis={axis} cursor={cursor} onHover={onHover} onDraft={setDraft} onSelect={selectRange} onClearSelection={clearRange} />
            {mode !== 'overview' && <V10ClimbMarks scenario={scenario} samples={samples} axis={axis} selected={selected} onSelect={navigate}/>}
          </div>

        </div>
        {mode === 'overview' && <aside className="v10-results-rail"><Results scenario={scenario} selected={null} onSelect={navigate} pending={pending} /><button className="v10-analyze-link" onClick={() => switchMode('analysis')}><BarChart3 size={17} /><span>Analyze ride<small>Inspect your recorded measurements</small></span><ArrowRight size={15} /></button></aside>}
      </div>
      {(mode === 'analysis' || mode === 'heartRate') && <section className="v10-analysis" aria-label="Ride analysis">
        <div className={`v10-selection-summary ${selection || preview ? 'has-selection' : ''}`} aria-live="polite"><div className="v10-selection-identity"><span>{preview ? 'Selecting' : climb && !committed ? 'Climb' : selection ? powerBest?'Power effort':'Selection' : 'Whole ride'}</span>{climb&&!committed&&!preview?<a className="v10-scope-vault" href={nav.href({mode:'vault',range:null})} target="_top" onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();openVault(climb.id);}}>{climb.name}<ArrowRight size={13}/></a>:<strong>{powerBest&&!preview?`Best ${powerBest.duration<60?`${powerBest.duration}s`:powerBest.duration%60===0?`${powerBest.duration/60} min`:timeLabel(powerBest.duration)}`:selection||preview?axis==='distance'?`${(displayed[0].d/1000).toFixed(2)}–${(displayed.at(-1)!.d/1000).toFixed(2)} km`:`${timeLabel(displayed[0].t)}–${timeLabel(displayed.at(-1)!.t)}`:scenario.ride.title}</strong>}{!pending&&powerBest&&effortBounds?.expanded&&<small className="v10-effort-boundary">{powerBest.start.toFixed(1)}–{powerBest.end.toFixed(1)} s · {Math.round(powerBest.watts)} W<br/>View includes surrounding recorded samples</small>}</div>
          <Figures pending={pending} className="v10-selection-figures" values={[{ label: 'Distance', value: distanceLabel(interval.distance), unit: 'km' }, { label: 'Elapsed time', value: timeLabel(interval.duration) }, { label: 'Elevation', value: interval.gain === null ? null : integer(interval.gain), unit: 'm' }, { label: 'Avg power', value: stats.power.average === null ? null : channelValue(stats.power.average, 'power'), unit: 'W' }]} />
          <div className="v10-selection-actions">{powerBest&&<button onClick={()=>{switchMode('power');requestAnimationFrame(()=>document.querySelector<SVGSVGElement>('.v10-power-room[aria-label="Power curve"] svg')?.focus());}}>Back to Power</button>}<button ref={adjustButton} onClick={editRange} aria-expanded={editing}><SlidersHorizontal size={14} />{selection ? 'Adjust' : 'Set interval'}</button>{selection && <button className="v10-summary-clear" onClick={clearRange}><X size={14} />Clear selection</button>}</div>
        </div>
        {editing && <form ref={editForm} className="v10-range-editor" onSubmit={e => { e.preventDefault(); applyRange(); }} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); closeEditor(); } }}><div><strong>Adjust interval</strong><span>Within this ride</span></div><label>From ({unit})<input aria-label={`Interval start in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" step="any" value={from} onChange={e => setFrom(e.target.value)} /></label><label>To ({unit})<input aria-label={`Interval end in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" step="any" value={to} onChange={e => setTo(e.target.value)} /></label><button type="submit">Apply</button><button type="button" onClick={closeEditor}>Cancel</button>{error && <p role="alert">{error}</p>}</form>}
        <div className="v10-inspection-bar"><span>{point ? <>{outsideSelection ? 'Outside selected interval' : 'At cursor'}<strong>{(point.d / 1000).toFixed(2)} km</strong><span>{timeLabel(point.t)}</span></> : null}</span></div>
        <V10Charts points={detail} channels={mode === 'heartRate' ? ['heartRate'] : channels} axis={axis} cursor={cursor} draft={preview} selected={!!selection} onHover={onHover} onDraft={setDraft} onSelect={selectRange} onClearSelection={clearRange} pending={pending} />
        <div hidden={mode === 'heartRate'} className="v10-channel-controls" role="group" aria-label="Visible measurements">{available.map(c => <label key={c}><input type="checkbox" checked={!hidden.includes(c)} disabled={!hidden.includes(c) && channels.length === 1} onChange={() => setHidden(current => current.includes(c) ? current.filter(x => x !== c) : [...current, c])} />{c === 'heartRate' ? 'Heart rate' : c[0].toUpperCase() + c.slice(1)}</label>)}</div>
        <details className="v10-measurement-details"><summary>About these measurements</summary><p>Chart averages include measured zeros and use covered time. Recording gaps over 30 seconds stay unconnected and are excluded from averages. Elapsed time includes pauses. Grade uses a centered 100 m window.</p><p>The cursor follows freely. Arrow keys inspect; leaving the chart clears the reading. Hold Shift with arrows to select in the measurement charts, then Enter to apply. A plain click in the map or chart, or Escape, returns to the whole ride. Drag inside the elevation selection to move it, or use its two edges to adjust the interval. Selection boundaries stay on recorded samples. Use Time to move a stationary interval.</p>{!available.includes('heartRate') && <p>Heart rate is not included in this ride.</p>}</details>
      </section>}
      <div hidden={mode!=='power'}><V10PowerCurve points={base} pending={pending} onEffort={openPowerEffort}/><V10PowerDistribution points={base} pending={pending}/>{available.includes('cadence')&&<V10PowerCadence points={base} scenario={scenario} pending={pending}/>}</div>
      {mode === 'economics' && economics && <V10Economics scenario={scenario} economics={economics} pending={pending} onVault={openVault} vaultHref={id=>nav.href({mode:'vault',climbId:id,range:null})}/>}

    </main>
  </div></>;
}
