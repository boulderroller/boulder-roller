import {useEffect,useId,useRef,useState,type ReactNode} from 'react';
import {ChevronDown} from 'lucide-react';
import {PowerCell,type RowPower} from './Rows';
import {Medal} from './marks';
import {Dialog} from './Dialog';
import {Chip} from './Controls';

export function Note({children}:{children:ReactNode}){return <div className="v15-note">{children}</div>;}
export function LinkButton({href,children,onClick}:{href:string;children:ReactNode;onClick?:()=>void}){return <a className="v15-button" href={href} target="_top" onClick={onClick}>{children}</a>;}
export type MenuOption={value:string;label:string;disabled?:boolean};
export function MenuSelect({label,value,options,onChange}:{label:string;value:string;options:readonly MenuOption[];onChange:(value:string)=>void}){
 const [open,setOpen]=useState(false),root=useRef<HTMLDivElement>(null),button=useRef<HTMLButtonElement>(null),id=useId();
 const close=()=>{setOpen(false);button.current?.focus();};
 useEffect(()=>{if(!open)return;const outside=(e:PointerEvent)=>{if(!root.current?.contains(e.target as Node))setOpen(false);};document.addEventListener('pointerdown',outside);(root.current?.querySelector<HTMLElement>('[aria-selected=true]:not(:disabled)')??root.current?.querySelector<HTMLElement>('[role=option]:not(:disabled)'))?.focus();return()=>document.removeEventListener('pointerdown',outside);},[open]);
 return <div className="v15-select" ref={root}><button className="v15-select-trigger" ref={button} type="button" aria-label={`${label}: ${options.find(o=>o.value===value)?.label??value}`} aria-haspopup="listbox" aria-expanded={open} aria-controls={open?id:undefined} onClick={()=>setOpen(!open)} onKeyDown={e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();setOpen(true);}}}><span>{label}</span>{options.find(o=>o.value===value)?.label}<ChevronDown/></button>{open&&<div id={id} className="v15-select-options" role="listbox" aria-label={label} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();close();}if(e.key==='Tab')setOpen(false);const nodes=[...root.current!.querySelectorAll<HTMLButtonElement>('[role=option]:not(:disabled)')],index=nodes.indexOf(document.activeElement as HTMLButtonElement);let next:number|undefined;if(e.key==='ArrowDown')next=(index+1)%nodes.length;if(e.key==='ArrowUp')next=(index-1+nodes.length)%nodes.length;if(e.key==='Home')next=0;if(e.key==='End')next=nodes.length-1;if(next!==undefined){e.preventDefault();nodes[next]?.focus();}}}>{options.map(option=><button type="button" key={option.value} role="option" aria-selected={option.value===value} disabled={option.disabled} onClick={()=>{onChange(option.value);close();}}>{option.label}</button>)}</div>}</div>;
}
export function ResultSummary({time,power,place,basis,placeBasis,newBest=false,controls,tone='dark'}:{time:string;power?:RowPower;place?:{rank:number;total:number;illustrative?:boolean};basis?:ReactNode;placeBasis?:ReactNode;newBest?:boolean;controls?:ReactNode;tone?:'dark'|'light'}){
 return <div className="v15-result-summary"><dl className="v15-result-time"><dt>Time</dt><dd><span className="v15-result-clock">{time}</span>{newBest&&<Chip>New best</Chip>}</dd>{basis&&<dd className="v15-result-basis">{basis}</dd>}</dl>{power&&<dl><dt>Avg power</dt><dd><PowerCell power={power} tone={tone}/></dd></dl>}{place&&<dl><dt>Place{place.illustrative?' · Illustrative':''}</dt><dd><Medal rank={place.rank} size={28}/> <span className="v15-result-place-total">of {place.total}</span></dd>{placeBasis&&<dd className="v15-result-basis">{placeBasis}</dd>}</dl>}{controls&&<div className="v15-result-controls">{controls}</div>}</div>;
}
export type Readout={label:string;value:ReactNode;power?:boolean};
export function ReadoutGrid({items,tone}:{items:readonly Readout[];tone?:'light'}){return <dl className="v15-readouts" data-tone={tone}>{items.map(item=><div key={item.label}><dt>{item.label}</dt><dd data-power={item.power||undefined}>{item.value}</dd></div>)}</dl>;}
export function Estimate({value,range,label}:{value:string;range?:string;label:string}){
 const [open,setOpen]=useState(false);
 if(!range)return <span>≈ {value}</span>;
 return <><button type="button" className="v15-estimate" aria-label={`${label}: approximately ${value}`} onClick={()=>setOpen(true)}>≈ {value}</button><Dialog open={open} onClose={()=>setOpen(false)} title={label}><p>{range}</p><Note>Founder copy</Note></Dialog></>;
}
export type AnalysisColumn={label:string;detail?:boolean;repeatOnCompact?:boolean};
export type AnalysisRow={id:string;cells:ReactNode[];active?:boolean;onHighlight?:()=>void};
export function AnalysisTable({label,columns,rows,total,onLeave}:{label:string;columns:readonly AnalysisColumn[];rows:readonly AnalysisRow[];total?:readonly ReactNode[];onLeave?:()=>void}){
 return <div className="v15-analysis-table" onMouseLeave={onLeave}><table aria-label={label}><thead><tr>{columns.map((c,i)=><th scope="col" key={i} data-detail={c.detail||undefined}>{c.label}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.id} data-active={row.active||undefined} onMouseEnter={row.onHighlight} onFocus={row.onHighlight} onBlur={onLeave} tabIndex={row.onHighlight?0:undefined}>{row.cells.map((cell,i)=><td key={i} data-detail={columns[i]?.detail||undefined}>{cell}{i===0&&columns.map((c,j)=>c.repeatOnCompact?<span className="v15-analysis-compact" key={j}>{row.cells[j]}</span>:null)}</td>)}</tr>)}</tbody>{total&&<tfoot><tr>{total.map((cell,i)=><td key={i} data-detail={columns[i]?.detail||undefined}>{cell}{i===0&&columns.map((c,j)=>c.repeatOnCompact?<span className="v15-analysis-compact" key={j}>{total[j]}</span>:null)}</td>)}</tr></tfoot>}</table></div>;
}
export function Zones({rows}:{rows:readonly {label:string;watts:string;time:string;percent:string;fraction:number}[]}){
 return <div className="v15-zones"><div className="v15-zone-bar" aria-hidden="true">{rows.map((row,i)=><span key={row.label} data-zone={i} style={{flex:row.fraction}}/>)}</div><AnalysisTable label="Power zones" columns={[{label:'Zone'},{label:'W'},{label:'Time'},{label:'%'}]} rows={rows.map((row,i)=>({id:row.label,cells:[<span className="v15-zone-name"><i data-zone={i}/>{row.label}</span>,row.watts,row.time,`${row.percent}%`]}))}/></div>;
}
