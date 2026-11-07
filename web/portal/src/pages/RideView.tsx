import { lazy, Suspense } from 'react';
import { RoomLoading } from '../components/loading/RoomLoading';

const RideViewCore = lazy(() => import('./RideViewCore'));

export default function RideView() {
  return (
    <Suspense fallback={<RoomLoading />}>
      <RideViewCore />
    </Suspense>
  );
}
