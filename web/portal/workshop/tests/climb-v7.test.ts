import {test} from 'node:test';
import assert from 'node:assert/strict';
import {climbReturnHref,carryClimbOrigin} from '../climb/climbV3Navigation';

test('V7 effort browsing returns to its own candidate and preserves visitor access',()=>{
 const origin=new URLSearchParams({climbOrigin:'wises',climbOriginId:'43f15658',climbOriginViewer:'visitor',climbOriginVariant:'climb-v7',viewer:'visitor'});
 const destination=new URL(carryClimbOrigin('/?surface=ride&viewer=owner',origin),'http://local.test').searchParams;
 assert.equal(climbReturnHref(destination),'/?surface=climb&variant=climb-v7&scenario=wises&viewer=visitor');
 assert.equal(destination.get('viewer'),'visitor');
});

import {climbV7Studies,parseV7Study,historyGap} from '../climb/climbV7Model';
test('an imported history binding cannot grant owner analysis to an unowned recording',()=>{
 const study=structuredClone(climbV7Studies.find(s=>s.id==='wises')!);
 const entry=study.feed!.entries.find(e=>e.id===study.candidate7!.historyRecordings[0].entryId)!;
 entry.owned=false;
 assert.throws(()=>parseV7Study(study),/History recording must/);
});

test('history gaps retain the precision of the displayed effort times',()=>{
 assert.equal(historyGap(235.4,235),'+0.4');
 assert.equal(historyGap(235,235.4),'−0.4');
 assert.equal(historyGap(239.99,240),'0');
});
