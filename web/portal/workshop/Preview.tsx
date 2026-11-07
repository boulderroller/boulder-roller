import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight, ChevronRight, Trophy, RotateCcw } from 'lucide-react';
import { RideRoomGeography, RideRoomIdentity, RideRoomRow } from '../src/components/ride/RideRoom';
import ClimbShapeGlyph from '../src/components/climbs/ClimbShapeGlyph';
import type { RideSample, RideSpan } from '../src/components/ride/rideRoomModel';
import { WorkshopMap } from './WorkshopMap';
import { Elevation } from './Elevation';
import { scenarios, identityScenario } from './scenarios';
import { CandidateV2 } from './CandidateV2';
import { CandidateV3 } from './CandidateV3';
import { CandidateV4 } from './CandidateV4';
import { CandidateV14 } from './CandidateV14';
import { CandidateV13 } from './CandidateV13';
import { parseV13Context, type V13Context } from './v13Context';
import { CandidateV12 } from './CandidateV12';
import { v12Identity } from './v12Example';
import { CandidateV11 } from './CandidateV11';
import { v11Identity } from './v11Example';
import { CandidateV10 } from './CandidateV10';
import { v10Identity } from './v10Example';
import { CandidateV9 } from './CandidateV9';
import { v9Identity } from './v9Example';
import { CandidateV8 } from './CandidateV8';
import { v8Identity } from './v8Example';
import { CandidateV7 } from './CandidateV7';
import { CandidateV6 } from './CandidateV6';
import { CandidateV5 } from './CandidateV5';
import { designFromQuery, isDesignVariant, type DesignVariant } from './designVariants';
import { climbResult, climbSamples, distanceLabel, integer, parseScenario, summarize, timeLabel, type Climb, type Scenario } from './scenario';

export type PreviewState = 'ready' | 'loading' | 'empty' | 'error';
export type { DesignVariant } from './designVariants';
export type Settings = { rideContext?: V13Context; rideOwner?:boolean; bundled?: boolean; scenario: Scenario; variant: DesignVariant; state: PreviewState; squint: boolean; revision: boolean };
const dateLabel = (date: string) => new Date(date).toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'America/New_York' });

function Stat({ label, value, unit, pending = false }: { label: string; value: string | null; unit?: string; pending?: boolean }) {
  if (value === null && !pending) return null;
  return <div><dt>{label}</dt><dd>{pending ? <span className="stat-wait"><span className="stat-measure" aria-hidden="true">{value}{unit && <span className="stat-unit">{unit}</span>}</span><span className="value-slot" /></span> : <>{value}{unit && <span className="stat-unit">{unit}</span>}</>}</dd></div>;
}

function ClimbRows({ scenario, selected, onSelect, pending = false, current = false, revision = true }: { scenario: Scenario; selected: string | null; onSelect: (id: string) => void; pending?: boolean; current?: boolean; revision?: boolean }) {
  return <section className="climbs-section" aria-label="Climbs on this ride">
    <div className="section-heading"><h2>Climbs on this ride</h2>{!pending && <span>{scenario.climbs.length}</span>}</div>
    {pending ? <div className="result-loading" role="status"><span className="word-slot" /><span className="short-slot" /><span className="value-slot" /><span className="short-slot" /></div> : scenario.climbs.length === 0 ? <p className="quiet-empty">No climbs on this ride.</p> : <div className="climb-rows">{scenario.climbs.map((c, i) => {
      const r = climbResult(scenario, c), profile = climbSamples(scenario, c).filter(p => p.elevation !== null).map(p => ({ distanceM: p.d - scenario.ride.samples.find(p => p.t === c.start)!.d, elevationM: p.elevation! }));
      return <button key={c.id} className={`climb-row ${selected === c.id ? 'selected' : ''}`} onClick={() => onSelect(c.id)} aria-label={`Open ${c.name}`} aria-pressed={selected === c.id}>
        {current ? <RideRoomRow profile={profile} name={c.name} detail={`${distanceLabel(r.distance)} km${r.gain !== null ? ` · ${integer(r.gain)} m` : ''}`} value={timeLabel(r.duration)} sub={r.power === null ? null : `${integer(r.power)} W`} /> : <>
          <span className="climb-number">{i + 1}</span><span className="climb-row-copy"><strong>{c.name}</strong><small>{distanceLabel(r.distance)} km{r.gain !== null && <> · {integer(r.gain)} m</>}{r.grade !== null && <> · {r.grade.toFixed(1)}%</>}</small>{r.improvement !== null && r.improvement > 0 && <span className="best-note"><Trophy size={12} />New best</span>}</span>
          <span className="climb-row-result"><strong>{timeLabel(r.duration)}</strong>{r.power !== null && <small>{integer(r.power)} W</small>}</span><ChevronRight size={15} className="row-chevron" />
        </>}
      </button>;
    })}</div>}
  </section>;
}

function ResultBlock({ scenario, climb }: { scenario: Scenario; climb: Climb }) {
  const result = climbResult(scenario, climb);
  return <section className="your-result"><div className="section-heading"><h2>Your result</h2><span>{dateLabel(scenario.ride.startedAt)}</span></div>
    <div className="result-time"><span>{timeLabel(result.duration)}</span><small>Time</small></div>
    {result.power !== null && <div className="result-power"><strong>{integer(result.power)}<span> W</span></strong><small>Avg power</small></div>}
    {result.improvement !== null && result.improvement > 0 && <p className="result-best"><Trophy size={15} /><strong>New best</strong><span>{timeLabel(result.improvement)} faster</span></p>}
    {result.previousBest !== null && result.improvement! <= 0 && <p className="previous-best">Best time <strong>{timeLabel(result.previousBest)}</strong></p>}
  </section>;
}

function Result({ scenario, climb }: { scenario: Scenario; climb: Climb }) {
  const result = climbResult(scenario, climb);
  const history = [...climb.history].sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
  const slowest = Math.max(result.duration, ...history.map(h => h.duration));
  return <>
    <ResultBlock scenario={scenario} climb={climb} />
    <section className="history-section"><div className="section-heading"><h2>Your history</h2><span>{history.length + 1} {history.length ? 'rides' : 'ride'}</span></div>
      <div className="history-row this-ride"><span>This ride</span><i style={{ width: `${result.duration / slowest * 46}%` }} /><strong>{timeLabel(result.duration)}</strong></div>
      {history.map((h, i) => <div className="history-row" key={`${h.date}-${i}`}><span>{new Date(h.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' })}</span><i style={{ width: `${h.duration / slowest * 46}%` }} /><strong>{timeLabel(h.duration)}</strong></div>)}
    </section>
  </>;
}

export function Preview() {
  const query = new URLSearchParams(location.search);
  const [settings, setSettings] = useState<Settings>(() => ({ bundled: true, scenario: scenarios.find(s => s.id === query.get('scenario')) ?? (['candidate-v5','candidate-v6','candidate-v7'].includes(designFromQuery(query.get('variant'))) ? identityScenario : scenarios[0]), variant: designFromQuery(query.get('variant')), state: 'ready', squint: false, revision: query.get('revision') !== '0' }));
  const [receivedSettings, setReceivedSettings] = useState(window.parent === window);
  const [sourceRevision, setSourceRevision] = useState(0);
  const [selected, setSelected] = useState<string | null>(null), [scrub, setScrub] = useState<number | null>(null);
  const [metrics, setMetrics] = useState(false);
  const navigation = useRef<'forward' | 'back' | null>(null);
  const savedScroll = useRef(0), focusTarget = useRef<HTMLHeadingElement>(null), lastScenario = useRef(settings.scenario.id);
  const { scenario, variant, state, revision } = settings;
  const v12Scenario = useMemo(() => v12Identity(scenario, settings.bundled === true), [scenario, settings.bundled]);
  const v11Scenario = useMemo(() => v11Identity(scenario, settings.bundled === true), [scenario, settings.bundled]);
  const v10Scenario = useMemo(() => v10Identity(scenario, settings.bundled === true), [scenario, settings.bundled]);
  const v9Scenario = useMemo(() => v9Identity(scenario, settings.bundled === true), [scenario, settings.bundled]);
  const v8Scenario = useMemo(() => v8Identity(scenario, settings.bundled === true), [scenario, settings.bundled]);
  const selectedClimb = scenario.climbs.find(c => c.id === selected) ?? null;
  const totals = useMemo(() => summarize(scenario.ride.samples), [scenario]);
  const scopeTotals = selectedClimb ? climbResult(scenario, selectedClimb) : totals;
  const pending = state === 'loading';
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== window.parent || event.data?.type !== 'workshop-settings') return;
      try {
        const next = event.data.settings;
        const nextScenario = next.scenario ? parseScenario(next.scenario) : null;
        if (!isDesignVariant(next.variant) || !['ready', 'loading', 'empty', 'error'].includes(next.state)) return;
        setReceivedSettings(true);
        if (nextScenario) setSourceRevision(value => value + 1);
        setSettings(previous => ({ rideContext: ['candidate-v13','candidate-v14'].includes(next.variant) ? parseV13Context(next.rideContext, nextScenario ?? previous.scenario) : undefined, rideOwner: next.rideOwner !== false, bundled: nextScenario ? next.bundled === true : previous.bundled, scenario: nextScenario ?? previous.scenario, variant: next.variant, state: next.state, squint: !!next.squint, revision: next.revision !== false }));
        if (nextScenario) { setSelected(null); setScrub(null); setMetrics(false); window.scrollTo(0, 0); }
        if (nextScenario) lastScenario.current = nextScenario.id;
      } catch { /* Parent validates imports and owns the error message. */ }
    };
    window.addEventListener('message', receive);
    window.parent.postMessage({ type: 'workshop-ready' }, location.origin);
    return () => window.removeEventListener('message', receive);
  }, []);
  useEffect(() => { if(receivedSettings) window.parent.postMessage({type:'workshop-rendered'},location.origin); },[receivedSettings,sourceRevision]);
  useEffect(() => {
    window.parent.postMessage({ type: 'workshop-selection', selected: selectedClimb?.name ?? null }, location.origin);
  }, [selectedClimb?.name]);
  useLayoutEffect(() => {
    if (!navigation.current) return;
    const direction = navigation.current; navigation.current = null;
    requestAnimationFrame(() => {
      window.scrollTo({ top: direction === 'forward' ? 0 : savedScroll.current, behavior: 'instant' });
      if (direction === 'forward') focusTarget.current?.focus({ preventScroll: true });
    });
  }, [selected]);
  const select = (id: string) => {
    navigation.current = 'forward';
    if (!selected) savedScroll.current = window.scrollY;
    setSelected(id); setScrub(null); setMetrics(false);
  };
  const back = () => { navigation.current = 'back'; setSelected(null); setScrub(null); };
  const recover = () => { if(window.parent === window) setSettings(s => ({ ...s, state: 'ready' })); window.parent.postMessage({ type: 'workshop-recover' }, location.origin); };
  const date = dateLabel(scenario.ride.startedAt);
  const samples = useMemo(() => scenario.ride.samples.map((p, index) => ({ t: p.t, d: p.d, elevation: p.elevation, power: p.power, cadence: null, speed: null, heartRate: null, index, gps: { latitude: p.lat, longitude: p.lon, elevationM: p.elevation, distanceM: p.d, timestamp: new Date(Date.parse(scenario.ride.startedAt) + p.t * 1000).toISOString(), sequenceNum: index } })) as RideSample[], [scenario]);
  const spans = useMemo(() => scenario.climbs.map(c => ({ id: c.id, name: c.name, start: c.start, end: c.end, pattern: {} })) as RideSpan[], [scenario]);
  const power = useMemo(() => samples.filter(p => p.power !== null).map(p => ({ t: p.t, v: p.power! })), [samples]);
  const currentSamples = selectedClimb ? samples.filter(p => p.t >= selectedClimb.start && p.t <= selectedClimb.end).map((p, i, arr) => ({ ...p, d: p.d - arr[0].d })) : samples;
  const bests = scenario.climbs.filter(c => (climbResult(scenario, c).improvement ?? 0) > 0), best = bests[0];
  return <BrowserRouter><div className={`rider-preview ${variant} ${pending ? 'is-loading' : ''} ${revision && variant === 'candidate' ? 'revised' : ''}`} data-squint={settings.squint}>
    {variant!=='candidate-v14'&&<header className="rider-shell"><span className="brand">Boulder Roller</span><span className="shell-context">{selectedClimb && !['candidate-v7', 'candidate-v8', 'candidate-v9', 'candidate-v10', 'candidate-v11', 'candidate-v12', 'candidate-v13','candidate-v14'].includes(variant) ? 'Climb' : 'Ride'}</span></header>}
    {variant==='candidate-v14' ? (receivedSettings ? <CandidateV14 key={`${scenario.id}:${sourceRevision}`} context={settings.rideContext} owner={settings.rideOwner!==false} scenario={v12Scenario} bundled={settings.bundled===true} state={state} recover={recover} focusTarget={focusTarget}/> : null) : state === 'empty' || state === 'error' ? <main className="unavailable-state"><h1>{state === 'empty' ? 'No ride selected' : 'Ride unavailable'}</h1><p>{state === 'empty' ? 'Choose a ride to see its route and climbs.' : 'The ride could not be loaded.'}</p><button onClick={recover}><RotateCcw size={16} />{state === 'empty' ? 'Open ride' : 'Try again'}</button></main> : variant === 'current' ? <main className="ride-room-page ride-detail-page">
      {selectedClimb && <button className="current-back" onClick={back}><ArrowLeft size={15} />{scenario.ride.title}</button>}
      <RideRoomGeography samples={currentSamples} spans={spans} power={power} identity={<RideRoomIdentity riderProfileHref={null} riderDisplayName="Recorded ride" riderInitials="R" rideStartedLabel={date} placeLabel={scenario.ride.location} roomTitle={selectedClimb?.name ?? scenario.ride.title} profile={currentSamples.flatMap(p => p.elevation === null ? [] : [{ distanceM: p.d, elevationM: p.elevation }])} stats={[[ 'Distance', pending ? '' : `${distanceLabel(scopeTotals.distance)} km` ], [ 'Elevation', pending || scopeTotals.gain === null ? '' : `${integer(scopeTotals.gain)} m` ], [ 'Time', pending ? '' : timeLabel(scopeTotals.duration) ]]} roomSummary={pending ? 'Loading ride…' : `${scenario.climbs.length} ${scenario.climbs.length === 1 ? 'climb' : 'climbs'}${best ? ' · 1 new best' : ''}`} />}>
        <div className="baseline-ledger">{selectedClimb ? <Result scenario={scenario} climb={selectedClimb} /> : <ClimbRows scenario={scenario} selected={selected} onSelect={select} pending={pending} current />}</div>
      </RideRoomGeography>
    </main> : variant === 'candidate-v13' ? (receivedSettings ? <CandidateV13 key={`${scenario.id}:${sourceRevision}`} context={settings.rideContext} owner={settings.rideOwner!==false} scenario={v12Scenario} bundled={settings.bundled === true} selected={selected} onSelect={id => { setSelected(id); setScrub(null); }} onBack={() => { setSelected(null); setScrub(null); }} pending={pending} focusTarget={focusTarget} /> : null) : variant === 'candidate-v12' ? (receivedSettings ? <CandidateV12 key={`${scenario.id}:${sourceRevision}`} owner={settings.rideOwner!==false} scenario={v12Scenario} bundled={settings.bundled === true} selected={selected} onSelect={id => { setSelected(id); setScrub(null); }} onBack={() => { setSelected(null); setScrub(null); }} pending={pending} focusTarget={focusTarget} /> : null) : variant === 'candidate-v11' ? (receivedSettings ? <CandidateV11 key={`${scenario.id}:${sourceRevision}`} owner={settings.rideOwner!==false} scenario={v11Scenario} bundled={settings.bundled === true} selected={selected} onSelect={id => { setSelected(id); setScrub(null); }} onBack={() => { setSelected(null); setScrub(null); }} pending={pending} focusTarget={focusTarget} /> : null) : variant === 'candidate-v10' ? (receivedSettings ? <CandidateV10 key={`${scenario.id}:${sourceRevision}`} owner={settings.rideOwner!==false} scenario={v10Scenario} bundled={settings.bundled === true} selected={selected} onSelect={id => { setSelected(id); setScrub(null); }} onBack={() => { setSelected(null); setScrub(null); }} pending={pending} focusTarget={focusTarget} /> : null) : variant === 'candidate-v9' ? (receivedSettings ? <CandidateV9 key={`${scenario.id}:${sourceRevision}`} scenario={v9Scenario} bundled={settings.bundled === true} selected={selected} onSelect={id => { setSelected(id); setScrub(null); }} onBack={() => { setSelected(null); setScrub(null); }} pending={pending} focusTarget={focusTarget} /> : null) : variant === 'candidate-v8' ? <CandidateV8 key={scenario.id} scenario={v8Scenario} bundled={settings.bundled === true} selected={selected} onSelect={id => { setSelected(id); setScrub(null); }} onBack={() => { setSelected(null); setScrub(null); }} pending={pending} focusTarget={focusTarget} /> : variant === 'candidate-v7' ? <CandidateV7 key={scenario.id} scenario={scenario} selected={selected} onSelect={id => { setSelected(id); setScrub(null); }} onBack={() => { setSelected(null); setScrub(null); }} pending={pending} focusTarget={focusTarget} /> : variant === 'candidate-v6' ? <CandidateV6 scenario={scenario} selected={selected} onSelect={select} onBack={back} pending={pending} focusTarget={focusTarget} /> : variant === 'candidate-v5' ? <CandidateV5 scenario={scenario} selected={selected} onSelect={select} onBack={back} pending={pending} focusTarget={focusTarget} /> : variant === 'candidate-v4' ? <CandidateV4 scenario={scenario} selected={selected} onSelect={select} onBack={back} pending={pending} focusTarget={focusTarget} /> : variant === 'candidate-v3' ? <CandidateV3 scenario={scenario} selected={selected} scrub={scrub} onScrub={setScrub} onSelect={select} onBack={back} pending={pending} focusTarget={focusTarget} /> : variant === 'candidate-v2' ? <CandidateV2 scenario={scenario} selected={selected} scrub={scrub} onScrub={setScrub} onSelect={select} onBack={back} pending={pending} focusTarget={focusTarget} metrics={metrics} onMetrics={() => setMetrics(x => !x)} /> : <main className="candidate-page" aria-busy={pending}>
      <div className="ride-context">{selectedClimb ? <button onClick={back}><ArrowLeft size={14} />{scenario.ride.title}<span>{distanceLabel(totals.distance)} km</span></button> : <span>{date}<i>·</i>{scenario.ride.location}</span>}</div>
      <header className="reading-header">
        <div className="reading-identity"><h1 ref={focusTarget} tabIndex={-1}>{selectedClimb && revision ? <a className="hill-door" href="#hill" onClick={e => e.preventDefault()}>{selectedClimb.name}<ArrowUpRight size={20} /></a> : selectedClimb?.name ?? scenario.ride.title}</h1><p>{selectedClimb ? scenario.ride.location : <>{scenario.climbs.length} {scenario.climbs.length === 1 ? 'climb' : 'climbs'} on this ride{best && !pending && <> · <button className="inline-best" onClick={() => select(best.id)}>{bests.length} new {bests.length === 1 ? 'best' : 'bests'} <ArrowUpRight size={13} /></button></>}</>}</p></div>
        <dl className="hero-stats"><Stat label="Distance" value={distanceLabel(scopeTotals.distance)} unit="km" pending={pending} /><Stat label="Elevation" value={scopeTotals.gain === null ? null : integer(scopeTotals.gain)} unit="m" pending={pending} />{selectedClimb ? <Stat label="Avg grade" value={'grade' in scopeTotals && typeof scopeTotals.grade === 'number' ? scopeTotals.grade.toFixed(1) : null} unit="%" pending={pending} /> : <Stat label="Elapsed time" value={timeLabel(totals.duration)} pending={pending} />}</dl>
        {selectedClimb && revision && !pending && <div className="phone-result"><ResultBlock scenario={scenario} climb={selectedClimb} /></div>}
      </header>
      <div className="ride-composition">
        <div className="geography-column"><WorkshopMap scenario={scenario} selected={selected} scrub={scrub} onScrub={setScrub} onSelect={select} revision={revision} /><Elevation scenario={scenario} selected={selected} scrub={scrub} onScrub={setScrub} onSelect={select} detail={!!selectedClimb} revision={revision} />
          {selectedClimb && <div className="ride-overview"><div className="overview-heading"><button onClick={back}><ArrowLeft size={13} />Whole ride</button><span>{distanceLabel(totals.distance)} km</span></div><Elevation scenario={scenario} selected={selected} scrub={scrub} onScrub={setScrub} onSelect={select} revision={revision} /></div>}
        </div>
        <aside className="results-column">{selectedClimb ? pending ? <div className="result-loading"><span className="word-slot" /><span className="value-slot" /></div> : <Result scenario={scenario} climb={selectedClimb} /> : <>
          {best && !pending && <button className="achievement" onClick={() => select(best.id)}><Trophy size={17} /><span><strong>New best on {best.name}</strong><small>{timeLabel(climbResult(scenario, best).duration)}<i>·</i>{timeLabel(climbResult(scenario, best).improvement!)} faster</small></span><ChevronRight size={16} /></button>}
          <ClimbRows scenario={scenario} selected={selected} onSelect={select} pending={pending} revision={revision} />
          <button className="metrics-toggle" aria-expanded={metrics} onClick={() => setMetrics(x => !x)}>Ride metrics<ChevronRight size={16} className={metrics ? 'rotated' : ''} /></button>
          {metrics && <dl className="ride-metrics"><Stat label="Elapsed time" value={timeLabel(totals.duration)} /><Stat label="Avg power" value={totals.power === null ? null : integer(totals.power)} unit="W" /><Stat label="Distance" value={distanceLabel(totals.distance)} unit="km" /></dl>}
        </>}</aside>
      </div>
      {selectedClimb && <div className="other-climbs"><ClimbRows scenario={scenario} selected={selected} onSelect={select} revision={revision} /></div>}
      <footer className="ride-footnote">{selectedClimb ? 'Route and dimensions show the recorded climb interval.' : scenario.source.kind === 'recorded' ? `Recorded on ${date}.` : date}</footer>
    </main>}
    {pending && <span className="sr-only" role="status">Loading ride results. Geography remains available.</span>}
  </div></BrowserRouter>;
}
