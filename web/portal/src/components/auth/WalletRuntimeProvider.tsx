import { lazy, Suspense, type ReactNode } from 'react';

const WalletContextProvider = lazy(() => (
  import('../../contexts/WalletContext')
    .then((module) => ({ default: module.WalletContextProvider }))
));

interface WalletRuntimeProviderProps {
  children: ReactNode;
  fallback?: ReactNode;
}

export function WalletRuntimeProvider({ children, fallback = null }: WalletRuntimeProviderProps) {
  return (
    <Suspense fallback={fallback}>
      <WalletContextProvider>
        {children}
      </WalletContextProvider>
    </Suspense>
  );
}
