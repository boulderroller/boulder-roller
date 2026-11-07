import { createElement as h } from 'react';
import type { ReactElement } from 'react';
import { ROOMS } from './share-preview.js';
import { rideCardShape, ridePresentationFacts, formatRidePresentation } from './ride-card-shape.js';
import type { Preview, ShareObject } from './share-preview.js';

const INK = '#F1EEE8', SOFT = '#9A9488', LINE = '#2A2825', SHEET = '#1B1A17';
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const text = (value: unknown) => typeof value === 'string' ? value : '';
const km = (value: unknown) => finite(value) ? `${(value/1000).toFixed(1)} km` : '—';
const metres = (value: unknown) => finite(value) ? `${Math.round(value).toLocaleString('en-US')} m` : '—';
const number = (value: unknown) => finite(value) ? value.toLocaleString('en-US') : '—';
const time = (value: unknown) => {
  if (!finite(value) || value < 0) return '—';
  const s = Math.floor(value), m = Math.floor(s / 60), hours = Math.floor(m / 60);
  return hours ? `${hours}:${String(m % 60).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}` : `${m}:${String(s % 60).padStart(2,'0')}`;
};
const date = (value: unknown, since = false) => {
  if (!text(value)) return '';
  const d = new Date(value as string);
  if (!Number.isFinite(d.getTime())) return '';
  return new Intl.DateTimeFormat('en-US', {month:'short', ...(since ? {} : {day:'numeric'}), year:'numeric', timeZone:'UTC'}).format(d);
};

function label(value: string, x: number, baseline: number, size: number, options: {mono?:boolean; weight?:number; soft?:boolean; right?:boolean; width?:number} = {}): ReactElement {
  return h('div', {style:{position:'absolute', display:'flex', ...(options.right ? {right:1200-x} : {left:x}),
    top:baseline-size*0.86, fontSize:size, lineHeight:1, fontFamily: options.mono ? 'Geist Mono' : 'Geist',
    fontWeight:options.weight ?? 400, color:options.soft ? SOFT : INK, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis',
    maxWidth:options.width ?? (options.right ? x-72 : 1128-x), letterSpacing:size===60 ? -0.5 : 0,
  }}, value);
}
function svg(children: ReactElement[]): ReactElement {
  return h('svg', {width:1200,height:630,viewBox:'0 0 1200 630',style:{position:'absolute',left:0,top:0}}, ...children);
}
const rule = (y: number) => h('line',{x1:72,x2:1128,y1:y,y2:y,stroke:LINE});
function facts(values: string[], words: string[], trailing?: [string,string]): ReactElement[] {
  return values.flatMap((value,i) => [label(value,[72,300,528][i],500,34,{mono:true,width:220}),label(words[i],[72,300,528][i],528,18,{soft:true})])
    .concat(trailing ? [label(trailing[0],1128,500,34,{mono:true,right:true,width:320}),label(trailing[1],1128,528,18,{soft:true,right:true})] : []);
}

// Explicit field allowlist: economic payload fields are never serialized or drawn.
export function cardElement(object: ShareObject | null, preview: Preview | null): ReactElement {
  const children: ReactElement[] = [];
  if (!object || !preview) {
    children.push(svg([h('rect',{x:544,y:231,width:48,height:48,rx:10,fill:INK})]), label('Boulder Roller',616,273,52,{weight:700}));
  } else {
    const room = ROOMS[object.kind];
    children.push(svg([h('rect',{x:72,y:548,width:18,height:18,rx:4,fill:INK})]), label('Boulder Roller',104,563,22,{weight:600}),label(room,1128,563,22,{soft:true,right:true}));
    if (object.kind === 'climbs') {
      const c = preview.climb ?? {};
      children.push(label('Climb geography: © OpenStreetMap contributors · openstreetmap.org/copyright',72,589,16));
      children.push(label('docs.boulderroller.xyz/open-data',1128,589,16,{right:true,width:360}));
      const elevationNotices = (c.geographicData?.sources ?? []).filter((source: any) => source.license_id !== 'ODbL-1.0').flatMap((source: any) => source.notices ?? []).map((notice: any) => text(notice.text));
      if (elevationNotices.length) children.push(label(`Elevation: ${elevationNotices.join(' ')}`,72,616,16,{width:1056}));
      children.push(label(text(preview.title),72,120,60,{weight:700}),label(text(c.region),72,166,26,{soft:true}));
      // The public preview passes the climb's stored points through as distance_m / elevation_m; the app type says distanceM / elevationM. Read both.
      const profile: Array<{distanceM: number; elevationM: number}> = (Array.isArray(c.elevationProfile) ? c.elevationProfile : [])
        .map((p: any) => ({distanceM: p?.distanceM ?? p?.distance_m, elevationM: p?.elevationM ?? p?.elevation_m}))
        .filter((p) => finite(p.distanceM) && finite(p.elevationM));
      const shape: ReactElement[] = [rule(442)];
      if (profile.length > 1) {
        const maxD = Math.max(...profile.map((p: any) => p.distanceM));
        const minE = Math.min(...profile.map((p: any) => p.elevationM));
        const range = Math.max(1,...profile.map((p: any) => p.elevationM-minE));
        if (maxD > 0) {
          const points = profile.map((p: any) => ({x:72+1056*p.distanceM/maxD,y:440-(p.elevationM-minE)/range*190*.92}));
          for (let i=1;i<points.length;i++) {
            const delta = profile[i].distanceM-profile[i-1].distanceM;
            const grade = delta > 0 ? Math.abs((profile[i].elevationM-profile[i-1].elevationM)/delta*100) : 0;
            shape.push(h('line',{x1:points[i-1].x,y1:points[i-1].y,x2:points[i].x,y2:points[i].y,stroke:INK,strokeOpacity:Math.min(1,.35+grade/12),strokeWidth:2+grade/4,strokeLinecap:'round'}));
          }
          shape.push(h('circle',{cx:points[0].x,cy:points[0].y,r:5,fill:INK}));
        }
      }
      const crown = c.recordBoard?.entries?.find((entry: any) => (entry.competitionRank ?? entry.rank) === 1 && finite(entry.bestTimeSeconds));
      children.push(svg(shape),...facts([km(c.lengthM),metres(c.elevGainM),finite(c.avgGradientPct) ? `${c.avgGradientPct.toFixed(1)}%` : '—'],['Distance','Elevation','Grade'],crown ? [time(crown.bestTimeSeconds),'Crown'] : undefined));
    } else if (object.kind === 'rides') {
      const r = preview.ride ?? {};
      const metrics = formatRidePresentation(ridePresentationFacts(r, object.id, 'public'));
      const rider = r.rider?.identityHidden ? null : r.rider;
      const sub = [text(rider?.username) ? `@${rider.username.replace(/^@+/,'')}` : '',date(r.startedAt),text(r.routePreview?.placeLabel)].filter(Boolean).join(' · ');
      const shape = rideCardShape(r.elevation_profile,r.counted_spans);
      children.push(label(text(preview.title),72,120,60,{weight:700}),label(sub,72,166,26,{soft:true}),svg([
        ...shape.fills.map(d=>h('path',{d,fill:SHEET})),
        ...shape.lines.map(d=>h('path',{d,fill:'none',stroke:SOFT,strokeWidth:1.6,strokeLinejoin:'round'})),
        ...shape.strokes.map(d=>h('path',{d,fill:'none',stroke:'#5592E2',strokeWidth:4,strokeLinejoin:'round',strokeLinecap:'round'})),rule(428),
      ]),...facts([metrics.distance,metrics.elevation,metrics.time],['Distance','Elevation','Time'],!shape.count ? undefined : [String(shape.count),'Climbs']));
    } else {
      const p = preview.profile ?? {}, rider = preview.rider?.identityHidden ? null : preview.rider;
      const name = text(preview.title), since = date(p.createdAt,true);
      const sub = [text(rider?.username) ? `@${rider.username.replace(/^@+/,'')}` : '',text(p.location),since ? `Since ${since}` : ''].filter(Boolean).join(' · ');
      children.push(svg([h('circle',{cx:112,cy:140,r:40,fill:SHEET,stroke:LINE}),rule(236)]),label(name.slice(0,1).toUpperCase(),100,153,34,{soft:true,weight:600}),label(name,176,128,60,{weight:700}),label(sub,176,170,26,{soft:true}));
      const stats = preview.leaderboard?.stats ?? {};
      [p.totalRides,stats.top10Count,stats.komCount].forEach((value,i) => children.push(label(number(value),[72,420,768][i],340,88,{mono:true,width:340}),label(['Rides','Seats','Crowns'][i],[72,420,768][i],378,22,{soft:true})));
      // No census in the public payload: an absent join is not a zero or a fabricated denominator.
    }
  }
  return h('div',{style:{display:'flex',position:'relative',width:1200,height:630,background:'#0F0E0C',color:INK,fontFamily:'Geist',overflow:'hidden'}},...children);
}
