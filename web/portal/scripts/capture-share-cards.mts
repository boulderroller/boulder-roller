import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import imageHandler from '../api/og.ts';
import headHandler from '../api/share.ts';
import {fixtures} from './share-card-fixtures.mts';
const output = new URL('../../../history/share-cards-2026-09-06/build/', import.meta.url);
await mkdir(output,{recursive:true});
const original = globalThis.fetch;
try {
  for (const [kind,payload] of Object.entries(fixtures)) {
    globalThis.fetch = async url => {
      if (url instanceof URL && url.protocol==='file:') return new Response(await readFile(url));
      return Response.json(payload);
    };
    const routeKind = kind==='brand' ? 'riders' : kind;
    const image = await imageHandler(new Request(`https://app.boulderroller.xyz/api/og?kind=${routeKind}&id=offline`));
    await writeFile(new URL(`${kind}.png`,output),Buffer.from(await image.arrayBuffer()));
    const head = await headHandler(new Request(`https://app.boulderroller.xyz/${routeKind}/offline`,{headers:{'user-agent':'Slackbot-LinkExpanding 1.0'}}));
    await writeFile(new URL(`${kind}-head.html`,output),await head.text());
  }
} finally {globalThis.fetch = original;}
console.log(`Offline endpoint evidence: ${fileURLToPath(output)}`);
