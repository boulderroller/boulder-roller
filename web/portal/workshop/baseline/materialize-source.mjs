import {readFileSync,existsSync,mkdirSync,mkdtempSync,copyFileSync,rmSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import path from 'node:path';
const digest=file=>createHash('sha256').update(readFileSync(file)).digest('hex');
// The archive is an immutable copy of the recorded source revision, not a source transform.
export function ensureRetainedSource(baseline){
 const manifest=JSON.parse(readFileSync(path.join(baseline,'source-manifest.json'),'utf8'));
 const archive=path.join(baseline,manifest.archive.file);
 if(digest(archive)!==manifest.archive.sha256)throw Error('Frozen archive changed.');
 const entries=Object.entries(manifest.sha256),missing=[];
 for(const [relative,expected]of entries){
  if(relative.startsWith('/')||relative.split('/').includes('..'))throw Error('Invalid frozen source path.');
  const file=path.join(baseline,'src',relative);
  if(!existsSync(file))missing.push(relative);else if(digest(file)!==expected)throw Error(`Frozen source changed: ${relative}. Preserve it before restoring the baseline.`);
 }
 if(missing.length){
  const members=execFileSync('tar',['-tzf',archive],{encoding:'utf8'}).trim().split('\n');
  if(members.length!==entries.length||members.some(member=>!Object.hasOwn(manifest.sha256,member.replace(/^src\//,''))||!member.startsWith('src/')))throw Error('Unexpected frozen archive member.');
  const temporary=mkdtempSync(path.join(tmpdir(),'br-retained-source-'));
  try{
   execFileSync('tar',['-xzf',archive,'-C',temporary]);
   for(const relative of missing){const source=path.join(temporary,'src',relative);if(digest(source)!==manifest.sha256[relative])throw Error(`Frozen archive entry changed: ${relative}`);const target=path.join(baseline,'src',relative);mkdirSync(path.dirname(target),{recursive:true});copyFileSync(source,target);}
  }finally{rmSync(temporary,{recursive:true,force:true});}
 }
 return entries.length;
}
