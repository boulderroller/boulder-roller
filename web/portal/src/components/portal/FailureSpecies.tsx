import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Slot } from '../loading/Slot';
import '../../styles/portal-public-rooms.css';

const AccessPanel = lazy(() => import('../auth/AccessPanel'));

export function useOffline() {
  const [offline, setOffline] = useState(() => !navigator.onLine);
  useEffect(() => {
    const update = () => setOffline(!navigator.onLine);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  return offline;
}

// Backend codes never reach a rider's row: a description is only shown when it reads as a sentence.
const riderSentence = (value: unknown): string | undefined => typeof value === 'string' && /\s/.test(value.trim()) ? value : undefined;

export function StateRow({ title, description, action, icon: _icon, className = '', ...props }: {
  icon?: ReactNode; title?: ReactNode; description?: ReactNode; action?: ReactNode; className?: string;
} & Omit<React.HTMLAttributes<HTMLDivElement>, 'title'>) {
  const sentence = typeof description === 'string' ? riderSentence(description) : description;
  return <div className={`ledger-state-row ${className}`} {...props}>
    <span className="ledger-state-mark" aria-hidden="true" />
    <div className="ledger-state-copy">{title && <h3>{title}</h3>}{sentence && <p>{sentence}</p>}</div>
    {action && <div className="ledger-state-action">{action}</div>}
  </div>;
}

export function RetainedRoom({ children }: { children: ReactNode }) {
  const offline = useOffline();
  return <div className="retained-room" data-offline={offline}>
    {offline && <StateRow className="offline-pinned-row" role="status" title="No connection. Try again." />}
    <div className="retained-room-content">{children}</div>
  </div>;
}

export function FailureSheet({ title, description, action, doors = [], shell = false }: {
  title?: ReactNode; description: ReactNode; action?: ReactNode;
  doors?: Array<{ label: string; href: string }>; shell?: boolean;
}) {
  return <div className="failure-paper">
    {shell && <header className="portal-shell__header"><a className="portal-shell__brand" href="/">Boulder Roller</a></header>}
    <section className="failure-sheet">
      <StateRow title={title} description={description} action={action} />
      {doors.map(door => <a className="failure-door-row" href={door.href} key={door.href}>{door.label}<span aria-hidden="true">›</span></a>)}
    </section>
  </div>;
}

function DoorFocus() {
  useEffect(() => { document.getElementById('access-sign-in-email')?.focus(); }, []);
  return null;
}

export function SignInDoor({ help }: { help: string }) {
  useEffect(() => {
    try { sessionStorage.setItem('br_return_url', location.pathname + location.search + location.hash); } catch { /* optional storage */ }
  }, []);
  return <Dialog.Root open>
    <Dialog.Portal><Dialog.Overlay className="public-room-scrim" />
      <Dialog.Content className="public-room-door access-gate" aria-describedby="session-door-help" onInteractOutside={e => e.preventDefault()} onEscapeKeyDown={e => e.preventDefault()}>
        <Dialog.Title className="sr-only">Sign in</Dialog.Title>
        <div className="access-entry-page"><div className="access-entry-page__intro">
          <p id="session-door-help">{help}</p>
          <Suspense fallback={<Slot width="18ch" />}><AccessPanel /><DoorFocus /></Suspense>
        </div></div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
