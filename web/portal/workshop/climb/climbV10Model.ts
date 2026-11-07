import {v9Effort,v9Ride} from './climbV9Model';

export const v10Effort=(href:string)=>v9Effort(href).replace('climbOriginVariant=climb-v9','climbOriginVariant=climb-v10');
export const v10Ride=(href:string)=>v9Ride(href).replace('climbOriginVariant=climb-v9','climbOriginVariant=climb-v10');

export const vaultNumber=(value:number)=>value.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:9});
