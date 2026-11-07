import {useEffect,useRef} from 'react';
import {parseScenario,type Scenario} from '../../scenario';

// Retained Ride V13 owns its parent's URL. This isolated host gives it that
// contract without allowing its navigation to change the Profile workspace.
export function ProfileRideHost(){
 const frame=useRef<HTMLIFrameElement>(null),recording=useRef<Scenario|null>(null);
 const send=()=>{if(recording.current)frame.current?.contentWindow?.postMessage({type:'workshop-settings',settings:{scenario:recording.current,variant:'candidate-v13',bundled:false,rideOwner:false,state:'ready',squint:false,revision:true}},location.origin);};
 useEffect(()=>{const receive=(e:MessageEvent)=>{
  if(e.origin!==location.origin)return;
  if(e.source===window.parent&&e.data?.type==='profile-v3-recording'){try{recording.current=parseScenario(e.data.recording);send();}catch{recording.current=null;}}
  if(e.source===frame.current?.contentWindow&&e.data?.type==='workshop-ready'){send();window.parent.postMessage({type:'profile-v3-ride-ready'},location.origin);}
 };window.addEventListener('message',receive);window.parent.postMessage({type:'profile-v3-ride-ready'},location.origin);return()=>window.removeEventListener('message',receive);},[]);
 return <iframe ref={frame} title="Ride V13 analysis" src="/?preview=1" style={{display:'block',width:'100%',height:'100dvh',border:0}}/>;
}
