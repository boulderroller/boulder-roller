import { lazy, Suspense } from 'react';
import { PageLoading } from '../components/loading/PageLoading';

const RideViewCore = lazy(() => import('./RideViewCore'));

export default function RideView() {
  return (
    <Suspense fallback={<PageLoading />}>
      <RideViewCore />
    </Suspense>
  );
}
