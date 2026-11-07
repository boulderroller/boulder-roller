import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { ArrowLeft, ArrowRight, ChevronRight, SlidersHorizontal, Trophy, X } from 'lucide-react';
import { V3Map } from './V3Map';
import { V3Charts } from './V3Charts';
import { climbResult, distanceLabel, integer, summarize, timeLabel, type Climb, type Scenario } from './scenario';
import { historyComparison } from './v2Model';
import { analysisSamples, nearestIndex, normalizeRange, rangeForClimb, scopedSamples, type Axis, type Channel, type MapFocus, type SampleRange } from './v3Model';
import './candidate-v3.css';

const dateLabel = (date: string) => new Date(date).toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'America/New_York' });
function Value({ children, pending }: { children: ReactNode; pending: boolean }) {
  return <span className="v3-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{children}</span></span>;
}
function Figures({ values, pending, className = '' }: { values: { label: string; value: string | null; unit?: string }[]; pending: boolean; className?: string }) {
  return <dl className={`v3-figures ${className}`}>{values.filter(v => v.value !== null).map(v => <div key={v.label}><dt>{v.label}</dt><dd><Value pending={pending}>{v.value}{v.unit && <span className="v3-unit">{v.unit}</span>}</Value></dd></div>)}</dl>;
}
function ClimbResults({ scenario, selected, onSelect, pending }: { scenario: Scenario; selected: string | null; onSelect: (id: string) => void; pending: boolean }) {
  const rows = scenario.climbs.map((climb, i) => ({ climb, number: i + 1, result: climbResult(scenario, climb) })).filter(row => row.climb.id !== selected);
  if (!rows.length) return null;
  return <section className="v3-climb-results" aria-label={selected ? 'Other climbs on this ride' : 'Climbs on this ride'}>
    <div className="v3-section-title"><h2>{selected ? 'Other climbs on this ride' : 'Climbs on this ride'}</h2><span>{rows.length} {rows.length === 1 ? 'climb' : 'climbs'}</span></div>
    <div className="v3-results-columns" aria-hidden="true"><span>Climb</span><span>Distance</span><span>Elevation</span><span>Avg grade</span><span>Time</span><span>Avg power</span><span /></div>
    {rows.map(({ climb, number, result }) => <button key={climb.id} className="v3-climb-result" aria-label={[`Open ${climb.name}`, `${distanceLabel(result.distance)} kilometers`, result.gain === null ? null : `${integer(result.gain)} meters elevation`, result.grade === null ? null : `${result.grade.toFixed(1)} percent average grade`, pending ? 'Results loading' : `${timeLabel(result.duration)} elapsed`, !pending && result.power !== null ? `${integer(result.power)} watts average power` : null, !pending && (result.improvement ?? 0) > 0 ? 'New best' : null].filter(Boolean).join(', ')} onClick={() => onSelect(climb.id)}>
      <span className="v3-climb-name"><span className="v3-climb-number">{number}</span><span><strong>{climb.name}</strong><small>{distanceLabel(result.distance)} km · {result.gain === null ? '—' : integer(result.gain)} m · {result.grade === null ? '—' : result.grade.toFixed(1)}%</small>{(result.improvement ?? 0) > 0 && <span className="v3-row-best"><Value pending={pending}><Trophy size={12} />New best</Value></span>}</span></span>
      <span className="v3-result-dimension">{distanceLabel(result.distance)}<small>km</small></span><span className="v3-result-dimension">{result.gain === null ? '—' : integer(result.gain)}<small>m</small></span><span className="v3-result-dimension">{result.grade === null ? '—' : result.grade.toFixed(1)}<small>%</small></span>
      <strong className="v3-result-time"><Value pending={pending}>{timeLabel(result.duration)}</Value></strong><span className="v3-result-watts"><Value pending={pending}>{result.power === null ? '—' : integer(result.power)}{result.power !== null && <small>W</small>}</Value></span><ChevronRight size={15} />
    </button>)}
  </section>;
}
function History({ scenario, climb, pending }: { scenario: Scenario; climb: Climb; pending: boolean }) {
  const result = climbResult(scenario, climb), rows = historyComparison(scenario.ride.startedAt, result.duration, climb.history);
  if (!rows.length) return null;
  return <section className="v3-history" aria-label="Your history"><div className="v3-section-title"><h2>Your history</h2><span>{rows.length} rides{scenario.source.history === 'illustrative' && ' · illustrative history'}</span></div>
    {rows.map((row, i) => <div key={`${row.date}-${i}`} className={`v3-history-row ${row.current ? 'is-current' : ''}`}><span>{row.current ? 'This ride' : dateLabel(row.date)}</span><span className="v3-history-track" aria-hidden="true"><i style={{ width: `${row.percent}%`, visibility: pending ? 'hidden' : undefined }} /></span><strong><Value pending={pending}>{timeLabel(row.duration)}</Value></strong></div>)}
  </section>;
}

export function CandidateV3({ scenario, selected, scrub, onScrub, onSelect, onBack, pending, focusTarget }: {
  scenario: Scenario; selected: string | null; scrub: number | null; onScrub: (index: number | null) => void;
  onSelect: (id: string) => void; onBack: () => void; pending: boolean; focusTarget: RefObject<HTMLHeadingElement | null>;
}) {
  const [mode, setMode] = useState<'overview' | 'analysis'>('overview'), [axis, setAxis] = useState<Axis>('distance');
  const [range, setRange] = useState<SampleRange | null>(null), [draft, setDraft] = useState<SampleRange | null>(null);
  const [editor, setEditor] = useState(false), [from, setFrom] = useState(''), [to, setTo] = useState(''), [rangeError, setRangeError] = useState('');
  const [hidden, setHidden] = useState<Channel[]>([]), lastContext = useRef({ selected, scenario });
  const samples = useMemo(() => analysisSamples(scenario.ride.samples), [scenario]);
  const climb = scenario.climbs.find(c => c.id === selected), climbRange = useMemo(() => rangeForClimb(samples, climb), [samples, climb]);
  const result = useMemo(() => climb ? climbResult(scenario, climb) : null, [scenario, climb]);
  const totals = useMemo(() => summarize(scenario.ride.samples), [scenario]);
  useEffect(() => {
    if (lastContext.current.selected !== selected || lastContext.current.scenario !== scenario) {
      setRange(null); setDraft(null); setEditor(false); setRangeError('');
      if (lastContext.current.scenario !== scenario) setHidden([]);
      lastContext.current = { selected, scenario };
    }
  }, [selected, scenario]);
  // A changed parent context takes effect in this render, before its cleanup effect.
  const sameContext = lastContext.current.selected === selected && lastContext.current.scenario === scenario;
  const activeRange = mode === 'analysis' && sameContext ? range ?? climbRange : climbRange;
  const mapRange = mode === 'analysis' && sameContext ? draft ?? activeRange : activeRange;
  const focus: MapFocus | null = mapRange ? { ...mapRange, kind: mode === 'analysis' && (draft || range) ? 'range' : 'climb' } : null;
  const scope = useMemo(() => scopedSamples(samples, activeRange), [samples, activeRange?.startIndex, activeRange?.endIndex]);
  const scopeSummary = useMemo(() => summarize(scope), [scope]);
  const available = useMemo(() => (['elevation', 'speed', 'power', 'heartRate', 'cadence'] as Channel[]).filter(key => samples.some(p => p[key] !== null)), [samples]);
  const channels = available.filter(key => !hidden.includes(key));
  const newBest = result?.improvement !== null && (result?.improvement ?? 0) > 0;
  const bestCount = scenario.climbs.filter(c => (climbResult(scenario, c).improvement ?? 0) > 0).length;
  const switchMode = (next: typeof mode) => { setMode(next); onScrub(null); setDraft(null); };
  const applyRange = (next: SampleRange) => { setRange(next); setDraft(null); setRangeError(''); onScrub(null); };
  const rangeFactor = axis === 'time' ? 60 : 1000, rangeUnit = axis === 'time' ? 'min' : 'km', rangeKey = axis === 'time' ? 't' : 'd';
  const changeAxis = (next: Axis) => { setAxis(next); setEditor(false); setRangeError(''); };
  const openEditor = () => { setFrom((scope[0][rangeKey] / rangeFactor).toFixed(3)); setTo((scope.at(-1)![rangeKey] / rangeFactor).toFixed(3)); setEditor(x => !x); setRangeError(''); };
  const applyTypedRange = () => {
    const a = Number(from), b = Number(to), max = samples.at(-1)![rangeKey] / rangeFactor;
    if (!from.trim() || !to.trim() || !Number.isFinite(a) || !Number.isFinite(b) || a < 0 || b <= a || b > max + .005) { setRangeError(`Choose a start before the end, within 0–${max.toFixed(3)} ${rangeUnit}.`); return; }
    applyRange(normalizeRange(samples.length, nearestIndex(samples, a * rangeFactor, axis), nearestIndex(samples, b * rangeFactor, axis))); setEditor(false);
  };
  const cameraKey = `${mode}:${activeRange?.startIndex ?? 0}:${activeRange?.endIndex ?? samples.length - 1}`;
  return <main className={`v3-page v3-${mode} ${climb ? 'v3-climb' : 'v3-ride'}`} aria-busy={pending}>
    <div className="v3-context">{climb ? <button onClick={onBack}><ArrowLeft size={14} />{scenario.ride.title}</button> : <time>{dateLabel(scenario.ride.startedAt)}</time>}<span>{scenario.ride.location}</span></div>
    <header className="v3-opening">
      <div className="v3-identity"><h1 ref={focusTarget} tabIndex={-1}>{climb?.name ?? scenario.ride.title}</h1>
        {climb && result ? <Figures className="v3-climb-dimensions" pending={false} values={[{ label: 'Distance', value: distanceLabel(result.distance), unit: 'km' }, { label: 'Elevation', value: result.gain === null ? null : integer(result.gain), unit: 'm' }, { label: 'Avg grade', value: result.grade === null ? null : result.grade.toFixed(1), unit: '%' }]} /> : <p>{scenario.climbs.length} {scenario.climbs.length === 1 ? 'climb' : 'climbs'}{bestCount > 0 && <><span className="v3-meta-dot">·</span><Value pending={pending}>{bestCount} new {bestCount === 1 ? 'best' : 'bests'}</Value></>}</p>}
      </div>
      {climb && result ? <div className="v3-personal-result"><Figures className="v3-personal-figures" pending={pending} values={[{ label: 'Your time', value: timeLabel(result.duration) }, { label: 'Avg power', value: result.power === null ? null : integer(result.power), unit: 'W' }]} />
        {newBest ? <p className="v3-new-best"><Value pending={pending}><Trophy size={14} /><strong>New best</strong><span>{timeLabel(result.improvement!)} faster</span></Value></p> : result.previousBest !== null && <p className="v3-previous-best">Best time <Value pending={pending}>{timeLabel(result.previousBest)}</Value></p>}
      </div> : <Figures pending={pending} values={[{ label: 'Distance', value: distanceLabel(totals.distance), unit: 'km' }, { label: 'Elevation', value: totals.gain === null ? null : integer(totals.gain), unit: 'm' }, { label: 'Elapsed time', value: timeLabel(totals.duration) }]} />}
    </header>
    <div className="v3-view-bar"><nav aria-label="Ride view"><button aria-current={mode === 'overview' ? 'page' : undefined} onClick={() => switchMode('overview')}>Overview</button><button aria-current={mode === 'analysis' ? 'page' : undefined} onClick={() => switchMode('analysis')}>Analysis</button></nav><span>{pending ? <span className="v3-loading-label">Loading results</span> : climb ? 'Your effort on this ride' : 'Route and climbs'}</span></div>
    <div className="v3-geography">
      <V3Map scenario={scenario} focus={focus} cameraKey={cameraKey} scrub={scrub} onScrub={onScrub} onSelect={onSelect} />
      {mode === 'overview' && <div className="v3-main-profile"><div className="v3-section-title"><h2>{climb ? 'The climb' : 'Ride elevation'}</h2>{climb && <span>{distanceLabel(scopeSummary.distance)} km</span>}</div>
        <V3Charts points={scope} channels={climb ? ['elevation', 'grade'] : ['elevation']} scrub={scrub} onScrub={onScrub} height={climb ? 122 : 92} climbs={climb ? [] : scenario.climbs} onClimb={onSelect} pending={false} />
        {climb && <button className="v3-analysis-link" onClick={() => switchMode('analysis')}>Analyze this climb<ArrowRight size={14} /></button>}
      </div>}
    </div>
    {mode === 'analysis' ? <section className="v3-analysis-workspace" aria-label="Ride analysis">
      <div className="v3-analysis-context"><div className="v3-section-title"><h2>Whole ride</h2><span>{distanceLabel(totals.distance)} km</span></div><V3Charts points={samples} channels={['elevation']} scrub={scrub} onScrub={onScrub} highlight={draft ?? activeRange} onRange={applyRange} onRangePreview={setDraft} height={67} overview /></div>
      <div className="v3-analysis-toolbar"><label className="v3-scope-picker"><span className="sr-only">Analysis scope</span><select aria-label="Analysis scope" value={range ? 'range' : selected ?? 'ride'} onChange={event => { setRange(null); if (event.target.value === 'ride') onBack(); else onSelect(event.target.value); }}><option value="ride">Whole ride</option>{scenario.climbs.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}{range && <option value="range">Selected stretch</option>}</select></label><div className="v3-axis-switch" role="group" aria-label="Chart horizontal axis"><button aria-pressed={axis === 'distance'} onClick={() => changeAxis('distance')}>Distance</button><button aria-pressed={axis === 'time'} onClick={() => changeAxis('time')}>Time</button></div><button className="v3-select-range" aria-expanded={editor} onClick={openEditor}><SlidersHorizontal size={14} />Select range</button>{range && <button aria-label="Clear selected stretch" className="v3-clear-range" onClick={() => { setRange(null); setDraft(null); onScrub(null); }}><X size={14} />Clear</button>}</div>
      {editor && <form className="v3-range-editor" onSubmit={event => { event.preventDefault(); applyTypedRange(); }}><label>From ({rangeUnit})<input aria-label={`Selection start in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" min={0} step="any" value={from} onChange={e => setFrom(e.target.value)} /></label><label>To ({rangeUnit})<input aria-label={`Selection end in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" min={0} step="any" value={to} onChange={e => setTo(e.target.value)} /></label><button type="submit">Apply selection</button>{rangeError && <p role="alert">{rangeError}</p>}</form>}
      <div className="v3-interval-summary" aria-live="polite"><strong>{range ? 'Selected stretch' : climb ? climb.name : 'Whole ride'}</strong><span>{distanceLabel(scopeSummary.distance)} km</span><span>{timeLabel(scopeSummary.duration)}</span>{scopeSummary.gain !== null && <span>{integer(scopeSummary.gain)} m elevation</span>}<small>{(scope[0].d / 1000).toFixed(2)}–{(scope.at(-1)!.d / 1000).toFixed(2)} km</small></div>
      <V3Charts points={scope} domainPoints={samples} channels={channels} axis={axis} scrub={scrub} onScrub={onScrub} onRange={applyRange} onRangePreview={setDraft} pending={pending} height={78} />
      <div className="v3-channel-controls" role="group" aria-label="Visible measurements">{available.map(channel => <label key={channel}><input type="checkbox" checked={!hidden.includes(channel)} disabled={!hidden.includes(channel) && channels.length === 1} onChange={() => setHidden(current => current.includes(channel) ? current.filter(c => c !== channel) : [...current, channel])} /><span>{channel === 'heartRate' ? 'Heart rate' : channel[0].toUpperCase() + channel.slice(1)}</span></label>)}</div>
      <details className="v3-data-details"><summary>About these measurements</summary><p>Drag across any chart to select a stretch. Use the arrow keys to inspect individual readings, or Select range to enter a distance or elapsed time. All charts and the map use the same samples.</p><p>Averages include zero readings and use covered time. Gaps over 30 seconds break the traces and are excluded from averages. Elapsed time includes pauses. Grade uses a centered 100 m elevation window; short or incomplete windows stay absent.</p>{samples.some(p => p.speedDerived) && <p>Speed is derived from distance and time where recorded speed is missing and adjacent samples are within 30 seconds.</p>}{!available.includes('heartRate') && <p>Heart rate was not recorded on this ride.</p>}</details>
    </section> : <>
      {climb && <section className="v3-ride-context-profile"><div className="v3-section-title"><button onClick={onBack}><ArrowLeft size={13} />Whole ride</button><span>{(scope[0].d / 1000).toFixed(1)}–{(scope.at(-1)!.d / 1000).toFixed(1)} km on this ride</span></div><V3Charts points={samples} channels={['elevation']} scrub={scrub} onScrub={onScrub} highlight={climbRange} height={58} overview /></section>}
      <div className={climb && climb.history.length ? 'v3-lower-with-history' : 'v3-lower'}>{climb && <History scenario={scenario} climb={climb} pending={pending} />}<ClimbResults scenario={scenario} selected={selected} onSelect={onSelect} pending={pending} /></div>
      {!climb && <div className="v3-ride-analysis-door"><div><h2>Ride analysis</h2><p>{available.filter(c => c !== 'elevation').map(c => c === 'heartRate' ? 'Heart rate' : c[0].toUpperCase() + c.slice(1)).join(' · ')}</p></div><button onClick={() => switchMode('analysis')}>Analyze ride<ArrowRight size={15} /></button></div>}
    </>}
    <footer className="v3-footnote">{climb ? scenario.source.kind === 'recorded' ? 'Route and dimensions show your recorded climb interval.' : 'Route and dimensions show the illustrative climb interval.' : `${scenario.source.kind === 'recorded' ? 'Recorded on' : 'Illustrative ride dated'} ${dateLabel(scenario.ride.startedAt)}.`}{scenario.source.history === 'illustrative' && ' Previous result dates and times are illustrative.'}</footer>
  </main>;
}
