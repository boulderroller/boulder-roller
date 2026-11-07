import type {ReactNode} from 'react';
export function Card({children,flush=false}:{children:ReactNode;flush?:boolean}) {return <div className="v15-card" data-flush={flush}>{children}</div>;}
