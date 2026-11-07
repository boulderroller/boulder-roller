type StateProps = {
  title: string;
  detail?: string;
};

export function LoadingState({ title, detail }: StateProps) {
  return (
    <div className="state-card state-card--loading">
      <div className="state-card__eyebrow">Loading</div>
      <h2>{title}</h2>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}

export function ErrorState({ title, detail, onRetry }: StateProps & { onRetry?: () => void }) {
  return (
    <div className="state-card state-card--error">
      <div className="state-card__eyebrow">Unavailable</div>
      <h2>{title}</h2>
      {detail ? <p>{detail}</p> : null}
      {onRetry ? (
        <div className="state-card__actions">
          <button type="button" className="search-button" onClick={onRetry}>Try again</button>
        </div>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, detail }: StateProps) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}
