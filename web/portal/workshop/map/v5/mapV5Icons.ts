import historic from './assets/historic.svg?raw';
import museum from './assets/museum.svg?raw';
import viewpoint from './assets/viewpoint.svg?raw';
import shelter from './assets/shelter.svg?raw';

let icons:Promise<{id:string;image:ImageData}[]>|undefined;
/** Local Maki CC0 artwork, rendered at 2x. The original SVGs remain untouched. */
export function landmarkImages(){
 return icons??=(Promise.all(Object.entries({historic,museum,viewpoint,shelter}).map(([id,svg])=>new Promise<{id:string;image:ImageData}>((resolve,reject)=>{
  const url=URL.createObjectURL(new Blob([svg.replace('<svg ','<svg fill="#64715d" ')],{type:'image/svg+xml'}));
  const image=new Image();
  image.onload=()=>{try{const canvas=document.createElement('canvas');canvas.width=30;canvas.height=30;const ctx=canvas.getContext('2d');if(!ctx)throw Error('Map symbol unavailable');ctx.drawImage(image,0,0,30,30);resolve({id:`m5-${id}`,image:ctx.getImageData(0,0,30,30)});}catch(error){reject(error);}finally{URL.revokeObjectURL(url);}};
  image.onerror=()=>{URL.revokeObjectURL(url);reject(Error('Map symbol unavailable'));};image.src=url;
 }))).catch(error=>{icons=undefined;throw error;}));
}
