// Development-only component proof. Not registered in the workshop or production build.
import {createRoot} from 'react-dom/client';
import {ArrowUpRight} from 'lucide-react';
import {MapRowContentsV7,MapLeaderV7} from '../MapRowV7';
import type {MapV6Climb} from '../../v6/mapV6Leaderboard';
import '../../../workshop.css';
import '../../map-v2.css';
import '../../v5/map-v5.css';
import '../map-v7.css';

const id='00000000-0000-4000-8000-000000000001';
const climb:MapV6Climb={id,name:'Test climb',source:'Synthetic component fixture',lengthM:1000,riseM:80,gradePct:8,bounds:[0,0,1,1],
 profile:[{distanceM:0,elevationM:20},{distanceM:300,elevationM:60},{distanceM:600,elevationM:65},{distanceM:1000,elevationM:100}],
 publicLeaderboard:{sourceUrl:`https://api.boulderroller.xyz/climbs/${id}/leaderboard`,capturedAt:'2026-09-13T21:27:00Z',response:{climb_id:id,kom_holder:'test-wallet-not-a-real-rider',kom_time_s:120,entries:[{wallet:'test-wallet-not-a-real-rider',position:1,competition_rank:1,best_time_seconds:120,tie_size:1,is_tied:false}]}}};
const tied=structuredClone(climb);tied.publicLeaderboard!.response.entries[0].tie_size=2;tied.publicLeaderboard!.response.entries[0].is_tied=true;
createRoot(document.getElementById('root')!).render(<main className="m2-page m5-page m7-page" style={{height:'auto',minHeight:'100vh',padding:20,overflow:'auto'}}>
 <p style={{marginBottom:24,maxWidth:350}}>Component check · synthetic fixture.<br/>No real rider or climb result.</p>
 <section style={{width:352,maxWidth:'100%',display:'grid',gap:16}}>
  <button className="m2-row" aria-label="Synthetic first-place tile"><MapRowContentsV7 climb={climb}/></button>
  <button className="m2-row" aria-pressed="true" aria-label="Synthetic tied first-place tile"><MapRowContentsV7 climb={tied}/></button>
  <div className="m5-card" style={{border:'1px solid #c8cfbf',borderRadius:9}}><h2>Selected-card footer</h2><div className="m2-inspector-bottom"><MapLeaderV7 climb={climb}/><a className="m2-open-climb" href="#">Open climb<ArrowUpRight size={15}/></a></div></div>
 </section>
</main>);
