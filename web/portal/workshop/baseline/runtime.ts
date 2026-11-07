import {baselineScenario,baselineStorageKey,parseBaselineImport,responseKey,withBaselineRoute,type BaselineScenario} from './model';
import {responseFor,type RouteFixtureOptions} from './fixtures/portal';
import publicFixtures from './fixtures/public.json';
import collectionFixture from './fixtures/collection.json';
import uploadFixture from './fixtures/upload.json';

export let selected:BaselineScenario;
export const requests:{path:string;method:string;status:number}[]=[];
export const servedResponses:Record<string,unknown>={};
const copy=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
const json=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}});
const unavailable=(message='Supplied response unavailable')=>json({detail:message},503);
let readAll=false,stale=false,released=false;
const held=new Set<()=>void>();
const hold=(resume:()=>Response|Promise<Response>)=>new Promise<Response>(resolve=>held.add(()=>resolve(resume())));
const readIds=new Set<string>();
const localEdits:Record<string,unknown>={};
export function selectFixture(s:BaselineScenario){selected=s;readAll=false;stale=false;released=false;held.clear();readIds.clear();for(const k of Object.keys(localEdits))delete localEdits[k];}
export const setStale=()=>{stale=true;};
export function releaseData(){released=true;stale=false;const pending=[...held];held.clear();pending.forEach(resume=>resume());}
export function fixtureResponse(url:URL,method:string,body:Record<string,unknown>={}):Response|Promise<Response>{
 const s=selected,p=url.pathname.replace(/^\/api/,'');
 const authentication=/^\/auth\/|^\/(users\/)?me$/.test(p);
 if(s.viewer==='signed-out'&&p.startsWith('/auth/'))return json({authenticated:false,invite_required:true,invite_validated:false,needs_profile_setup:false,user:null});
 if(s.viewer==='public'&&(/^\/(portfolio|analytics|privacy|notifications|wallet|balances)(\/|$)/.test(p)||p.startsWith('/users/me/')))return unavailable('Private data is not supplied to this viewer.');
 if(s.viewer==='signed-out'&&!p.startsWith('/public/previews/')&&!p.startsWith('/auth/')&&!p.startsWith('/compliance/')&&p!=='/status'&&s.room!=='access')return unavailable('Private data is not supplied to this viewer.');
 if(s.id==='loading'&&!released&&!authentication)return hold(()=>fixtureResponse(url,method,body));
 if((s.id==='error'||stale)&&!authentication)return unavailable();
 if(s.id==='privacy-error'&&p.startsWith('/privacy/'))return unavailable('Privacy settings unavailable');
 // These are the exact local edit seams used by e2e/settings.spec.ts. No account request leaves this frame.
 if(['settings','access'].includes(s.room)&&method==='PUT'&&['/users/me','/privacy/settings','/notifications/preferences'].includes(p)){
  const current=responseFor(url,'GET',{darkMode:false}) as Record<string,unknown>;
  const value=p==='/users/me'?{...current,...body}:p==='/notifications/preferences'?body:{...current,...body,profile_visibility:body.is_public===false?'private':'public'};
  localEdits[p]=value;return json(value);
 }
 if(method==='GET'&&Object.hasOwn(localEdits,p))return json(localEdits[p]);
 if(!authentication&&s.responses&&method==='GET'&&Object.hasOwn(s.responses,responseKey(url))&&p!=='/notifications')return json(s.responses[responseKey(url)]);
 if(p.startsWith('/public/previews/')){
  if(s.id==='not-found')return json({detail:'Not available'},404);
  let key=p.replace('/public/previews','').replace(/^\/activities\//,'/rides/').replace(/^\/(athletes|users)\//,'/riders/');
  const data=publicFixtures[key as keyof typeof publicFixtures];return data?json(data):json({detail:'Not available'},404);
 }
 if(p.startsWith('/compliance/deletion-status/')){
  if(method!=='GET')return unavailable('Deletion is not performed in this workshop.');
  if(s.id==='not-found')return json({detail:'Not found'},404);
  // Exact completed specimen from e2e/account-deletion.spec.ts:82–98; queued specimen uses its supplied status.
  return json({contract_version:'account-deletion.v1',request_id:'b55fa9f6-44ae-4ad5-a080-2829af46f954',status:s.id==='queued'?'queued':'completed',requested_at:'2026-08-24T12:00:00Z',updated_at:s.id==='queued'?'2026-08-24T12:00:04Z':'2026-08-24T12:00:03Z',completed_at:s.id==='queued'?null:'2026-08-24T12:00:03Z',blockers:[],failure_code:null,retryable:s.id!=='queued',attempt_count:1});
 }
 if(s.room==='upload'||p==='/sheet-storage'){
  if(p==='/rides/upload/init'){
   if(s.id==='duplicate')return json({detail:{error:'duplicate_file',existing_ride_id:uploadFixture.id}},409);
   if(s.id==='failure')return json({detail:'invalid file parse'},422);
   return json({upload_id:'upload-sheet-1',signed_url:location.origin+'/sheet-storage',expires_in:600});
  }
  if(p==='/sheet-storage')return s.id==='uploading'&&!released?hold(()=>fixtureResponse(url,method,body)):json({Key:'rides/upload-sheet-1.gpx'});
  if(p==='/rides/upload/abort')return json({status:'aborted'});
  if(p==='/rides/upload/complete')return json({ride_id:uploadFixture.id,status:s.id==='processing'?'pending':'completed'});
  if(p===`/rides/${uploadFixture.id}/status`)return json({ride_id:uploadFixture.id,status:'pending',phase1_completed_at:null});
  if(p===`/rides/${uploadFixture.id}`)return json(uploadFixture);
 }
 // Preparations may be inspected, but no signing, submission, deletion or social mutation succeeds.
 if(method!=='GET'&&!(/^\/notifications\/(read-all|[^/]+\/read)$/.test(p))&&!p.endsWith('/prepare')&&p!=='/geocoding/search')return unavailable('This action is isolated in the retained workshop.');
 if(p.includes('/notifications/')&&method!=='GET'){if(p==='/notifications/read-all')readAll=true;else readIds.add(p.split('/')[2]);return json({status:'ok'});}
 const options:RouteFixtureOptions={darkMode:false,withRideLogEmptyStates:s.room==='rides'&&s.id==='library',withRideMedia:true,withTrainingFigures:s.id!=='missing'&&s.id!=='establishing',withThresholdPendingTraining:s.id==='pending',withClimbViewSpecimen:true,withCanonVaultCreationSpecimen:s.id==='create',withExactTokenSpecimen:s.room==='portfolio'};
 if(s.id==='empty'){options.rideListTotal=0;options.profileRideTotal=0;options.withTrainingFigures=false;options.withExactTokenSpecimen=false;}
 let data=responseFor(url,method,options,body) as any;
 if(p==='/status')data={solana_stub:false}; // Supplied normal-shell response in e2e/settings.spec.ts.
 if(s.room==='profile'&&s.id==='private'&&p.startsWith('/users/private')){
  if(p.endsWith('/leaderboard-positions'))return json({detail:'Not found'},404);
  // backend/app/routes/users.py:890–1098 private non-owner projection and its social-contract test.
  const profile=copy(responseFor(new URL('/users/tim/profile',url),method,options)) as any;
  profile.privacy={visibility:'private',can_view:false,is_owner:false,is_follower:false,redact_gps:true,reason:'private_profile'};
  const rider={...profile.rider,display_name:null,avatar_url:null,is_public:false,viewer_relationship:'none'};
  profile.rider=rider;profile.profile={...profile.profile,rider,privacy:profile.privacy,is_public:false,display_name:null,bio:null,avatar_url:null,created_at:null,total_rides:0,total_distance_km:0,total_elevation_m:0,follower_count:0,following_count:0};delete profile.profile.wallet;
  profile.viewer_capabilities={can_view:false,can_follow:false,can_share:false,can_report:true,can_open_scan:false,viewer_relationship:'none'};
  profile.follow_state={is_following:false,is_followed_by:false,is_mutual_follow:false};
  profile.recent_rides={is_public:false,rides:[],count:0,privacy:profile.privacy};profile.leaderboard=null;profile.beetle_cards={is_public:false,cards:[],count:0,privacy:profile.privacy};
  profile.modules=['profile','follow','recent_rides','beetle_cards','leaderboard'].map(id=>({contract_version:'public_profile_module.v1',id,state:id==='follow'?'present':'hidden',title:{profile:'Profile',follow:'Follow state',recent_rides:'Recent rides',beetle_cards:'BeetleCards',leaderboard:'Leaderboard'}[id],reason:id==='follow'?null:'private_profile',...(['recent_rides','beetle_cards','leaderboard'].includes(id)?{count:0}:{})}));
  return json(profile);
 }
 if(s.room==='portfolio'&&p==='/portfolio/snapshot'&&['collection','partial'].includes(s.id)){
  data=copy(collectionFixture);if(s.id==='partial')data.collectionSnapshot.coverage.completeness='partial';
 }
 if(s.room==='portfolio'&&s.id==='empty'&&p==='/portfolio/snapshot'){
  data=copy(collectionFixture);data.portfolio.stakedPositions=[];data.collectionSnapshot.positions=[];data.collectionSnapshot.coverage.observedCount=0;data.collectionSnapshot.coverage.expectedCount=0;data.collectionSnapshot.uncollectedDungBaseUnits='0';
 }
 if(s.id==='establishing'&&['/analytics/fitness','/analytics/training-load'].includes(p)){
  const authority={threshold_state:'establishing',threshold_training_state:null,threshold_version:'establishing'};
  data=p==='/analytics/fitness'?{...authority,ctl:null,atl:null,tsb:null,form:null}:{...authority,daily_loads:[],total_tss:null,avg_daily_tss:null};
 }
 if(p==='/users/me/threshold'&&s.id==='establishing')data={contract_version:'threshold.v1',state:'establishing',current_w:null,established_at:null,last_raised_at:null,pending_monday:null,sealing_in_progress:false};
 if(p==='/notifications'){
  if(s.responses&&Object.hasOwn(s.responses,responseKey(url)))data=copy(s.responses[responseKey(url)]);
  if(s.id==='empty')data={notifications:[],unread_count:0};
  else if(data&&(readAll||s.id==='read'||readIds.size)){const notifications=data.notifications.map((n:any)=>({...n,read:n.read||readAll||s.id==='read'||readIds.has(n.id)}));data={...data,notifications,unread_count:notifications.filter((n:any)=>!n.read).length};}
 }
 if(s.room==='search'&&s.id==='empty'&&p.startsWith('/search'))data=p==='/search/suggestions'?{contract_version:'search.v1',sections:[]}:{contract_version:'search.v1',results:[],has_more:false,query:url.searchParams.get('q')??''};
 if(p==='/search'&&data?.results){const type=url.searchParams.get('type');if(type&&type!=='all')data={...data,results:data.results.filter((r:any)=>r.type===type||r.type+'s'===type)};}
 if(data?.__api_error)return json({detail:data.detail},data.status);
 return data===undefined?unavailable():json(data);
}

export function installBaseline(){
 const p=new URLSearchParams(location.search),room=p.get('room')??'profile',id=p.get('scenario');
 const saved=sessionStorage.getItem(`br-baseline-import:${room}:${id}`);
 selected=withBaselineRoute(saved?parseBaselineImport(JSON.parse(saved),room):baselineScenario(room,id),p.get('route'));
 const routeState=p.get('routeState');if(routeState)selected=parseBaselineImport({...selected,routeState:JSON.parse(routeState)},room);
 const key=baselineStorageKey(selected),session=window.sessionStorage,local=window.localStorage;
 const scoped=(backing:Storage)=>({get length(){return Object.keys(backing).filter(k=>k.startsWith(key+':')).length;},key:(i:number)=>Object.keys(backing).filter(k=>k.startsWith(key+':'))[i]?.slice(key.length+1)??null,getItem:(k:string)=>backing.getItem(key+':'+k),setItem:(k:string,v:string)=>backing.setItem(key+':'+k,String(v)),removeItem:(k:string)=>backing.removeItem(key+':'+k),clear:()=>Object.keys(backing).filter(k=>k.startsWith(key+':')).forEach(k=>backing.removeItem(k))});
 Object.defineProperty(window,'sessionStorage',{value:scoped(session)});Object.defineProperty(window,'localStorage',{value:scoped(local)});
 localStorage.setItem('br_authenticated',selected.viewer==='signed-out'?'false':'true');
 localStorage.setItem('br_setup_reprompt_dismissed','true');localStorage.setItem('boulder-roller-theme-id','hoo-breddin');localStorage.setItem('boulder-roller-dark-mode','false');
 const fetchAsset=window.fetch.bind(window);
 window.fetch=async(input,init)=>{
  const url=new URL(input instanceof Request?input.url:String(input),location.href),method=(init?.method??(input instanceof Request?input.method:'GET')).toUpperCase();
  const api=url.pathname.startsWith('/api/')||url.pathname==='/sheet-storage'||url.hostname.includes('api.boulderroller')||url.hostname==='storage.test';
  if(!api){
   if(method==='GET'&&(url.origin===location.origin||/\.(cartocdn\.com|carto\.com|openstreetmap\.org)$/.test(url.hostname)||url.hostname==='demotiles.maplibre.org'))return fetchAsset(input,init);
   return unavailable('External services are disconnected in the retained workshop.');
  }
  let body={};if(typeof init?.body==='string'){try{body=JSON.parse(init.body);}catch{/* File bodies are never transmitted. */}}
  const pending=fixtureResponse(url,method,body);
  const signal=init?.signal??(input instanceof Request?input.signal:undefined);
  const result=await (signal?Promise.race([pending,new Promise<Response>((_,reject)=>{const abort=()=>reject(new DOMException('Cancelled','AbortError'));if(signal.aborted)abort();else signal.addEventListener('abort',abort,{once:true});})]):pending);
  requests.push({path:url.pathname,method,status:result.status});if(result.ok&&method==='GET')servedResponses[responseKey(url)]=await result.clone().json();return result;
 };
 // No provider socket, beacon or alternate XHR transport may bypass the fixture fetch boundary.
 navigator.sendBeacon=()=>false;
 if(navigator.share)navigator.share=async()=>{throw new DOMException('Sharing is not performed in the retained workshop.','AbortError');};
 Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition:(_success:unknown,error?:(e:unknown)=>void)=>error?.({code:1,message:'Location is not requested in the retained workshop.'}),watchPosition:()=>0,clearWatch:()=>{}}});
 const BlockedSocket=class {constructor(){throw Error('External connections are disabled in the retained workshop.');}};
 window.WebSocket=BlockedSocket as unknown as typeof WebSocket;
 window.XMLHttpRequest=BlockedSocket as unknown as typeof XMLHttpRequest;
 window.open=(href)=>{window.parent.postMessage({type:'baseline-external',href:String(href)},location.origin);return null;};
 return selected;
}
