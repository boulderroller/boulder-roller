import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Download, Eye, FileUp, Maximize2, Monitor, Smartphone, X } from 'lucide-react';
import { feedScenarios, feedImports, feedById, type FeedScenario } from './feedModel';
import {withV4Example,feedV4Scenarios,feedV4ById} from './feedV4Model';
import {parseFeedV5,withV5Example,feedV5Scenarios,feedV5ById} from './feedV5Model';
import {feedV7ById,feedV7Scenarios,withV7Example,parseFeedV7,rekeyV7Feed} from './feedV7Model';
import {parseFeedV6,withV6Example,feedV6Scenarios,feedV6ById} from './feedV6Model';
import v6Reference from '../references/strava-feed-v6-segment.png';
import { withV3Example } from './feedV3Model';
import giftReference from '../references/strava-feed-v3-achievements.png';
import { withV2Example, type FeedV2Scenario } from './feedV2Model';
import { visitWorkshop } from '../workbenchNavigation';
import type { FeedSettings } from './FeedPreview';
import top from '../references/strava-feed-top.png';
import scrolled from '../references/strava-feed-scrolled.png';
import phone from '../references/strava-feed-phone.png';
import phoneScrolled from '../references/strava-feed-phone-scrolled.png';
export const FEED_CANDIDATES = [{ id: 'feed-v1', label: 'Candidate v1', references: { desktop: [top, scrolled], phone: [phone, phoneScrolled] }, date: '9 Sep 2026' }, { id: 'feed-v2', label: 'Candidate v2', references: { desktop: [top, scrolled], phone: [phone, phoneScrolled] }, date: '9 Sep 2026' }, { id: 'feed-v3', label: 'Candidate v3', references: { desktop: [top, giftReference], phone: [phone, phoneScrolled] }, date: '9–11 Sep 2026' }, { id: 'feed-v4', label: 'Candidate v4', references: { desktop: [top, giftReference], phone: [phone, phoneScrolled] }, date: '9–11 Sep 2026' }, { id: 'feed-v5', label: 'Candidate v5', references: { desktop: [top, giftReference], phone: [phone, phoneScrolled] }, date: '9–11 Sep 2026' }, { id: 'feed-v6', label: 'Candidate v6', references: { desktop: [top, v6Reference], phone: [phone, phoneScrolled] }, date: '12 Sep 2026' }, { id:'feed-v7', label:'Candidate v7', references:{desktop:[top,v6Reference],phone:[phone,phoneScrolled]}, date:'12 Sep 2026' }, { id:'feed-v8', label:'Candidate v8', references:{desktop:[top,v6Reference],phone:[phone,phoneScrolled]}, date:'12 Sep 2026' }, { id:'feed-v9', label:'Candidate v9', references:{desktop:[top,v6Reference],phone:[phone,phoneScrolled]}, date:'12 Sep 2026' }, { id:'feed-v11', label:'Candidate v11', references:{desktop:[top,v6Reference],phone:[phone,phoneScrolled]}, date:'19 Oct 2026' }, { id:'feed-v12', label:'Candidate v12', references:{desktop:[top,v6Reference],phone:[phone,phoneScrolled]}, date:'19 Oct 2026' }, { id:'feed-v13', label:'Candidate v13', references:{desktop:[top,v6Reference],phone:[phone,phoneScrolled]}, date:'19 Oct 2026' }] as const;
type FeedVariant=typeof FEED_CANDIDATES[number]['id'];
const candidateId=(id:string|null):FeedVariant=>FEED_CANDIDATES.find(c=>c.id===id)?.id??'feed-v1';
const scenarioFor=(id:string|null,variant:FeedVariant):FeedScenario=>['feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(variant)?feedV7ById(id):variant==='feed-v6'?feedV6ById(id):variant==='feed-v5'?feedV5ById(id):variant==='feed-v4'?feedV4ById(id):feedById(id);
export function FeedWorkshop({ active }: {
    active: boolean;
}) {
    const initial = new URLSearchParams(location.search), [variant, setVariant] = useState<FeedVariant>(candidateId(initial.get('variant'))), [scenario, setScenario] = useState(() => scenarioFor(initial.get('scenario'),candidateId(initial.get('variant')))), [filter, setFilter] = useState(initial.get('filter') === 'following' ? 'following' : 'everyone'), [state, setState] = useState<FeedSettings['state']>(() => initial.get('scenario')?.startsWith('feed-import-') && !feedImports.has(initial.get('scenario')!) ? 'error' : 'ready');
    const [riderId,setRiderId]=useState<string|null>(initial.get('rider'));
    const [missing, setMissing] = useState(() => initial.get('scenario')?.startsWith('feed-import-') && !feedImports.has(initial.get('scenario')!) ? initial.get('scenario') : null);
    const [view, setView] = useState('fit'), [reference, setReference] = useState(false), [squint, setSquint] = useState(false), [referencePosition, setReferencePosition] = useState(0), [dataOpen, setDataOpen] = useState(false), [error, setError] = useState('');
    const frame = useRef<HTMLIFrameElement>(null), dialog = useRef<HTMLDialogElement>(null), dataButton = useRef<HTMLButtonElement>(null), stage = useRef<HTMLDivElement>(null), [width, setWidth] = useState(1440), lastSent = useRef<FeedScenario | null>(null), settings = useRef({ scenario, filter, state, variant,riderId }), isActive = useRef(active);
    settings.current = { scenario, filter, state, variant,riderId };
    isActive.current = active;
    const send = (force = false) => { const next = settings.current; frame.current?.contentWindow?.postMessage({ type: 'feed-settings', settings: { ...next, active: isActive.current, scenario: force || next.scenario !== lastSent.current ? (['feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(next.variant) ? withV7Example(next.scenario) : next.variant === 'feed-v6' ? withV6Example(next.scenario) : next.variant === 'feed-v5' ? withV5Example(next.scenario) : next.variant === 'feed-v4' ? withV4Example(next.scenario) : next.variant === 'feed-v3' ? withV3Example(next.scenario) : next.variant === 'feed-v2' ? withV2Example(next.scenario) : next.scenario) : undefined } }, location.origin); lastSent.current = next.scenario; };
    useEffect(() => { send(true); }, [scenario, variant]);
    useEffect(() => { send(); }, [filter, state, active,riderId]);
    useEffect(() => { if (!active || missing)
        return; const u = new URL(location.href); u.searchParams.set('surface', 'feed'); u.searchParams.set('variant', variant); u.searchParams.set('scenario', scenario.id); u.searchParams.set('filter', filter); history.replaceState(history.state, '', u); }, [active, scenario, filter, missing, variant]);
    useEffect(() => { const pop = () => { if (new URLSearchParams(location.search).get('surface') !== 'feed')
        return; const p = new URLSearchParams(location.search); setRiderId(p.get('rider')); setVariant(candidateId(p.get('variant'))); setScenario(scenarioFor(p.get('scenario'),candidateId(p.get('variant')))); setFilter(p.get('filter') === 'following' ? 'following' : 'everyone'); }; const receive = (e: MessageEvent) => { if (e.origin !== location.origin || e.source !== frame.current?.contentWindow)
        return; if (e.data?.type === 'feed-ready')
        send(true); if(e.data?.type==='feed-rider'&&isActive.current){const id=typeof e.data.riderId==='string'?e.data.riderId:null;const u=new URL(location.href);if(id){u.searchParams.set('rider',id);history.pushState({...history.state,feedRider:true},'',u);}else{u.searchParams.delete('rider');history.replaceState({...history.state,feedRider:false},'',u);}setRiderId(id);} if (e.data?.type === 'feed-filter')
        setFilter(e.data.filter === 'following' ? 'following' : 'everyone'); if (e.data?.type === 'feed-recover') {
        const id = new URLSearchParams(location.search).get('scenario');
        if (id?.startsWith('feed-import-') && !feedImports.has(id))
            setDataOpen(true);
        else
            setState('ready');
    } if (e.data?.type === 'feed-open-ride' && isActive.current)
        visitWorkshop('ride', e.data.href); }; window.addEventListener('popstate', pop); window.addEventListener('message', receive); return () => { window.removeEventListener('popstate', pop); window.removeEventListener('message', receive); }; }, []);
    useEffect(() => { if (!stage.current)
        return; const observer = new ResizeObserver(e => setWidth(e[0].contentRect.width)); observer.observe(stage.current); return () => observer.disconnect(); }, []);
    useEffect(() => { if (dataOpen)
        dialog.current?.showModal();
    else
        dialog.current?.close(); }, [dataOpen]);
    const close = () => { setDataOpen(false); setError(''); dataButton.current?.focus(); };
    const load = async (file: File) => { try {
        if (file.size > 20 * 1024 * 1024)
            throw Error('Choose a file smaller than 20 MB.');
        const next = rekeyV7Feed(parseFeedV7(JSON.parse(await file.text())),crypto.randomUUID());
        setRiderId(null);
        setMissing(null);
        feedImports.set(next.id, next);
        setScenario(next);
        setState('ready');
        setFilter('everyone');
        close();
    }
    catch (e) {
        setError(e instanceof Error ? e.message : 'Could not read this Feed.');
    } };
    const exportData = () => { const url = URL.createObjectURL(new Blob([JSON.stringify(['feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(variant) ? withV7Example(scenario) : variant === 'feed-v6' ? withV6Example(scenario) : variant === 'feed-v5' ? withV5Example(scenario) : variant === 'feed-v4' ? withV4Example(scenario) : variant === 'feed-v3' ? withV3Example(scenario) : variant === 'feed-v2' ? withV2Example(scenario) : scenario, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = `${scenario.id}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
    const scale = view === 'desktop' && reference ? Math.min(1, width / 1440) : 1, candidate = FEED_CANDIDATES.find(c => c.id === variant)!, referenceImages = view === 'phone' ? candidate.references.phone : candidate.references.desktop;
    return <div className="workshop feed-workshop" hidden={!active}>
  <header className="workshop-toolbar"><div className="workshop-title"><strong>Feed workshop</strong><span>Boulder Roller</span></div><label className="scenario-picker"><select aria-label="Feed scenario" value={missing ?? scenario.id} onChange={e => { setMissing(null);setRiderId(null);const u=new URL(location.href);u.searchParams.delete('rider');history.replaceState(history.state,'',u); setScenario(scenarioFor(e.target.value,variant)); setState('ready'); }}>{missing && <option value={missing}>Imported Feed unavailable</option>}{[...feedScenarios, ...(['feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(variant)?feedV7Scenarios:variant==='feed-v6'?feedV6Scenarios:variant==='feed-v5'?feedV5Scenarios:variant==='feed-v4'?feedV4Scenarios:[]), ...feedImports.values()].map(s => <option key={s.id} value={s.id}>{s.label}</option>)}</select><ChevronDown size={14}/></label><div className="view-switch" role="group" aria-label="Feed candidates">{FEED_CANDIDATES.map(c => <button key={c.id} aria-pressed={variant===c.id} onClick={()=>{setRiderId(null);const u=new URL(location.href);u.searchParams.delete('rider');history.replaceState(history.state,'',u);setVariant(c.id);setScenario(scenarioFor(scenario.id,c.id));}}>{c.label}</button>)}</div><div className="viewport-switch" role="group" aria-label="Preview size">{[['fit', 'Fit window', Maximize2], ['desktop', 'Desktop preview', Monitor], ['phone', 'Phone preview', Smartphone]].map(([id, name, Icon]) => { const Glyph = Icon as typeof Monitor; return <button key={String(id)} aria-label={String(name)} aria-pressed={view === id} onClick={() => setView(String(id))}><Glyph size={17}/></button>; })}</div><label className="state-picker"><span>State</span><select aria-label="Loading state" value={state} onChange={e => setState(e.target.value as FeedSettings['state'])}><option value="ready">Ready</option><option value="loading">Loading results</option><option value="empty">Empty</option><option value="error">Error</option></select></label>{state === 'loading' && <button onClick={() => setState('ready')}>Release data</button>}</header>
  <div className="workshop-subbar"><span>{candidate.label}</span><div><button aria-pressed={squint} onClick={() => setSquint(v => !v)}><Eye size={14}/>Squint</button><button aria-pressed={reference} onClick={() => setReference(v => !v)}>Strava reference</button><button ref={dataButton} onClick={() => setDataOpen(true)}><FileUp size={14}/>Data</button></div></div>
  {missing && <p className="workshop-info">This imported Feed is no longer available. <button onClick={() => setDataOpen(true)}>Import Feed again</button></p>}
  <div className={`workshop-stage ${reference ? 'with-reference' : ''} viewport-${view}`}><div ref={stage} className="preview-stage">{reference && view === 'desktop' && <div className="comparison-heading"><strong>Boulder Roller</strong></div>}<div className="preview-size" data-squint={squint} style={view === 'desktop' ? { width: 1440 * scale, height: 1000 * scale } : undefined}><div className="preview-frame" data-viewport={view} style={view === 'desktop' ? { height: 1000, transform: `scale(${scale})`, transformOrigin: 'top left' } : undefined}><iframe ref={frame} title="Interactive Boulder Roller feed preview" src="/?feed-preview=1"/></div></div>{view === 'phone' && <span className="frame-dimensions">390 × 844 · actual responsive viewport</span>}</div>{reference && <aside className="reference-panel"><div className="reference-heading"><strong>Strava · Feed</strong><div className="view-switch"><button aria-pressed={referencePosition === 0} onClick={() => setReferencePosition(0)}>Top</button><button aria-pressed={referencePosition === 1} onClick={() => setReferencePosition(1)}>Scrolled</button></div><button aria-label="Close reference" onClick={() => setReference(false)}><X size={16}/></button></div><figure className="reference-frame"><div className="reference-image" data-squint={squint}><a href={referenceImages[referencePosition]} target="_blank" rel="noreferrer"><img src={referenceImages[referencePosition]} alt={`Retained Strava Feed ${referencePosition ? 'scrolled' : 'top'} at ${view === 'phone' ? 'phone' : 'desktop'} width`}/></a></div></figure><p>Retained capture · {candidate.date} · different activity data.<br /><a href="https://www.strava.com/dashboard" target="_blank" rel="noreferrer">Open Strava Feed</a></p></aside>}</div>
  <footer className="workshop-status"><span><Check size={12}/>Illustrative Feed · retained ride geometry and measurements · social changes stay in this session</span><button disabled={!!missing} onClick={exportData}><Download size={13}/>Export scenario</button></footer>
  <dialog ref={dialog} className="data-dialog" onCancel={close}><div className="dialog-heading"><div><h2>Feed data</h2><p>{scenario.source}</p>{['feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'].includes(variant) && <><p>{withV7Example(scenario).workshopV3?.source}</p><p>{withV7Example(scenario).workshopV7?.source}</p></>}{variant === 'feed-v6' && <><p>{withV6Example(scenario).workshopV3?.source}</p><p>{withV6Example(scenario).workshopV6?.source}</p></>}{variant === 'feed-v5' && <><p>{withV5Example(scenario).workshopV3?.source}</p><p>{withV5Example(scenario).workshopV5?.source}</p></>}{variant === 'feed-v4' && <p>{withV4Example(scenario).workshopV3?.source}</p>}{variant === 'feed-v3' && <p>{withV3Example(scenario).workshopV3?.source}</p>}{variant === 'feed-v2' && <p>{(withV2Example(scenario) as FeedV2Scenario).workshopV2?.source}</p>}</div><button aria-label="Close Feed data" onClick={close}><X size={19}/></button></div><div className="data-actions"><label className="upload-scenario"><FileUp size={16}/>Choose JSON file<input type="file" accept=".json,application/json" onChange={e => { const file = e.target.files?.[0]; if (file)
        void load(file); e.target.value = ''; }}/></label><button onClick={exportData}>Export current scenario</button></div><p className="data-note">Export this Feed as a starting point. Each item includes its complete ride scenario. Imports and comments stay in this browser session.</p>{error && <p role="alert" className="import-error">{error}</p>}</dialog>
 </div>;
}
