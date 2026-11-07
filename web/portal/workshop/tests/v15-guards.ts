import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname,relative,resolve,sep} from 'node:path';
import postcss from 'postcss';
import valueParser from 'postcss-value-parser';
import ts from 'typescript';
import registrationHashes from './v15-registration-sha256.json';

const namedColours=new Set([...Object.keys(createRequire(import.meta.url)('color-name')),'transparent','currentcolor']);
const colourFunctions=new Set(['rgb','rgba','hsl','hsla','hwb','lab','lch','oklab','oklch','color','device-cmyk','light-dark']);
export function literalColours(css:string):string[] {
 const problems:string[]=[];
 postcss.parse(css).walkDecls(declaration=>{
  valueParser(declaration.value).walk(node=>{
   if(node.type==='function'&&colourFunctions.has(node.value.toLowerCase()))problems.push(`${declaration.prop}: ${node.value}()`);
   if(node.type==='word'&&(/^#[\da-f]{3,8}$/i.test(node.value)||namedColours.has(node.value.toLowerCase())))problems.push(`${declaration.prop}: ${node.value}`);
  });
 });
 return problems;
}

export const digest=(bytes:Uint8Array|string)=>createHash('sha256').update(bytes).digest('hex');
export function preservationProblems(root:string,hashes:Record<string,string>):string[] {
 return Object.entries(hashes).flatMap(([file,expected])=>{
  try{return digest(readFileSync(`${root}/${file}`))===expected?[]:[`changed ${file}`];}catch{return [`missing ${file}`];}
 });
}

const layoutProperties=new Set(['display','position','inset','inset-block','inset-inline','top','right','bottom','left','width','min-width','max-width','height','min-height','max-height','grid','grid-template-columns','grid-template-rows','grid-auto-flow','grid-auto-rows','grid-column','grid-row','grid-area','flex','flex-direction','flex-wrap','flex-basis','flex-grow','flex-shrink','align-items','align-self','align-content','justify-content','justify-items','justify-self','gap','row-gap','column-gap','margin','margin-top','margin-right','margin-bottom','margin-left','padding','padding-top','padding-right','padding-bottom','padding-left','overflow','overflow-x','overflow-y','order','aspect-ratio','container-type','container-name']);
// A deliberately small selector grammar: room classes, combinators and state
// pseudos. No tag, attribute, universal, escaped or unknown selector can slip
// through a class-name search, including inside a functional pseudo.
function roomSelector(selector:string,prefix:string):boolean {
 let at=0;
 const spaces=()=>{const start=at;while(/\s/.test(selector[at]??'')&&at<selector.length)at++;return at>start;};
 const roomClass=()=>{
  const token=/^\.[a-z][\w-]*/.exec(selector.slice(at))?.[0];
  if(!token||!token.slice(1).startsWith(`${prefix}-`))return false;
  at+=token.length;return true;
 };
 function compound():boolean {
  if(!roomClass())return false;
  while(at<selector.length){
   if(selector[at]==='.'){if(!roomClass())return false;continue;}
   const functional=/^:(?:is|where|not|has)\(/.exec(selector.slice(at))?.[0];
   if(functional){at+=functional.length;if(!list()||selector[at++]!==')')return false;continue;}
   const pseudo=/^::?(?:hover|focus|focus-visible|focus-within|active|disabled|checked|empty|first-child|last-child)\b/.exec(selector.slice(at))?.[0];
   if(pseudo){at+=pseudo.length;continue;}
   break;
  }
  return true;
 }
 function complex():boolean {
  spaces();if(!compound())return false;
  while(at<selector.length){
   const separated=spaces();
   if(at===selector.length||selector[at]===','||selector[at]===')')return true;
   if(/[>+~]/.test(selector[at])){at++;spaces();}
   else if(!separated)return false;
   if(!compound())return false;
  }
  return true;
 }
 function list():boolean {
  if(!complex())return false;
  while(selector[at]===','){at++;if(!complex())return false;}
  return true;
 }
 return list()&&at===selector.length;
}
const candidateOwners:Readonly<Record<string,string>>={
 'effort/effort.css':'effort','effort/EffortView.tsx':'effort','effort/Origins.tsx':'effort',
 'climb/climb-v17.css':'climb','climb/ClimbV17.tsx':'climb',
};
export function candidateCssProblems(css:string,filename?:string):string[] {
 const problems:string[]=[],parsed=postcss.parse(css);
 parsed.walkRules(rule=>{
  for(const selector of rule.selectors){
   const prefix=selector.match(/^\.([a-z][\w-]*)-page(?=[\s.:>+~,{]|$)/)?.[1];
   if(!prefix||prefix==='v15'||!roomSelector(selector,prefix))problems.push(`selector ${selector}`);
   if(filename&&prefix!==candidateOwners[filename])problems.push(`owner ${filename}: ${selector}`);
  }
 });
 parsed.walkAtRules(rule=>{if(!['media','container','supports','layer'].includes(rule.name))problems.push(`at-rule ${rule.name}`);});
 parsed.walkDecls(d=>{if(!layoutProperties.has(d.prop)||d.important)problems.push(`property ${d.prop}`);});
 return problems;
}
/** Registration files are reviewed as exact source, not an unrestricted styling
 * escape hatch. A new route requires updating its explicit source digest. */
export function registrationProblems(filename:string,source:string):string[]{
 const expected=(registrationHashes as Record<string,string>)[filename];
 return expected===digest(source)?[]:[`unreviewed registration ${filename}`];
}
export function kitCssProblems(source:string,filename:string):string[]{
 const problems:string[]=[],css=postcss.parse(source);
 css.walkAtRules(rule=>{if(rule.name.toLowerCase()==='import')problems.push('at-rule import');});
 if(filename==='tokens.css')return problems;
 problems.push(...literalColours(source));
 css.walkDecls(d=>{if(d.prop.startsWith('--v15-'))problems.push(`token ${d.prop}`);});
 css.walkRules(rule=>{
  for(const selector of rule.selectors){
   const legal=filename==='KitSpecimen.css'?roomSelector(selector,'specimen'):selector.startsWith(':where(.v15-kit)');
   if(!legal)problems.push(`selector ${selector}`);
  }
 });return problems;
}
export function componentColourProblems(source:string):string[]{
 const problems:string[]=[],file=ts.createSourceFile('component.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const paint=/color|fill|stroke|background|border|shadow|outline/i;
 const check=(name:string,value:ts.Node|undefined)=>{
  if(!paint.test(name)||!value)return;
  const expression=ts.isJsxExpression(value)?value.expression:value;
  if(expression&&ts.isStringLiteralLike(expression))problems.push(...literalColours(`a{${name}:${expression.text}}`));
 };
 function visit(node:ts.Node){
  if(ts.isJsxAttribute(node))check(node.name.getText(file),node.initializer);
  if(ts.isPropertyAssignment(node))check(node.name.getText(file),node.initializer);
  ts.forEachChild(node,visit);
 }
 visit(file);return problems;
}
export function candidateTsxProblems(source:string,filename?:string):string[] {
 const problems:string[]=[],file=ts.createSourceFile('candidate.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 function visit(node:ts.Node){
  if(ts.isStringLiteralLike(node)||ts.isJsxText(node)||ts.isTemplateHead(node)||ts.isTemplateMiddle(node)||ts.isTemplateTail(node)){
   const text=node.text;
   const root=ts.isStringLiteral(node)&&ts.isJsxAttribute(node.parent)&&node.parent.name.getText(file)==='className'&&/^v15-kit [a-z][\w-]*-page$/.test(text);
   if(root&&filename&&text!==`v15-kit ${candidateOwners[filename]}-page`)problems.push(`owner ${filename}: ${text}`);
   if(!root&&/(?:--)?v15-/.test(text))problems.push(`kit expression ${text}`);
  }
  ts.forEachChild(node,visit);
 }
 visit(file);return problems;
}
export function mainKitImports(entry:string):string[] {
 const root=dirname(resolve(entry)),kit=resolve(root,'v15'),gate=resolve(kit,'WorkshopGate.tsx'),paths=new Set<string>(),visited=new Set<string>();
 const options:ts.CompilerOptions={allowJs:true,module:ts.ModuleKind.ESNext,moduleResolution:ts.ModuleResolutionKind.Bundler,baseUrl:root,paths:{'@/*':['../src/*']}};
 function walk(filename:string){
  if(visited.has(filename))return;visited.add(filename);
  const file=ts.createSourceFile(filename,readFileSync(filename,'utf8'),ts.ScriptTarget.Latest,true);
  function dependency(node:ts.Expression){
   const dynamic=ts.isTemplateExpression(node),literal=dynamic?node.head:node;
   if(!ts.isStringLiteralLike(literal)&&!ts.isTemplateHead(literal))return;
   const specifier=literal.text;
   // Mirror the workshop's Vite root URLs and @ alias, including template
   // prefixes that cannot yet resolve to a complete module filename.
   const local=specifier.startsWith('/')?resolve(root,`.${specifier}`):specifier.startsWith('@/')?resolve(root,'../src',specifier.slice(2)):specifier.startsWith('.')?resolve(dirname(filename),specifier):undefined;
   const resolved=dynamic?undefined:ts.resolveModuleName(local??specifier,filename,options,ts.sys).resolvedModule;
   const target=resolved?.resolvedFileName??local;
   if(target&&(target===kit||target.startsWith(`${kit}${sep}`))&&(dynamic||target!==gate)){
    paths.add(`${relative(root,filename)} -> ${specifier}`);return;
   }
   if(resolved&&!resolved.isExternalLibraryImport&&!resolved.resolvedFileName.includes(`${sep}node_modules${sep}`)&&/\.[cm]?[jt]sx?$/.test(resolved.resolvedFileName))walk(resolved.resolvedFileName);
  }
  function visit(node:ts.Node){
   if((ts.isImportDeclaration(node)||ts.isExportDeclaration(node))&&node.moduleSpecifier)dependency(node.moduleSpecifier);
   if(ts.isCallExpression(node)&&(node.expression.kind===ts.SyntaxKind.ImportKeyword||(ts.isIdentifier(node.expression)&&node.expression.text==='require'))&&node.arguments[0])dependency(node.arguments[0]);
   if(ts.isImportEqualsDeclaration(node)&&ts.isExternalModuleReference(node.moduleReference)&&node.moduleReference.expression)dependency(node.moduleReference.expression);
   ts.forEachChild(node,visit);
  }
  visit(file);
 }
 walk(resolve(entry));return [...paths];
}
