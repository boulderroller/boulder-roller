import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {boardComplete,boardGap,boardLeader,boardRows,distanceTicks,heroFitPadding,plural,podiumRows,powerColumn,roundTicks,stripCells,v14Effort,v14Ride} from '../climb/climbV14Model';
import {climbReturnHref} from '../climb/climbV3Navigation';
import {climbById} from '../climb/climbModel';
import {inspectV7} from '../climb/climbV7Model';
import {v9Study} from '../climb/climbV9Model';
import {roomDestination} from '../roomRegistry';
const source=(file:string)=>readFileSync(new URL(`../climb/${file}`,import.meta.url),'utf8');
test('V14 effort and ride links return to V14 with their viewer context',()=>{
 const href='/?surface=ride&scenario=r&climb=c&from=1&to=2&climbOrigin=wises&climbOriginViewer=visitor';
 for(const destination of [v14Ride(href),v14Effort(href)])assert.equal(climbReturnHref(new URL(destination,'http://local.test').searchParams),'/?surface=climb&variant=climb-v14&scenario=wises&viewer=visitor');
});
test('V14 is registered as a candidate while V13 stays the default and the room destination',()=>{
 const workshop=source('ClimbWorkshop.tsx'),preview=source('ClimbPreview.tsx');
 assert.match(workshop,/\{id:'climb-v14',label:'Candidate v14'\}(?:,\{id:'climb-v\d+',label:'Candidate v\d+'\})*\] as const/);
 assert.match(workshop,/v==='climb-v14'\?'climb-v14':'climb-v13';/);
 assert.match(workshop,/'climb-v13','climb-v14'(?:,'climb-v\d+')*\]\.includes\(variant\)\?v9Study/);
 assert.match(preview,/settings\.variant==='climb-v14'\?ClimbV14:/);
 assert.match(preview,/'climb-v13','climb-v14'(?:,'climb-v\d+')*\]\.includes\(rest\.variant\)\?parseV9Study/);
 assert.match(roomDestination('climb'),/variant=climb-v13/);
});
test('V14 draws only from its own stylesheet and the V14 variable face',()=>{
 const css=source('climb-v14.css'),room=source('ClimbV14.tsx');
 assert.match(css,/@font-face\{font-family:'Geist V14';src:url\('\.\/fonts\/geist-variable-latin\.woff2'\)/);
 assert.doesNotMatch(room,/climb-v(?:[2-9]|1[0-3])\.css/);
 for(const weight of css.matchAll(/font-weight:(\d+)(?![\d ])/g))assert.ok(['400','440','560'].includes(weight[1]),`unexpected weight ${weight[1]}`);
 for(const size of css.matchAll(/font-size:(\d+)px/g))assert.ok(Number(size[1])>=11,`text under 11px: ${size[1]}`);
});
test('the board rows match V13: overall carries dates, qualified uses vault attempts, empty clears',()=>{
 const study=v9Study(climbById('wises')),data=inspectV7(study,'rider');
 const overall=boardRows(data,study,'ready','overall');
 assert.equal(overall.length,data.board?.rows.length);
 assert.ok(overall.every(r=>r.date));
 assert.equal(overall.filter(r=>r.current).length,1);
 assert.deepEqual(boardRows(data,study,'empty','overall'),[]);
 const qualified=boardRows(data,study,'ready','qualified');
 assert.equal(qualified.length,study.candidate9?.attempts.length??0);
});
const r=(rank:number,duration:number,current=false)=>({rank,duration,current});
const full=[r(1,225.9),r(2,227.2),r(3,228.5),r(4,231),r(5,235,true)];
test('gaps print in tenths from a fastest the board holds, and vanish without one',()=>{
 assert.equal(boardGap(227.2,r(1,225.9)),1.3);
 assert.equal(boardGap(225.9,r(1,225.9)),0);
 assert.equal(boardGap(230,undefined),null);
 assert.equal(boardGap(251,r(3,251)),null,'a partial board that starts at 3rd has no fastest');
});
test('a partial board claims no leader, no rider count and no podium',()=>{
 const study=v9Study(climbById('sprague')),data=inspectV7(study,'visitor'),rows=boardRows(data,study,'ready','overall');
 assert.deepEqual(rows.map(x=>x.rank),[3]);
 assert.equal(boardLeader(rows),undefined);
 assert.equal(boardComplete(rows),false);
 assert.deepEqual(podiumRows(rows),[]);
 assert.deepEqual(stripCells({viewer:'visitor',overall:rows}),[]);
 assert.deepEqual(stripCells({viewer:'rider',overall:rows}),[]);
});
test('a full board leads, counts and builds the podium from its top three places',()=>{
 assert.equal(boardLeader(full)?.rank,1);
 assert.equal(boardComplete(full),true);
 assert.equal(boardComplete([r(1,1),r(1,1),r(3,2)]),true,'ties share a place');
 assert.equal(boardComplete([r(1,1),r(2,2),r(5,3)]),false,'a gap in the places is a partial board');
 assert.deepEqual(podiumRows(full).map(x=>x.rank),[1,2,3]);
 assert.deepEqual(podiumRows([r(1,1),r(2,2)]).map(x=>x.rank),[1,2]);
});
test('the strip summarises the rider and never restates the podium or the board foot',()=>{
 assert.deepEqual(stripCells({viewer:'rider',personal:{rank:5},overall:full,legend:{},economy:{}}),['best','overall','legend']);
 assert.deepEqual(stripCells({viewer:'rider',personal:{},overall:full.map(x=>({...x,current:false})),economy:{}}),['best'],'no place and no Local Legend: only the best');
 assert.deepEqual(stripCells({viewer:'rider',personal:{rank:1},overall:[r(1,200,true),r(2,210)],legend:{},economy:{}}),['best','overall','legend']);
 assert.deepEqual(stripCells({viewer:'rider',personal:undefined,overall:[...full.slice(0,4),r(5,235,true)]}),['overall'],'a board row without history still gives the place');
 assert.deepEqual(stripCells({viewer:'visitor',personal:undefined,overall:full,legend:{},economy:{}}),[],'a visitor meets Local Legend in the board foot');
 assert.deepEqual(stripCells({viewer:'signed-out',overall:full,legend:{},economy:{}}),[]);
 assert.deepEqual(stripCells({viewer:'rider',personal:undefined,overall:full.map(x=>({...x,current:false})),legend:{},economy:{}}),[],'a first visit has no place to summarise');
 assert.deepEqual(stripCells({viewer:'rider',personal:{rank:5},overall:full,legend:{}}),['best','overall'],'Local Legend comes with the Vault economy');
 for(const kind of ['fastest','leaderboard'])assert.doesNotMatch(source('ClimbV14.tsx'),new RegExp(`case '${kind}'`));
});
test('Local Legend goes to the board foot only when the strip does not carry it',()=>{
 const room=source('ClimbV14.tsx');
 assert.match(room,/legend=\{economy&&!cells\.includes\('legend'\)\?legendFact:undefined\}/);
 assert.match(source('ClimbV14Board.tsx'),/\{legend&&<span className="c14-foot-legend">/);
});
test('the Black Rock rider holds a board row without history: the strip takes the place from it',()=>{
 const study=v9Study(climbById('black-rock')),data=inspectV7(study,'rider'),rows=boardRows(data,study,'ready','overall');
 assert.equal(data.personal,undefined);
 assert.deepEqual(stripCells({viewer:'rider',personal:data.personal,overall:rows}),['overall']);
});
test('power earns a column only when most rows carry it',()=>{
 assert.equal(powerColumn([272,null,null,null]),false);
 assert.equal(powerColumn([272,301,null]),true);
 assert.equal(powerColumn([]),false);
});
test('counts are pluralised; allocation values print at their own precision through vaultNumber',()=>{
 assert.equal(plural(1,'rider'),'1 rider');
 assert.equal(plural(10,'rider'),'10 riders');
 assert.equal(plural(5,'effort'),'5 efforts');
 const vault=source('ClimbV14Vault.tsx');
 assert.match(vault,/<dd>\{vaultNumber\(active\.allocations\[key\]\)\}<Unit>DUNG<\/Unit><\/dd>/);
 assert.doesNotMatch(vault,/fixedNumber|rowPrecision/);
});
test('profile ticks sit on round values inside the climb, and the distance end keeps its own label',()=>{
 assert.deepEqual(roundTicks(46.6,106.9),[50,75,100]);
 assert.deepEqual(roundTicks(55.2,123.4),[60,80,100,120]);
 assert.deepEqual(roundTicks(90.8,99.9),[92.5,95,97.5]);
 assert.deepEqual(roundTicks(90.8,118),[100,110],'Black Rock: two round lines beat five crowded ones');
 assert.deepEqual(roundTicks(12.5,99.9),[25,50,75]);
 assert.deepEqual(roundTicks(5,5),[]);
 for(const [lo,hi] of [[46.6,106.9],[90.8,99.9],[0,3]])for(const t of roundTicks(lo,hi))assert.ok(t>=lo&&t<=hi,'ticks never claim an elevation outside the climb');
 assert.deepEqual(distanceTicks(1160),[0,0.5]);
 assert.deepEqual(distanceTicks(590),[0,0.25]);
 assert.deepEqual(distanceTicks(2000),[0,1]);
 assert.deepEqual(distanceTicks(2030),[0,1]);
});
test('the Vault keeps the climb totals out of Your position: a card of their own under the climb name',()=>{
 const vault=source('ClimbV14Vault.tsx'),position=vault.slice(vault.indexOf('c14-position'),vault.indexOf('c14-vault-climb'));
 assert.doesNotMatch(position,/lifetimeTributeCal|depositedPrincipalCal|c14-inset/);
 assert.match(vault,/<section className="c14-card c14-vault-climb" aria-label=\{`\$\{name\} Vault`\}>\s*<div className="c14-card-top"><p className="c14-kicker">\{name\}<\/p>/);
});
test('the frame names the room: phone title is the climb, breadcrumb uses a chevron, wordmark is plain',()=>{
 const shell=source('ClimbV14Shell.tsx');
 assert.match(shell,/<span className="c14-phone-title">\{name\?\?'Map'\}<\/span>/);
 assert.match(shell,/<li aria-hidden="true"><ChevronRight\/><\/li>/);
 assert.match(shell,/<Link href=\{feedHref\}>Boulder Roller<\/Link>/);
 assert.doesNotMatch(shell,/c14-nav-sub|<Mark/);
});
test('the masthead fit draws the route in the clear right half on desktop and clear of the chrome on phone',()=>{
 assert.deepEqual(heroFitPadding(1190,400,false),{left:619,right:64,top:40,bottom:56});
 assert.deepEqual(heroFitPadding(372,218,true),{left:24,right:24,top:44,bottom:44});
});
test('V14 keeps its own dialog: the only filled button is Collect DUNG, which commits',()=>{
 const vault=source('ClimbV14Vault.tsx'),action=source('ClimbV14Action.tsx'),css=source('climb-v14.css');
 assert.doesNotMatch(vault,/<ClimbV8Action/);
 assert.match(action,/className="c14-button" onClick=\{onClose\}>Back to Vault/);
 assert.match(action,/className="c14-button c14-button-wide" disabled=\{!valid\}>Review deposit/);
 assert.doesNotMatch(action,/c14-primary/);
 assert.equal([...vault.matchAll(/className="c14-primary"/g)].length,1);
 assert.match(vault,/className="c14-primary" onClick=\{\(\)=>setAction\('collect'\)\}>Collect DUNG<\/button>/);
 assert.doesNotMatch(css,/c7-primary-button/);
 assert.doesNotMatch(css,/^\.c14-page :is\(button|^\.c14-page :is\(strong/m,'resets must not outrank single-class rules');
});
