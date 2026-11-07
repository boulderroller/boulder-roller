import {test} from 'node:test';
import assert from 'node:assert/strict';
import {PALETTE} from '../palette/palette';
import {deltaE2000,parseColour,toLab} from '../palette/colour';
import {declarations,familyRole,mapValue,nearestToken,prefixSelector,roleFor,selectorOverride} from '../palette/applyPalette';
import {LEGACY_SELECTORS} from '../palette/palette';

test('every palette token is a named six-digit colour with at least one role',()=>{
 const names=new Set<string>();
 for(const t of PALETTE){
  assert.match(t.name,/^[a-z][a-z0-9-]*$/,t.name);
  assert.ok(!names.has(t.name),`duplicate ${t.name}`);names.add(t.name);
  assert.match(t.value,/^#[0-9a-f]{6}$/,t.name);
  assert.ok(t.roles.length>0,t.name);
 }
});

test('colours parse from hex, short hex, rgb and rgba as the browser serialises them',()=>{
 assert.deepEqual(parseColour('#fff'),[255,255,255,1]);
 assert.deepEqual(parseColour('#26302108')?.slice(0,3),[38,48,33]);
 assert.deepEqual(parseColour('rgb(56, 70, 48)'),[56,70,48,1]);
 assert.deepEqual(parseColour('rgba(38, 48, 33, 0.5)'),[38,48,33,0.5]);
 assert.equal(parseColour('url(#gradient)'),null);
});

test('CIEDE2000 is zero for equal colours and symmetric',()=>{
 const a=toLab([244,244,241]),b=toLab([41,44,39]);
 assert.equal(deltaE2000(a,a),0);
 assert.ok(Math.abs(deltaE2000(a,b)-deltaE2000(b,a))<1e-9);
});

test('every twin selector gains the same specificity, so twins keep the original cascade',()=>{
 assert.equal(prefixSelector('.a, .b > span'),':root[data-palette] .a, :root[data-palette] .b > span');
 assert.equal(prefixSelector(':root'),':root[data-palette][data-palette]');
 assert.equal(prefixSelector('html body'),'html[data-palette][data-palette] body');
 assert.equal(prefixSelector(':is(.a, .b) .c'),':root[data-palette] :is(.a, .b) .c');
 assert.equal(prefixSelector('[data-x="a,b"]'),':root[data-palette] [data-x="a,b"]');
});

test('properties map to the role their colour plays',()=>{
 assert.equal(roleFor('color'),'text');
 assert.equal(roleFor('background-color'),'surface');
 assert.equal(roleFor('border-top-color'),'line');
 assert.equal(roleFor('fill'),'svg');
 assert.equal(roleFor('box-shadow'),'shadow');
 assert.equal(roleFor('width'),null);
});

test('shorthands written with var() are twinned whole, so the original cascade holds',()=>{
 const parsed=declarations('display: flex; background: var(--c10-olive); color: var(--c10-white); border: 0px; --x: url("a;b"); box-shadow: rgba(0, 0, 0, 0.1) 0px 1px 2px !important');
 assert.deepEqual(parsed.map(d=>d.prop),['display','background','color','border','--x','box-shadow']);
 assert.equal(parsed[4].value,'url("a;b")');
 assert.equal(parsed[5].important,true);
 assert.deepEqual(parsed.map(d=>familyRole(d.prop)),[null,'surface','text','line','any','shadow']);
 assert.equal(familyRole('background-position'),'surface');
 assert.equal(familyRole('border-radius'),'line');
});

test('a token colour maps to itself, and alpha survives as a tint of the token',()=>{
 const t=PALETTE[0], role=t.roles[0];
 assert.equal(nearestToken(parseColour(t.value)!,role)?.name,t.name);
 assert.equal(mapValue(t.value,role),`var(--pal-${t.name})`);
 const [r,g,b]=parseColour(t.value)!;
 assert.equal(mapValue(`rgba(${r}, ${g}, ${b}, 0.5)`,role),`color-mix(in srgb, var(--pal-${t.name}) 50%, transparent)`);
});

test('values keep their structure: only colours change inside shadows and gradients',()=>{
 const shadow=mapValue('rgba(38, 48, 33, 0.043) 0px 1px 2px','shadow');
 assert.match(shadow,/^color-mix\(in srgb, var\(--pal-[a-z0-9-]+\) 4\.3%, transparent\) 0px 1px 2px$/);
 const gradient=mapValue('linear-gradient(rgb(255, 255, 255), rgb(244, 244, 241))','surface');
 assert.match(gradient,/^linear-gradient\(var\(--pal-[a-z0-9-]+\), var\(--pal-[a-z0-9-]+\)\)$/);
 assert.equal(mapValue('url(#fade) currentcolor','svg'),'url(#fade) currentcolor');
 assert.equal(mapValue('var(--white-line)','line'),'var(--white-line)');
});

test('selector overrides match a property family, but a custom property only exactly',()=>{
 const custom=LEGACY_SELECTORS.find(o=>o.property?.startsWith('--'));
 if(custom){
  assert.equal(selectorOverride(custom.selector,custom.property!)?.token,custom.token);
  assert.notEqual(selectorOverride(custom.selector,custom.property+'-extra'),custom);
 }
 const family=LEGACY_SELECTORS.find(o=>o.property==='background');
 if(family)assert.equal(selectorOverride(family.selector,'background-color')?.token,family.token);
});

test('an override can set the alpha, so a translucent mark can be drawn opaque',()=>{
 const t=PALETTE[0], role=t.roles[0];
 const [r,g,b]=parseColour(t.value)!;
 assert.equal(mapValue(`rgba(${r}, ${g}, ${b}, 0.6)`,role,t.name,1),`var(--pal-${t.name})`);
 assert.equal(mapValue(`rgba(${r}, ${g}, ${b}, 1)`,role,t.name,0.5),`color-mix(in srgb, var(--pal-${t.name}) 50%, transparent)`);
});
