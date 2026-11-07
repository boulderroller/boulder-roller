import type {ButtonHTMLAttributes,ReactNode} from 'react';
type ButtonProps=Omit<ButtonHTMLAttributes<HTMLButtonElement>,'className'|'style'>;
export function Button({variant='secondary',...props}:ButtonProps&{variant?:'primary'|'secondary'|'text'}) {return <button type="button" {...props} className="v15-button" data-variant={variant}/>;}
export function IconButton({size='quiet',label,children,...props}:ButtonProps&{size?:'quiet'|'bordered'|'help'|'map';label:string;children:ReactNode}) {return <button type="button" {...props} aria-label={label} className="v15-icon-button" data-size={size}>{children}</button>;}
export function Segmented<T extends string>({label,options,value,onChange,disabled=false}:{label:string;options:readonly {value:T;label:string}[];value:T;onChange:(value:T)=>void;disabled?:boolean}) {
 return <div className="v15-segmented" role="group" aria-label={label}>{options.map(option=><button type="button" key={option.value} aria-pressed={value===option.value} disabled={disabled} onClick={()=>onChange(option.value)}>{option.label}</button>)}</div>;
}
export function Chip({kind='tag',children}:{kind?:'tag'|'status';children:ReactNode}) {return <span className="v15-chip" data-kind={kind}>{children}</span>;}
