import {v7RideHref,v7RiderHref,v7RideContext} from './feedV7Model';
export {v7NetworkItems as v8NetworkItems,riderForEntry,riderForBoard} from './feedV7Model';
export type {FeedV7Scenario as FeedV8Scenario,V7Rider as V8Rider} from './feedV7Model';
const origin=(href:string)=>{const u=new URL(href,'http://workshop.local');u.searchParams.set('feedVariant','feed-v8');return u.pathname+u.search;};
export const v8RideHref=(...args:Parameters<typeof v7RideHref>)=>origin(v7RideHref(...args));
export const v8RiderHref=(...args:Parameters<typeof v7RiderHref>)=>{const u=new URL(v7RiderHref(...args),'http://workshop.local');u.searchParams.set('variant','feed-v8');return u.pathname+u.search;};
export const v8RideContext=(...args:Parameters<typeof v7RideContext>)=>{const c=v7RideContext(...args);return c?{...c,climbs:c.climbs.map(climb=>({...climb,leaderboard:climb.leaderboard.map(row=>({...row,...(row.href?{href:origin(row.href)}:{})}))}))}:undefined;};
