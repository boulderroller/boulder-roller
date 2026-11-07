type ProfileInput={lengthM:number;profile?:{distanceM:number;elevationM:number}[]};
/** Same fourfold vertical exaggeration for every hill; steep profiles fit both axes together. */
export function profileGlyph(climb:ProfileInput){
 const p=climb.profile;if(!p?.length||climb.lengthM<=0)return null;
 let low=Infinity,high=-Infinity;
 for(const point of p){low=Math.min(low,point.elevationM);high=Math.max(high,point.elevationM);}
 const width=72,height=44,padding=3,exaggeration=4;
 const scale=Math.min((width-padding*2)/climb.lengthM,(height-padding*2)/Math.max(1,(high-low)*exaggeration));
 const points=p.map(point=>[padding+point.distanceM*scale,height-padding-(point.elevationM-low)*scale*exaggeration] as [number,number]);
 return {points,width,height};
}
