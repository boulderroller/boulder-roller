import {memo} from 'react';
import {RankMark} from '../../../src/components/rankmarks/RankMark';
import type {MapClimb} from '../mapModel';
import {publicLeader} from '../v6/mapV6Leaderboard';
import {profileGlyph} from './mapV7Profile';

const Profile=memo(function Profile({climb}:{climb:MapClimb}){
 const profile=profileGlyph(climb);if(!profile)return null;
 const {points,width,height}=profile,outline=points.map(p=>p.map(n=>n.toFixed(2)).join(',')).join(' ');
 return <svg className="m7-trace" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${climb.name} elevation profile; vertical scale exaggerated two times`}>
  <title>Elevation profile · vertical scale ×2</title>
  <polygon points={`${points[0][0]},${height-3} ${outline} ${points.at(-1)![0]},${height-3}`} fill="currentColor" opacity=".13"/>
  <polyline points={outline} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>
 </svg>;
});

export const MapLeaderV7=memo(function MapLeaderV7({climb}:{climb:MapClimb}){
 const leader=publicLeader(climb);if(!leader)return null;
 const time=`${Math.floor(leader.timeSeconds/60)}:${String(leader.timeSeconds%60).padStart(2,'0')}`;
 const date=new Date(leader.capturedAt).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
 return <span className="m7-leader" title={`Public ${leader.tied?'joint first place':'first place'} · captured ${date} · ${leader.sourceUrl}`}>
  <RankMark rank={1} size={20}/><span className="m7-holder">{leader.name}</span>{leader.tied&&<small>Joint 1st</small>}<span className="m7-leader-time">{time}</span>
 </span>;
});

export const MapRowContentsV7=memo(function MapRowContentsV7({climb:c}:{climb:MapClimb}){
 return <><strong className="m7-row-name">{c.name}</strong><span className="m7-row-data" data-has-profile={!!c.profile}>
  <Profile climb={c}/><span className="m7-measurements">
   <span><span className="sr-only">Distance </span>{(c.lengthM/1000).toFixed(2)}<small>km</small></span>
   <span><span className="sr-only">Elevation rise </span>{Math.round(c.riseM).toLocaleString()}<small>m rise</small></span>
   <span><span className="sr-only">Average grade </span>{c.gradePct.toFixed(1)}<small>%</small></span>
  </span>
 </span><MapLeaderV7 climb={c}/></>;
});
