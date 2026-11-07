// Use the unchanged canonical measurement tool with the six required widths.
import {sizes} from '../tools/page-tools.mjs';
sizes.splice(0,sizes.length,...[1440,1366,1280,1100,950,390].map(width=>({name:String(width),width,height:width===390?844:900})));
await import('../tools/v15-measure.mjs');
