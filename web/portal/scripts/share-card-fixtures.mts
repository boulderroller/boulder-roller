// Offline public-preview fixtures only. Never installed as backend or live data.
const rideProfile = [0,18,6,35,70,20,10,60,100,30,25,110,150,70,50,95,140,45,20,80,55,10].map((e,i)=>({distance_m:i*2500,elevation_m:e+20}));
const rideSpans = [[7500,12500],[25000,30000],[37500,42500]].map(([start,end],i)=>({start_distance_m:start,end_distance_m:end,pattern_id:`offline-climb-${i+1}`}));
const base = {contractVersion:'public_preview.v1',previewPolicy:{privacy:{canView:true}},seo:{robots:'index,follow',description:'Philadelphia'}};
export const fixtures = {
  climbs:{...base,objectType:'climb',title:'Wises Mill Road',climb:{region:'Philadelphia',lengthM:1100,elevGainM:84,avgGradientPct:7.6,elevationProfile:[{distanceM:0,elevationM:24},{distanceM:160,elevationM:26},{distanceM:310,elevationM:38},{distanceM:440,elevationM:46},{distanceM:550,elevationM:47},{distanceM:670,elevationM:75},{distanceM:850,elevationM:93},{distanceM:1100,elevationM:108}],recordBoard:{entries:[{rank:1,bestTimeSeconds:235}]}}},
  rides:{...base,objectType:'ride',title:'In the bag',ride:{id:'ride-1',elevation_profile:rideProfile,counted_spans:rideSpans,startedAt:'2016-08-28T12:00:00Z',distanceM:128730,elevationM:1013,durationS:18727,rider:{username:'dungbeetlephoenix'},routePreview:{placeLabel:'Philadelphia'}}},
  riders:{...base,objectType:'rider',title:'Tim Trail',seo:{robots:'index,follow',description:'Rider profile on Boulder Roller.'},rider:{username:'tim'},profile:{totalRides:12,createdAt:'2026-01-01T12:00:00Z'},leaderboard:{stats:{top10Count:1,komCount:0}}},
  brand:{...base,objectType:'rider',title:'Private identity must not appear',seo:{robots:'noindex,nofollow',description:'Private place must not appear'}},
};
