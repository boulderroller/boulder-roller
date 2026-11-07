import { execFileSync } from 'node:child_process';
import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react-swc';
import path from 'path';

interface PortalBuildInfo {
  app: 'portal';
  sha: string;
  shortSha: string;
  branch: string;
  environment: string;
  builtAt: string;
}

function toProxyTarget(rawValue?: string): string | null {
  if (!rawValue) return null;
  const value = rawValue.trim();
  if (value.startsWith('http://') || value.startsWith('https://')) {
    return value.replace(/\/$/, '');
  }
  return null;
}

function isDeferredStartupChunk(fileName: string): boolean {
  return /(^|\/)(AuthRuntimeProviders|PrivyContext|WalletContext|auth-privy|auth-wallet-runtime|auth-ui|charts|maps|solana|solana-wallets|ui-kit|toasts|wallets)-.*\.js$/.test(fileName);
}

function shouldSkipBootRouteJsPreloads(
  filename: string,
  context: { hostId: string; hostType: 'html' | 'js' },
): boolean {
  if (context.hostType !== 'js') return false;

  return /(^|\/)(index|App)-.*\.js$/.test(context.hostId)
    && /(^|\/)(App|InviteGate|AuthenticatedApp|AuthRuntimeProviders|PrivyContext|WalletContext)-.*\.js$/.test(filename);
}

function manualChunks(id: string): string | undefined {
  if (
    id.includes('commonjsHelpers.js') ||
    id.includes('preload-helper') ||
    id.includes('vite/preload') ||
    (
      id.toLowerCase().includes('process') &&
      !id.includes('process-warning')
    ) ||
    id.includes('/node_modules/process/browser') ||
    id.includes('/node_modules/process/index')
  ) {
    return 'vendor-helpers';
  }

  if (!id.includes('node_modules')) return undefined;
  // Both map rooms share the already-budgeted vector runtime.
  if (id.includes('/maplibre-gl/')) return 'ClimbMap';

  const normalizedId = id.toLowerCase();
  if (
    normalizedId.includes('headlessui') ||
    normalizedId.includes('heroicons')
  ) {
    return 'auth-ui';
  }

  if (
    id.includes('@privy-io/') ||
    id.includes('@solana/wallet-adapter') ||
    id.includes('@solana/') ||
    id.includes('/bs58/') ||
    id.includes('/bn.js/')
  ) {
    return 'auth-wallet-runtime';
  }
  if (
    id.includes('/sonner/')
  ) {
    return 'toasts';
  }
  if (
    id.includes('@radix-ui/') ||
    id.includes('/cmdk/') ||
    id.includes('/vaul/') ||
    id.includes('/motion/') ||
    id.includes('/react-hook-form/') ||
    id.includes('/react-day-picker/') ||
    id.includes('/embla-carousel-react/') ||
    id.includes('/input-otp/') ||
    id.includes('/class-variance-authority/') ||
    id.includes('/clsx/') ||
    id.includes('/tailwind-merge/') ||
    id.includes('/next-themes/')
  ) {
    return 'ui-kit';
  }
  if (
    id.includes('/leaflet/') ||
    id.includes('/react-leaflet/') ||
    id.includes('/leaflet-hotline/') ||
    id.includes('/h3-js/')
  ) {
    return 'maps';
  }
  if (id.includes('/recharts/')) return 'charts';
  if (
    id.includes('@tanstack/react-query') ||
    id.includes('@tanstack/react-virtual')
  ) {
    return 'tanstack';
  }
  if (id.includes('@sentry/react')) return 'sentry';
  if (
    id.includes('/react/') ||
    id.includes('/react-dom/') ||
    id.includes('/react-router/') ||
    id.includes('/react-router-dom/') ||
    id.includes('/scheduler/') ||
    id.includes('/history/')
  ) {
    return 'react-core';
  }

  return undefined;
}

function readGitValue(args: string[], cwd: string, fallback = 'unknown'): string {
  try {
    return execFileSync('git', args, {
      cwd,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim() || fallback;
  } catch {
    return fallback;
  }
}

function escapeHtmlAttribute(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function createPortalBuildInfo(mode: string, repoRoot: string): PortalBuildInfo {
  const sha = (
    process.env.VERCEL_GIT_COMMIT_SHA ||
    process.env.GITHUB_SHA ||
    readGitValue(['rev-parse', 'HEAD'], repoRoot)
  ).trim();
  const branch = (
    process.env.VERCEL_GIT_COMMIT_REF ||
    process.env.GITHUB_REF_NAME ||
    readGitValue(['rev-parse', '--abbrev-ref', 'HEAD'], repoRoot)
  ).trim();

  return {
    app: 'portal',
    sha,
    shortSha: sha === 'unknown' ? 'unknown' : sha.slice(0, 12),
    branch,
    environment: process.env.VERCEL_ENV || mode,
    builtAt: new Date().toISOString(),
  };
}

function portalBuildInfoPlugin(buildInfo: PortalBuildInfo): Plugin {
  return {
    name: 'br-portal-build-info',
    transformIndexHtml(html) {
      const meta = [
        `<meta name="br-portal-build-sha" content="${escapeHtmlAttribute(buildInfo.sha)}" />`,
        `<meta name="br-portal-build-time" content="${escapeHtmlAttribute(buildInfo.builtAt)}" />`,
      ].join('\n      ');
      return html.replace('</head>', `      ${meta}\n    </head>`);
    },
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'version.json',
        source: `${JSON.stringify(buildInfo, null, 2)}\n`,
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '');
  const repoRoot = path.resolve(__dirname, '../..');
  const buildInfo = createPortalBuildInfo(mode, repoRoot);
  const fallbackProxyTarget =
    mode === 'production' ? 'https://api.boulderroller.xyz' : 'http://localhost:8080';

  const apiProxyTarget =
    toProxyTarget(env.VITE_API_PROXY_TARGET) ||
    toProxyTarget(process.env.VITE_API_PROXY_TARGET) ||
    toProxyTarget(env.VITE_API_URL) ||
    fallbackProxyTarget;

  return {
    plugins: [
      react(),
      portalBuildInfoPlugin(buildInfo),
    ],
    resolve: {
      extensions: ['.js', '.jsx', '.ts', '.tsx', '.json'],
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      target: 'esnext',
      outDir: 'build',
      chunkSizeWarningLimit: 700,
      modulePreload: {
        resolveDependencies: (filename, deps, context) => {
          if (shouldSkipBootRouteJsPreloads(filename, context)) {
            return [];
          }

          if (context.hostType === 'js' && /(^|\/)(index|App)-.*\.js$/.test(context.hostId)) {
            return deps.filter((dep) => !isDeferredStartupChunk(dep));
          }

          if (context.hostType !== 'html') {
            return deps;
          }

          return deps.filter((dep) => !isDeferredStartupChunk(dep));
        },
      },
      rollupOptions: {
        output: {
          hoistTransitiveImports: false,
          manualChunks,
        },
      },
    },
    server: {
      port: 3000,
      open: true,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
          rewrite: (pathValue) => pathValue.replace(/^\/api/, ''),
        },
      },
    },
    preview: {
      port: 4173,
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
          rewrite: (pathValue) => pathValue.replace(/^\/api/, ''),
        },
      },
    },
  };
});
