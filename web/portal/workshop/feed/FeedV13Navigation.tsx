import {createContext,useContext,type ReactNode,type MouseEvent} from 'react';
import {openFeedRide} from './FeedV2Context';
import {v13RideHref,type FeedV13Scenario} from './feedV13Model';
import type {FeedEntry} from './feedModel';
export const V13Navigation=createContext<{scenario:FeedV13Scenario;filter:string;beforeNavigate:()=>void}|null>(null);
export function useV13Destination(){
 const navigation=useContext(V13Navigation);
 if(!navigation)throw new Error('Feed V13 navigation requires its provider');
 return {save:navigation.beforeNavigate,href:(entry:FeedEntry,climb?:string,view:'overview'|'analysis'|'vault'='overview')=>v13RideHref(entry,climb,view,navigation.scenario,navigation.filter),open:(event:MouseEvent<HTMLAnchorElement>,href:string,before?:()=>void)=>openFeedRide(event,href,()=>{navigation.beforeNavigate();before?.();})};
}
export function FeedV13Link({entry,climb,view,children,...props}:{entry:FeedEntry;climb?:string;view?:'overview'|'analysis'|'vault';children:ReactNode;className?:string;onFocus?:()=>void;onBlur?:()=>void;onMouseEnter?:()=>void;onMouseLeave?:()=>void}){
 const destination=useV13Destination(),href=destination.href(entry,climb,view);
 return <a {...props} href={href} target="_top" onClick={e=>destination.open(e,href)}>{children}</a>;
}
