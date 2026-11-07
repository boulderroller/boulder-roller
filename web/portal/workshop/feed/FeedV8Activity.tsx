import {useState} from 'react';
import {FeedV2Dialog} from './FeedV2Context';
import {FeedV8WorldMap} from './FeedV8WorldMap';
import {formatFeedCal} from './feedV2Model';
import {worldPeriodLabel,type FeedV3World} from './feedV3Model';

export function FeedV8Activity({world,initialRegion,onClose}:{world:FeedV3World;initialRegion:string|null;onClose:()=>void}) {
  const [selected,setSelected]=useState<string|null>(initialRegion);
  const [inspected,setInspected]=useState<string|null>(null);
  const active=inspected??selected;
  const max=Math.max(1,...world.regions.map(r=>r.climbsRidden));
  const select=(id:string|null)=>{setSelected(current=>id===current?null:id);setInspected(null);};
  const hasCal=world.rideCal!==undefined||world.tributeCal!==undefined;
  return <FeedV2Dialog title="Network activity" onClose={onClose}>
    <div className="f8-activity">
      <div className="f8-activity-heading">
        <div><span>{worldPeriodLabel(world.periodStart,world.periodEnd)}</span><div><strong>{world.climbsRidden?.toLocaleString()??'—'}</strong><span>climbs ridden</span></div></div>
        <span>Boulder Roller</span>
      </div>
      <div className="f8-atlas">
        <FeedV8WorldMap expanded regions={world.regions} activeId={active} selectedId={selected} onInspect={r=>setInspected(r?.id??null)} onOpen={r=>select(r.id)}/>
        <div className="f8-region-panel">
          <div className="f8-region-heading"><h3>Regions</h3><button aria-pressed={selected===null} onClick={()=>select(null)}>All regions</button></div>
          <div className="f8-regions" aria-label="Activity by region">
            {world.regions.map(r=><button className="f8-region" key={r.id} aria-pressed={selected===r.id} data-active={active===r.id} onPointerEnter={()=>setInspected(r.id)} onPointerLeave={()=>setInspected(null)} onFocus={()=>setInspected(r.id)} onBlur={()=>setInspected(null)} onClick={()=>select(r.id)}>
              <span className="f8-region-name">{r.name}</span><strong>{r.climbsRidden.toLocaleString()}</strong>
              <span className="f8-region-track" aria-hidden="true"><i style={{width:`${r.climbsRidden/max*100}%`}}/></span>
              {world.climbsRidden!==undefined&&world.climbsRidden>0&&<small>{(r.climbsRidden/world.climbsRidden*100).toFixed(1)}%</small>}
            </button>)}
          </div>
        </div>
      </div>
      <footer className="f8-activity-foot">
        {hasCal&&<div><span>Across all regions</span><dl>
          {world.rideCal!==undefined&&<div><dt>Ride CAL</dt><dd>{formatFeedCal(world.rideCal)}<small>CAL</small></dd></div>}
          {world.tributeCal!==undefined&&<div><dt>Climb tribute</dt><dd>{formatFeedCal(world.tributeCal)}<small>CAL</small></dd></div>}
        </dl></div>}
        <time dateTime={world.asOf}>Through {new Date(world.asOf).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:'America/New_York',timeZoneName:'short'})}</time>
      </footer>
    </div>
  </FeedV2Dialog>;
}
