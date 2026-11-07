// Isolated component proof; not a registered scenario or production entrypoint.
import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MapV7} from '../MapV7';
import {initialMapState,type MapStudy} from '../../mapModel';
import '../../../workshop.css';

const invalidPortrait='data:image/png;base64,broken';
const validPortrait='data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30"><rect width="30" height="30" fill="#737e58"/></svg>');
function Check(){
 const [portrait,setPortrait]=useState(invalidPortrait);
 const study:MapStudy={version:1,id:'identity-fixture',label:'Synthetic identity check',source:'Synthetic component fixture; no rider or climb evidence',climbs:[],viewer:{id:'fixture',name:'Example Rider',portrait}};
 return <><p style={{margin:12}}>Synthetic component check · no real rider data. <button onClick={()=>setPortrait(validPortrait)}>Use valid portrait</button></p><MapV7 study={study} viewer="rider" loadState="empty" snapshot={initialMapState(study)} active onChange={()=>{}} onRecover={()=>{}} detailHref={()=>'#'}/></>;
}
createRoot(document.getElementById('root')!).render(<Check/>);
