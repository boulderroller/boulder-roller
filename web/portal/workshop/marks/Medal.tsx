import React,{useId} from 'react';
import {formatInteger} from '../../src/lib/formatters';

// Approved board.py: bezel top/bottom, rim, face top/bottom, numeral.
const metals={
 gold:['#FAEBB5','#BE8E33','#8A6A1F','#D7AC4A','#F6E3A0','#3A2A06'],
 silver:['#FBFCFD','#A9B2BD','#77808B','#C1C8D2','#F3F5F8','#2A2F36'],
 bronze:['#F6D8BF','#A5643A','#77472A','#C58453','#F1CDAE','#3A2010'],
 pewter:['#F3F4F0','#B3B8AC','#8A9083','#C9CDC2','#EEF0EA','#30352B'],
};
/** Workshop row medal. The production RankMark sprite remains unchanged. */
export function Medal({rank,size}:{rank:number;size:number}){
 const id=useId(),metal=rank===1?'gold':rank===2?'silver':rank===3?'bronze':'pewter';
 if(!Number.isInteger(rank)||rank<1||!Number.isFinite(size)||size<=0)return null;
 const label=`Rank ${formatInteger(rank)}`;
 if(rank>=100)return <span role="img" aria-label={label} style={{fontFamily:"'Geist V15', Geist, system-ui",fontSize:13,fontWeight:600,color:'var(--c15-ink, #292c27)'}}>{formatInteger(rank)}</span>;
 const [bt,bb,rim,ft,fb,ink]=metals[metal],font=size>=40?16:size>=32?13:11;
 return <svg width={size} height={size} viewBox="0 0 24 24" role="img" aria-label={label} data-metal={metal} style={{flex:'none',overflow:'visible'}}>
  <defs>
   <linearGradient id={`${id}b`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={bt}/><stop offset="1" stopColor={bb}/></linearGradient>
   <linearGradient id={`${id}f`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={ft}/><stop offset="1" stopColor={fb}/></linearGradient>
   <filter id={`${id}s`} x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy=".55" stdDeviation=".5" floodColor="#292c27" floodOpacity=".28"/></filter>
  </defs>
  <g filter={`url(#${id}s)`}><circle cx="12" cy="11.6" r="11" fill={`url(#${id}b)`} stroke={rim} strokeWidth=".6"/></g>
  {size>=28&&Array.from({length:36},(_,i)=>{const a=2*Math.PI*i/36;return <line key={i} x1={(12+Math.cos(a)*9.3).toFixed(2)} y1={(11.6+Math.sin(a)*9.3).toFixed(2)} x2={(12+Math.cos(a)*10.4).toFixed(2)} y2={(11.6+Math.sin(a)*10.4).toFixed(2)} stroke={rim} strokeOpacity=".28" strokeWidth=".35"/>;})}
  <circle cx="12" cy="11.6" r={size>=28?8.5:8.9} fill={`url(#${id}f)`}/>
  <text x="12" y="12" textAnchor="middle" dominantBaseline="central" fontFamily="'Geist V15', Geist, system-ui" fontWeight="600" fontSize={font*24/size} letterSpacing={rank>=10?'-.05em':'-.02em'} fill={ink}>{rank}</text>
 </svg>;
}
