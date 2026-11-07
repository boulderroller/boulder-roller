import { Link } from 'react-router-dom';
import AddressDisplay from '@/components/AddressDisplay';
import CopyButton from '@/components/CopyButton';
import RelativeTime from '@/components/RelativeTime';
import { describeExplorerEvent, extractEventReferences, type ExplorerReference } from '@/lib/explorer';
import { formatCount, humanizeEventName, shortenAddress } from '@/lib/format';
import type { ExplorerEvent } from '@/types';

type EventFeedItemProps = {
  event: ExplorerEvent;
  omitKinds?: ExplorerReference['kind'][];
};

function renderReference(reference: ExplorerReference) {
  if (reference.kind === 'climb') {
    return (
      <Link to={`/climb/${reference.value}`} className="feed-context__link">
        {reference.label} #{reference.value}
      </Link>
    );
  }

  if (reference.kind === 'account') {
    return <AddressDisplay address={reference.value} chars={4} />;
  }

  return (
    <span className="feed-context__text">
      {reference.label} {reference.value}
    </span>
  );
}

export default function EventFeedItem({ event, omitKinds = [] }: EventFeedItemProps) {
  const references = extractEventReferences(event).filter((reference) => !omitKinds.includes(reference.kind));
  const story = describeExplorerEvent(event);

  return (
    <article className="feed-item">
      <div className="feed-item__meta">
        <span className="event-badge">{humanizeEventName(event.event_name)}</span>
        <span className="addr-group">
          <Link to={`/tx/${event.tx_signature}`} className="mono-link">
            {shortenAddress(event.tx_signature, 8)}
          </Link>
          <CopyButton text={event.tx_signature} />
        </span>
      </div>
      {references.length ? (
        <div className="feed-item__context">
          {references.map((reference) => (
            <span className="feed-context" key={`${reference.kind}-${reference.label}-${reference.value}`}>
              {renderReference(reference)}
            </span>
          ))}
        </div>
      ) : null}
      <div className="feed-item__story">
        <strong className="feed-item__story-title">{story.title}</strong>
        <p className="feed-item__story-detail">{story.detail}</p>
        {story.highlights.length ? (
          <div className="meta-badges">
            {story.highlights.map((highlight) => (
              <span className="meta-badge meta-badge--story" key={highlight}>
                {highlight}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="feed-item__body">
        <span><RelativeTime value={event.block_time} /></span>
        <span>slot {formatCount(event.slot)}</span>
      </div>
    </article>
  );
}
