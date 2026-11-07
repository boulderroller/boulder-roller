/* Shared-source check against the production TypeScript boundary producer. */
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../../..');
const {materializeBoundary}=require(root+'/indexer/dist/stage1-boundary');
const {canonical}=require(root+'/indexer/dist/stage1');
const v=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(canonical(materializeBoundary(v.checkpoint,v.coverage,v.transactions,v.hill,v.boundary)));
