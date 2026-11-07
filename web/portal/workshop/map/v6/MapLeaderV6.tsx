import {memo} from 'react';
import {RankMark} from '../../../src/components/rankmarks/RankMark';
import {publicLeader} from './mapV6Leaderboard';
import type {MapClimb} from '../mapModel';

export const MapLeaderV6=memo(function MapLeaderV6({climb,compact=false}:{climb:MapClimb;compact?:boolean}){
 const leader=publicLeader(climb);if(!leader)return null;
 const seconds=Math.round(leader.timeSeconds),time=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
 const date=new Date(leader.capturedAt).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
 return <span className="m6-leader" data-compact={compact} title={`Public ${leader.tied?'joint first place':'first place'} · captured ${date} · ${leader.sourceUrl}`}>
  <RankMark rank={1} size={compact?28:32}/>
  <span className="m6-leader-person"><span className="m6-leader-name">{leader.name}</span><span className="m6-leader-label">{leader.tied?'Joint 1st':'1st place'}</span></span>
  <span className="m6-leader-time">{time}</span>
 </span>;
});
