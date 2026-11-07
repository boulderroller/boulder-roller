import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import path from 'node:path';
import {ensureRetainedSource} from './baseline/materialize-source.mjs';
ensureRetainedSource(path.resolve(__dirname,'baseline'));

export default defineConfig({
  root: __dirname,
  cacheDir: path.resolve(__dirname,'../../..','.cache/portal-workshop'),
  envDir: path.resolve(__dirname, '..'),
  plugins: [{name:'retained-v1-boundaries',enforce:'pre',resolveId(source,importer){
    if(importer?.includes('/baseline/src/')){
      if(/\/(AuthRuntimeContext|useDeferredWalletTransactionSigner|WalletTransactionSignerBridge)$/.test(source))return path.resolve(__dirname,'baseline/auth-runtime.tsx');
    }else if(source==='../../hooks/useFormatters')return path.resolve(__dirname,'formatters.ts');
    return null;
  }},react()],
  publicDir: path.resolve(__dirname,'baseline/public'),
  resolve: {
    alias: [
      { find: '@', replacement: path.resolve(__dirname, '../src') },
    ],
    dedupe: ['react', 'react-dom'],
  },
  server: { host: 'localhost', port: 4318, strictPort: true, open: false, fs: { allow: [path.resolve(__dirname, '..')] } },
  build: { outDir: '../workshop-dist', emptyOutDir: true, rollupOptions:{input:{workshop:path.resolve(__dirname,'index.html'),baseline:path.resolve(__dirname,'baseline/index.html')}} },
});
