import {useEffect,useRef,useState} from 'react';
import {MapV2} from './MapV2';
import {MapV3} from './v3/MapV3';
import {MapV4} from './v4/MapV4';
import {MapV5} from './v5/MapV5';
import {MapV6} from './v6/MapV6';
import {MapV7} from './v7/MapV7';
import {parseMapV6Study} from './v6/mapV6Leaderboard';
import {restoreCandidateState,stateFromCandidateQuery as stateFromQuery,candidateHref,readCandidate,readCandidateSnapshot,saveCandidateSnapshot,type MapCandidate} from './v7/mapV7Model';
import {parseMapStudy,type MapStudy,type MapViewer,type MapState,type MapLoadState} from './mapModel';
import {mapStudyById,wisesStudy,mapStudies} from './mapScenarios';
import {readViewer} from './mapNavigation';
export type MapSettings={study:MapStudy;viewer:MapViewer;loadState:MapLoadState;variant:MapCandidate;active:boolean;snapshot:MapState;revision:number};
export function MapPreview(){
 const p=new URLSearchParams(location.search),found=mapStudyById(p.get('scenario')),missingId=p.get('scenario')&&!found?p.get('scenario'):null,s=found??(missingId?mapStudies.find(s=>s.id==='no-climbs')!:wisesStudy);
 const firstVariant=readCandidate(p.get('variant'));
 const [ready,setReady]=useState(window===window.parent),[settings,setSettings]=useState<MapSettings>(()=>({study:s,viewer:readViewer(p.get('viewer')),loadState:['loading','empty','error','map-error'].includes(p.get('state')??'')?p.get('state') as MapLoadState:'ready',variant:firstVariant,active:true,snapshot:stateFromQuery(s,p,readCandidateSnapshot(s.id,firstVariant)),revision:0}));
 const latest=useRef(settings);latest.current=settings;
 useEffect(()=>{document.title='Map preview · Boulder Roller';const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==window.parent||e.data?.type!=='map-settings')return;try{const next=e.data.settings as MapSettings,study=(next.variant==='map-v7'||next.variant==='map-v6'?parseMapV6Study:parseMapStudy)(next.study);setSettings({...next,study,snapshot:restoreCandidateState(study,next.snapshot,next.variant)});setReady(true);}catch{setSettings(s=>({...s,variant:readCandidate(e.data.settings?.variant),loadState:'error'}));setReady(true);}};const pop=()=>{if(window!==window.parent)return;const p=new URLSearchParams(location.search);const study=mapStudyById(p.get('scenario'))??latest.current.study,variant=readCandidate(p.get('variant'));setSettings(s=>({...s,study,variant,snapshot:stateFromQuery(study,p,history.state?.mapVariant===variant?history.state.map:readCandidateSnapshot(study.id,variant))}));};window.addEventListener('message',receive);window.addEventListener('popstate',pop);window.parent.postMessage({type:'map-ready'},location.origin);return()=>{window.removeEventListener('message',receive);window.removeEventListener('popstate',pop);};},[]);
 const update=(snapshot:MapState,push=false)=>{const current=latest.current;if(settings.variant!==current.variant||settings.revision!==current.revision||snapshot.studyId!==current.study.id)return;latest.current={...current,snapshot};setSettings(latest.current);saveCandidateSnapshot(snapshot,current.variant);
  if(window===window.parent){const url=new URL(candidateHref(current.study,current.viewer,snapshot.detailId,snapshot.originId??snapshot.missingOriginId,current.variant),location.origin);url.searchParams.set('map-preview','1');if(current.loadState!=='ready')url.searchParams.set('state',current.loadState);history[push?'pushState':'replaceState']({map:snapshot,mapVariant:current.variant},'',url);}else window.parent.postMessage({type:'map-state',snapshot,push,variant:current.variant,revision:current.revision},location.origin);
 };
 if(window===window.parent&&missingId)return <div className="m2-page"><div className="map-missing"><h1>Map scenario unavailable</h1><p>The imported scenario is no longer available in this session.</p><a href={"/?surface=map&variant="+settings.variant+"&scenario="+encodeURIComponent(missingId)}>Import again</a></div></div>;
 if(!ready)return <div className="m2-page"/>;
 const Candidate=settings.variant==='map-v7'?MapV7:settings.variant==='map-v6'?MapV6:settings.variant==='map-v5'?MapV5:settings.variant==='map-v4'?MapV4:settings.variant==='map-v3'?MapV3:MapV2;
 return <Candidate key={`${settings.variant}:${settings.study.id}`} {...settings} onChange={update} onRecover={()=>window===window.parent?setSettings(s=>({...s,loadState:'ready'})):window.parent.postMessage({type:'map-recover'},location.origin)} detailHref={id=>{const href=candidateHref(settings.study,settings.viewer,id,settings.snapshot.originId??settings.snapshot.missingOriginId,settings.variant);return window===window.parent?href+'&map-preview=1':href;}}/>;
}
