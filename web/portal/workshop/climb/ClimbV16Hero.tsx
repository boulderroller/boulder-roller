import type {ReactNode} from 'react';
import type {PaddingOptions} from 'maplibre-gl';
import {X} from 'lucide-react';
import type {DiscoveryV4} from '../feed/feedV4Model';
import {distanceLabel} from '../scenario';
import {selectedTerrain} from './climbModel';
import {elevationLabel} from './climbV12Measurements';
import {localGrade,pitchGrade,type Hero} from './climbV16Model';
import {ClimbV16Map} from './ClimbV16Map';
import {ClimbV16Profile} from './ClimbV16Profile';
export const Unit=({children}:{children:ReactNode})=><>{' '}<span className="c16-unit">{children}</span></>;
/** A unit that closes up on its figure, as Standard writes 1.2%. */
export const Tight=({children}:{children:ReactNode})=><span className="c16-unit">{children}</span>;
type Dimensions={gain:number;grade:number;min:number;max:number;difference:number};
export type Terrain={terrain:DiscoveryV4;dimensions:Dimensions;index:number|null;onIndex:(i:number|null)=>void;range:[number,number]|null;onRange:(r:[number,number]|null)=>void};
type MapProps={expanded:boolean;onExpand:()=>void;fitPadding:(w:number,h:number)=>PaddingOptions};

function Identity({terrain,dimensions}:Pick<Terrain,'terrain'|'dimensions'>){
 return <dl className="c16-hero-stats" aria-label="Climb statistics"><div><dt>Distance</dt><dd>{distanceLabel(terrain.length)}<Unit>km</Unit></dd></div><div><dt title="Total uphill elevation change in this climb’s supplied profile">Elevation gain</dt><dd>{elevationLabel(dimensions.gain)}<Unit>m</Unit></dd></div><div><dt title="Finish minus start elevation, divided by climb distance">Avg grade</dt><dd>{dimensions.grade.toFixed(1)}<Tight>%</Tight></dd></div></dl>;
}
export function ElevationFacts({dimensions,className='c16-elev-facts'}:{dimensions:Dimensions;className?:string}){
 return <dl className={className} aria-label="Climb elevations"><div><dt>Lowest elev</dt><dd>{elevationLabel(dimensions.min)}<Unit>m</Unit></dd></div><div><dt>Highest elev</dt><dd>{elevationLabel(dimensions.max)}<Unit>m</Unit></dd></div><div><dt title="Highest minus lowest elevation on this climb">Elev difference</dt><dd>{elevationLabel(dimensions.difference)}<Unit>m</Unit></dd></div></dl>;
}
/** The hover readout: distance, elevation and the local grade (production's ±25 m window). Empty when idle. */
export function Readout({terrain,index}:Pick<Terrain,'terrain'|'index'>){
 const active=index===null?null:terrain.profile[index];
 return <output className="c16-readout-line" aria-live="polite">{active&&<>{distanceLabel(active.d)}<Unit>km</Unit><i> · </i>{elevationLabel(active.elevation)}<Unit>m</Unit><i> · </i>{pitchGrade(localGrade(terrain.profile,terrain.length,active.d))}<Tight>%</Tight></>}</output>;
}
function Selection({terrain,range,onRange}:Pick<Terrain,'terrain'|'range'|'onRange'>){
 const selected=selectedTerrain(terrain.profile,range);
 return selected?<div className="c16-selection" role="status"><span>Selection</span><strong>{distanceLabel(selected.distance)}<Unit>km</Unit></strong><strong>{selected.grade===null?null:<>{pitchGrade(selected.grade)}<Tight>%</Tight><Unit>avg grade</Unit></>}</strong><button className="c16-icon-button" aria-label="Clear selection" onClick={()=>onRange(null)}><X/></button></div>:null;
}
/** A compound name breaks only between its two streets, the slash closing the first line. */
const Name=({name}:{name:string})=>{const parts=name.split(' / ');return parts.length===2?<><span className="c16-name-part">{parts[0]} /</span> <span className="c16-name-part">{parts[1]}</span></>:<>{name}</>;};
/** The kicker sits with the title as its eyebrow; the rule and the stats close the card, so the free space falls between them. */
const Copy=({terrain,dimensions,split=false}:Pick<Terrain,'terrain'|'dimensions'>&{split?:boolean})=><header className="c16-hero-copy"><div className="c16-hero-title">{terrain.locality&&<p className="c16-kicker">{terrain.locality}</p>}<h1 data-long={terrain.name.length>24}>{split?<Name name={terrain.name}/>:terrain.name}</h1></div><Identity terrain={terrain} dimensions={dimensions}/></header>;
/** The masthead's map: A lays its type on the green ground (V13 and V14's) behind a band-coloured fade; C keeps the night ground. */
function HeroMap({t,map,ground}:{t:Terrain;map:MapProps;ground:'night'|'light'}){
 return <div className="c16-hero-art"><ClimbV16Map discovery={t.terrain} index={t.index} onInspect={t.onIndex} range={t.range} onClear={()=>t.onRange(null)} fitPadding={map.fitPadding} ground={ground} quiet={!map.expanded} relief={ground==='night'} masthead><button className="c16-map-size" onClick={map.onExpand} aria-expanded={map.expanded}>{map.expanded?'Compact map':'Expand map'}</button></ClimbV16Map><div className="c16-hero-scrim" aria-hidden="true"/><Copy terrain={t.terrain} dimensions={t.dimensions} split={ground==='light'}/></div>;
}
/** The masthead, in one of three directions. Every direction sits on the band colour; A's dark is a fade behind its type, B and C are dark cards. */
export function ClimbV16Hero({hero,t,map}:{hero:Hero;t:Terrain;map:MapProps}){
 if(hero==='b')return <section className="c16-hero" data-hero="b" aria-label="Climb terrain">
  <div className="c16-hill-top"><header className="c16-hero-copy">{t.terrain.locality&&<p className="c16-kicker">{t.terrain.locality}</p>}<h1 data-long={t.terrain.name.length>24}>{t.terrain.name}</h1></header>
   <div className="c16-hill-stats"><Identity terrain={t.terrain} dimensions={t.dimensions}/><span className="c16-hill-rule" aria-hidden="true"/><ElevationFacts dimensions={t.dimensions} className="c16-hero-stats c16-hill-elev"/></div></div>
  <div className="c16-hill-plot" role="group" aria-label="Elevation"><Readout terrain={t.terrain} index={t.index}/><ClimbV16Profile terrain={t.terrain} index={t.index} onIndex={t.onIndex} range={t.range} onRange={t.onRange} tone="dark"/><Selection {...t}/></div>
 </section>;
 if(hero==='c')return <section className="c16-hero" data-hero="c" data-expanded={map.expanded} aria-label="Climb terrain">
  <HeroMap t={t} map={map} ground="night"/>
  <div className="c16-plate-profile" role="group" aria-label="Elevation"><div className="c16-plate-head"><span className="c16-kicker">Elevation</span><Readout terrain={t.terrain} index={t.index}/><ElevationFacts dimensions={t.dimensions}/></div>
   <ClimbV16Profile terrain={t.terrain} index={t.index} onIndex={t.onIndex} range={t.range} onRange={t.onRange} tone="dark"/><Selection {...t}/></div>
 </section>;
 return <section className="c16-hero" data-hero="a" data-expanded={map.expanded} aria-label="Climb terrain"><HeroMap t={t} map={map} ground="light"/></section>;
}
/** A's light elevation card: the grade-banded line, its strip and the extremes, beside the standing column. */
export function ClimbV16Elevation({t}:{t:Terrain}){
 return <section className="c16-card c16-elevation" role="group" aria-label="Elevation"><div className="c16-elevation-head"><span className="c16-kicker">Elevation</span><Readout terrain={t.terrain} index={t.index}/><ElevationFacts dimensions={t.dimensions}/></div>
  <ClimbV16Profile terrain={t.terrain} index={t.index} onIndex={t.onIndex} range={t.range} onRange={t.onRange} tone="light"/><Selection {...t}/></section>;
}
/** B's map card: V14's pale ground in a light card, the route fit with room for its end labels. */
export function ClimbV16MapCard({t,map}:{t:Terrain;map:MapProps}){
 return <section className="c16-card c16-map-card" data-expanded={map.expanded} aria-label="Climb map"><ClimbV16Map discovery={t.terrain} index={t.index} onInspect={t.onIndex} range={t.range} onClear={()=>t.onRange(null)} fitPadding={map.fitPadding} ground="light" quiet={false}><button className="c16-map-size" onClick={map.onExpand} aria-expanded={map.expanded}>{map.expanded?'Compact map':'Expand map'}</button></ClimbV16Map></section>;
}
