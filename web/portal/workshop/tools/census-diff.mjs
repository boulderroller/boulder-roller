import {readFile} from 'node:fs/promises';

const [beforeFile,afterFile]=process.argv.slice(2);
if(!beforeFile||!afterFile)throw new Error('Usage: node workshop/tools/census-diff.mjs <before.json> <after.json>');
const before=JSON.parse(await readFile(beforeFile,'utf8')),after=JSON.parse(await readFile(afterFile,'utf8'));
const left=new Map(before.elements.map(element=>[element.path,element])),right=new Map(after.elements.map(element=>[element.path,element])),differences=[];
for(const path of new Set([...left.keys(),...right.keys()])){
 const a=left.get(path),b=right.get(path);
 if(!a||!b){differences.push({path,property:'element',before:a?'present':'absent',after:b?'present':'absent'});continue;}
 for(const group of ['box','styles'])for(const property of new Set([...Object.keys(a[group]),...Object.keys(b[group])])){
  if(a[group][property]!==b[group][property])differences.push({path,property:`${group}.${property}`,before:a[group][property],after:b[group][property]});
 }
}
console.log(JSON.stringify({beforeCount:left.size,afterCount:right.size,differingProperties:differences.length,first20:differences.slice(0,20)},null,2));
process.exitCode=differences.length?1:0;
