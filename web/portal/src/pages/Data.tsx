import { lazy, Suspense } from 'react';
import { LoadingRows } from '../components/loading/LoadingSystem';

const DataCore = lazy(() => import('./DataCore'));

export default function Data() {
  return (
    <Suspense fallback={<LoadingRows label="Loading training" rows={4} />}>
      <DataCore />
    </Suspense>
  );
}
