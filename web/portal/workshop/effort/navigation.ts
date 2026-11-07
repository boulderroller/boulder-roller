/** Page-history restoration also works for direct preview tabs and reloads. */
export function rememberEffortScroll(){history.replaceState({...history.state,effortScroll:scrollY},'',location.href);}
export function installEffortHistory(){
 const restore=()=>{if(Number.isFinite(history.state?.effortScroll))requestAnimationFrame(()=>window.scrollTo(0,history.state.effortScroll));};
 const click=(event:MouseEvent)=>{if((event.target as Element)?.closest('a[href]'))rememberEffortScroll();};
 window.addEventListener('pagehide',rememberEffortScroll);window.addEventListener('pageshow',restore);window.addEventListener('popstate',restore);document.addEventListener('click',click,true);restore();
 return()=>{window.removeEventListener('pagehide',rememberEffortScroll);window.removeEventListener('pageshow',restore);window.removeEventListener('popstate',restore);document.removeEventListener('click',click,true);};
}
