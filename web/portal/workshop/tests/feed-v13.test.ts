import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=(file:string)=>readFileSync(new URL(`../${file}`,import.meta.url),'utf8');
test('Feed V13 is registered beside the preserved V12',()=>{
 assert.match(source('feed/FeedWorkshop.tsx'),/id:'feed-v13',\s*label:'Candidate v13'/);
 assert.match(source('feed/FeedPreview.tsx'),/settings.variant === 'feed-v13' \? FeedV13/);
});
test('masthead ownership follows the bound viewer, even after entries move or flags disagree',async()=>{
 const {v13OwnRide}=await import('../feed/feedV13Model');const {feedV7ById}=await import('../feed/feedV7Model');
 const s=structuredClone(feedV7ById('mixed'));
 assert.deepEqual(s.entries.map(e=>v13OwnRide(s,e)),[true,false,false]);
 s.entries.reverse();assert.deepEqual(s.entries.map(e=>v13OwnRide(s,e)),[false,false,true]);
 s.entries[0].owned=true;s.entries[2].owned=false;
 assert.equal(v13OwnRide(s,s.entries[0]),false);assert.equal(v13OwnRide(s,s.entries[2]),true);
 assert.match(source('feed/FeedV13.tsx'),/data-own=\{v13OwnRide\(scenario,entry\)\}/);
 assert.match(source('feed/feed-v13.css'),/data-own=false/);
});
test('result rows use the 24px Medal while personal-best-only placement stays unchanged',()=>{
 const s=source('feed/FeedV13Results.tsx');
 assert.match(s,/import \{Medal\} from '..\/marks\/Medal'/);
 assert.match(s,/<Medal rank=\{r.leaderboard.rank\} size=\{24\}/);
 assert.match(s,/r.personalRank&&r.personalRank!==1/);
 assert.match(source('feed/FeedV13Network.tsx'),/<Medal rank=\{row.rank\} size=\{24\}/);
 for(const file of ['feed/FeedV13Network.tsx','feed/FeedV13Riders.tsx']){assert.doesNotMatch(source(file),/RankMark/);assert.match(source(file),/<Medal rank=\{row.rank\} size=\{24\}/);}
});
test('Feed V13 links keep their own generation and reach Climb V16 and Ride V14',async()=>{
 const {v13RideHref,v13ClimbHref,v13RiderHref,v13RideContext,v13RailItems}=await import('../feed/feedV13Model');
 const {feedV7ById}=await import('../feed/feedV7Model');const {rideFeedHref}=await import('../rideV14Model');const {roomDestination}=await import('../roomRegistry');
 const s=feedV7ById('mixed'),e=s.entries[0],query=(href:string)=>new URL(href,'http://test').searchParams;
 const ride=query(v13RideHref(e,undefined,'overview',s,'following'));assert.equal(ride.get('variant'),'candidate-v14');assert.equal(ride.get('feedVariant'),'feed-v13');
 assert.equal(query(rideFeedHref(ride)).get('variant'),'feed-v13');assert.equal(query(rideFeedHref(ride)).get('filter'),'following');
 assert.equal(query(v13RiderHref(s,s.workshopV7!.riders[0].id)).get('variant'),'feed-v13');
 for(const item of v13RailItems(s))assert.equal(query(item.href!).get('variant'),'climb-v16');
 assert.equal(v13ClimbHref('unknown'),undefined);assert.ok(v13RideContext(e.ride.id,s.id));
 assert.equal(query(roomDestination('feed')).get('variant'),'feed-v9');
});
test('V13 preserves the measured-copy route fit and omitted-elevation stat contract',async()=>{
 const {v13HeroPadding,v13RideFacts}=await import('../feed/feedV13Model');const {v12HeroPadding,v12RideFacts}=await import('../feed/feedV12Model');const {feedV7ById}=await import('../feed/feedV7Model');
 for(const args of [[780,280,false,340],[390,520,true,390]] as const)assert.deepEqual(v13HeroPadding(args[0],args[1],args[2],args[3]),v12HeroPadding(args[0],args[1],args[2],args[3]));
 const ride=structuredClone(feedV7ById('mixed').entries[0].ride);assert.deepEqual(v13RideFacts(ride),v12RideFacts(ride));ride.ride.samples.forEach(p=>p.elevation=null);assert.deepEqual(v13RideFacts(ride).map(x=>x.label),['Distance','Elapsed time']);
});

test('ride links use the masthead identity for long-feed, reordered and unbound entries',async()=>{
 const {v13OwnRide,v13RideHref}=await import('../feed/feedV13Model');const {feedV7ById}=await import('../feed/feedV7Model');
 for(const id of ['long-feed','mixed']){
  const s=structuredClone(feedV7ById(id));s.entries.reverse();
  const viewerEntries=s.entries.filter(e=>v13OwnRide(s,e));assert.ok(viewerEntries.length>0);
  s.entries.forEach(e=>e.owned=!v13OwnRide(s,e));
  for(const entry of s.entries)for(const view of ['overview','analysis','vault'] as const){
   const query=new URL(v13RideHref(entry,view==='overview'?undefined:entry.ride.climbs[0]?.id,view,s,'following'),'http://test').searchParams;
   assert.equal(query.get('viewer'),v13OwnRide(s,entry)?'owner':'visitor',`${id} ${entry.id} ${view}`);
   assert.equal(query.get('feedScenario'),s.id);assert.equal(query.get('feedFilter'),'following');assert.equal(query.get('feedVariant'),'feed-v13');
  }
  delete s.workshopV7;
  for(const owned of [true,false]){const entry={...s.entries[0],owned};assert.equal(new URL(v13RideHref(entry,undefined,'overview',s),'http://test').searchParams.get('viewer'),owned?'owner':'visitor');}
 }
});
