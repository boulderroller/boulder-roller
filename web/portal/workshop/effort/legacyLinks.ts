import {effortHref,findEffort,queryState} from './model';
import {installEffortHistory,rememberEffortScroll} from './navigation';

// Explicit opt-in integration. Frozen candidates retain their source and their
// normal navigation. Recorded Wises/Black Rock links enter the canonical view.
installEffortHistory();
document.addEventListener('click',event=>{
 if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
 const element=event.target as Element,link=element.closest<HTMLAnchorElement>('a[href]');
 if(!link)return;
 const url=new URL(link.href),state=queryState(location.search),params=new URLSearchParams(location.search);
 const climbId=url.searchParams.get('climb'),name=link.querySelector('.r14-climb-copy')?.textContent??'';
 const slug=climbId==='43f15658'||name.includes('Wises Mill')?'wises':climbId==='4fd1981e'||name.includes('Black Rock')?'black-rock':null;
 const timeLink=link.classList.contains('r14-result-row')||link.getAttribute('aria-label')?.startsWith('Analyze')||url.searchParams.get('view')==='analysis';
 if(!slug||!timeLink)return;
 event.preventDefault();event.stopImmediatePropagation();rememberEffortScroll();
 const effort=findEffort(slug,state.gates),viewer=params.get('viewer')==='signed-out'?'anon':state.viewer;
 location.assign(effortHref(effort,viewer));
},true);
