import {useEffect,useMemo,useRef,useState,type MouseEvent} from 'react';
import {ArrowLeft,ArrowUpRight,ChevronDown,ChevronUp,Compass,Search,UserRound,X,RotateCcw,List,SlidersHorizontal} from 'lucide-react';
import {RankMark} from '../../../src/components/rankmarks/RankMark';
import {MapCanvasV5 as MapCanvas} from '../v5/MapCanvasV5';
import '../v5/map-v5.css';
import './map-v7.css';
import {MapProfileV5} from '../v5/MapProfileV5';
import {MapRowContentsV7,MapLeaderV7} from './MapRowV7';
import {filterClimbs,normalizeFilters,activeFilterCount,EMPTY_FILTERS,FILTER_OPTIONS,type MapFilters,type MapV7State} from './mapV7Model';
import {ClimbMap} from '../../climb/ClimbMap';
import {ClimbV3Profile} from '../../climb/ClimbV3Profile';
import {clearClimb,closeClimb,openClimb,selectClimb,surroundingBounds,visibleClimbs,type Bounds,type MapClimb,type MapState,type MapStudy,type MapViewer,type MapLoadState,type MapCamera} from '../mapModel';
import type {DiscoveryV4} from '../../feed/feedV4Model';
import '../map-v2.css';
const distance=(n:number)=>(n/1000).toFixed(2),rise=(n:number)=>Math.round(n).toLocaleString(),grade=(n:number)=>n.toFixed(1);
const time=(n:number)=>{const seconds=Math.round(n);return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;};
function Facts({climb}:{climb:MapClimb}){return <dl className="m2-facts"><div><dt>Distance</dt><dd>{distance(climb.lengthM)}<small>km</small></dd></div><div><dt>Elevation rise</dt><dd>{rise(climb.riseM)}<small>m</small></dd></div><div><dt>Avg grade</dt><dd>{grade(climb.gradePct)}<small>%</small></dd></div></dl>;}
function Identity({study,viewer}:{study:MapStudy;viewer:MapViewer}){
 const [failedPortrait,setFailedPortrait]=useState<string|null>(null);
 const person=viewer==='rider'?study.viewer:undefined;
 const initials=person?.name.split(/\s+/).filter(Boolean).map(part=>Array.from(part)[0]).filter(Boolean)??[];
 return person?<span className="m2-person"><span className="m2-avatar" aria-hidden="true">{person.portrait&&failedPortrait!==person.portrait?<img src={person.portrait} alt="" onError={()=>setFailedPortrait(person.portrait!)}/>:`${initials[0]??''}${initials.length>1?initials.at(-1):''}`.toLocaleUpperCase()}</span><span>{person.name}</span></span>:<a href="https://app.boulderroller.xyz/profile" target="_blank" rel="noreferrer" aria-label={viewer==='signed-out'?'Sign in to Boulder Roller':'Open your profile'}>{viewer==='signed-out'?'Sign in':<UserRound size={19}/>}</a>;
}
function Standing({climb,study,viewer}:{climb:MapClimb;study:MapStudy;viewer:MapViewer}){const r=viewer==='rider'&&climb.standing?.viewerId===study.viewer?.id?climb.standing:undefined;return r?<div className="m2-standing"><span><strong>{r.name}</strong><small>{time(r.timeSeconds)}</small></span><div><RankMark rank={r.rank} size={52}/><small>Rank {r.rank}</small></div></div>:null;}
function MapClimbDetail({climb,study,viewer,onReturn,returnHref}:{climb:MapClimb;study:MapStudy;viewer:MapViewer;onReturn:()=>void;returnHref:string}){
 const [index,setIndex]=useState<number|null>(null),[range,setRange]=useState<[number,number]|null>(null),[detailCamera,setDetailCamera]=useState<MapCamera|null>(null);const heading=useRef<HTMLHeadingElement>(null);
 useEffect(()=>{heading.current?.focus();},[climb.id]);
 const terrain:DiscoveryV4|undefined=climb.geometry&&climb.profile&&climb.geometry.coordinates.length===climb.profile.length?{name:climb.name,locality:climb.locality,length:climb.lengthM,gain:climb.riseM,source:climb.source,geometry:climb.geometry,profile:climb.profile.map(p=>({d:p.distanceM,elevation:p.elevationM}))}:undefined;
 const detailStudy=useMemo(()=>({...study,id:`${study.id}:detail:${climb.id}`,originId:climb.id,climbs:[climb]}),[study,climb]);
 const back=(e:MouseEvent<HTMLAnchorElement>)=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onReturn();};
 return <main className="m2-detail"><div className="m2-detail-bar"><a href={returnHref} onClick={back}><ArrowLeft size={16}/>Map</a><a href={returnHref} onClick={back}>Explore climbs<Compass size={15}/></a></div><header><div>{climb.locality&&<p>{climb.locality}</p>}<h1 ref={heading} tabIndex={-1}>{climb.name}</h1></div><Facts climb={climb}/></header><div className="m2-detail-body"><section aria-label="Climb geography">{terrain?<><div className="m2-detail-map"><ClimbMap discovery={terrain} index={index} onInspect={setIndex} range={range} onClear={()=>setRange(null)}/></div><ClimbV3Profile terrain={terrain} index={index} range={range} onIndex={setIndex} onRange={setRange}/>{range&&<button className="m2-clear-range" onClick={()=>setRange(null)}>Clear selection<X size={14}/></button>}</>:<><div className="m2-detail-map"><MapCanvas detail study={detailStudy} originId={climb.id} climbs={detailStudy.climbs} selectedId={climb.id} hoveredId={null} camera={detailCamera} active focus={null} onCamera={camera=>setDetailCamera(camera)} onSelect={()=>{}} onHover={()=>{}} onClear={()=>{}}/></div>{climb.profile?<div className="m2-independent-profile"><MapProfileV5 climb={climb}/></div>:<p className="m2-geography-note">Elevation profile not supplied.</p>}{!climb.geometry&&<p className="m2-geography-note">Route not supplied. The marker uses the supplied bounds.</p>}</>}</section><aside><Standing {...{climb,study,viewer}}/><h2>Climb data</h2><dl><div><dt>Elevation rise</dt><dd>{climb.riseM.toFixed(2)} m</dd></div><div><dt>Distance</dt><dd>{climb.lengthM.toFixed(2)} m</dd></div><div><dt>Average grade</dt><dd>{climb.gradePct.toFixed(3)}%</dd></div></dl><p>Elevation rise measures the difference between the start and finish.</p>{study.sourceUrl&&<a href={study.sourceUrl} target="_blank" rel="noreferrer">Data and sources<ArrowUpRight size={14}/></a>}</aside></div><footer>{study.attribution?.join(" · ")??climb.source}</footer></main>;
}
type Props={study:MapStudy;viewer:MapViewer;loadState:MapLoadState;snapshot:MapV7State;active:boolean;onChange:(next:MapState,push?:boolean)=>void;onRecover:()=>void;detailHref:(id:string|null)=>string};
export function MapV7({study,viewer,loadState,snapshot,active,onChange,onRecover,detailHref}:Props){
 const [filtersOpen,setFiltersOpen]=useState(false),filtersButton=useRef<HTMLButtonElement>(null),filtersPanel=useRef<HTMLElement>(null),firstFilter=useRef<HTMLSelectElement>(null);
 const [hovered,setHovered]=useState<string|null>(null),[focus,setFocus]=useState<{id:string;nonce:number}|null>(null),[pendingArea,setPendingArea]=useState<Bounds|null>(null);
 const latest=useRef(snapshot),list=useRef<HTMLDivElement>(null),listToggle=useRef<HTMLButtonElement>(null),phoneToggle=useRef<HTMLButtonElement>(null),cardLink=useRef<HTMLAnchorElement>(null),restoreFocus=useRef(false),cameraControl=useRef<(()=>MapCamera|null)|null>(null);latest.current=snapshot;
 const commit=(next:MapState,push=false)=>{latest.current=next;onChange(next,push);};
 const set=(patch:Partial<MapV7State>)=>commit({...latest.current,...patch});
 const loading=loadState==='loading',error=loadState==='error',empty=loadState==='empty',listOpen=snapshot.sheetExpanded;
 const selected=study.climbs.find(c=>c.id===snapshot.selectedId),origin=study.climbs.find(c=>c.id===snapshot.originId),detail=study.climbs.find(c=>c.id===snapshot.detailId);
 const hasInspector=!!selected&&!loading&&!error&&!empty;
 const filters=normalizeFilters(snapshot.filters),filterCount=activeFilterCount(filters);
 const filteredClimbs=useMemo(()=>filterClimbs(study.climbs,snapshot.filters,snapshot.query),[study,snapshot.filters,snapshot.query]);
 const rows=useMemo(()=>visibleClimbs({...study,climbs:filteredClimbs},snapshot),[study,filteredClimbs,snapshot.area,snapshot.query,snapshot.sort]);
 const mapClimbs=useMemo(()=>loading||empty||error?[]:filteredClimbs,[filteredClimbs,loading,empty,error]);
 const closeFilters=()=>{setFiltersOpen(false);filtersButton.current?.focus({preventScroll:true});};
 const applySearch=(nextFilters:MapFilters,query=latest.current.query)=>{
  const matching=filterClimbs(study.climbs,nextFilters,query);
  set({filters:nextFilters,query,scrollTop:0,selectedId:matching.some(c=>c.id===latest.current.selectedId)?latest.current.selectedId:null});setHovered(null);
 };
 useEffect(()=>{
  if(!filtersOpen)return;
  firstFilter.current?.focus({preventScroll:true});
  const outside=(e:PointerEvent)=>{if(!filtersPanel.current?.contains(e.target as Node)&&!filtersButton.current?.contains(e.target as Node))setFiltersOpen(false);};
  document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);
 },[filtersOpen]);
 const closeList=()=>{set({sheetExpanded:false});(matchMedia('(max-width: 599px)').matches&&hasInspector?phoneToggle.current:listToggle.current)?.focus({preventScroll:true});};
 const choose=(id:string,keyboard=false)=>{
  const phone=matchMedia('(max-width: 599px)').matches,changed=latest.current.selectedId!==id;
  commit({...selectClimb(latest.current,id),sheetExpanded:phone?false:latest.current.sheetExpanded});
  if(changed)setFocus({id,nonce:Date.now()});
  if(keyboard&&phone)requestAnimationFrame(()=>cardLink.current?.focus({preventScroll:true}));
 };
 const open=(id:string)=>{const camera=cameraControl.current?.();restoreFocus.current=true;commit(openClimb({...latest.current,camera:camera??latest.current.camera},id),true);};
 const returnMap=()=>commit(closeClimb(latest.current),true);
 const openLink=(e:MouseEvent<HTMLAnchorElement>,id:string)=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();open(id);};
 useEffect(()=>{if(loading||error||empty)set({sheetExpanded:true});},[loadState]);
 useEffect(()=>{if(list.current&&listOpen)list.current.scrollTop=snapshot.scrollTop;if(!detail&&restoreFocus.current){requestAnimationFrame(()=>cardLink.current?.focus({preventScroll:true}));restoreFocus.current=false;}},[snapshot.detailId,listOpen]);
 const inspector=selected&&!loading&&!error&&!empty&&<section className="m5-card" aria-label="Selected climb">
  {origin&&origin.id!==selected.id&&<a className="m5-origin" href={detailHref(origin.id)} onClick={e=>openLink(e,origin.id)}><ArrowLeft size={12}/>{origin.name}</a>}
  <div className="m2-selected-heading"><div>{selected.locality&&<p className="m5-locality">{selected.locality}</p>}<h1>{selected.name}</h1></div><button aria-label="Clear selected climb" onClick={()=>{commit(clearClimb(latest.current));setHovered(null);requestAnimationFrame(()=>listToggle.current?.focus({preventScroll:true}));}}><X size={17}/></button></div>
  <MapProfileV5 climb={selected}/><Facts climb={selected}/><div className="m2-inspector-bottom"><MapLeaderV7 climb={selected}/><a className="m2-open-climb" ref={cardLink} href={detailHref(selected.id)} onClick={e=>openLink(e,selected.id)}>Open climb<ArrowUpRight size={15}/></a></div><Standing climb={selected} {...{study,viewer}}/>
 </section>;
 return <div className="m2-page m5-page m7-page" data-candidate="map-v7" data-scenario={study.id} data-state={loadState} data-viewer={viewer} data-selected-id={snapshot.selectedId??''} data-origin-id={snapshot.originId??''} data-list-open={listOpen} data-has-inspector={hasInspector} onKeyDown={e=>{
  if(e.key!=='Escape'||detail||e.defaultPrevented)return;
  if(filtersOpen){e.preventDefault();closeFilters();return;}
  if(e.target instanceof HTMLSelectElement)return;
  if(e.target instanceof HTMLInputElement&&snapshot.query){e.preventDefault();applySearch(filters,'');return;}
  e.preventDefault();if(listOpen)closeList();else{commit(clearClimb(latest.current));setHovered(null);requestAnimationFrame(()=>listToggle.current?.focus({preventScroll:true}));}
 }}>
  <header className="m2-shell"><a href="/?surface=feed&variant=feed-v9&scenario=mixed" target="_top" className="m2-brand">Boulder Roller</a><nav aria-label="Portal"><a href="/?surface=feed&variant=feed-v9&scenario=mixed" target="_top">Feed</a><a href={detailHref(null)} aria-current={!detail?'page':undefined} onClick={e=>{e.preventDefault();if(detail)returnMap();}}>Map</a></nav><Identity {...{study,viewer}}/></header>
  <main className="m5-browse" hidden={!!detail}>
   <div className="m5-ground"><MapCanvas study={study} originId={snapshot.originId} climbs={mapClimbs} selectedId={selected?.id??null} hoveredId={hovered} camera={snapshot.camera} active={active&&!detail} forceFailure={loadState==='map-error'} focus={focus} listOpen={listOpen} cameraControl={cameraControl} onCamera={(camera,bounds)=>{const current=latest.current;commit({...current,camera,area:current.area??bounds});setPendingArea(current.area&&bounds.some((v,i)=>Math.abs(v-current.area![i])>.0005)?bounds:null);}} onRetry={onRecover} onSelect={id=>choose(id)} onHover={setHovered} onClear={()=>{commit(clearClimb(latest.current));setHovered(null);}}/>
    {pendingArea&&<button className="m2-search-area" onClick={()=>{set({area:pendingArea,scrollTop:0});setPendingArea(null);}}>Search this area</button>}
   </div>
   <div className="m5-search-bar"><label><Search size={16}/><input type="search" aria-label="Search climbs" placeholder="Search climbs" value={snapshot.query} onFocus={()=>{setFiltersOpen(false);set({sheetExpanded:true});}} onChange={e=>applySearch(filters,e.target.value)}/></label><button ref={filtersButton} className="m5-filter-toggle" aria-label="Filter climbs" aria-expanded={filtersOpen} aria-controls="m5-filters" data-active={filterCount>0} onClick={()=>{if(filtersOpen)closeFilters();else{setFiltersOpen(true);set({sheetExpanded:false});}}}><SlidersHorizontal size={16}/><span>Filters{filterCount>0?` · ${filterCount}`:''}</span></button><button ref={listToggle} aria-label={listOpen?'Hide climb list':'Show climb list'} aria-expanded={listOpen} aria-controls="m5-climb-list" onClick={()=>listOpen?closeList():set({sheetExpanded:true})}>{listOpen?<X size={15}/>:<List size={16}/>}<span>List</span></button></div>
   {filtersOpen&&<section ref={filtersPanel} className="m5-filters" id="m5-filters" aria-label="Climb filters">
    <div className="m5-filter-heading"><h2>Filters</h2><button aria-label="Close filters" onClick={closeFilters}><X size={16}/></button></div>
    {(Object.keys(FILTER_OPTIONS) as (keyof MapFilters)[]).map((key,i)=><label key={key}><span>{key==='distance'?'Distance':key==='grade'?'Average grade':'Elevation rise'}</span><select ref={i===0?firstFilter:undefined} aria-label={key==='distance'?'Filter distance':key==='grade'?'Filter average grade':'Filter elevation rise'} value={filters[key]} onChange={e=>applySearch({...filters,[key]:e.target.value})}>{FILTER_OPTIONS[key].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>)}
    <div className="m5-filter-footer"><button disabled={!filterCount} onClick={()=>applySearch(EMPTY_FILTERS)}>Reset filters</button><button onClick={closeFilters}>Done</button></div>
   </section>}
   {!loading&&!empty&&!error&&!filtersOpen&&!listOpen&&rows.length===0&&(filterCount>0||snapshot.query)&&<div className="m5-no-matches" role="status"><span>No climbs match</span><button onClick={()=>{applySearch(EMPTY_FILTERS,'');}}>Reset search and filters</button></div>}
   <aside className="m5-dock" data-open={listOpen} aria-label="Browse climbs" hidden={!listOpen&&!inspector&&!snapshot.missingOriginId}>
   {hasInspector&&<button ref={phoneToggle} className="m5-phone-list" aria-label={listOpen?'Hide climb list':'Show climb list'} aria-expanded={listOpen} aria-controls="m5-climb-list" onClick={()=>set({sheetExpanded:!listOpen})}>{listOpen?<ChevronDown size={16}/>:<ChevronUp size={16}/>}<span>Climbs</span></button>}
    {snapshot.missingOriginId&&<div className="m2-missing-origin" role="alert"><span>The starting climb is not in this supplied map.</span><button onClick={()=>set({missingOriginId:undefined})}>Browse supplied climbs</button></div>}
    <div className="m5-list" id="m5-climb-list" hidden={!listOpen}>
     <div className="m2-results-head"><div><h2>Climbs</h2><span aria-live="polite">{!loading&&!error?(empty?0:rows.length):''}</span></div><label className="m2-sort"><span className="sr-only">Sort climbs</span><select aria-label="Sort climbs" value={snapshot.sort} onChange={e=>set({sort:e.target.value as MapState['sort'],scrollTop:0})}><option value="name">Name</option><option value="rise">Elevation rise</option><option value="grade">Grade</option><option value="distance">Distance</option></select></label></div>
     <div className="m2-results" ref={list} aria-busy={loading} onScroll={e=>set({scrollTop:e.currentTarget.scrollTop})}>
      {loading?<div className="m2-loading" role="status"><span className="sr-only">Loading climbs</span>{Array.from({length:6},(_,i)=><div key={i}><i/><span/><b/></div>)}</div>:error?<div className="m2-state" role="alert"><h3>Could not load climbs</h3><button onClick={onRecover}><RotateCcw size={14}/>Try again</button></div>:empty||!rows.length?<div className="m2-state" role="status"><h3>{filterCount||snapshot.query?'No climbs match':'No climbs in this area'}</h3>{filterCount||snapshot.query?<button onClick={()=>applySearch(EMPTY_FILTERS,'')}>Reset search and filters</button>:study.climbs.length>0?<button onClick={()=>{set({area:surroundingBounds({...study,originId:undefined}),scrollTop:0});onRecover();}}>Browse supplied climbs</button>:null}</div>:<ol>{rows.map(c=><li key={c.id}><button className="m2-row" data-climb-id={c.id} aria-label={`Select ${c.name}`} aria-pressed={selected?.id===c.id} onClick={e=>choose(c.id,e.detail===0)} onMouseEnter={()=>setHovered(c.id)} onMouseLeave={()=>setHovered(null)} onFocus={()=>setHovered(c.id)} onBlur={()=>setHovered(null)}><MapRowContentsV7 climb={c}/></button></li>)}</ol>}
     </div>
     <div className="m2-index-credit">{study.publishedAt&&<span>Climb data · {new Date(study.publishedAt).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})}</span>}{study.sourceUrl&&<a href={study.sourceUrl} target="_blank" rel="noreferrer" aria-label="Climb data and sources"><ArrowUpRight size={12}/></a>}</div>
    </div>
    {inspector}
   </aside>

  </main>
  {detail&&<MapClimbDetail key={detail.id} climb={detail} {...{study,viewer}} onReturn={returnMap} returnHref={detailHref(null)}/>}
 </div>;
}
