import {v10Effort,v10Ride} from './climbV10Model';
export const v13Effort=(href:string)=>v10Effort(href).replace('climbOriginVariant=climb-v10','climbOriginVariant=climb-v13');
export const v13Ride=(href:string)=>v10Ride(href).replace('climbOriginVariant=climb-v10','climbOriginVariant=climb-v13');
