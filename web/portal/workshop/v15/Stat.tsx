import type {ReactNode} from 'react';
export function Unit({children}:{children:ReactNode}) {return <span className="v15-unit">{children}</span>;}
export function Stat({label,value,basis}:{label:string;value:ReactNode;basis?:ReactNode}) {
 return <dl className="v15-stat"><dt>{label}</dt><dd className="v15-stat-value">{value}</dd>{basis!==undefined&&<dd className="v15-stat-basis">{basis}</dd>}</dl>;
}
export function Stats({children,compact=false}:{children:ReactNode;compact?:boolean}) {return <div className="v15-stats" data-compact={compact||undefined}>{children}</div>;}
