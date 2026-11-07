import type {ReactNode} from 'react';

/** One neutral account surface for the climb's Vault and the rider's position. */
export function ClimbV10Plate({title,action,children,className='',label}:{title:string;action?:ReactNode;children:ReactNode;className?:string;label?:string}){
 return <section className={`c10-plate ${className}`} aria-label={label??title}>
  <header className="c10-plate-header"><h3>{title}</h3>{action}</header>
  {children}
 </section>;
}
