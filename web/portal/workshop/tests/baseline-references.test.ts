import {test} from 'node:test';
import assert from 'node:assert/strict';
import {stravaReferencesFor} from '../baseline/referenceModel';
test('retained rooms use their relevant Strava screenshots and true source widths',()=>{
 const profile=stravaReferencesFor('profile');assert.ok(profile.some(c=>c.source.endsWith('03-profile-top.png')));assert.ok(profile.some(c=>c.viewportWidth===430));
 assert.ok(stravaReferencesFor('rides').some(c=>c.source.endsWith('11-my-activities-top.png')));
 for(const room of ['training','settings','search','legacy-analysis','public-rider','public-ride','public-climb','climb-flows','shell','ride-flows'])assert.ok(stravaReferencesFor(room).length,room);
 for(const room of ['portfolio','upload','notifications','access','guide','account-deletion'])assert.equal(stravaReferencesFor(room).length,0,room);
 assert.ok(profile.every(c=>c.kind==='historical Strava reference'&&c.date==='2026-09-09'&&c.url.startsWith('https://www.strava.com/')));
});
