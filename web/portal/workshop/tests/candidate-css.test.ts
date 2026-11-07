import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {ArrowUpRight} from 'lucide-react';
const root=fileURLToPath(new URL('..',import.meta.url));
function componentClasses(){
 const classes=new Set<string>();
 const add=(text:string)=>text.split(/\s+/).filter(token=>/^[a-zA-Z_][\w-]*$/.test(token)).forEach(token=>classes.add(token));
 const scan=(dir:string)=>{for(const entry of readdirSync(dir,{withFileTypes:true})){
  if(entry.name==='tests'||entry.name==='node_modules')continue;
  const path=join(dir,entry.name);
  if(entry.isDirectory())scan(path);
  else if(entry.name.endsWith('.tsx')){
   const source=ts.createSourceFile(path,readFileSync(path,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
   const strings=(node:ts.Node)=>{if(ts.isStringLiteralLike(node)||ts.isTemplateHead(node)||ts.isTemplateMiddle(node)||ts.isTemplateTail(node))add(node.text);ts.forEachChild(node,strings);};
   const visit=(node:ts.Node)=>{
    if(ts.isJsxAttribute(node)&&node.name.getText(source)==='className'&&node.initializer)strings(node.initializer);
    if(ts.isBinaryExpression(node)&&node.operatorToken.kind===ts.SyntaxKind.EqualsToken&&ts.isPropertyAccessExpression(node.left)&&node.left.name.text==='className')strings(node.right);
    if(ts.isBindingElement(node)&&node.name.getText(source)==='className'&&node.initializer)strings(node.initializer);
    ts.forEachChild(node,visit);
   };visit(source);
  }
 }};scan(root);
 // These two imported renderers own classes not authored in workshop TSX.
 for(const match of renderToStaticMarkup(createElement(ArrowUpRight)).matchAll(/class="([^"]+)"/g))add(match[1]);
 const map=readFileSync(new URL('../../node_modules/maplibre-gl/src/ui/map.ts',import.meta.url),'utf8');
 for(const match of map.matchAll(/DOM\.create\('[^']+', '([^']+)'/g))add(match[1]);
 return classes;
}
const emitted=componentClasses();
for(const file of ['climb/climb-v16.css','feed/feed-v13.css'])test(`${file} class selectors have workshop component producers`,()=>{
 const css=readFileSync(join(root,file),'utf8').replace(/\/\*[\s\S]*?\*\//g,''),classes=new Set<string>();
 for(const match of css.matchAll(/([^{}]+)\{/g))if(!match[1].trim().startsWith('@'))for(const name of match[1].matchAll(/\.([A-Za-z_][\w-]*)/g))classes.add(name[1]);
 assert.ok(classes.size>100,'Audit must include the full stylesheet');
 assert.deepEqual([...classes].filter(name=>!emitted.has(name)).sort(),[],'Unproduced class selectors');
});
