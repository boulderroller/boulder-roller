import { feedScenarios, type FeedScenario } from './feedModel';
import { parseFeedV2, withV2Example, type FeedV2Scenario, type WorldSummary } from './feedV2Model';
import portRoyal from '../data/port-royal-discovery.json';

export type RidingDay = { date: string; rides: number; distance: number; duration: number; elevation: number };
export type Standing = { entryId: string; climbId: string; rank: number };
export type PersonalRiding = { viewer: string; from: string; through: string; days: RidingDay[]; standings: Standing[] };
export type WorldRegion = { id: string; name: string; lon: number; lat: number; climbsRidden: number };
export type Discovery = { name: string; source: string; length: number; gain: number; profile: {d:number;elevation:number}[] };
export type FeedV3World = WorldSummary & { regions: WorldRegion[]; discovery?: Discovery };
export type FeedV3Scenario = FeedV2Scenario & { workshopV3?: { source: string; personal?: PersonalRiding; world?: FeedV3World } };

const cache = new WeakMap<FeedScenario, FeedV3Scenario>();
export function withV3Example(source: FeedScenario): FeedV3Scenario {
  if (!feedScenarios.includes(source)) return source;
  const cached = cache.get(source); if (cached) return cached;
  const feed = withV2Example(source), own = source.entries.find(e=>e.owned);
  const gains = [0,184,0,421,0,682,365,0,210,176,0,0,811,552,0,364,0,228,0,937,403,0,218,0,346,0,472,1021];
  const days = gains.map((elevation,i) => ({date:`2016-08-${String(i+1).padStart(2,'0')}`, rides:elevation ? 1:0, elevation, distance:elevation ? Math.round((elevation*54+9400)/100)*100:0, duration:elevation ? Math.round(elevation*5.2+1800):0}));
  days[27] = {...days[27],distance:128700,duration:18727};
  const next: FeedV3Scenario = {...feed, workshopV3:{
    source:'Feed V3: a complete illustrative 28-day riding summary, current Top 10 examples, and independent regional activity totals. These are replaceable design inputs, not inferred from the feed. Port Royal Avenue uses retained canonical terrain captured 6 Sep 2026; its public place, activity and economic states are not asserted.',
    ...(own ? {personal:{viewer:source.viewer,from:'2016-08-01',through:'2016-08-28',days,standings:own.ride.climbs.slice(0,2).map((c,i)=>({entryId:own.id,climbId:c.id,rank:i===0?7:4}))}}:{}),
    world:{...feed.workshopV2!.world!,regions:[
      {id:'philadelphia',name:'Philadelphia',lon:-75.1652,lat:39.9526,climbsRidden:612},
      {id:'boulder',name:'Boulder',lon:-105.2705,lat:40.015,climbsRidden:562},
      {id:'nice',name:'Nice',lon:7.262,lat:43.71,climbsRidden:110},
    ],discovery:{name:portRoyal.name,source:portRoyal.source,length:portRoyal.length_m,gain:portRoyal.elev_gain_m,profile:portRoyal.canonical_profile.map(p=>({d:p.dist_m,elevation:p.elev_m}))}},
  }};
  cache.set(source,next); return next;
}

const dayMs=86400000;
const finite=(v:unknown):v is number=>typeof v==='number' && Number.isFinite(v);
const nonnegative=(v:unknown)=>finite(v)&&v>=0;
const dateOnly=(v:unknown):v is string=>typeof v==='string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0,10)===v;
function check(value:unknown,message:string):asserts value { if(!value) throw Error(message); }

export function parseFeedV3(value:unknown):FeedV3Scenario {
  const feed=parseFeedV2(value) as FeedV3Scenario, context=feed.workshopV3;
  if(context===undefined) return feed;
  check(context && typeof context.source==='string' && context.source.trim(),'V3 context needs its source.');
  const p=context.personal;
  if(p!==undefined){
    check(p && p.viewer===feed.viewer && feed.entries.some(e=>e.owned),'Personal history must belong to the viewer.');
    check(dateOnly(p.from)&&dateOnly(p.through)&&p.through>=p.from,'Invalid personal period.');
    const count=(Date.parse(p.through)-Date.parse(p.from))/dayMs+1;
    check(count<=366&&Array.isArray(p.days)&&p.days.length===count,'Personal period needs complete daily history.');
    const sorted=[...p.days].sort((a,b)=>a.date.localeCompare(b.date));
    sorted.forEach((d,i)=>{
      check(dateOnly(d.date)&&d.date===new Date(Date.parse(p.from)+i*dayMs).toISOString().slice(0,10),'Personal period needs complete daily history.');
      check([d.rides,d.distance,d.duration,d.elevation].every(nonnegative)&&Number.isInteger(d.rides),'Invalid daily riding values.');
      check(d.rides>0 || d.distance+d.duration+d.elevation===0,'A day with no rides must have zero riding values.');
    });
    check(Array.isArray(p.standings),'Personal standings must be supplied.');
    const seen=new Set<string>();
    p.standings.forEach(s=>{const e=feed.entries.find(e=>e.id===s.entryId), key=`${s.entryId}:${s.climbId}`;
      check(e?.owned&&e.ride.climbs.some(c=>c.id===s.climbId)&&Number.isInteger(s.rank)&&s.rank>=1&&s.rank<=10&&!seen.has(key),'Invalid personal standing.');seen.add(key);
    });
  }
  const w=context.world;
  if(w!==undefined){
    // Reuse the frozen summary validator while retaining the separate V3 input.
    parseFeedV2({...feed,workshopV2:{source:context.source,world:w,rideEconomics:[]}});
    check(Array.isArray(w.regions)&&w.regions.length<=50,'Invalid world regions.');
    const seen=new Set<string>();
    w.regions.forEach(r=>{check(r&&typeof r.id==='string'&&r.id&&typeof r.name==='string'&&r.name&&finite(r.lon)&&Math.abs(r.lon)<=180&&finite(r.lat)&&Math.abs(r.lat)<=85&&Number.isInteger(r.climbsRidden)&&r.climbsRidden>=0&&!seen.has(r.id),'Invalid world region.');seen.add(r.id);});
    if(w.climbsRidden!==undefined) check(w.regions.reduce((n,r)=>n+r.climbsRidden,0)===w.climbsRidden,'World region counts must match the supplied total.');
    const d=w.discovery;
    if(d!==undefined){check(d&&typeof d.name==='string'&&d.name&&typeof d.source==='string'&&d.source&&finite(d.length)&&d.length>0&&nonnegative(d.gain)&&Array.isArray(d.profile)&&d.profile.length>=2,'Invalid discovery.');
      d.profile.forEach((point,i)=>check(finite(point.d)&&finite(point.elevation)&&point.d>=0&&point.d<=d.length&&(i===0||point.d>d.profile[i-1].d),'Invalid discovery profile.'));
    }
  }
  return feed;
}
export function personalDays(p:PersonalRiding,count:7|28){return [...p.days].sort((a,b)=>a.date.localeCompare(b.date)).filter(d=>Date.parse(d.date)>Date.parse(p.through)-count*dayMs);}
export function ridingSummary(days:RidingDay[]){return days.reduce((s,d)=>({rides:s.rides+d.rides,distance:s.distance+d.distance,duration:s.duration+d.duration,elevation:s.elevation+d.elevation}),{rides:0,distance:0,duration:0,elevation:0});}
export function worldPeriodLabel(from:string,end:string){
  const options={timeZone:'America/New_York'};
  const first=new Date(from),last=new Date(Date.parse(end)-1);
  const month=(d:Date)=>d.toLocaleDateString('en-US',{...options,month:'short',year:'numeric'});
  const date=(d:Date)=>d.toLocaleDateString('en-US',{...options,month:'short',day:'numeric'});
  return `${date(first)}–${month(first)===month(last)?last.toLocaleDateString('en-US',{...options,day:'numeric'}):date(last)}`;
}
