import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useParams, useLocation } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import ExplorerShell from '@/components/ExplorerShell';
import { LoadingState } from '@/components/PageStates';
import { queryClient } from '@/lib/queryClient';

const ObservatoryPage = lazy(() => import('@/pages/ObservatoryPage'));
const VaultPage = lazy(() => import('@/pages/VaultPage'));
const TransactionPage = lazy(() => import('@/pages/TransactionPage'));
const AccountPage = lazy(() => import('@/pages/AccountPage'));
const ProofPage = lazy(() => import('@/pages/ProofPage'));
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'));

function LegacyVaultRedirect() {
  const { id = '' } = useParams();
  return <Navigate to={`/climb/${id}`} replace />;
}

function PageFallback() {
  const path = useLocation().pathname;
  return path === '/' || path.startsWith('/climb/') ? null : <LoadingState title="Loading page" />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ExplorerShell>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/" element={<ObservatoryPage />} />
              <Route path="/climb/:id" element={<VaultPage />} />
              <Route path="/vault/:id" element={<LegacyVaultRedirect />} />
              <Route path="/tx/:signature" element={<TransactionPage />} />
              <Route path="/account/:pubkey" element={<AccountPage />} />
              <Route path="/proof/:id" element={<ProofPage />} />
              <Route path="/observatory" element={<Navigate to="/" replace />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </Suspense>
        </ExplorerShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
