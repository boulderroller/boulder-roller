import {createRoot} from 'react-dom/client';
import {Leaderboard} from '../v15/Rows';

export function pinSample(){
 const board=document.querySelector<HTMLElement>('.v15-leaderboard')!,pin=board.querySelector<HTMLElement>('.v15-board-pin')!,slot=board.querySelector<HTMLElement>('.v15-board-pin-space')!;
 const real=board.querySelector('.v15-board-rows [data-current=true]')?.getBoundingClientRect(),box=pin.getBoundingClientRect(),boardBox=board.getBoundingClientRect();
 const visible=getComputedStyle(pin).visibility==='visible',realOnScreen=!!real&&real.top<innerHeight&&real.bottom>0;
 const first=board.querySelector('.v15-board-rows .v15-board-row')?.getBoundingClientRect(),slotHeight=slot.getBoundingClientRect().height,rowsBox=board.querySelector('.v15-board-rows')!.getBoundingClientRect();
 const rowsOnScreen=!!first&&first.top<innerHeight-slotHeight&&rowsBox.bottom>0;
 // Hit-test the strip where the sticky slot rides: an empty slot must let clicks through to the rows beneath it.
 const slotBox=slot.getBoundingClientRect(),deadZone:string[]=[];
 for(const fx of [.25,.5,.75]){const x=slotBox.left+slotBox.width*fx,y=slotBox.top+slotBox.height/2;if(y<0||y>=innerHeight)continue;const hit=document.elementFromPoint(x,y);if(hit&&slot.contains(hit)&&!(visible&&pin.contains(hit)))deadZone.push(`${Math.round(x)},${Math.round(y)}`);}
 // The final child's normal-flow slot ends at the board's bottom. Sticky
 // displacement must not change that reserved space or the following section.
 const slotTop=boardBox.bottom-slot.getBoundingClientRect().height,coversOutsideBoard=new Set<string>();
 if(visible)for(const fx of [.1,.5,.9])for(const fy of [.25,.75]){
  const x=box.left+box.width*fx,y=box.top+box.height*fy;
  if(y<0||y>=innerHeight)continue;
  const stack=document.elementsFromPoint(x,y),at=stack.findIndex(el=>pin.contains(el));
  if(at<0)continue;
  for(const el of stack.slice(at+1))if(!board.contains(el)&&!el.contains(board))coversOutsideBoard.add(`${el.tagName.toLowerCase()}.${[...el.classList].join('.')}`);
 }
 return {y:scrollY,visible,realOnScreen,rowsOnScreen,deadZone,pinTop:box.top,pinHeight:box.height,slotTop,expectedTop:Math.min(slotTop,innerHeight-box.height),boardTop:boardBox.top,boardBottom:boardBox.bottom,parentMinTop:boardBox.top+parseFloat(getComputedStyle(slot).marginTop),viewportHeight:innerHeight,position:getComputedStyle(pin).position,slotPosition:getComputedStyle(slot).position,slotBottom:getComputedStyle(slot).bottom,directChild:slot.parentElement===board,coversOutsideBoard:[...coversOutsideBoard],nextSectionDocTop:document.querySelectorAll('.v15-section')[1].getBoundingClientRect().top+scrollY};
}

export async function inlinePeriodsScrollCalls(){
 const element=document.createElement('div');element.className='v15-kit';document.body.append(element);
 const root=createRoot(element),previous=history.state,scroll=window.scrollTo;
 let calls=0;
 window.scrollTo=((...args:unknown[])=>{calls++;Reflect.apply(scroll,window,args);}) as typeof scroll;
 const render=()=>root.render(<Leaderboard initialRows={[]} signedIn={false} periods={[{value:'all-time',label:'All time'}]}/>);
 try{
  history.replaceState({...previous,v15Scroll:100},'');
  render();await new Promise(resolve=>setTimeout(resolve,80));
  calls=0;render();await new Promise(resolve=>setTimeout(resolve,80));return calls;
 }finally{window.scrollTo=scroll;history.replaceState(previous,'');root.unmount();element.remove();}
}
