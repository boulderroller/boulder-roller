import { type ReactNode } from 'react';
import { PrivyProvider } from '../../contexts/PrivyContext';

interface AuthRuntimeProvidersProps {
  children: ReactNode;
}

export default function AuthRuntimeProviders({ children }: AuthRuntimeProvidersProps) {
  return (
    <PrivyProvider>
      {children}
    </PrivyProvider>
  );
}
