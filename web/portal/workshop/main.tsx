import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowUpRight, Check, ChevronDown, Download, Eye, FileUp, Info, Maximize2, Monitor, Smartphone, X } from 'lucide-react';
import { Preview, type DesignVariant, type PreviewState, type Settings } from './Preview';
import { scenarios, identityScenario } from './scenarios';
import { v12LayoutScenarios } from './v12LayoutScenarios';
const baseWorkshopScenarios = [...scenarios, ...v12LayoutScenarios, ...allV6Scenarios().flatMap(s => v6Entries(s).map(e => e.ride))].filter((s,i,all) => all.findIndex(x => x.id === s.id) === i);
const retainedImports = new Map<string,Scenario>();
const retainedImportKeys = new WeakMap<Scenario,string>();
import { DESIGNS, designFromQuery } from './designVariants';
import { parseScenario, type Scenario } from './scenario';
import './workshop.css';
import {WorkshopGate as Gate} from './v15/WorkshopGate';
import { FeedWorkshop } from './feed/FeedWorkshop';
import { FeedPreview } from './feed/FeedPreview';
import {v9RideContext} from './feed/feedV9Model';
import {v11RideContext} from './feed/feedV11Model';
import {v13RideContext} from './feed/feedV13Model';
import {v12RideContext} from './feed/feedV12Model';
import {v8RideContext} from './feed/feedV8Model';
import {v7RideContext} from './feed/feedV7Model';
import {feedV6Ride as feedRide, allV6Scenarios, v6Entries, v6RideContext} from './feed/feedV6Model';
import {feedImports} from './feed/feedModel';
import { currentPage, visitWorkshop } from './workbenchNavigation';
import {ROOMS,FINAL_ROOMS,roomFor,roomDestination,finalsActive,FINALS_PARAM,type WorkshopPage} from './roomRegistry';
import {installPalette,paletteActive,setPaletteActive} from './palette/applyPalette';
import {BaselineWorkshop} from './baseline/BaselineWorkshop';
import {ProfileV6Workspace as ProfileWorkshop} from './profile/v6/ProfileV6Workspace';
import {ProfileV6Preview} from './profile/v6/ProfileV6Preview';
import {ProfileV5Preview} from './profile/v5/ProfileV5Preview';
import {ProfileV4Preview} from './profile/v4/ProfileV4Preview';
import {ProfileRideHost} from './profile/v3/ProfileRideHost';
import {ProfileV3Preview} from './profile/v3/ProfileV3Preview';
import {ProfilePreview} from './profile/ProfilePreview';
import {baselineRooms,type BaselineRoom} from './baseline/model';
import './workbench.css';
import {ClimbWorkshop} from './climb/ClimbWorkshop';
import {ClimbPreview} from './climb/ClimbPreview';
import {MapWorkshop} from './map/MapWorkshop';
import {MapPreview} from './map/MapPreview';
import stravaRide from './references/strava-ride.png';
import stravaClimb from './references/strava-climb.png';
import stravaAnalysis from './references/strava-analysis.png';
import stravaAnalysisSelection from './references/strava-analysis-selection.png';

const referenceViews = {
  ride: { label: 'Ride', date: '9 Sep 2026', frames: [{ image: stravaRide, caption: 'Ride overview', alt: 'Retained Strava activity detail showing freely grouped figures above an unobstructed map and elevation profile.' }] },
  climb: { label: 'Climb', date: '9 Sep 2026', frames: [{ image: stravaClimb, caption: 'Climb overview', alt: 'Retained Strava Manayunk Wall detail showing climb dimensions, map, elevation, and personal results.' }] },
  analysis: { label: 'Analysis', date: '10 Sep 2026', frames: [
    { image: stravaAnalysis, caption: 'Whole ride · recorded power, heart rate and cadence', alt: 'Drake Deuel’s Morning Ride on Strava: terrain map, whole-ride elevation, and aligned speed, recorded power, heart rate, cadence and temperature charts.' },
    { image: stravaAnalysisSelection, caption: 'Selected climb · all five charts share the same interval', alt: 'An 8.1-mile climbing interval stays marked in the whole-ride elevation profile and map while all five charts zoom together, with updated averages and a shared cursor for exact readings.' },
  ] },
};
type ReferenceView = keyof typeof referenceViews;
const rideViewPreferences = {view:"fit",squint:false,reference:false,referenceRoom:"ride" as ReferenceView};

function Workshop() {
  const workshopScenarios = [...baseWorkshopScenarios,...[...feedImports.values()].flatMap(s=>v6Entries(s).map(e=>e.ride))].filter((s,i,all)=>all.findIndex(x=>x.id===s.id)===i);
  const query = new URLSearchParams(location.search);
  const [scenario, setScenario] = useState(() => workshopScenarios.find(s => s.id === query.get('scenario')) ?? feedRide(query.get('scenario')) ?? retainedImports.get(query.get('scenario') ?? '') ?? (['candidate-v5','candidate-v6','candidate-v7'].includes(designFromQuery(query.get('variant'))) ? identityScenario : scenarios[0]));
  const savedScroll = history.state?.[query.get('variant') === 'candidate-v14' ? 'r14' : query.get('variant') === 'candidate-v13' ? 'v13' : 'v12']?.scroll;
  const restorePageScroll = useRef<number | null>(Number.isFinite(savedScroll) ? savedScroll : null);
  const [rideOwner,setRideOwner]=useState(query.get('viewer')!=='visitor');
  const [custom, setCustom] = useState<Scenario | null>(() => retainedImports.get(query.get('scenario') ?? '') ?? null), [variant, setVariant] = useState<DesignVariant>(() => designFromQuery(query.get('variant')));
  const missingImport = useRef((query.get('scenario')?.startsWith('local-') || query.get('scenario')?.startsWith('feed-local-')) && !retainedImports.has(query.get('scenario') ?? '') && !feedRide(query.get('scenario')));
  const importedSources = useRef(retainedImports), importKeys = useRef(retainedImportKeys), restoring = useRef<Scenario | null>(null);
  const [view, setView] = useState(rideViewPreferences.view), [state, setState] = useState<PreviewState>(() => missingImport.current ? 'error' : 'ready');
  const [squint, setSquint] = useState(rideViewPreferences.squint), [revision, setRevision] = useState(true), [reference, setReference] = useState(rideViewPreferences.reference), [referenceRoom, setReferenceRoom] = useState<ReferenceView>(rideViewPreferences.referenceRoom);
  useEffect(()=>{Object.assign(rideViewPreferences,{view,squint,reference,referenceRoom});},[view,squint,reference,referenceRoom]);
  const referenceView = referenceViews[referenceRoom];
  const previewStage = useRef<HTMLDivElement>(null), [stageWidth, setStageWidth] = useState(1440);
  const previewScale = view === 'desktop' && reference ? Math.min(1, stageWidth / 1440) : 1;
  const previewHeight = reference && referenceRoom === 'analysis' ? 1175 : 1000;
  const [dataOpen, setDataOpen] = useState(false), [infoOpen, setInfoOpen] = useState(false), [json, setJson] = useState(''), [error, setError] = useState('');
  const [selected, setSelected] = useState<string | null>(null), [exporting, setExporting] = useState(false), [copied, setCopied] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null), lastSent = useRef<Scenario | null>(null), settings = useRef<Settings>({ scenario, variant, state, squint, revision });
  const dialog = useRef<HTMLDialogElement>(null), importButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (!previewStage.current) return; const observer = new ResizeObserver(entries => setStageWidth(entries[0].contentRect.width)); observer.observe(previewStage.current); return () => observer.disconnect(); }, []);
  settings.current = { rideContext: ['candidate-v13','candidate-v14'].includes(variant) && (workshopScenarios.includes(scenario) || feedRide(scenario.id) === scenario) ? (query.get('feedVariant')==='feed-v13'?v13RideContext:query.get('feedVariant')==='feed-v12'?v12RideContext:query.get('feedVariant')==='feed-v11'?v11RideContext:query.get('feedVariant')==='feed-v9'?v9RideContext:query.get('feedVariant')==='feed-v8'?v8RideContext:query.get('feedVariant')==='feed-v7'?v7RideContext:v6RideContext)(scenario.id, query.get('feedScenario'), query.get('feedFilter') ?? 'everyone') : undefined, rideOwner, scenario, variant, state: missingImport.current ? 'error' : state, squint, revision, bundled: scenarios.includes(scenario) };
  const send = (force = false) => {
    const value = settings.current;
    if (lastSent.current && value.scenario !== lastSent.current && restoring.current !== value.scenario) {
      const url = new URL(location.href);
      for (const key of ['view','climb','from','to','axis','effort']) url.searchParams.delete(key);
      const {v9, v9Return, v10, v10Return, v11, v11Return, v12, v12Return, v13, v13Return, r14, r14Return, ...rest} = window.history.state ?? {};
      window.history.replaceState(rest, '', url);
    }
    restoring.current = null;
    frame.current?.contentWindow?.postMessage({ type: 'workshop-settings', settings: { ...value, scenario: force || value.scenario !== lastSent.current ? value.scenario : undefined } }, location.origin);
    lastSent.current = value.scenario;
  };
  useEffect(() => { send(); }, [scenario, variant, state, squint, revision, rideOwner]);
  useEffect(() => {
    const url = new URL(location.href);
    if (missingImport.current) return;
    url.searchParams.set('variant', variant);
    url.searchParams.set('viewer',rideOwner?'owner':'visitor');
    if (workshopScenarios.includes(scenario) || feedRide(scenario.id) === scenario) url.searchParams.set('scenario', ['candidate-v8','candidate-v9','candidate-v10','candidate-v11','candidate-v12','candidate-v13','candidate-v14'].includes(variant) && scenario.id === 'identity' ? scenarios[0].id : scenario.id);
    else if (['candidate-v9','candidate-v10','candidate-v11','candidate-v12','candidate-v13','candidate-v14'].includes(variant)) {
      let key = importKeys.current.get(scenario);
      if (!key) { key = `local-${crypto.randomUUID()}`; importKeys.current.set(scenario,key); importedSources.current.set(key,scenario); }
      url.searchParams.set('scenario',key);
    } else url.searchParams.delete('scenario');
    window.history.replaceState(window.history.state, '', url);
  }, [scenario, variant, state, rideOwner]);
  useEffect(() => {
    const pop=()=>{const p=new URLSearchParams(location.search);setVariant(designFromQuery(p.get('variant')));setRideOwner(p.get('viewer')!=='visitor');const key=p.get('scenario')??'';const next=workshopScenarios.find(s=>s.id===key)??feedRide(key)??importedSources.current.get(key);missingImport.current=(key.startsWith('local-')||key.startsWith('feed-local-'))&&!next;restoring.current=next??null;if(next){setScenario(next);setState('ready');}else if(missingImport.current)setState('error');};
    window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop);
  }, []);
  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === 'workshop-ready') send(true);
      if (event.data?.type === 'feed-open-ride' && typeof event.data.href === 'string' && event.data.href.startsWith('/?')) visitWorkshop('ride',event.data.href);
      if(event.data?.type==='workshop-open-climb'&&typeof event.data.href==='string'&&event.data.href.startsWith('/?'))visitWorkshop('climb',event.data.href);
      if (event.data?.type === 'workshop-open-feed' && typeof event.data.href === 'string' && event.data.href.startsWith('/?')) {const u=new URL(event.data.href,location.origin);const from=new URLSearchParams(location.search).get('feedVariant');if(from==='feed-v7'||from==='feed-v8'||from==='feed-v9'||from==='feed-v11'||from==='feed-v12'||from==='feed-v13')u.searchParams.set('variant',from);visitWorkshop('feed',u.pathname+u.search);}
      if (event.data?.type === 'workshop-rendered' && restorePageScroll.current !== null) { const top=restorePageScroll.current; restorePageScroll.current=null; requestAnimationFrame(()=>frame.current?.contentWindow?.scrollTo({top,behavior:'instant'})); }
      if (event.data?.type === 'workshop-selection') setSelected(event.data.selected);
      if (event.data?.type === 'workshop-recover') { if(missingImport.current){setExporting(false);setDataOpen(true);}else setState('ready'); }
    };
    window.addEventListener('message', receive);
    return () => window.removeEventListener('message', receive);
  }, []);
  useEffect(() => { if (dataOpen) dialog.current?.showModal(); else if (dialog.current?.open) dialog.current.close(); }, [dataOpen]);
  const closeData = () => { setDataOpen(false); setError(''); importButton.current?.focus(); };
  const load = (raw: string) => {
    try {
      if (raw.length > 20 * 1024 * 1024) throw new Error('Choose a scenario smaller than 20 MB.');
      const parsed = parseScenario(JSON.parse(raw));
      missingImport.current=false;
      setCustom(parsed); setScenario(parsed); setState('ready'); closeData();
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not read the scenario.'); }
  };
  const showExport = () => { if(missingImport.current)return; setJson(JSON.stringify(scenario, null, 2)); setExporting(true); setCopied(false); setError(''); setDataOpen(true); };
  const copyExport = async () => {
    try { await navigator.clipboard.writeText(json); setCopied(true); }
    catch { setError('Select the JSON below and copy it.'); }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(scenario, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = `${scenario.id.replace(/[^a-z0-9-]/gi, '-')}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <div className="workshop">
    <header className="workshop-toolbar">
      <div className="workshop-title"><strong>Ride workshop</strong><span>Boulder Roller</span></div>
      <label className="scenario-picker"><span className="sr-only">Ride scenario</span><select aria-label="Ride scenario" value={scenario === custom ? 'custom' : ['candidate-v8','candidate-v9','candidate-v10','candidate-v11','candidate-v12','candidate-v13','candidate-v14'].includes(variant) && scenario.id === 'identity' ? scenarios[0].id : scenario.id} onChange={e => { const next = e.target.value === 'custom' ? custom : workshopScenarios.find(s => s.id === e.target.value); if (next) { missingImport.current=false; setScenario(next); setState('ready'); } }}>{workshopScenarios.filter(s => !s.id.startsWith('feed-') || s.id===scenario.id).filter(s => (['candidate-v12','candidate-v13','candidate-v14'].includes(variant)||!v12LayoutScenarios.includes(s)||s===scenario)).filter(s => !['candidate-v8','candidate-v9','candidate-v10','candidate-v11','candidate-v12','candidate-v13','candidate-v14'].includes(variant) || s.id !== 'identity').map(s => <option key={s.id} value={s.id}>{s.label}</option>)}{custom && <option value="custom">Imported · {custom.label}</option>}</select><ChevronDown size={14} /></label>
      <div className="view-switch" role="group" aria-label="Design">{DESIGNS.map(design => <button key={design.id} aria-pressed={variant === design.id} onClick={() => setVariant(design.id)}>{design.label}</button>)}</div>
      <div className="viewport-switch" role="group" aria-label="Preview size"><button aria-label="Fit window" title="Fit window" aria-pressed={view === 'fit'} onClick={() => setView('fit')}><Maximize2 size={16} /></button><button aria-label="Desktop preview" title="Desktop · 1440 px" aria-pressed={view === 'desktop'} onClick={() => setView('desktop')}><Monitor size={17} /></button><button aria-label="Phone preview" title="Phone · 390 × 844" aria-pressed={view === 'phone'} onClick={() => setView('phone')}><Smartphone size={17} /></button></div>
      <label className="state-picker"><span>State</span><select aria-label="Loading state" value={state} onChange={e => setState(e.target.value as PreviewState)}><option value="ready">Ready</option><option value="loading">Loading results</option><option value="empty">Empty</option><option value="error">Error</option></select></label>
      {state === 'loading' && <button className="release-button" onClick={() => setState('ready')}>Release data</button>}
    </header>
    <div className="workshop-subbar"><span className="preview-caption" style={['candidate-v9','candidate-v10','candidate-v11','candidate-v12','candidate-v13','candidate-v14'].includes(variant)?{minWidth:0,overflow:'hidden',flex:1}:undefined}>{variant === 'candidate-v14' ? 'Candidate v14' : variant === 'candidate-v13' ? 'Candidate v13' : variant === 'candidate-v12' ? 'Candidate v12' : variant === 'candidate-v11' ? 'Candidate v11' : variant === 'candidate-v10' ? 'Candidate v10' : variant === 'candidate-v9' ? 'Candidate v9' : variant === 'candidate-v8' ? 'Candidate v8' : variant === 'candidate-v7' ? 'Candidate v7' : variant === 'candidate-v6' ? 'Candidate v6' : variant === 'candidate-v5' ? 'Candidate v5' : variant === 'candidate-v4' ? 'Candidate v4' : variant === 'candidate-v3' ? 'Candidate v3' : variant === 'candidate-v2' ? 'Candidate v2' : variant === 'candidate' ? revision ? 'Candidate v1 · Claude revision' : 'Candidate v1 · original' : 'Current · existing Ride room components'}{selected && <><i>/</i>{['candidate-v9','candidate-v10','candidate-v11','candidate-v12','candidate-v13','candidate-v14'].includes(variant)?<span title={selected} style={{minWidth:0,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{selected}</span>:selected}</>}</span><div>{['candidate-v10','candidate-v11','candidate-v12','candidate-v13','candidate-v14'].includes(variant)&&<label className="v10-preview-owner"><span className="sr-only">Preview viewer</span><select aria-label="Preview viewer" value={rideOwner?'owner':'visitor'} onChange={e=>setRideOwner(e.target.value==='owner')}><option value="owner">Ride owner</option><option value="visitor">Visitor</option></select></label>}{variant === 'candidate' && <button className="revision-toggle" aria-pressed={revision} onClick={() => setRevision(x => !x)}><Check size={14} />Claude changes</button>}<button aria-pressed={squint} onClick={() => setSquint(x => !x)}><Eye size={14} />Squint</button><button aria-pressed={reference} onClick={() => setReference(x => !x)}>Strava reference</button><button ref={importButton} onClick={() => { setExporting(false); setCopied(false); setDataOpen(true); }}><FileUp size={14} />Data</button><button aria-expanded={infoOpen} aria-label="About this workshop" onClick={() => setInfoOpen(x => !x)}><Info size={15} /></button></div></div>
    {infoOpen && <section className="workshop-info"><p><strong>One ride, fifteen presentations.</strong> Current uses the portal’s Ride room composition. Candidate v1 retains the original and Claude revision. Candidate v2 refines the opening, readable data, history comparison and map hierarchy. Candidate v3 adds a lighter frame, focused climb geography and linked ride analysis. Candidate v4 gives the ride a stable sidebar, neutral data surfaces and a directly adjustable analysis interval. Candidate v5 adds easy interval clearing and rider identity. Candidate v6 brings the summary together, enriches the map, lightens chart traces and adds Power Curve. Candidate v7 keeps climbs within ride Analysis, adds an adjustable map and shared chart selection behavior. Candidate v8 carries rider identity across bundled scenarios, tucks secondary stats and illustrative CAL under Show more, and adds a tribute view and covered-time power distribution. Candidate v9 refines the expanding header, adds local ride description, private notes and co-rider controls, combines curve, distribution and power–cadence density under Power, and connects tribute to local Vault pages and recorded efforts. Candidate v10 adds cadence versus estimated gradient, Power Curve effort navigation, owner-only ride controls and linked climb terrain. Candidate v11 adds soft Power Curve selection with explicit effort analysis, a compact Analysis header, aligned navigation and clearer chart readings. Candidate v12 contains long climb lists beside the map, restores list position after Analysis, and shortens the CAL navigation label. Candidate v13 expands feed-linked results inside Overview, separates current leaderboards from historical ride results, and adds signed average grade to selected analysis sections. Every candidate preserves its reviewed generation. This is a local design workshop.</p>{['candidate-v9','candidate-v10','candidate-v11','candidate-v12','candidate-v13','candidate-v14'].includes(variant) && <p>V9–V14 rider identity, social context, historical results, CAL amounts and Vault destinations are illustrative workshop data. Notes and comments stay in this session; no group matching or messages are sent. Vault geometry comes from this ride’s traversal, not a verified canonical binding. Only this ride has a full recording; older effort summaries have no linked recording.</p>}<p>{scenario.source.description}</p><p>Distance, elapsed time, elevation gain and power are derived from the selected samples. Elevation gain sums positive recorded changes across gaps of at most 30 seconds; it can differ from the device’s filtered total. Climb labels refer to recorded traversal windows. History: <strong>{scenario.source.history}</strong>.</p></section>}
    <div className={`workshop-stage ${reference ? 'with-reference' : ''} viewport-${view}`}>
      {missingImport.current && <p role="status">This imported recording is no longer available in this window. Import it again or choose a recorded ride. <button onClick={()=>{missingImport.current=false;const url=new URL(location.href);url.searchParams.set('scenario',scenarios[0].id);for(const key of ['view','climb','from','to','axis','effort'])url.searchParams.delete(key);const {v9,v9Return,v10,v10Return,v11,v11Return,v12,v12Return,v13,v13Return,r14,r14Return,...rest}=window.history.state??{};window.history.replaceState(rest,'',url);setScenario(scenarios[0]);setState('ready');}}>Open recorded ride</button></p>}<div className="preview-stage" ref={previewStage}>{reference && view === 'desktop' && <div className="comparison-heading"><strong>Boulder Roller</strong></div>}<div className="preview-size" data-squint={squint} style={view === 'desktop' ? { width: 1440 * previewScale, height: previewHeight * previewScale } : undefined}><div className="preview-frame" data-viewport={view} style={view === 'desktop' ? { height: previewHeight, transform: `scale(${previewScale})`, transformOrigin: 'top left' } : undefined}><iframe ref={frame} title="Interactive Boulder Roller ride preview" src="/?preview=1" /></div></div>{view === 'phone' && <span className="frame-dimensions">390 × 844 · actual responsive viewport</span>}{reference && view === 'desktop' && <span className="frame-dimensions">1440 px viewport · scaled to reference width</span>}</div>
      {reference && <aside className="reference-panel"><div className="reference-heading"><strong>Strava web</strong><div className="view-switch">{(Object.keys(referenceViews) as ReferenceView[]).map(key => <button key={key} aria-pressed={referenceRoom === key} onClick={() => setReferenceRoom(key)}>{referenceViews[key].label}</button>)}</div><button aria-label="Close reference" onClick={() => setReference(false)}><X size={16} /></button></div>
        {referenceView.frames.map(frame => <figure className="reference-frame" key={frame.image}>
          <div className="reference-image" data-squint={squint}><a href={frame.image} target="_blank" rel="noreferrer" title="Open full reference"><img src={frame.image} alt={frame.alt} /></a></div>
          {referenceRoom === 'analysis' && <figcaption>{frame.caption}</figcaption>}
        </figure>)}
        <p>Retained capture · {referenceView.date} · different ride data<br />{referenceRoom === 'analysis' && <><a href="https://www.strava.com/activities/20113623084/analysis" target="_blank" rel="noreferrer">Morning Ride · Drake Deuel · open live analysis</a><br />Recorded power, heart rate and cadence. The subscription panel remains visible; chart selection was exercised live.<br /></>}Click an image to inspect at full size.</p>
      </aside>}
    </div>
    <footer className="workshop-status"><span><Check size={12} />{missingImport.current ? 'Imported recording unavailable' : scenario.source.kind === 'recorded' ? 'Recorded GPS and measurements' : 'Illustrative GPS and measurements'}{v12LayoutScenarios.includes(scenario) && <strong> · Illustrative climb windows</strong>}{scenario.source.history === 'illustrative' && <strong> · Illustrative history</strong>}{scenario.id === 'excerpt' && ' · Recorded excerpt; power omitted'}</span><button disabled={missingImport.current} onClick={showExport}><Download size={13} />Export scenario</button></footer>
    <dialog ref={dialog} className="data-dialog" onCancel={closeData} onClose={() => setDataOpen(false)}><div className="dialog-heading"><div><h2>{exporting ? 'Export this scenario' : 'Bring in a ride'}</h2><p>{exporting ? 'The complete dataset is ready to copy or download.' : 'Load a workshop scenario, or export this one as a starting point.'}</p></div><button aria-label="Close data dialog" onClick={closeData}><X size={20} /></button></div>
      <div className="data-actions"><label className="upload-scenario"><FileUp size={17} />Choose JSON file<input type="file" accept=".json,application/json" onChange={async e => { const file = e.target.files?.[0]; if (file) { if (file.size > 20 * 1024 * 1024) { setError('Choose a scenario smaller than 20 MB.'); return; } load(await file.text()); } e.target.value = ''; }} /></label><button disabled={missingImport.current} onClick={showExport}><Download size={16} />Export current scenario</button>{exporting && <button onClick={download}>Download JSON</button>}</div>
      <label className="paste-label" htmlFor="scenario-json">{exporting ? `${scenario.ride.samples.length.toLocaleString()} samples · ${scenario.climbs.length} climbs · complete JSON` : 'Or paste scenario JSON'}</label>{exporting ? <pre className="export-preview">{json.slice(0, 1100)}{json.length > 1100 ? '\n… Preview shortened. Copy JSON includes the complete dataset.' : ''}</pre> : <textarea id="scenario-json" value={json} onChange={e => setJson(e.target.value)} spellCheck={false} placeholder='{"version":1,"id":"my-ride", …}' />}
      <>{exporting && <details className="complete-export"><summary>Show complete JSON</summary><textarea aria-label="Complete scenario JSON" readOnly value={json} spellCheck={false} /></details>}</><p className="data-note">Each sample contains longitude, latitude, distance in meters, elapsed seconds, elevation and optional power, cadence, speed and heart rate. Climb boundaries use those same elapsed seconds. Files stay in this workshop session.</p>
      {error && <p className="import-error" role="alert">{error}</p>}<div className="dialog-footer"><button onClick={closeData}>Cancel</button><button className="load-button" onClick={() => exporting ? copyExport() : load(json)} disabled={!json.trim()}>{exporting ? copied ? 'Copied' : 'Copy JSON' : 'Load scenario'}<ArrowUpRight size={15} /></button></div>
    </dialog>
  </div>;
}

const root = import.meta.hot?.data.root ?? createRoot(document.getElementById('root')!);
if (import.meta.hot) import.meta.hot.data.root = root;
function Workbench() {
 const [baselineVisited,setBaselineVisited]=useState<BaselineRoom[]>(()=>baselineRooms.filter(r=>r.id===currentPage()).map(r=>r.id));
 useEffect(()=>{const pop=()=>{const next=currentPage();if(baselineRooms.some(r=>r.id===next))setBaselineVisited(old=>old.includes(next as BaselineRoom)?old:[...old,next as BaselineRoom]);};window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop);},[]);
 const [page,setPage] = useState(currentPage), [feedVisited,setFeedVisited] = useState(currentPage()==='feed'), [climbVisited,setClimbVisited]=useState(currentPage()==='climb'), [mapVisited,setMapVisited]=useState(currentPage()==='map');
 useEffect(()=>{document.title=`${roomFor(page).label} workshop · Boulder Roller`;},[page]);
 const [finals,setFinals]=useState(()=>finalsActive(location.search));
 const [palette,setPalette]=useState(paletteActive);
 const togglePalette=(on:boolean)=>{setPaletteActive(on);setPalette(on);};
 useEffect(()=>{document.documentElement.toggleAttribute('data-finals',finals);},[finals]);
 useEffect(()=>{const pop=()=>setFinals(finalsActive(location.search));window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop);},[]);
 useEffect(()=>{if(finals&&!roomFor(page).hasFinal)visitWorkshop(FINAL_ROOMS[0].id);},[finals,page]);
 const toggleFinals=(on:boolean)=>{const url=new URL(location.href);if(on)url.searchParams.set(FINALS_PARAM,'1');else url.searchParams.delete(FINALS_PARAM);history.replaceState(history.state,'',url);setFinals(on);if(on){if(!roomFor(page).hasFinal){visitWorkshop(FINAL_ROOMS[0].id);return;}const locked=new URL(roomDestination(page),location.origin).searchParams.get('variant');if(url.searchParams.get('variant')!==locked)visitWorkshop(page,roomDestination(page));}};
 useEffect(() => { const pop=()=>{const next=currentPage();setPage(next);if(next==='feed')setFeedVisited(true);if(next==='climb')setClimbVisited(true);if(next==='map')setMapVisited(true);}; window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop); }, []);
 return <><div className="workbench-page-bar"><div className="workbench-controls"><label><span>Workshop page</span><select aria-label="Workshop page" value={page} onChange={e=>visitWorkshop(e.target.value as WorkshopPage)}>{(finals?FINAL_ROOMS:ROOMS).map(room=><option key={room.id} value={room.id}>{room.label}</option>)}</select></label><label className="finals-toggle"><input type="checkbox" checked={finals} onChange={e=>toggleFinals(e.target.checked)}/>Finals</label><label className="finals-toggle" title="Preview the room on the shared palette"><input type="checkbox" checked={palette} onChange={e=>togglePalette(e.target.checked)}/>Palette</label></div><span>{finals?roomFor(page).finals:roomFor(page).detail}</span></div>{page==='ride'&&<Workshop/>}{page==='effort'&&<iframe title="Effort V1" src={`/?${new URLSearchParams({...Object.fromEntries(new URLSearchParams(location.search)),'effort-preview':'1'})}`} style={{width:'100%',height:'calc(100vh - 46px)',border:0,display:'block'}}/>}{page==='kit'&&<iframe title="V15 kit" src="/?kit-preview=1" style={{width:'100%',height:'calc(100vh - 46px)',border:0,display:'block'}}/>}{feedVisited&&<FeedWorkshop active={page==='feed'}/>}
 {page==='climb'&&<a href="/?surface=climb&variant=climb-v17">Candidate V17 · V15 kit</a>}{page==='climb'&&new URLSearchParams(location.search).get('variant')==='climb-v17'?<iframe title="Climb V17" src={`/?${new URLSearchParams({...Object.fromEntries(new URLSearchParams(location.search)),'climb-preview':'1'})}`} style={{width:'100%',height:'calc(100vh - 46px)',border:0,display:'block'}}/>:climbVisited&&<ClimbWorkshop active={page==='climb'}/>}{mapVisited&&<MapWorkshop active={page==='map'}/>}{baselineVisited.map(room=>room==='profile'?<ProfileWorkshop key={room} active={page===room}/>:<BaselineWorkshop key={room} room={room} active={page===room}/>)}</>;
}
installPalette();
const params=new URLSearchParams(location.search);
root.render(<Gate>{params.has('profile-v6-preview') ? <ProfileV6Preview/> : params.has('profile-v5-preview') ? <ProfileV5Preview/> : params.has('profile-v4-preview') ? <ProfileV4Preview/> : params.has('profile-v3-ride') ? <ProfileRideHost/> : params.has('profile-v3-preview') ? <ProfileV3Preview/> : params.has('profile-preview') ? <ProfilePreview/> : params.has('map-preview') ? <MapPreview/> : params.has('climb-preview') ? <ClimbPreview/> : params.has('preview') ? <Preview /> : params.has('feed-preview') ? <FeedPreview/> : <Workbench/>}</Gate>);
