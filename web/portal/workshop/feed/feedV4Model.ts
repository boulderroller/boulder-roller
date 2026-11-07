import {climbResult} from '../scenario';
import {v12LayoutScenarios} from '../v12LayoutScenarios';
import {feedScenarios,feedById,feedRide,mixedFeed,type FeedEntry,type FeedScenario} from './feedModel';
import {parseFeedV3,withV3Example,type Discovery,type FeedV3Scenario,type FeedV3World} from './feedV3Model';
import portRoyal from '../data/port-royal-discovery.json';

export type DiscoveryV4=Discovery & {locality?:string;geometry?:{type:'LineString';coordinates:[number,number][]}};
export type FeedV4Scenario=FeedV3Scenario & {workshopV3?:NonNullable<FeedV3Scenario['workshopV3']>&{world?:FeedV3World&{discovery?:DiscoveryV4}}};
const examples=new WeakMap<FeedScenario,FeedV4Scenario>();
export function withV4Example(source:FeedScenario):FeedV4Scenario{
 if(!feedScenarios.includes(source))return source;
 const cached=examples.get(source);if(cached)return cached;
 const base=withV3Example(source),context=base.workshopV3!,world=context.world!;
 const next:FeedV4Scenario={...base,workshopV3:{...context,
  source:context.source+' V4 adds retained Port Royal route geometry and an explicit Philadelphia locality, supported by the Philadelphia canon export. Elevation is the canonical net rise.',
  world:{...world,discovery:{...world.discovery!,locality:'Philadelphia, Pennsylvania',geometry:{type:'LineString',coordinates:portRoyal.geometry.coordinates.map(p=>[p[0],p[1]])}}}}};
 examples.set(source,next);return next;
}
export function parseFeedV4(value:unknown):FeedV4Scenario{
 const feed=parseFeedV3(value) as FeedV4Scenario,d=feed.workshopV3?.world?.discovery;
 if(!d)return feed;
 if(d.locality!==undefined&&(typeof d.locality!=='string'||!d.locality.trim()||d.locality.length>120))throw Error('Discovery locality must be 1–120 characters.');
 if(d.geometry!==undefined){
  const g=d.geometry;
  if(!g||g.type!=='LineString'||!Array.isArray(g.coordinates)||g.coordinates.length<2||g.coordinates.length>10000||!g.coordinates.every(p=>Array.isArray(p)&&p.length===2&&Number.isFinite(p[0])&&Math.abs(p[0])<=180&&Number.isFinite(p[1])&&Math.abs(p[1])<=85))throw Error('Invalid discovery route coordinates.');
  if(!g.coordinates.some(p=>p[0]!==g.coordinates[0][0]||p[1]!==g.coordinates[0][1]))throw Error('Discovery route needs distinct coordinates.');
 }
 return feed;
}
export function discoveryGrade(d:Discovery){return d.profile[0].d===0&&d.profile.at(-1)!.d===d.length?(d.profile.at(-1)!.elevation-d.profile[0].elevation)/d.length*100:null;}
export function achievementCollection(entry:FeedEntry){
 const all=entry.ride.climbs.map(climb=>({climb,result:climbResult(entry.ride,climb)}));
 const bests=all.filter(r=>(r.result.improvement??0)>0),ordinary=all.filter(r=>(r.result.improvement??0)<=0);
 return {bests,results:[...bests,...ordinary],visible:bests.length?bests.slice(0,2):ordinary.slice(0,1)};
}
export type FeedAchievement=ReturnType<typeof achievementCollection>['results'][number];
function bestsStudy(count:3|10):FeedV4Scenario{
 const source=structuredClone(withV4Example(mixedFeed));
 source.id=`achievements-${count}`;source.label=count===3?'3 new bests · example history':'10 new bests · layout study';
 source.source+=' Explicit achievement study: prior times are illustrative.';
 const entry=source.entries[0],base=count===10?v12LayoutScenarios[0]:entry.ride;
 entry.ride={...base,id:`feed-v4-bests-${count}`,source:{...base.source,history:'illustrative',description:count===10?'Ten illustrative climb windows and prior times on the retained recording. Measurements and GPS are unchanged; these are not additional detected climbs or canonical Vault matches.':'Retained recording with illustrative previous times for three personal bests.'},ride:{...base.ride,rider:{displayName:source.viewer,source:'illustrative'}},climbs:base.climbs.map((c,i)=>({...c,history:[{date:'2016-08-21T12:00:00-04:00',duration:climbResult(base,c).duration+5+i*3}]}))};
 if(count===10){source.workshopV2!.rideEconomics=[];source.workshopV3!.personal!.standings=[];}
 else source.workshopV2!.rideEconomics=source.workshopV2!.rideEconomics.map(e=>({...e,rideId:entry.ride.id}));
 return parseFeedV4(source);
}
export const feedV4Scenarios=[bestsStudy(3),bestsStudy(10)];
export const feedV4ById=(id:string|null)=>feedV4Scenarios.find(s=>s.id===id)??feedById(id);
export const feedV4Ride=(id:string|null)=>feedV4Scenarios.flatMap(s=>s.entries).find(e=>e.ride.id===id)?.ride??feedRide(id);
