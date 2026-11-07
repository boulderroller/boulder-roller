import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,copyFileSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {ensureRetainedSource} from '../baseline/materialize-source.mjs';
test('frozen archive materializes exact source and refuses changed bytes',()=>{
 const dir=mkdtempSync(path.join(tmpdir(),'br-frozen-source-'));
 try{
  for(const file of ['source.tar.gz','source-manifest.json'])copyFileSync(path.resolve('workshop/baseline',file),path.join(dir,file));
  assert.equal(ensureRetainedSource(dir),441);assert.equal(ensureRetainedSource(dir),441);
  const file=path.join(dir,'src/App.tsx');const original=readFileSync(file);writeFileSync(file,'changed');assert.throws(()=>ensureRetainedSource(dir),/Frozen source changed/);writeFileSync(file,original);
  writeFileSync(path.join(dir,'source.tar.gz'),'changed');assert.throws(()=>ensureRetainedSource(dir),/archive changed/);
 }finally{rmSync(dir,{recursive:true,force:true});}
});
