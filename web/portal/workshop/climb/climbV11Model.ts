import {v10Effort,v10Ride} from './climbV10Model';
export const v11Effort=(href:string)=>v10Effort(href).replace('climbOriginVariant=climb-v10','climbOriginVariant=climb-v11');
export const v11Ride=(href:string)=>v10Ride(href).replace('climbOriginVariant=climb-v10','climbOriginVariant=climb-v11');
