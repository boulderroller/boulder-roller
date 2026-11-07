import type {MouseEvent,ReactNode} from 'react';
export function ClimbV7Link({href,children,className,label}:{href:string;children:ReactNode;className?:string;label?:string}){
 function visit(e:MouseEvent<HTMLAnchorElement>){if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();window.parent.postMessage({type:'climb-open',href},location.origin);}
 return <a className={className} aria-label={label} href={href} target="_top" onClick={visit}>{children}</a>;
}
