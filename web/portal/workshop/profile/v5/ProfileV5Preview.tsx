import {useEffect,useRef,useState} from 'react';
import {ProfileV5} from './ProfileV5';
import {initialV5State,parseProfileV5,profileV5Study,resolveV5Study,restoreV5State,v5Key,type ProfileV5Study,type V5State,type V5Viewer,type V5Availability} from './profileV5Model';

export type ProfileV5Settings={study:ProfileV5Study;state:V5State;viewer:V5Viewer;availability:V5Availability;active:boolean;loadError:boolean};
export function initialV5Settings():ProfileV5Settings{
 const p=new URLSearchParams(location.search),viewer:V5Viewer=p.get('viewer')==='visitor'?'visitor':'owner';let study:ProfileV5Study,loadError=false;
 const v5=p.get('variant')==='profile-v5'||p.has('profile-v5-preview');
 try{study=resolveV5Study(v5?(p.get('scenario')??'rider'):(sessionStorage.getItem('br-profile-v5:last-scenario')??'rider'));}catch{study=profileV5Study();loadError=true;}
 let saved:Partial<V5State>={};try{saved=JSON.parse(sessionStorage.getItem(`${v5Key(study.id)}:${viewer}:state`)??'null')??{};}catch{}
 const state=restoreV5State(study,viewer,{...saved,...(v5?history.state?.profileV5:{}),tab:(v5?p.get('tab'):null)??saved.tab,detailId:v5?p.get('detail'):null} as Partial<V5State>);
 return {study,state,viewer,availability:loadError?'error':v5&&['loading','error','offline'].includes(p.get('state')??'')?p.get('state') as V5Availability:'ready',active:true,loadError};
}
export function ProfileV5Preview(){
 const standalone=window===window.parent,[settings,setSettings]=useState(initialV5Settings),[ready,setReady]=useState(standalone),latest=useRef(settings),signature=useRef('');latest.current=settings;
 const change=(state:V5State,push=false)=>{const current=latest.current,stateSafe=restoreV5State(current.study,current.viewer,state);if(standalone){setSettings({...current,state:stateSafe});const u=new URL(location.href);u.searchParams.set('tab',stateSafe.tab);stateSafe.detailId?u.searchParams.set('detail',stateSafe.detailId):u.searchParams.delete('detail');history[push?'pushState':'replaceState']({profileV5:stateSafe},'',u);sessionStorage.setItem(`${v5Key(current.study.id)}:${current.viewer}:state`,JSON.stringify(stateSafe));}else window.parent.postMessage({type:'profile-v5-state',studyId:current.study.id,viewer:current.viewer,state:stateSafe,push},location.origin);};
 const changeStudy=(raw:ProfileV5Study)=>{try{const study=parseProfileV5(raw);sessionStorage.setItem(v5Key(study.id),JSON.stringify(study));if(standalone){setSettings({...latest.current,study});}else window.parent.postMessage({type:'profile-v5-study',study},location.origin);return true;}catch{return false;}};
 useEffect(()=>{document.title='Profile V5 preview · Boulder Roller';const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==window.parent||e.data?.type!=='profile-v5-data')return;try{const next=e.data.settings as ProfileV5Settings,key=JSON.stringify(next.study),study=signature.current===key?latest.current.study:parseProfileV5(next.study);signature.current=key;setSettings({...next,study,state:restoreV5State(study,next.viewer,next.state)});setReady(true);}catch{setSettings(s=>({...s,availability:'error'}));setReady(true);}};const pop=()=>{if(standalone)setSettings(initialV5Settings());};window.addEventListener('message',receive);window.addEventListener('popstate',pop);window.parent.postMessage({type:'profile-v5-ready'},location.origin);return()=>{window.removeEventListener('message',receive);window.removeEventListener('popstate',pop);};},[]);
 if(!ready)return <div className="p5-page"/>;
 return <ProfileV5 {...settings} onChange={change} onStudy={changeStudy} onNavigate={href=>standalone?location.assign(href):window.parent.postMessage({type:'profile-v5-navigate',href},location.origin)} onRecover={()=>{if(standalone){if(!settings.loadError)setSettings(s=>({...s,availability:'ready'}));}else window.parent.postMessage({type:'profile-v5-recover'},location.origin);}}/>;
}
