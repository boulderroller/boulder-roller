type ToastMethod = 'success' | 'error' | 'warning' | 'info';

export interface NotifyOptions {
  description?: string;
  duration?: number;
  id?: string | number;
}

export interface NotifyEnvelope {
  method: ToastMethod;
  message: string;
  options?: NotifyOptions;
}

let runtimePromise: Promise<typeof import('./notifyRuntime')> | null = null;

function loadRuntime() {
  if (!runtimePromise) {
    runtimePromise = import('./notifyRuntime');
  }
  return runtimePromise;
}

function emit(method: ToastMethod, message: string, options?: NotifyOptions) {
  const payload: NotifyEnvelope = { method, message, options };

  void loadRuntime()
    .then(({ emitToast }) => {
      emitToast(payload);
    })
    .catch(() => {
      // Notifications should never break control flow.
    });
}

export const notify = {
  success(message: string, options?: NotifyOptions) {
    emit('success', message, options);
  },
  error(message: string, options?: NotifyOptions) {
    emit('error', message, options);
  },
  warning(message: string, options?: NotifyOptions) {
    emit('warning', message, options);
  },
  info(message: string, options?: NotifyOptions) {
    emit('info', message, options);
  },
};
