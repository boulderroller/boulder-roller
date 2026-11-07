import {useEffect,useRef,useState} from 'react';
import {ArrowLeft} from 'lucide-react';
import {ProfileV3} from './ProfileV3';
import {profileStudy,parseProfileStudy,resolveProfileStudy,restoreProfileState,initialProfileState,allowedTab,profileV3Key,type ProfileStudy,type ProfileState,type Viewer,type Availability} from './profileV3Model';
export type ProfileSettings={study:ProfileStudy;state:ProfileState;viewer:Viewer;availability:Availability;active:boolean};
export function initialSettings():ProfileSettings{
 const p=new URLSearchParams(location.search),viewer:Viewer=p.get('viewer')==='visitor'?'visitor':'owner';let study:ProfileStudy,missing=false;
 try{const id=p.get('scenario')??'recorded';study=resolveProfileStudy(id,sessionStorage.getItem(profileV3Key(id)));}catch{study=profileStudy('empty');missing=true;}
 let saved:ProfileState|undefined;try{saved=JSON.parse(sessionStorage.getItem(`${profileV3Key(study.id)}:${viewer}:state`)??'null')??undefined;}catch{}
 const state=restoreProfileState(study,viewer,{...initialProfileState(viewer,p.get('tab')),...saved,...history.state?.profileV3,tab:allowedTab(p.get('tab')??saved?.tab??null,viewer),detail:p.get('detail')});
 return {study,state,viewer,availability:missing?'error':['loading','error','offline'].includes(p.get('state')??'')?p.get('state') as Availability:'ready',active:true};
}
function RideBridge({settings,onReturn}:{settings:ProfileSettings;onReturn:()=>void}){
 const frame=useRef<HTMLIFrameElement>(null),recording=settings.study.recording;
 const send=()=>{if(recording)frame.current?.contentWindow?.postMessage({type:'profile-v3-recording',recording},location.origin);};
 useEffect(()=>{const receive=(e:MessageEvent)=>{if(e.origin===location.origin&&e.source===frame.current?.contentWindow&&e.data?.type==='profile-v3-ride-ready')send();};window.addEventListener('message',receive);return()=>window.removeEventListener('message',receive);},[recording]);
 const effort=settings.state.detail!=='ride'?settings.state.detail:null;
 return <div className="p3-ride-bridge"><header><button onClick={onReturn}><ArrowLeft size={15}/>Back to profile</button><span>{recording?.ride.title}</span></header><iframe ref={frame} title="Recorded ride detail" src={`/?profile-v3-ride=1&variant=candidate-v13&view=${effort?'analysis':'overview'}${effort?'&climb='+encodeURIComponent(effort):''}`}/></div>;
}
export function ProfileV3Preview(){
 const standalone=window===window.parent,[settings,setSettings]=useState(initialSettings),[ready,setReady]=useState(standalone),latest=useRef(settings),signature=useRef('');latest.current=settings;
 const change=(state:ProfileState,push=false)=>{const current=latest.current;if(standalone){setSettings({...current,state});const u=new URL(location.href);u.searchParams.set('tab',state.tab);state.detail?u.searchParams.set('detail',state.detail):u.searchParams.delete('detail');history[push?'pushState':'replaceState']({profileV3:state,profileDetail:!!state.detail},'',u);sessionStorage.setItem(`${profileV3Key(current.study.id)}:${current.viewer}:state`,JSON.stringify(state));}else window.parent.postMessage({type:'profile-v3-state',studyId:current.study.id,viewer:current.viewer,state,push},location.origin);};
 const back=()=>{if(standalone){change({...latest.current.state,detail:null});}else window.parent.postMessage({type:'profile-v3-back'},location.origin);};
 useEffect(()=>{const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==window.parent||e.data?.type!=='profile-v3-data')return;try{const next=e.data.settings as ProfileSettings;const key=JSON.stringify(next.study),study=signature.current===key?latest.current.study:parseProfileStudy(next.study);signature.current=key;setSettings({...next,study,state:restoreProfileState(study,next.viewer,next.state)});setReady(true);}catch{setSettings(s=>({...s,availability:'error'}));setReady(true);}};const pop=()=>{if(standalone)setSettings(initialSettings());};window.addEventListener('message',receive);window.addEventListener('popstate',pop);window.parent.postMessage({type:'profile-v3-ready'},location.origin);return()=>{window.removeEventListener('message',receive);window.removeEventListener('popstate',pop);};},[]);
 if(!ready)return <div className="p3-page"/>;
 const navigate=(href:string)=>standalone?location.assign(href):window.parent.postMessage({type:'profile-v3-navigate',href},location.origin);
 return <><div hidden={!!settings.state.detail}><ProfileV3 {...settings} onChange={change} onNavigate={navigate} onRecover={()=>standalone?setSettings(s=>({...s,availability:'ready'})):window.parent.postMessage({type:'profile-v3-recover'},location.origin)}/></div>{settings.state.detail&&settings.study.recording&&<RideBridge settings={settings} onReturn={back}/>}</>;
}
