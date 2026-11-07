import { lazy, Suspense } from 'react';
import { LoadingRows } from '../loading/LoadingSystem';

const ActivityFeedCore = lazy(() => import('./ActivityFeedCore'));

interface ActivityFeedProps {
  isConnected: boolean;
}

export default function ActivityFeed(props: ActivityFeedProps) {
  return (
    <Suspense fallback={<LoadingRows label="Loading feed" rows={5} />}>
      <ActivityFeedCore {...props} />
    </Suspense>
  );
}
