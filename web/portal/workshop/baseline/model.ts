export const BASELINE_REVISION='a63ffc77f9638b78d3a404be2575aaa7ddd9c145';
type Choice={id:string;label:string};
const choices=(...items:string[]):Choice[]=>items.map(item=>{const [id,label]=item.split('|');return {id,label:label??id};});
export const baselineRooms=[
 {id:'profile',label:'Rider Profile · Overview',route:'/profile',owner:'Profile',scenarios:choices('owner|Own rider','public|Another public rider','private|Private profile','empty|No riding history','loading|Loading','error|Unavailable','stale|Retained data, offline')},
 {id:'rides',label:'Rides library',route:'/profile?tab=rides',owner:'Profile',scenarios:choices('library|Rides and processing rows','empty|Empty library','loading|Loading','error|Unavailable','stale|Retained data, offline')},
 {id:'training',label:'Training',route:'/profile?tab=training',owner:'Profile',scenarios:choices('figures|Supplied training figures','missing|Missing figures','establishing|Threshold establishing','pending|Threshold pending','loading|Loading','error|Unavailable','stale|Retained data, offline')},
 {id:'portfolio',label:'Portfolio / Balance',route:'/profile?tab=portfolio',owner:'Profile',scenarios:choices('balances|Balances and receipts','collection|Complete collection snapshot','partial|Partial collection snapshot','empty|No positions','loading|Loading','error|Unavailable','stale|Retained data, offline')},
 {id:'settings',label:'Settings',route:'/settings',owner:'Settings',scenarios:choices('identity|Identity','performance|Performance','privacy|Privacy','connections|Connections','alerts|Alerts','establishing|Threshold establishing','pending|Threshold pending','error|Unavailable')},
 {id:'notifications',label:'Notifications',route:'/notifications',owner:'Notifications',scenarios:choices('unread|Supplied unread ledger','read|Read ledger','empty|Empty ledger','loading|Loading','error|Unavailable','stale|Last loaded, refresh unavailable')},
 {id:'upload',label:'Upload ride',route:'/upload',owner:'Upload',scenarios:choices('file|File and privacy selection','privacy-error|Privacy unavailable','uploading|Hold upload','processing|Processing response','complete|Saved response','duplicate|Duplicate file response','failure|Upload failed')},
 {id:'guide',label:'Guide',route:'/docs',owner:'Guide',scenarios:choices('contents|Current contents and links')},
 {id:'search',label:'Global Search',route:'/profile?search=riders',owner:'Shell',scenarios:choices('results|Suggestions and results','empty|No results','error|Search unavailable')},
 {id:'access',label:'Access / onboarding',route:'/',owner:'Access',scenarios:choices('signin|Sign in and invite','session|Session recovery','onboarding|Identity setup','first-ride|First ride','loading|Session checking','error|Session unavailable')},
 {id:'public-ride',label:'Ride · signed-out preview',route:'/rides/preview-ride',owner:'Ride',scenarios:choices('public|Public ride','loading|Loading','error|Unavailable','not-found|Not available')},
 {id:'public-climb',label:'Climb · signed-out preview',route:'/climbs/preview-climb',owner:'Climb',scenarios:choices('public|Public climb','loading|Loading','error|Unavailable','not-found|Not available')},
 {id:'public-rider',label:'Rider · signed-out preview',route:'/athletes/tim',owner:'Profile',scenarios:choices('public|Public rider','private|Private rider','loading|Loading','error|Unavailable','not-found|Not available')},
 {id:'climb-flows',label:'Climb · Vault V1 flows',route:'/climbs/11111111-1111-4111-8111-111111111111',owner:'Climb',scenarios:choices('attached|Attached Vault','rides|Your history','history|DUNG history','deposit|Deposit CAL','withdraw|Withdraw CAL','collect|Collect DUNG','create|Create Vault','loading|Loading','error|Unavailable')},
 {id:'account-deletion',label:'Account deletion',route:'/account-deletion',owner:'Account',scenarios:choices('completed|Retained completed response','queued|Retained queued response','recovery|Recovery unavailable','not-found|Recovery not found','invalid|Invalid capability','loading|Checking status','error|Status unavailable')},
 {id:'shell',label:'Shell / shared overlays',route:'/docs',owner:'Shell',scenarios:choices('navigation|Navigation and account menu','loading|Route loading','not-found|Not found','share|Share ride','edit|Edit ride','confirmation|Delete confirmation')},
 {id:'ride-flows',label:'Ride · retained V1 flows',route:'/rides/ride-1',owner:'Ride',scenarios:choices('ride|Supplied ride and actions','loading|Loading','error|Unavailable')},
 {id:'legacy-analysis',label:'Ride · legacy Analyze',route:'/activities/ride-1/analyze',owner:'Ride',scenarios:choices('recording|Supplied recording','loading|Loading','error|Unavailable')},
] as const;
export type BaselineRoom=typeof baselineRooms[number]['id'];
export type BaselineScenario={version:1;room:BaselineRoom;candidate:string;id:string;label:string;viewer:'owner'|'public'|'signed-out';route:string;source:{kind:'supplied-fixture';revision:string;file:string;capturedAt:string|null};responses?:Record<string,unknown>;routeState?:{returnTo:string}};
export function baselineScenario(room:string,id?:string|null):BaselineScenario{
 const spec=baselineRooms.find(r=>r.id===room);if(!spec)throw Error('Unknown baseline room.');
 const choice=id?spec.scenarios.find(s=>s.id===id):spec.scenarios[0];if(!choice)throw Error('This scenario is not supplied for this room.');
 let route:string=spec.route;
 if(room==='profile'&&['public','private'].includes(choice.id))route='/athletes/'+(choice.id==='private'?'private':'tim');
 if(room==='public-rider'&&choice.id==='private')route='/athletes/private';
 if(room==='settings')route='/settings?tab='+({identity:'profile',establishing:'performance',pending:'performance'}[choice.id]??choice.id);
 if(room==='climb-flows'&&choice.id==='create')route+='/create-vault';
 if(room==='climb-flows'&&['rides','history','deposit','withdraw','collect'].includes(choice.id))route+='?climbView='+choice.id;
 if(room==='shell'&&choice.id==='not-found')route='/unavailable-route';
 const viewer=room.startsWith('public-')||(room==='access'&&!['onboarding','first-ride'].includes(choice.id))||room==='account-deletion'?'signed-out':room==='profile'&&['public','private'].includes(choice.id)?'public':'owner';
 return {version:1,room:spec.id,candidate:`${room}-v1`,id:choice.id,label:choice.label,viewer,route,source:{kind:'supplied-fixture',revision:BASELINE_REVISION,file:room.startsWith('public-')?'e2e/public-previews.spec.ts':room==='account-deletion'?'e2e/account-deletion.spec.ts':room==='portfolio'&&['collection','partial'].includes(choice.id)?'e2e/portfolio-snapshot.spec.ts':'e2e/portal-v2-routes.spec.ts',capturedAt:null}};
}
export function parseBaselineImport(value:unknown,room:string):BaselineScenario{
 if(!value||typeof value!=='object')throw Error('Choose a baseline scenario JSON object.');
 const v=value as BaselineScenario,expected=baselineScenario(room,v.id);
 if(v.version!==1||v.room!==room||v.candidate!==expected.candidate||v.viewer!==expected.viewer)throw Error('The room, V1 candidate and viewer must match the selected scenario.');
 if(v.route!==expected.route)withBaselineRoute(expected,v.route);
 if(v.routeState&&(typeof v.routeState.returnTo!=='string'||!v.routeState.returnTo.startsWith('/')||v.routeState.returnTo.startsWith('//')||!routeOwner(v.routeState.returnTo)))throw Error('Invalid retained return route.');
 if(v.source?.kind!=='supplied-fixture'||typeof v.source.file!=='string'||typeof v.source.revision!=='string')throw Error('Supply fixture provenance; imports are never live evidence.');
 if(v.responses&&(typeof v.responses!=='object'||Array.isArray(v.responses)||Object.keys(v.responses).some(k=>!/^GET \/(?!\/)/.test(k)||k.includes('#'))))throw Error('Response keys must be exact GET paths including query parameters.');
 return v;
}
export const baselineStorageKey=(s:BaselineScenario)=>`br-baseline:${s.room}:${s.candidate}:${s.id}:${s.viewer}`;
export function responseKey(url:URL){const p=new URLSearchParams(url.search);p.sort();const query=p.toString();return `GET ${url.pathname.replace(/^\/api/,'')}${query?'?'+query:''}`;}
export function routeOwner(href:string):BaselineRoom|'ride'|'feed'|'climb'|'map'|null{
 const u=new URL(href,'http://workshop.local'),p=u.pathname;
 if(p==='/profile')return (['rides','training','portfolio'].includes(u.searchParams.get('tab')??'')?u.searchParams.get('tab'):'profile') as BaselineRoom;
 if(/^\/(athletes|rider|riders)\//.test(p))return 'profile';
 if(p==='/my-activities'||p==='/training')return 'rides';if(p==='/data')return 'training';if(p==='/portfolio')return 'portfolio';
 if(p.endsWith('/analyze'))return 'legacy-analysis';if(/^\/(activities|rides|ride)\//.test(p))return 'ride-flows';
 if(/^\/(climbs|climb|segments|vaults)\//.test(p))return 'climb-flows';
 if(['/map','/climbs','/vaults'].includes(p))return 'map';
 if(p==='/docs')return 'guide';if(p==='/account-deletion')return 'account-deletion';
 if(['/settings','/notifications','/upload'].includes(p))return p.slice(1) as BaselineRoom;
 if(p==='/'||p==='/dashboard')return 'feed';return null;
}
export function withBaselineRoute(s:BaselineScenario,href:string|null):BaselineScenario{
 if(!href)return s;if(!href.startsWith('/')||href.startsWith('//'))throw Error('Invalid retained route.');
 const owner=routeOwner(href),u=new URL(href,'http://workshop.local');
 const matching=owner===s.room||(s.room==='public-rider'&&owner==='profile')||(s.room==='public-ride'&&owner==='ride-flows')||(s.room==='public-climb'&&owner==='climb-flows')||href===s.route;
 if(!matching)throw Error('This route belongs to another room.');
 if(s.room==='profile'&&s.viewer!=='owner'&&(!/^\/(athletes|rider|riders)\/(tim|private)$/.test(u.pathname)||['training','portfolio'].includes(u.searchParams.get('tab')??'')))throw Error('Other riders are public only.');
 if(s.room==='profile'&&s.viewer==='owner'&&u.pathname!=='/profile')throw Error('Choose the public rider scenario.');
 return {...s,route:href};
}

export function baselineJourney(s:BaselineScenario,href:string){
 let owner=routeOwner(href);
 if(s.viewer!=='owner'){
  if(owner==='ride-flows')owner='public-ride';
  else if(owner==='climb-flows')owner=href.includes('create-vault')||href.includes('climbView=')?'access':'public-climb';
  else if(owner==='profile')owner=href.startsWith('/profile')?'access':'public-rider';
  else if(['training','portfolio','settings','notifications','upload','legacy-analysis'].includes(owner??''))owner='access';
 }
 return {owner,href:owner==='access'?'/':href};
}
