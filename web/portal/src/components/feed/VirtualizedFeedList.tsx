import { memo, useCallback, useEffect, type CSSProperties } from 'react';
import { useWindowVirtualizer } from '@tanstack/react-virtual';
import type { ActivityFeedItem as ActivityFeedItemType } from '../../types';
import { ActivityFeedItem } from './ActivityFeedItem';

interface VirtualizedFeedListProps {
  activities: ActivityFeedItemType[];
  scrollMargin: number;
  isLoading: boolean;
  isConnected: boolean;
  onLoadMore: () => void;
  onActivityClick: (activity: ActivityFeedItemType) => void;
  onRiderClick: (path: string) => void;
}

const estimateFeedItemSize = (activity: ActivityFeedItemType | undefined): number => {
  if (!activity) return 420;
  const hasBand = Boolean(activity.routePreview) || activity.visualType === 'image';
  return hasBand ? 430 : 220;
};

const VirtualizedFeedList = memo(({
  activities,
  scrollMargin,
  isLoading,
  isConnected,
  onLoadMore,
  onActivityClick,
  onRiderClick,
}: VirtualizedFeedListProps) => {
  const estimateSize = useCallback((index: number) => estimateFeedItemSize(activities[index]), [activities]);

  const rowVirtualizer = useWindowVirtualizer({
    count: activities.length,
    estimateSize,
    overscan: 6,
    scrollMargin,
  });

  const [lastItem] = [...rowVirtualizer.getVirtualItems()].reverse();

  useEffect(() => {
    if (!lastItem) return;
    if (lastItem.index >= activities.length - 8 && !isLoading && isConnected) {
      const timeoutId = setTimeout(() => {
        onLoadMore();
      }, 0);
      return () => clearTimeout(timeoutId);
    }
  }, [lastItem, activities.length, isLoading, isConnected, onLoadMore]);

  return (
    <div
      className="feed-virtual-list"
      style={{
        '--feed-virtual-list-height': `${rowVirtualizer.getTotalSize() - scrollMargin}px`,
      } as CSSProperties}
    >
      {rowVirtualizer.getVirtualItems().map((virtualItem) => (
        <div
          key={virtualItem.key}
          ref={rowVirtualizer.measureElement}
          data-index={virtualItem.index}
          className="feed-virtual-row"
          style={{
            '--feed-virtual-row-offset': `${virtualItem.start - scrollMargin}px`,
          } as CSSProperties}
        >
          <ActivityFeedItem
            activity={activities[virtualItem.index]}
            onClick={() => onActivityClick(activities[virtualItem.index])}
            onRiderClick={onRiderClick}
          />
        </div>
      ))}
    </div>
  );
});

VirtualizedFeedList.displayName = 'VirtualizedFeedList';

export default VirtualizedFeedList;
