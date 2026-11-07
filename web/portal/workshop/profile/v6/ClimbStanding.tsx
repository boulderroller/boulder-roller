import {ArrowUpRight,ChevronRight} from 'lucide-react';
import {RankMark} from '../../../src/components/rankmarks/RankMark';
import {timeLabel} from '../../scenario';
import {V6_GEOGRAPHY,type Standing,type OwnerEconomy} from './profileV6Model';

export const amount=(value:number)=>new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(value);
const ordinal=(n:number)=>`${n}${n%100>=11&&n%100<=13?'th':n%10===1?'st':n%10===2?'nd':n%10===3?'rd':'th'}`;
export function ClimbStanding({standings,economy,href,onNavigate,onPosition}:{standings:Standing[];economy:OwnerEconomy|null;href:(id:string)=>string;onNavigate:(href:string)=>void;onPosition:(id:string)=>void}){
 return <div className="p6-standing-list">{standings.map(standing=>{
  const hill=V6_GEOGRAPHY.find(c=>c.id===standing.climbId)!;
  const position=economy?.positions.find(p=>p.climbId===standing.climbId);
  return <div className="p6-standing-row" key={hill.id}>
   <a className="p6-standing-result" href={href(hill.id)} onClick={event=>{if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();onNavigate(href(hill.id));}}>
    <span className="p6-rank">{standing.competitionRank!==null&&<RankMark rank={standing.competitionRank} size={58}/>}</span>
    <span className="p6-hill-name"><strong>{hill.name}</strong><span>{standing.competitionRank===null?'Current place unavailable':`${ordinal(standing.competitionRank)} place`}</span></span>
    <span className="p6-hill-time"><strong>{timeLabel(standing.bestSeconds)}</strong><span>Best time</span></span>
    <ArrowUpRight size={13}/>
    <span className="sr-only">Best on {standing.achievedAt.slice(0,10)}. Standing as of {standing.asOf.slice(0,10)}.</span>
   </a>
   {position&&<button className="p6-hill-economy" data-position={hill.id} aria-label={`My position on ${hill.name}`} onClick={()=>onPosition(hill.id)}>
    <span><b>{amount(position.calDeposited)}</b> CAL deposited</span>
    {position.dung&&<span><b>{amount(position.dung.amount)}</b> DUNG {position.dung.state}</span>}
    <ChevronRight size={12}/>
   </button>}
  </div>;
 })}</div>;
}
