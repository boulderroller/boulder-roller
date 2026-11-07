import ts from 'typescript';
import {ensureRetainedSource} from './materialize-source.mjs';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const baseline=path.dirname(fileURLToPath(import.meta.url)),portal=path.resolve(baseline,'../..');
ensureRetainedSource(baseline);
const manifest=JSON.parse(readFileSync(path.join(baseline,'source-manifest.json'),'utf8'));
for(const [relative,expected] of Object.entries({...Object.fromEntries(Object.entries(manifest.sha256).map(([file,hash])=>['src/'+file,hash])),...manifest.dependencies})){
 const actual=createHash('sha256').update(readFileSync(path.join(baseline,relative))).digest('hex');
 if(actual!==expected)throw Error(`Frozen source changed: ${relative}`);
 const original=createHash('sha256').update(execFileSync('git',['show',`${manifest.revision}:web/portal/${relative}`],{cwd:portal,maxBuffer:16*1024*1024})).digest('hex');
 if(original!==expected)throw Error(`Recorded revision differs from the frozen manifest: ${relative}.`);
}
const options={noEmit:true,strict:true,jsx:ts.JsxEmit.ReactJSX,moduleResolution:ts.ModuleResolutionKind.Bundler,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022,skipLibCheck:true,esModuleInterop:true,resolveJsonModule:true,allowImportingTsExtensions:true,types:['vite/client','node']};
function diagnostics(entry){return ts.getPreEmitDiagnostics(ts.createProgram([entry],options));}
function identity(d,root){return [d.file?path.relative(root,d.file.fileName):'',d.start,d.code,ts.flattenDiagnosticMessageText(d.messageText,' ')].join('|');}
// The hashes above verify this source against its recorded Git revision.
// Live portal code may evolve or retire files without changing this baseline.
const original=diagnostics(path.join(baseline,'src/main.tsx')),known=new Set(original.map(d=>identity(d,baseline)));
const current=diagnostics(path.join(baseline,'entry.tsx'));
const inherited=current.filter(d=>d.file&&(/^(src|server)\//.test(path.relative(baseline,d.file.fileName)))&&known.has(identity(d,baseline)));
const added=current.filter(d=>!inherited.includes(d));
if(added.length){console.error(ts.formatDiagnosticsWithColorAndContext(added,{getCurrentDirectory:()=>portal,getCanonicalFileName:f=>f,getNewLine:()=> '\n'}));process.exitCode=1;}
console.log(`Frozen source: ${Object.keys(manifest.sha256).length} exact files. Baseline adapters: ${added.length} new type errors. ${inherited.length} source diagnostics reproduced unchanged on the original implementation.`);
