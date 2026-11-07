import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {feedV7ById,parseFeedV7,rekeyV7Feed} from '../feed/feedV7Model';
import {v9RideContext} from '../feed/feedV9Model';
import {rideFeedHref} from '../rideV14Model';
import {roomDestination} from '../roomRegistry';
const source=(file:string)=>readFileSync(new URL(`../${file}`,import.meta.url),'utf8');
const query=(href:string)=>new URL(href,'http://workshop.test').searchParams;

test('V12 is registered beside V9, whose accepted final is preserved',()=>{
 const workshop=source('feed/FeedWorkshop.tsx'),preview=source('feed/FeedPreview.tsx');
 assert.match(workshop,/id:'feed-v12',\s*label:'Candidate v12'/);
 assert.match(preview,/settings.variant === 'feed-v12' \? FeedV12/);
 assert.match(workshop,/'feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'\]\.includes/);
 assert.match(preview,/'feed-v7','feed-v8','feed-v9','feed-v11','feed-v12','feed-v13'\]\.includes/);
 assert.match(source('roomRegistry.ts'),/Feed · 12 preserved candidates/);
 assert.equal(query(roomDestination('feed')).get('variant'),'feed-v9');
});
test('the shared destination map binds every room and all four You tabs',async()=>{
 const {destinations,destinationHref,youItems}=await import('../frame/destinations');
 for(const [name,variant] of Object.entries({feed:'feed-v13',map:'map-v7',profile:'profile-v6',upload:'upload-v1',notifications:'notifications-v1',settings:'settings-v1',climb:'climb-v16',ride:'candidate-v14'}))assert.equal(query(destinationHref(name as keyof typeof destinations)).get('variant'),variant);
 assert.equal(query(destinationHref('feed')).get('scenario'),'mixed');
 assert.equal(query(destinationHref('map')).get('viewer'),'rider');
 assert.deepEqual(youItems.map(item=>[item.label,query(item.href).get('tab')]),[['Profile','overview'],['Rides','rides'],['Training','training'],['Portfolio','portfolio']]);
 assert.equal(query(destinationHref('profile',{tab:'training'})).get('scenario'),'rider');
 assert.equal(query(destinationHref('climb',{scenario:'black-rock',viewer:'visitor'})).get('viewer'),'visitor');
});
test('ride and rider links keep the scenario, filter and exact effort context in V12',async()=>{
 const {v12RideHref,v12RiderHref}=await import('../feed/feedV12Model');
 const s=feedV7ById('mixed'),e=s.entries[0],c=e.ride.climbs[0];
 const q=query(v12RideHref(e,c.id,'analysis',s.id,'following'));
 assert.equal(q.get('variant'),'candidate-v14');assert.equal(q.get('feedVariant'),'feed-v12');
 assert.equal(q.get('feedScenario'),s.id);assert.equal(q.get('feedFilter'),'following');
 assert.equal(q.get('climb'),c.id);assert.equal(q.get('view'),'analysis');
 assert.equal(query(rideFeedHref(q)).get('variant'),'feed-v12');assert.equal(query(rideFeedHref(q)).get('filter'),'following');
 const rider=query(v12RiderHref(s,s.workshopV7!.riders[0].id,'following'));
 assert.equal(rider.get('variant'),'feed-v12');assert.equal(rider.get('filter'),'following');assert.equal(rider.get('scenario'),s.id);
 assert.match(source('CandidateV13.tsx'),/feedQuery.get\('feedVariant'\)==='feed-v12'\?'feed-v12'/);
 assert.match(source('main.tsx'),/query.get\('feedVariant'\)==='feed-v12'\?v12RideContext/);
});
test('ride context preserves every V9 fact and changes only the destination generation',async()=>{
 const {v12RideContext}=await import('../feed/feedV12Model');
 const s=feedV7ById('mixed'),id=s.entries[0].ride.id,before=v9RideContext(id,s.id,'following')!,after=v12RideContext(id,s.id,'following')!;
 assert.deepEqual(after.economics,before.economics);assert.equal(after.source,before.source);
 assert.deepEqual(after.climbs.map(c=>({...c,leaderboard:c.leaderboard.map(({href,...r})=>r)})),before.climbs.map(c=>({...c,leaderboard:c.leaderboard.map(({href,...r})=>r)})));
 for(const row of after.climbs.flatMap(c=>c.leaderboard))if(row.href){assert.equal(query(row.href).get('feedVariant'),'feed-v12');assert.equal(query(row.href).get('variant'),'candidate-v14');}
 assert.equal(v12RideContext('missing','missing'),undefined);
});
test('V12 round trips stay on V12 and Ride V14 when shared destinations move forward',async()=>{
 const {destinations}=await import('../frame/destinations');
 const {v12RideHref,v12RiderHref,v12RideContext}=await import('../feed/feedV12Model');
 const feed=destinations.feed as {variant:string},ride=destinations.ride as {variant:string};
 const savedFeed=feed.variant,savedRide=ride.variant,s=feedV7ById('mixed'),entry=s.entries[0];
 try{
  feed.variant='feed-v13';ride.variant='candidate-v15';
  const q=query(v12RideHref(entry,undefined,'overview',s.id,'following'));
  assert.equal(q.get('variant'),'candidate-v14');assert.equal(q.get('feedVariant'),'feed-v12');
  assert.equal(query(rideFeedHref(q)).get('variant'),'feed-v12');
  assert.equal(query(v12RiderHref(s,s.workshopV7!.riders[0].id,'following')).get('variant'),'feed-v12');
  for(const row of v12RideContext(entry.ride.id,s.id,'following')!.climbs.flatMap(c=>c.leaderboard))if(row.href){
   assert.equal(query(row.href).get('variant'),'candidate-v14');assert.equal(query(row.href).get('feedVariant'),'feed-v12');
  }
 }finally{feed.variant=savedFeed;ride.variant=savedRide;}
});
test('the rail takes names and places from V9 personal standings, never from a hard-coded list',async()=>{
 const {v12RailItems,v12ClimbHref}=await import('../feed/feedV12Model');
 const s=structuredClone(feedV7ById('mixed')),items=v12RailItems(s);
 assert.deepEqual(items.map(i=>i.label),['Wises Mill Road','Black Rock Road']);
 assert.deepEqual(items.map(i=>i.meta),['7th','4th']);
 assert.deepEqual(items.map(i=>query(i.href!).get('scenario')),['wises','black-rock']);
 for(const item of items){assert.equal(query(item.href!).get('variant'),'climb-v15');assert.equal(query(item.href!).get('viewer'),'rider');}
 s.workshopV3!.personal!.standings[0].rank=11;s.entries[0].ride.climbs[0].name='Supplied climb name';
 assert.equal(v12RailItems(s)[0].label,'Supplied climb name');assert.equal(v12RailItems(s)[0].meta,'11th');
 assert.deepEqual(v12RailItems({...s,workshopV3:undefined}),[]);
 s.workshopV3!.personal!.standings.push({...s.workshopV3!.personal!.standings[0],entryId:'missing'});
 assert.equal(v12RailItems(s).length,2);
 assert.equal(v12ClimbHref('unknown-climb'),undefined);
 s.entries[0].ride.climbs[0].id='unknown-climb';s.workshopV3!.personal!.standings[0].climbId='unknown-climb';
 assert.equal(v12RailItems(s)[0].href,undefined,'unbound imported climbs do not borrow a known destination');
});
test('the three ride stat cells omit missing elevation and keep known zeroes',async()=>{
 const {v12RideFacts}=await import('../feed/feedV12Model');
 const s=structuredClone(feedV7ById('mixed').entries[0].ride);
 assert.deepEqual(v12RideFacts(s).map(f=>f.label),['Distance','Elapsed time','Elevation']);
 s.ride.samples.forEach(p=>p.elevation=null);
 assert.deepEqual(v12RideFacts(s).map(f=>f.label),['Distance','Elapsed time']);
 s.ride.samples.forEach(p=>p.elevation=0);
 assert.equal(v12RideFacts(s).find(f=>f.label==='Elevation')?.value,'0');
});
test('V12 uses the unchanged V9 scenario import and identity contract',async()=>{
 const {v12RideHref,v12RiderHref}=await import('../feed/feedV12Model');
 const s=rekeyV7Feed(parseFeedV7(JSON.parse(JSON.stringify(feedV7ById('mixed')))),'v12-test');
 assert.equal(query(v12RideHref(s.entries[0],undefined,'overview',s.id)).get('scenario'),s.entries[0].ride.id);
 assert.equal(query(v12RiderHref(s,s.workshopV7!.riders[0].id)).get('rider'),s.workshopV7!.riders[0].id);
});

test('the route fit clears the measured desktop copy and the complete phone copy block',async()=>{
 const {v12HeroPadding}=await import('../feed/feedV12Model');
 const {heroFitPadding15}=await import('../climb/climbV15Model');
 for(const copyWidth of [340,440]){
  const fit=v12HeroPadding(780,280,false,copyWidth);
  assert.equal(fit.left,copyWidth+140,'route clears the copy and its opaque fade');
  assert.equal(fit.right,48,'no space is reserved for absent map controls');
  assert.equal(fit.top,48);assert.equal(fit.bottom,48);
 }
 assert.deepEqual(v12HeroPadding(390,400,true,390),{...heroFitPadding15(390,400,true,'a'),bottom:248});
 assert.equal(v12HeroPadding(390,520,true,390).bottom,368);
});
