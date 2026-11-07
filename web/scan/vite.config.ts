import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react-swc';
import path from 'path';

function toProxyTarget(rawValue?: string): string | null {
  if (!rawValue) return null;
  const value = rawValue.trim();
  if (value.startsWith('http://') || value.startsWith('https://')) {
    return value.replace(/\/$/, '');
  }
  return null;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '');
  const proxyTarget =
    toProxyTarget(env.VITE_SCAN_API_PROXY_TARGET) ||
    toProxyTarget(process.env.VITE_SCAN_API_PROXY_TARGET) ||
    toProxyTarget(env.VITE_SCAN_API_URL) ||
    'http://localhost:3001';

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        // Vitest resolves in Node, where maplibre-contour exports no matching condition.
        ...(mode === 'test' ? { 'maplibre-contour': path.resolve(__dirname, 'node_modules/maplibre-contour/dist/index.mjs') } : {}),
      },
    },
    build: {
      outDir: 'build',
      target: 'esnext',
    },
    server: {
      port: 3004,
      open: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          rewrite: (value) => value.replace(/^\/api/, ''),
        },
      },
    },
    preview: {
      port: 4174,
      host: '127.0.0.1',
    },
  };
});
