import type {DiscoveryV4} from '../feed/feedV4Model';

// Use the supplied profile consistently: legacy terrain.gain can mean net rise
// for canonical geography or cumulative ascent for a retained recording.
export function climbMeasurements(terrain:Pick<DiscoveryV4,'length'|'profile'>){
 let min=Infinity,max=-Infinity,gain=0;
 for(let i=0;i<terrain.profile.length;i++){
  const p=terrain.profile[i];
  min=Math.min(min,p.elevation);max=Math.max(max,p.elevation);
  if(i)gain+=Math.max(0,p.elevation-terrain.profile[i-1].elevation);
 }
 const rise=terrain.profile.at(-1)!.elevation-terrain.profile[0].elevation;
 return {min,max,rise,difference:max-min,gain,grade:rise/terrain.length*100};
}

const elevationFormat=new Intl.NumberFormat('en-US',{maximumFractionDigits:1});
export const elevationLabel=(meters:number)=>elevationFormat.format(Object.is(Math.round(meters*10),-0)?0:meters);
