// One registration point; candidate implementations remain owned by their rooms.
import {baselineRooms} from './baseline/model';
// Finals: the candidate Tim locked, settled or accepted for each room, with the date of that decision.
const FINALS = {
 ride:'Ride · V12 accepted 11 Sep 2026 · V13 carries the feed-linked result',
 feed:'Feed · V9 accepted 13 Sep 2026',
 climb:'Climb · V13 locked 14 Sep 2026',
 map:'Map · V7 settled 14 Sep 2026',
 profile:'Rider Profile · V6 locked 14 Sep 2026',
} as const;
export const ROOMS = [
 {id:'ride', label:'Ride', detail:'Ride · 14 preserved candidates', finals:FINALS.ride, hasFinal:true, href:'/?surface=ride&variant=candidate-v13&scenario=recorded'},
 {id:'feed', label:'Feed', detail:'Feed · 12 preserved candidates', finals:FINALS.feed, hasFinal:true, href:'/?surface=feed&variant=feed-v9&scenario=mixed'},
 {id:'climb', label:'Climb', detail:'Climb · retained baseline + 16 candidates', finals:FINALS.climb, hasFinal:true, href:'/?surface=climb&variant=climb-v13&scenario=wises&viewer=rider'},
 {id:'map', label:'Map', detail:'Map · retained baseline + 6 candidates', finals:FINALS.map, hasFinal:true, href:'/?surface=map&variant=map-v7&scenario=wises&viewer=rider'},
 ...baselineRooms.map(room=>({id:room.id,label:room.id==='profile'?'Rider Profile':room.label,detail:room.id==='profile'?'Rider Profile · retained V1–V5 and Candidate V6':`${room.label} · frozen V1 baseline`,finals:room.id==='profile'?FINALS.profile:`${room.label} · frozen V1 · no locked candidate yet`,hasFinal:room.id==='profile',href:room.id==='profile'?'/?surface=profile&variant=profile-v6&scenario=rider':`/?surface=${room.id}&variant=${room.id}-v1&scenario=${room.scenarios[0].id}`})),
 {id:'kit', label:'V15 kit', detail:'V15 kit', finals:'V15 kit · no locked candidate yet', hasFinal:false, href:'/?surface=kit'},
 {id:'effort', label:'Effort', detail:'Effort · V1 on the V15 kit', finals:'Effort · no locked candidate yet', hasFinal:false, href:'/?surface=effort&variant=effort-v1'},
] as const;
export type WorkshopPage = typeof ROOMS[number]['id'];
export const roomFor = (id:string|null) => ROOMS.find(room=>room.id===id)??ROOMS[0];
export const roomDestination = (id:string) => roomFor(id).href;
export const FINALS_PARAM = 'finals';
// Rooms that have a locked, settled or accepted candidate; Finals lists only these.
export const FINAL_ROOMS = ROOMS.filter(room=>room.hasFinal);
export const finalsActive = (search:string) => new URLSearchParams(search).get(FINALS_PARAM)==='1';
export const finalsDestination = (id:string) => { const url=new URL(roomDestination(id),'http://workshop.local'); url.searchParams.set(FINALS_PARAM,'1'); return url.pathname+url.search; };
