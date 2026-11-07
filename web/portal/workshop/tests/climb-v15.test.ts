import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {boardLeader,boardRows,endLabelAnchor,gapScale,gradeBands,heroFitPadding15,heroFor,localGrade,overallBasis,pitchGrade,railClimbs,v15Effort,v15Ride} from '../climb/climbV15Model';
import {climbReturnHref} from '../climb/climbV3Navigation';
import {climbById,climbStudies} from '../climb/climbModel';
import {inspectV7} from '../climb/climbV7Model';
import {v9Study} from '../climb/climbV9Model';
import {roomDestination} from '../roomRegistry';
const source=(file:string)=>readFileSync(new URL(`../climb/${file}`,import.meta.url),'utf8');
const terrainOf=(id:string)=>inspectV7(v9Study(climbById(id)),'rider').terrain!;
const r=(rank:number,duration:number,current=false)=>({rank,duration,current});

test('V15 is registered as a candidate while V13 stays the default and the room destination',()=>{
 const workshop=source('ClimbWorkshop.tsx'),preview=source('ClimbPreview.tsx');
 assert.match(workshop,/\{id:'climb-v15',label:'Candidate v15'\},\{id:'climb-v16',label:'Candidate v16'\}\] as const/);
 assert.match(workshop,/v==='climb-v15'\?'climb-v15':/);
 assert.match(workshop,/'climb-v14','climb-v15','climb-v16'\]\.includes\(variant\)\?v9Study/);
 assert.match(workshop,/<select aria-label="Masthead"/);
 assert.match(preview,/settings\.variant==='climb-v15'\)return <ClimbV15 /);
 assert.match(preview,/'climb-v14','climb-v15','climb-v16'\]\.includes\(rest\.variant\)\?parseV9Study/);
 assert.match(source('climbV3Navigation.ts'),/'climb-v14','climb-v15','climb-v16'\]/);
 assert.match(roomDestination('climb'),/variant=climb-v13/);
});
test('the masthead direction defaults to A and accepts only B or C otherwise',()=>{
 assert.equal(heroFor(null),'a');
 assert.equal(heroFor('b'),'b');
 assert.equal(heroFor('c'),'c');
 assert.equal(heroFor('d'),'a');
});
test('V15 effort and ride links return to V15 with their viewer context',()=>{
 const href='/?surface=ride&scenario=r&climb=c&from=1&to=2&climbOrigin=wises&climbOriginViewer=visitor';
 for(const destination of [v15Ride(href),v15Effort(href)])assert.equal(climbReturnHref(new URL(destination,'http://local.test').searchParams),'/?surface=climb&variant=climb-v15&scenario=wises&viewer=visitor');
});
test('grade bands follow production: 100 m bins, equal rungs merged and regraded',()=>{
 const wises=terrainOf('wises');
 assert.deepEqual(gradeBands(wises.profile,wises.length).map(b=>Number(b.grade.toFixed(1))),[0.7,6.2,4.5,6.0,5.8,7.5,4.0,8.1]);
 const sprague=terrainOf('sprague'),bands=gradeBands(sprague.profile,sprague.length);
 assert.ok(bands.some(b=>b.rung===3&&Math.abs(b.grade-11.9)<.05),'the 11.9% wall');
 assert.ok(bands.some(b=>b.grade<3),'the false flat');
 for(let i=1;i<bands.length;i++){assert.notEqual(bands[i].rung,bands[i-1].rung,'adjacent bands sit on different rungs');assert.equal(bands[i].from,bands[i-1].to);}
 assert.equal(bands.at(-1)!.to,sprague.length);
 assert.deepEqual(gradeBands([{d:0,elevation:1}],100),[]);
});
test('local grade uses the ±25 m window, clamped to the climb',()=>{
 const flat=[{d:0,elevation:10},{d:100,elevation:20}];
 assert.equal(Number(localGrade(flat,100,50).toFixed(6)),10);
 assert.equal(Number(localGrade(flat,100,0).toFixed(6)),10,'clamped at the start');
 assert.equal(localGrade([{d:0,elevation:5},{d:0,elevation:5}],0,0),0);
});
test('gap bars scale to the largest gap in view and vanish without a fastest',()=>{
 const scale=gapScale([r(1,200),r(2,210),r(3,240)])!;
 assert.equal(scale(200),0);
 assert.equal(scale(220),.5);
 assert.equal(scale(240),1);
 assert.equal(gapScale([r(3,251)]),null,'a partial board has no fastest');
 assert.equal(gapScale([]),null,'an empty board draws nothing');
 assert.equal(gapScale([r(1,200)])!(200),0,'a lone leader has no bar');
});
test('Black Rock: the rider has a board place and no history, so Overall carries the board time and the gap',()=>{
 const study=v9Study(climbById('black-rock')),data=inspectV7(study,'rider'),rows=boardRows(data,study,'ready','overall');
 assert.equal(data.personal,undefined);
 assert.deepEqual(overallBasis(rows.find(x=>x.current),boardLeader(rows)),{duration:82,gap:5.2});
 assert.deepEqual(overallBasis(r(3,251,true),undefined),{duration:251,gap:null},'no fastest: time only');
 assert.equal(overallBasis(undefined,r(1,1)),null);
});
test('the rail lists the four distinct climbs the data holds, named from terrain, linked to V15 with viewer and hero',()=>{
 const items=railClimbs(climbStudies,{current:climbById('wises'),viewer:'rider',hero:'b',state:'ready'});
 assert.deepEqual(items.map(i=>i.name),['Wises Mill Road','Black Rock Road','Sprague Road','Jefferson Street / North Woodbine Avenue']);
 assert.equal(new Set(items.map(i=>i.climbId)).size,4);
 for(const item of items){const q=new URL(item.href,'http://local.test').searchParams;assert.equal(q.get('variant'),'climb-v15');assert.equal(q.get('viewer'),'rider');assert.equal(q.get('hero'),'b');}
 assert.deepEqual(items.map(i=>i.active),[true,false,false,false]);
 assert.deepEqual(items.map(i=>i.rank),[7,4,undefined,undefined],'places only where the board holds one');
 assert.ok(railClimbs(climbStudies,{current:climbById('sprague'),viewer:'visitor',hero:'a',state:'ready'}).every(i=>i.rank===undefined),'a visitor has no places');
 const firstStudy=v9Study(climbById('first-visit')),firstRows=boardRows(inspectV7(firstStudy,'rider'),firstStudy,'ready','overall');
 const first=railClimbs(climbStudies,{current:climbById('first-visit'),viewer:'rider',hero:'a',state:'ready'});
 assert.equal(first[0].active,true);
 assert.equal(first[0].rank,firstRows.find(x=>x.current)?.rank,'the active climb takes its place from the study being viewed');
 for(const s of ['ClimbV15.tsx','ClimbV15Shell.tsx'])assert.doesNotMatch(source(s),/'Black Rock Road'|'Sprague Road'/,'names are never hard-coded');
});
test('the open climb shows no place while its results load, are empty or fail; the other climbs keep theirs',()=>{
 for(const state of ['loading','empty','error'] as const){
  const items=railClimbs(climbStudies,{current:climbById('wises'),viewer:'rider',hero:'a',state});
  assert.equal(items[0].active,true);
  assert.equal(items[0].rank,undefined,`no place on the open climb while ${state}`);
  assert.equal(items[1].rank,4,'Black Rock keeps its own place');
 }
});
test('pitch grades never print -0.0, use a true minus, and carry no plus sign',()=>{
 assert.equal(pitchGrade(6.24),'6.2');
 assert.equal(pitchGrade(-0.04),'0.0');
 assert.equal(pitchGrade(0),'0.0');
 assert.equal(pitchGrade(-0.5),'−0.5');
 assert.equal(pitchGrade(11.94),'11.9');
});
test('end labels sit on the side away from the line',()=>{
 assert.equal(endLabelAnchor([1,0],[0,0]).anchor,'left');
 assert.equal(endLabelAnchor([0,0],[1,0]).anchor,'right');
 assert.equal(endLabelAnchor([0,1],[0,0]).anchor,'bottom','north is up: the label sits above');
 assert.equal(endLabelAnchor([0,0],[0,1]).anchor,'top');
 assert.deepEqual(endLabelAnchor([1,0],[0,0]).offset,[8,0]);
});
test('the route fit keeps the copy clear and at least 48px on every edge',()=>{
 assert.deepEqual(heroFitPadding15(1172,320,false,'a'),{left:610,right:100,top:48,bottom:48});
 assert.deepEqual(heroFitPadding15(1172,248,false,'c'),{left:633,right:100,top:48,bottom:48});
 assert.deepEqual(heroFitPadding15(773,232,false,'card'),{top:48,right:48,bottom:48,left:48});
 // A's phone masthead keeps 76px on top: the credit and Expand map sit there, and an end label must clear them (Sprague's Start).
 assert.deepEqual(heroFitPadding15(374,400,true,'a'),{top:76,right:84,bottom:236,left:48});
 assert.deepEqual(heroFitPadding15(374,300,true,'c'),{top:48,right:84,bottom:168,left:48});
 assert.deepEqual(heroFitPadding15(374,240,true,'card'),{top:48,right:48,bottom:48,left:48});
 assert.deepEqual(heroFitPadding15(374,600,true,'b'),{top:48,right:84,bottom:176,left:48});
});
test('A lays its type on the green ground; only C keeps the night ground',()=>{
 const hero=source('ClimbV15Hero.tsx'),map=source('ClimbV15Map.tsx'),css=source('climb-v15.css');
 assert.match(hero,/data-hero="a"[^\n]*<HeroMap t=\{t\} map=\{map\} ground="light"\/>/);
 assert.match(hero,/data-hero="c"[\s\S]*?<HeroMap t=\{t\} map=\{map\} ground="night"\/>/);
 assert.match(map,/base=night\?nightGround\(json,relief\):lightMast\?mastheadGround\(json\):v12Ground\(json\)/,'A\'s masthead tunes V14\'s v12Ground; B\'s card keeps it as is');
 assert.match(map,/function mastheadGround\(source:StyleSpecification\):StyleSpecification\{\n const style=v12Ground\(source\);/);
 assert.match(css,/\.c15-hero\[data-hero=a\] \.c15-hero-scrim\{display:none\}/);
 assert.match(css,/\.c15-hero\[data-hero=a\] \.c15-hero-art>\.c15-hero-copy::before\{[^}]*rgb\(38 60 30\/0\) 100%\)\}/,'the fade clears inside the copy\'s reach');
 assert.match(css,/\.c15-hero\[data-hero=a\]\[data-expanded=true\] \.c15-hero-art>\.c15-hero-copy\{bottom:auto\}/,'expanded, the dark keeps to the type');
});
test('V15 draws only from its own stylesheet and the V15 variable face',()=>{
 const css=source('climb-v15.css');
 assert.match(css,/@font-face\{font-family:'Geist V15';src:url\('\.\/fonts\/geist-variable-latin\.woff2'\)/);
 for(const file of ['ClimbV15.tsx','ClimbV15Shell.tsx','ClimbV15Hero.tsx','ClimbV15Map.tsx','ClimbV15Profile.tsx','ClimbV15Board.tsx','ClimbV15Vault.tsx','ClimbV15History.tsx','ClimbV15Action.tsx'])assert.doesNotMatch(source(file),/climb-v(?:[2-9]|1[0-4])\.css|c14-/,file);
 for(const weight of css.matchAll(/font-weight:(\d+)(?![\d ])/g))assert.ok(['400','440','560'].includes(weight[1]),`unexpected weight ${weight[1]}`);
 for(const size of css.matchAll(/font-size:(\d+)px/g))assert.ok(Number(size[1])>=11,`text under 11px: ${size[1]}`);
 assert.match(css,/--c15-route-night:#5592e2/);
 assert.doesNotMatch(source('../palette/palette.ts'),/route-night/,'the night route stays local to V15');
 const body=css.replace(/\/\*[\s\S]*?\*\//g,'').replace(/@font-face\{[^}]*\}/,'');
 for(const block of body.matchAll(/([^{}]+)\{[^{}]*\}/g)){const selectors=block[1].trim();if(!selectors||selectors.startsWith('@')||/^(?:from|to|\d+%)$/.test(selectors))continue;
  const parts:string[]=[];let depth=0,part='';for(const ch of selectors){if(ch==='(')depth++;if(ch===')')depth--;if(ch===','&&depth===0){parts.push(part);part='';}else part+=ch;}parts.push(part);
  for(const selector of parts){const s=selector.trim();if(!s)continue;assert.ok(/(?:^|\s|\()\.c15-|:where\(\.c15-page\)|^tr\[data-current=true\] \.c15-/.test(s),`selector outside .c15-page: ${s}`);}}
});
test('the only filled button is Collect DUNG, which commits; tags are never olive-800',()=>{
 const vault=source('ClimbV15Vault.tsx'),action=source('ClimbV15Action.tsx'),css=source('climb-v15.css');
 const all=['ClimbV15.tsx','ClimbV15Shell.tsx','ClimbV15Hero.tsx','ClimbV15Map.tsx','ClimbV15Board.tsx','ClimbV15History.tsx','ClimbV15Action.tsx'].map(source).join('\n');
 assert.doesNotMatch(all,/c15-primary/);
 assert.equal([...vault.matchAll(/className="c15-primary"/g)].length,1);
 assert.match(vault,/className="c15-primary" onClick=\{\(\)=>setAction\('collect'\)\}>Collect DUNG<\/button>/);
 assert.match(action,/className="c15-button" onClick=\{onClose\}>Back to Vault/);
 assert.match(css,/\.c15-chip,\.c15-tag\{[^}]*background:var\(--c15-data-soft\)/);
 assert.doesNotMatch(css,/\.c15-(?:tag|chip)[^{]*\{[^}]*background:var\(--c15-action\)/);
 assert.doesNotMatch(css,/^\.c15-page :is\(button|^\.c15-page :is\(strong/m,'resets must not outrank single-class rules');
});
test('section order: Leaderboard, then Your history, then the Vault closes the page',()=>{
 const room=source('ClimbV15.tsx'),board=room.indexOf('<ClimbV15Board'),history=room.indexOf('<ClimbV15History'),vault=room.indexOf('<ClimbV15Vault');
 assert.ok(board>0&&board<history&&history<vault);
});
test('A\'s elevation is one route-blue line over grade-banded columns; strip labels print only where they fit',()=>{
 const profile=source('ClimbV15Profile.tsx'),css=source('climb-v15.css');
 assert.match(profile,/className="c15-profile-column" data-rung=\{b\.rung\}/);
 assert.match(css,/\.c15-profile-line\{fill:none;stroke:var\(--c15-route\);stroke-width:2;/);
 assert.match(css,/\.c15-grade-strip>\[data-rung='2'\]\{background:var\(--c15-ink-3\);color:#fff\}/,'white on rung 2 clears 4.5:1');
 assert.doesNotMatch(profile,/width\*share>=40&&label/);
});
test('the rail names each climb in full and shows a place as text; the phone topbar names the section',()=>{
 const shell=source('ClimbV15Shell.tsx');
 assert.doesNotMatch(shell,/RankMark/);
 assert.match(shell,/<span className="c15-phone-title">Map<\/span>/);
});
