import {useEffect,useRef,useState} from 'react';
import {ProfileV4} from './ProfileV4';
import {initialV4State,parseProfileV4,profileV4Study,resolveV4Study,restoreV4State,v4Key,type ProfileV4Study,type V4State,type V4Viewer,type V4Availability} from './profileV4Model';

export type ProfileV4Settings={study:ProfileV4Study;state:V4State;viewer:V4Viewer;availability:V4Availability;active:boolean;loadError:boolean};
export function initialV4Settings():ProfileV4Settings{
 const p=new URLSearchParams(location.search),viewer:V4Viewer=p.get('viewer')==='visitor'?'visitor':'owner';let study:ProfileV4Study,loadError=false;
 const v4=p.get('variant')==='profile-v4'||p.has('profile-v4-preview');
 try{study=resolveV4Study(v4?(p.get('scenario')??'rider'):(sessionStorage.getItem('br-profile-v4:last-scenario')??'rider'));}catch{study=profileV4Study();loadError=true;}
 let saved:Partial<V4State>={};try{saved=JSON.parse(sessionStorage.getItem(`${v4Key(study.id)}:${viewer}:state`)??'null')??{};}catch{}
 const state=restoreV4State(study,viewer,{...saved,...(v4?history.state?.profileV4:{}),tab:(v4?p.get('tab'):null)??saved.tab,detailId:v4?p.get('detail'):null} as Partial<V4State>);
 return {study,state,viewer,availability:loadError?'error':v4&&['loading','error','offline'].includes(p.get('state')??'')?p.get('state') as V4Availability:'ready',active:true,loadError};
}
export function ProfileV4Preview(){
 const standalone=window===window.parent,[settings,setSettings]=useState(initialV4Settings),[ready,setReady]=useState(standalone),latest=useRef(settings),signature=useRef('');latest.current=settings;
 const change=(state:V4State,push=false)=>{const current=latest.current,stateSafe=restoreV4State(current.study,current.viewer,state);if(standalone){setSettings({...current,state:stateSafe});const u=new URL(location.href);u.searchParams.set('tab',stateSafe.tab);stateSafe.detailId?u.searchParams.set('detail',stateSafe.detailId):u.searchParams.delete('detail');history[push?'pushState':'replaceState']({profileV4:stateSafe},'',u);sessionStorage.setItem(`${v4Key(current.study.id)}:${current.viewer}:state`,JSON.stringify(stateSafe));}else window.parent.postMessage({type:'profile-v4-state',studyId:current.study.id,viewer:current.viewer,state:stateSafe,push},location.origin);};
 const changeStudy=(raw:ProfileV4Study)=>{try{const study=parseProfileV4(raw);if(standalone){sessionStorage.setItem(v4Key(study.id),JSON.stringify(study));setSettings({...latest.current,study});}else window.parent.postMessage({type:'profile-v4-study',study},location.origin);}catch{setSettings(s=>({...s,availability:'error'}));}};
 useEffect(()=>{document.title='Profile V4 preview · Boulder Roller';const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==window.parent||e.data?.type!=='profile-v4-data')return;try{const next=e.data.settings as ProfileV4Settings,key=JSON.stringify(next.study),study=signature.current===key?latest.current.study:parseProfileV4(next.study);signature.current=key;setSettings({...next,study,state:restoreV4State(study,next.viewer,next.state)});setReady(true);}catch{setSettings(s=>({...s,availability:'error'}));setReady(true);}};const pop=()=>{if(standalone)setSettings(initialV4Settings());};window.addEventListener('message',receive);window.addEventListener('popstate',pop);window.parent.postMessage({type:'profile-v4-ready'},location.origin);return()=>{window.removeEventListener('message',receive);window.removeEventListener('popstate',pop);};},[]);
 if(!ready)return <div className="p4-page"/>;
 return <ProfileV4 {...settings} onChange={change} onStudy={changeStudy} onNavigate={href=>standalone?location.assign(href):window.parent.postMessage({type:'profile-v4-navigate',href},location.origin)} onRecover={()=>{if(standalone){if(!settings.loadError)setSettings(s=>({...s,availability:'ready'}));}else window.parent.postMessage({type:'profile-v4-recover'},location.origin);}}/>;
}
