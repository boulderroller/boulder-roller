import {createContext,useContext,type ReactNode,type MouseEvent} from 'react';
import {openFeedRide} from './FeedV2Context';
import {v12RideHref} from './feedV12Model';
import type {FeedEntry} from './feedModel';
export const V12Navigation=createContext({scenarioId:'mixed',filter:'everyone',beforeNavigate:()=>{}});
export function useV12Destination(){
 const navigation=useContext(V12Navigation);
 return {save:navigation.beforeNavigate,href:(entry:FeedEntry,climb?:string,view:'overview'|'analysis'|'vault'='overview')=>v12RideHref(entry,climb,view,navigation.scenarioId,navigation.filter),open:(event:MouseEvent<HTMLAnchorElement>,href:string,before?:()=>void)=>openFeedRide(event,href,()=>{navigation.beforeNavigate();before?.();})};
}
export function FeedV12Link({entry,climb,view,children,...props}:{entry:FeedEntry;climb?:string;view?:'overview'|'analysis'|'vault';children:ReactNode;className?:string;onFocus?:()=>void;onBlur?:()=>void;onMouseEnter?:()=>void;onMouseLeave?:()=>void}){
 const destination=useV12Destination(),href=destination.href(entry,climb,view);
 return <a {...props} href={href} target="_top" onClick={e=>destination.open(e,href)}>{children}</a>;
}
