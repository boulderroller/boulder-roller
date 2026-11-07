import { createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Toaster, toast } from 'sonner';

import type { NotifyEnvelope, NotifyOptions } from './notify';

const TOAST_ROOT_ID = 'br-toast-root';

let toastRoot: Root | null = null;
let mounted = false;

function ensureContainer(): HTMLElement | null {
  if (typeof document === 'undefined') return null;

  const existing = document.getElementById(TOAST_ROOT_ID);
  if (existing) return existing;

  const container = document.createElement('div');
  container.id = TOAST_ROOT_ID;
  document.body.appendChild(container);
  return container;
}

function ensureToasterMounted() {
  if (mounted) return;

  const container = ensureContainer();
  if (!container) return;

  if (!toastRoot) {
    toastRoot = createRoot(container);
  }

  toastRoot.render(
    createElement(Toaster, {
      position: 'bottom-right',
      toastOptions: {
        style: {
          background: 'var(--color-bg)',
          color: 'var(--color-text)',
          border: '2px solid var(--color-border)',
          borderRadius: '0px',
          boxShadow: '4px 4px 0px 0px var(--color-border)',
        },
      },
    }),
  );

  mounted = true;
}

export function emitToast({ method, message, options }: NotifyEnvelope) {
  ensureToasterMounted();

  const handler = (toast as unknown as Record<string, ((msg: string, opts?: NotifyOptions) => void)>)[method];
  if (typeof handler === 'function') {
    handler(message, options);
    return;
  }

  toast(message, options);
}
