import React,{Suspense,useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Router,useLocation,createPath,type To} from 'react-router-dom';
import {QueryClientProvider} from '@tanstack/react-query';
import {queryClient} from './src/lib/queryClient';
import {ThemeProvider} from './src/contexts/ThemeContext';
import {AuthProvider} from './src/contexts/AuthContext';
import AuthenticatedApp from './src/AuthenticatedApp';
import InviteGate from './src/components/auth/InviteGate';
import Onboarding from './src/pages/Onboarding';
import SessionRecoveryScreen from './src/components/auth/SessionRecoveryScreen';
import AccountDeletionStatusScreen,{AccountDeletionRecoveryScreen,AccountDeletionCapabilityErrorScreen} from './src/components/account/AccountDeletionStatusScreen';
import ShareModal from './src/components/modals/ShareModal';
import EditActivityModal from './src/components/modals/EditActivityModal';
import DeleteConfirmModal from './src/components/modals/DeleteConfirmModal';
import {RouteLoadingFallback} from './src/components/loading/LoadingSystem';
import {AuthRuntimeProvider} from './auth-runtime';
import {selected,setStale,releaseData,requests,servedResponses} from './runtime';
import {rides} from './fixtures/portal';
import {formatDate,formatDuration,formatDistance} from './src/lib/formatters';
import {routeOwner,withBaselineRoute} from './model';
import {Toaster} from 'sonner';
import './src/index.css';
import './styles';

queryClient.setDefaultOptions({queries:{retry:false,refetchOnWindowFocus:false}});
function announce(type:string,extra:Record<string,unknown>={}){window.parent.postMessage({type,room:selected.room,candidate:selected.candidate,scenario:selected.id,...extra},location.origin);}
function RetainedRouter({children}:{children:React.ReactNode}){
 const make=(to:To,state?:unknown)=>{const href=typeof to==='string'?to:createPath(to),u=new URL(href,location.origin);return {pathname:u.pathname,search:u.search,hash:u.hash,state,key:crypto.randomUUID()};};
 const [current,setCurrent]=useState(()=>make(selected.route,selected.routeState));
 const entries=React.useRef([current]),index=React.useRef(0);
 const navigate=(to:To,state:unknown,replace=false)=>{
  const next=make(to,state),href=createPath(next);
  try{withBaselineRoute(selected,href);}catch{announce('baseline-route',{href,routeState:state,owner:routeOwner(href)});return;}
  if(replace)entries.current[index.current]=next;else{entries.current=entries.current.slice(0,index.current+1);entries.current.push(next);index.current++;}setCurrent(next);
 };
 return <Router location={current} navigator={{createHref:to=>typeof to==='string'?to:createPath(to),push:(to,state)=>navigate(to,state),replace:(to,state)=>navigate(to,state,true),go:delta=>{index.current=Math.max(0,Math.min(entries.current.length-1,index.current+delta));setCurrent(entries.current[index.current]);}}}>{children}</Router>;
}
function Journey(){const location=useLocation();useEffect(()=>{announce('baseline-route',{href:location.pathname+location.search+location.hash,routeState:location.state,owner:routeOwner(location.pathname+location.search)});},[location]);return null;}
function Preview(){
 const [released,setReleased]=useState(false),[closed,setClosed]=useState(false),[checkingRecovery,setCheckingRecovery]=useState(false);
 useEffect(()=>{
  announce('baseline-ready');
  const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==window.parent)return;if(e.data?.type==='baseline-stale'){
   setStale();announce('baseline-availability',{state:'offline'});if(selected.room==='notifications')void queryClient.invalidateQueries();else{Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>false});window.dispatchEvent(new Event('offline'));}
  }if(e.data?.type==='baseline-release'){releaseData();setReleased(true);Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>true});window.dispatchEvent(new Event('online'));if(selected.id==='stale')void queryClient.invalidateQueries();announce('baseline-availability',{state:'ready'});}
  if(e.data?.type==='baseline-inspect')announce('baseline-requests',{requests});if(e.data?.type==='baseline-export')announce('baseline-export',{responses:{...selected.responses,...servedResponses}});};
  window.addEventListener('message',receive);return()=>window.removeEventListener('message',receive);
 },[]);
 if(selected.room==='access'){
  if(selected.id==='onboarding'||selected.id==='first-ride')return <Onboarding initialStep={selected.id==='first-ride'?'first_ride':'identity'} onIdentitySaved={()=>'first_ride'} onComplete={destination=>announce('baseline-route',{href:destination,owner:routeOwner(destination)})}/>;
  if(selected.id==='session')return <SessionRecoveryScreen onReLogin={()=>{}}/>;
  return <InviteGate sessionPending={selected.id==='loading'&&!released} sessionCheckError={selected.id==='error'?'Session unavailable':null}/>;
 }
 if(selected.room==='account-deletion'){
  if(selected.id==='recovery')return <AccountDeletionRecoveryScreen checking={checkingRecovery} onRetry={()=>{setCheckingRecovery(true);setTimeout(()=>setCheckingRecovery(false),600);}} onDiscard={()=>announce('baseline-route',{href:'/',owner:'access'})}/>;
  if(selected.id==='invalid')return <AccountDeletionCapabilityErrorScreen kind="invalid" onDiscard={()=>announce('baseline-route',{href:'/',owner:'access'})}/>;
  return <AccountDeletionStatusScreen capability={{version:2,wallet:'AccountDeletionRider1111111111111111111111',requestId:'b55fa9f6-44ae-4ad5-a080-2829af46f954',statusToken:'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',createdAt:'2026-08-24T12:00:00.000Z'}} onFinish={()=>announce('baseline-route',{href:'/',owner:'access'})} onDiscard={()=>announce('baseline-route',{href:'/',owner:'access'})} onOpenPortfolio={()=>announce('baseline-route',{href:'/profile?tab=portfolio',owner:'portfolio'})}/>;
 }
 if(selected.room==='shell'&&selected.id==='loading'&&!released)return <RouteLoadingFallback/>;
 const ride=rides[0];
 return <><Journey/><AuthenticatedApp publicRoutesOnly={selected.viewer==='signed-out'}/>{selected.room==='shell'&&!closed&&<>
  {selected.id==='share'&&<ShareModal activity={{id:ride.id,title:ride.title,date:formatDate(ride.started_at),distance:ride.distance_m/1000,duration:formatDuration(ride.duration_s),elevation:ride.elevation_m,dungEarned:ride.cal_earned}} onClose={()=>setClosed(true)}/>}
  {selected.id==='edit'&&<EditActivityModal activity={{id:ride.id,title:ride.title,date:formatDate(ride.started_at),distance:ride.distance_m/1000,duration:formatDuration(ride.duration_s),description:'',visibility:'public',commentsEnabled:true,hideFromLeaderboards:false}} onClose={()=>setClosed(true)} onSave={()=>{announce('baseline-action',{message:'Local form reviewed. No ride was changed.'});setClosed(true);}}/>}
  {selected.id==='confirmation'&&<DeleteConfirmModal activity={{id:ride.id,title:ride.title,date:formatDate(ride.started_at),distance:formatDistance(ride.distance_m,'metric'),rewardValue:ride.cal_earned,rewardAsset:'CAL'}} onClose={()=>setClosed(true)} onConfirm={()=>announce('baseline-action',{message:'Deletion was not performed. The retained confirmation remains available.'})}/>}
 </>}</>;
}
createRoot(document.getElementById('root')!).render(<RetainedRouter><QueryClientProvider client={queryClient}><ThemeProvider><AuthRuntimeProvider><AuthProvider><Suspense fallback={<RouteLoadingFallback/>}><Preview/></Suspense><Toaster/></AuthProvider></AuthRuntimeProvider></ThemeProvider></QueryClientProvider></RetainedRouter>);
