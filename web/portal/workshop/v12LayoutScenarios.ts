import { scenarios } from './scenarios';
import { parseScenario, type Scenario } from './scenario';

// Layout fixtures only: unchanged recording, explicitly illustrative traversal
// windows and names. These are not additional detected or canonical climbs.
function layoutStudy(count: number): Scenario {
 const source=scenarios[0], samples=source.ride.samples;
 return parseScenario({
  ...source, id:`layout-${count}`, label:`${count} climbs · layout study`,
  source:{...source.source,history:'none',description:`Layout study with ${count} illustrative climb windows and names on the retained recording. GPS, time, elevation, power and cadence are unchanged. These windows are not detected climbs or canonical Vault matches. No history or economics is supplied.`},
  ride:{...source.ride,rider:{displayName:'Example Rider',source:'illustrative'}},
  climbs:Array.from({length:count},(_,i)=>{
   const start=Math.floor((i+.5)/(count+1)*(samples.length-1));
   const end=Math.min(samples.length-1,start+75);
   return {id:`layout-${count}-${i+1}`,name:i%7===6?`Layout study climb ${i+1} with a deliberately long name`:`Study climb ${i+1}`,start:samples[start].t,end:samples[end].t,history:[]};
  }),
 });
}
export const v12LayoutScenarios=[layoutStudy(10),layoutStudy(30)];
