import {
  Component,
  createContext,
  lazy,
  type ErrorInfo,
  type ReactNode,
  Suspense,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';

type AuthRuntimeStatus = 'idle' | 'loading' | 'ready' | 'failed';

class AuthRuntimeModuleError extends Error {
  readonly cause: unknown;

  constructor(cause: unknown) {
    super('Auth runtime module failed to load');
    this.name = 'AuthRuntimeModuleError';
    this.cause = cause;
  }
}

const AuthRuntimeProviders = lazy(async () => {
  try {
    return await import('../components/auth/AuthRuntimeProviders');
  } catch (error) {
    throw new AuthRuntimeModuleError(error);
  }
});

interface AuthRuntimeContextValue {
  ready: boolean;
  status: AuthRuntimeStatus;
  error: string | null;
  ensureRuntime: () => void;
  retryRuntime: () => void;
}

const AuthRuntimeContext = createContext<AuthRuntimeContextValue>({
  ready: false,
  status: 'idle',
  error: null,
  ensureRuntime: () => {},
  retryRuntime: () => {},
});

interface AuthRuntimeControllerValue {
  enabled: boolean;
  markFailed: (error: unknown) => void;
  markReady: () => void;
  registerOutlet: (id: string, target: HTMLElement, content: ReactNode) => void;
  resetKey: number;
  unregisterOutlet: (id: string) => void;
}

const AuthRuntimeControllerContext = createContext<AuthRuntimeControllerValue | null>(null);

interface AuthRuntimeOutlet {
  content: ReactNode;
  id: string;
  target: HTMLElement;
}

function AuthRuntimePortal({ outlet }: { outlet: AuthRuntimeOutlet | null }) {
  if (!outlet) return null;
  return createPortal(outlet.content, outlet.target, outlet.id);
}

function AuthRuntimeReadyBoundary({ children, onReady }: { children: ReactNode; onReady: () => void }) {
  useEffect(() => {
    onReady();
  }, [onReady]);

  return <AuthRuntimeProviders>{children}</AuthRuntimeProviders>;
}

interface AuthRuntimeErrorBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
  onError: (error: unknown) => void;
  resetKey: number;
}

class AuthRuntimeErrorBoundary extends Component<AuthRuntimeErrorBoundaryProps, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, errorInfo: ErrorInfo) {
    this.props.onError(error);
    console.error('Auth runtime failed to load', error, errorInfo);
  }

  componentDidUpdate(prevProps: AuthRuntimeErrorBoundaryProps) {
    if (prevProps.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }

    return this.props.children;
  }
}

export function AuthRuntimeProvider({ children }: { children: ReactNode }) {
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState<AuthRuntimeStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [runtimeResetKey, setRuntimeResetKey] = useState(0);
  const [outlet, setOutlet] = useState<AuthRuntimeOutlet | null>(null);
  const lastRuntimeErrorRef = useRef<unknown>(null);

  const ensureRuntime = useCallback(() => {
    if (enabled || status === 'failed') return;
    setError(null);
    setEnabled(true);
    setStatus('loading');
  }, [enabled, status]);

  const markReady = useCallback(() => {
    lastRuntimeErrorRef.current = null;
    setError(null);
    setStatus('ready');
  }, []);

  const markFailed = useCallback((runtimeError: unknown) => {
    lastRuntimeErrorRef.current = runtimeError;
    setError('Sign-in failed to load.');
    setEnabled(false);
    setStatus('failed');
  }, []);

  const retryRuntime = useCallback(() => {
    if (lastRuntimeErrorRef.current instanceof AuthRuntimeModuleError) {
      lastRuntimeErrorRef.current = null;
      window.location.reload();
      return;
    }

    lastRuntimeErrorRef.current = null;
    setEnabled(false);
    setStatus('idle');
    setError(null);
    setRuntimeResetKey((currentKey) => currentKey + 1);
    window.requestAnimationFrame(() => {
      setEnabled(true);
      setStatus('loading');
    });
  }, []);

  const registerOutlet = useCallback((id: string, target: HTMLElement, content: ReactNode) => {
    setOutlet((current) => (
      current?.id === id && current.target === target && current.content === content
        ? current
        : { content, id, target }
    ));
  }, []);

  const unregisterOutlet = useCallback((id: string) => {
    setOutlet((current) => current?.id === id ? null : current);
  }, []);

  const value = useMemo(() => ({
    ready: status === 'ready',
    status,
    error,
    ensureRuntime,
    retryRuntime,
  }), [ensureRuntime, error, retryRuntime, status]);

  const controller = useMemo(() => ({
    enabled,
    markFailed,
    markReady,
    registerOutlet,
    resetKey: runtimeResetKey,
    unregisterOutlet,
  }), [enabled, markFailed, markReady, registerOutlet, runtimeResetKey, unregisterOutlet]);

  return (
    <AuthRuntimeControllerContext.Provider value={controller}>
      <AuthRuntimeContext.Provider value={value}>
        {children}
        {enabled && (
          <AuthRuntimeErrorBoundary fallback={null} onError={markFailed} resetKey={runtimeResetKey}>
            <Suspense fallback={null}>
              <AuthRuntimeReadyBoundary onReady={markReady}>
                <AuthRuntimePortal outlet={outlet} />
              </AuthRuntimeReadyBoundary>
            </Suspense>
          </AuthRuntimeErrorBoundary>
        )}
      </AuthRuntimeContext.Provider>
    </AuthRuntimeControllerContext.Provider>
  );
}

interface AuthRuntimeBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}

export function AuthRuntimeBoundary({ children, fallback }: AuthRuntimeBoundaryProps) {
  const controller = useContext(AuthRuntimeControllerContext);
  const { ready } = useAuthRuntime();
  const outletId = useId();
  const outletRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const target = outletRef.current;
    if (!controller || !target) return;

    controller.registerOutlet(outletId, target, children);
    return () => controller.unregisterOutlet(outletId);
  }, [children, controller, outletId]);

  return (
    <>
      {!ready && fallback}
      <div ref={outletRef} style={{ display: ready ? 'contents' : 'none' }} />
    </>
  );
}

export function useAuthRuntime() {
  return useContext(AuthRuntimeContext);
}
