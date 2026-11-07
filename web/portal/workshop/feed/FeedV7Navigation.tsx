import {createContext,useContext,type ReactNode,type MouseEvent} from 'react';
import {openFeedRide} from './FeedV2Context';
import {v7RideHref} from './feedV7Model';
import type {FeedEntry} from './feedModel';
export const V7Navigation=createContext({scenarioId:'mixed',filter:'everyone',beforeNavigate:()=>{}});
export function useV7Destination(){
 const navigation=useContext(V7Navigation);
 return {save:navigation.beforeNavigate,href:(entry:FeedEntry,climb?:string,view:'overview'|'analysis'|'vault'='overview')=>v7RideHref(entry,climb,view,navigation.scenarioId,navigation.filter),open:(event:MouseEvent<HTMLAnchorElement>,href:string,before?:()=>void)=>openFeedRide(event,href,()=>{navigation.beforeNavigate();before?.();})};
}
export function FeedV7Link({entry,climb,view,children,...props}:{entry:FeedEntry;climb?:string;view?:'overview'|'analysis'|'vault';children:ReactNode;className?:string;onFocus?:()=>void;onBlur?:()=>void;onMouseEnter?:()=>void;onMouseLeave?:()=>void}){
 const destination=useV7Destination(),href=destination.href(entry,climb,view);
 return <a {...props} href={href} target="_top" onClick={e=>destination.open(e,href)}>{children}</a>;
}
