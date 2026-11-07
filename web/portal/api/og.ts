import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ImageResponse } from '@vercel/og';
import { shareObject, publicPreview } from '../server/share-preview.js';
import { cardElement } from '../server/share-card.js';
// Node runtime: the Edge runtime refuses to compile the renderer's WebAssembly from bytes.

const FONT_DIRS = [
  path.join(process.cwd(), 'server', 'fonts'),
  path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'server', 'fonts'),
];
async function font(name: string): Promise<ArrayBuffer> {
  let lastError: unknown;
  for (const dir of FONT_DIRS) {
    try { const buf = await readFile(path.join(dir, name)); return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer; }
    catch (error) { lastError = error; }
  }
  throw lastError;
}
async function fonts() {
  // Bundled with the function via vercel.json functions.includeFiles.
  const files = await Promise.all([
    font('Geist-Regular.ttf'), font('Geist-SemiBold.ttf'), font('Geist-Bold.ttf'), font('GeistMono-Regular.ttf'),
  ]);
  return [
    {name:'Geist',data:files[0],weight:400 as const,style:'normal' as const},
    {name:'Geist',data:files[1],weight:600 as const,style:'normal' as const},
    {name:'Geist',data:files[2],weight:700 as const,style:'normal' as const},
    {name:'Geist Mono',data:files[3],weight:400 as const,style:'normal' as const},
  ];
}
// Web fetch-style named export: the Node runtime ignores a Response returned from a default export.
export async function GET(request: Request): Promise<Response> {
  const object = shareObject(request);
  const [preview,fontData] = await Promise.all([publicPreview(object),fonts()]);
  return new ImageResponse(cardElement(object,preview), {width:1200,height:630,fonts:fontData,headers:{
    'Cache-Control':'public, max-age=0, s-maxage=3600', 'X-Robots-Tag':preview ? 'index,follow' : 'noindex,nofollow',
  }});
}
