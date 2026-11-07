import { useDelayedVisibility } from './LoadingSystem';
import { Slot } from './Slot';

interface AppBootScreenProps {
  description?: string;
  eyebrow?: string;
  onRetry?: () => void;
  title?: string;
}

export default function AppBootScreen({
  description = 'Opening the app.',
  eyebrow: _eyebrow = 'Boulder Roller',
  onRetry,
  title = 'Opening Boulder Roller',
}: AppBootScreenProps) {
  const visible = useDelayedVisibility(!onRetry);
  const normalizedTitle = title.replace(/[.!?]+$/, '').trim();
  const normalizedDescription = description.replace(/[.!?]+$/, '').trim();
  const shouldAnnounceTitle = normalizedTitle !== normalizedDescription;

  return (
    <div className="app-boot-screen">
      <header className="app-boot-screen__header">
        <span className="app-boot-screen__brand">Boulder Roller</span>
        <div className="shell-live-rule" data-live={visible} aria-hidden="true" />
      </header>
      <div
        role={onRetry ? 'alert' : 'status'}
        aria-live={onRetry ? 'assertive' : 'polite'}
        className="app-boot-screen__panel"
      >
        {shouldAnnounceTitle && (
          <span className="app-boot-screen__sr-only">{title}. </span>
        )}
        <p className={onRetry ? "app-boot-screen__description" : "sr-only"}>
          {description}
        </p>

        {onRetry ? (
          <button type="button" className="app-boot-screen__retry" onClick={onRetry}>
            Try again
          </button>
        ) : (
          <Slot width="18ch" />
        )}
      </div>
    </div>
  );
}
