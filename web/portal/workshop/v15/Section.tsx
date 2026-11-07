import {useId,type ReactNode} from 'react';
export function Section({title,aside,children}:{title:string;aside?:ReactNode;children:ReactNode}) {
 const id=useId();
 return <section className="v15-section" aria-labelledby={id}><header className="v15-section-head"><h2 id={id}>{title}</h2><span className="v15-rule"/>{aside&&<span className="v15-section-aside">{aside}</span>}</header><div className="v15-section-content">{children}</div></section>;
}
