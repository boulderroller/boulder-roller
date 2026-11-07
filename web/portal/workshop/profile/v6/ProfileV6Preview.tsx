import {useEffect,useRef,useState} from 'react';
import {ProfileV6} from './ProfileV6';
import {studyForV6Viewer,initialV6State,parseProfileV6,profileV6Study,resolveV6Study,restoreV6State,v6Key,type ProfileV6Study,type V6State,type V6Viewer,type V6Availability} from './profileV6Model';

export type ProfileV6Settings={study:ProfileV6Study;state:V6State;viewer:V6Viewer;availability:V6Availability;active:boolean;loadError:boolean};
export function initialV6Settings():ProfileV6Settings{
 const p=new URLSearchParams(location.search),viewer:V6Viewer=p.get('viewer')==='visitor'?'visitor':'owner';let study:ProfileV6Study,loadError=false;
 const v6=p.get('variant')==='profile-v6'||p.has('profile-v6-preview');
 try{study=resolveV6Study(v6?(p.get('scenario')??'rider'):(sessionStorage.getItem('br-profile-v6:last-scenario')??'rider'));}catch{study=profileV6Study();loadError=true;}
 let saved:Partial<V6State>={};try{saved=JSON.parse(sessionStorage.getItem(`${v6Key(study.id)}:${viewer}:state`)??'null')??{};}catch{}
 const state=restoreV6State(study,viewer,{...saved,...(v6?history.state?.profileV6:{}),tab:(v6?p.get('tab'):null)??saved.tab,detailId:v6?p.get('detail'):null} as Partial<V6State>);
 return {study,state,viewer,availability:loadError?'error':v6&&['loading','error','offline'].includes(p.get('state')??'')?p.get('state') as V6Availability:'ready',active:true,loadError};
}
const initialPreviewSettings=()=>{const settings=initialV6Settings();return {...settings,study:studyForV6Viewer(settings.study,settings.viewer)};};
export function ProfileV6Preview(){
 const standalone=window===window.parent,[settings,setSettings]=useState(initialPreviewSettings),[ready,setReady]=useState(standalone),latest=useRef(settings),signature=useRef('');latest.current=settings;
 const change=(state:V6State,push=false)=>{const current=latest.current,stateSafe=restoreV6State(current.study,current.viewer,state);if(standalone){setSettings({...current,state:stateSafe});const u=new URL(location.href);u.searchParams.set('tab',stateSafe.tab);stateSafe.detailId?u.searchParams.set('detail',stateSafe.detailId):u.searchParams.delete('detail');history[push?'pushState':'replaceState']({profileV6:stateSafe},'',u);sessionStorage.setItem(`${v6Key(current.study.id)}:${current.viewer}:state`,JSON.stringify(stateSafe));}else window.parent.postMessage({type:'profile-v6-state',studyId:current.study.id,viewer:current.viewer,state:stateSafe,push},location.origin);};
 const changeStudy=(raw:ProfileV6Study)=>{if(latest.current.viewer!=='owner')return false;try{const study=parseProfileV6(raw);sessionStorage.setItem(v6Key(study.id),JSON.stringify(study));if(standalone){setSettings({...latest.current,study});}else window.parent.postMessage({type:'profile-v6-study',study},location.origin);return true;}catch{return false;}};
 useEffect(()=>{document.title='Profile V6 preview · Boulder Roller';const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==window.parent||e.data?.type!=='profile-v6-data')return;try{const next=e.data.settings as ProfileV6Settings,key=JSON.stringify(next.study),study=signature.current===key?latest.current.study:parseProfileV6(next.study);signature.current=key;setSettings({...next,study,state:restoreV6State(study,next.viewer,next.state)});setReady(true);}catch{setSettings(s=>({...s,availability:'error'}));setReady(true);}};const pop=()=>{if(standalone)setSettings(initialPreviewSettings());};window.addEventListener('message',receive);window.addEventListener('popstate',pop);window.parent.postMessage({type:'profile-v6-ready'},location.origin);return()=>{window.removeEventListener('message',receive);window.removeEventListener('popstate',pop);};},[]);
 if(!ready)return <div className="p6-page"/>;
 return <ProfileV6 {...settings} onChange={change} onStudy={changeStudy} onNavigate={href=>standalone?location.assign(href):window.parent.postMessage({type:'profile-v6-navigate',href},location.origin)} onRecover={()=>{if(standalone){if(!settings.loadError)setSettings(s=>({...s,availability:'ready'}));}else window.parent.postMessage({type:'profile-v6-recover'},location.origin);}}/>;
}
