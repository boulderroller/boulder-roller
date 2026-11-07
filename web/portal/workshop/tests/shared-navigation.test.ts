import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ROOMS, FINAL_ROOMS, roomFor, roomDestination, finalsDestination, finalsActive} from '../roomRegistry';

test('shared dispatch keeps Map and the locked Climb candidate as room defaults',()=>{
 assert.equal(roomFor('map').id,'map');
 assert.equal(roomFor('climb').id,'climb');
 assert.match(roomDestination('map'), /variant=map-v7/);
 assert.match(roomDestination('climb'), /variant=climb-v13/);
 assert.equal(roomFor('unknown').id,'ride');
});

test('finals open every room on its locked, settled or accepted candidate',()=>{
 for (const [id,variant] of [['ride','candidate-v13'],['feed','feed-v9'],['climb','climb-v13'],['map','map-v7'],['profile','profile-v6']] as const) {
  assert.match(finalsDestination(id), new RegExp(`variant=${variant}(&|$)`));
  assert.match(finalsDestination(id), /finals=1/);
 }
 assert.ok(ROOMS.every(room=>room.finals.length>0));
 assert.deepEqual(FINAL_ROOMS.map(room=>room.id), ['ride','feed','climb','map','profile']);
 assert.ok(ROOMS.filter(room=>!room.hasFinal).every(room=>room.finals.includes('no locked candidate yet')));
 assert.equal(finalsActive('?surface=climb&finals=1'), true);
 assert.equal(finalsActive('?surface=climb'), false);
});
