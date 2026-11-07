import {v7RideHref,v7RiderHref,v7RideContext} from './feedV7Model';
export {v7NetworkItems as v9NetworkItems,riderForEntry,riderForBoard} from './feedV7Model';
export type {FeedV7Scenario as FeedV9Scenario,V7Rider as V9Rider} from './feedV7Model';
const origin=(href:string)=>{const u=new URL(href,'http://workshop.local');u.searchParams.set('feedVariant','feed-v9');return u.pathname+u.search;};
export const v9RideHref=(...args:Parameters<typeof v7RideHref>)=>origin(v7RideHref(...args));
export const v9RiderHref=(...args:Parameters<typeof v7RiderHref>)=>{const u=new URL(v7RiderHref(...args),'http://workshop.local');u.searchParams.set('variant','feed-v9');return u.pathname+u.search;};
export const v9RideContext=(...args:Parameters<typeof v7RideContext>)=>{const c=v7RideContext(...args);return c?{...c,climbs:c.climbs.map(climb=>({...climb,leaderboard:climb.leaderboard.map(row=>({...row,...(row.href?{href:origin(row.href)}:{})}))}))}:undefined;};
