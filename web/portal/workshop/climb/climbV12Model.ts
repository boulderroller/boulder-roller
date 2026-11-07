import {v10Effort,v10Ride} from './climbV10Model';
export const v12Effort=(href:string)=>v10Effort(href).replace('climbOriginVariant=climb-v10','climbOriginVariant=climb-v12');
export const v12Ride=(href:string)=>v10Ride(href).replace('climbOriginVariant=climb-v10','climbOriginVariant=climb-v12');
