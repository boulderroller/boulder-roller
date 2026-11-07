import { Slot } from '../components/loading/Slot';
import { useMemo, useState, type CSSProperties, type KeyboardEvent, type MouseEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertTriangle, Bell } from 'lucide-react';
import type { Notification } from '../lib/api';
import { useNotifications, useMarkAllNotificationsRead, useMarkNotificationRead } from '../hooks/queries';
import { formatInteger, formatMonthDay, formatTime, formatWeekday } from '../lib/formatters';
import { describePush, type PushRow } from '../lib/notificationLedger';
import { PushGlyph } from '../components/notifications/PushGlyph';
import { StateRow, PortalFrame, PortalPage } from '../components/portal/PortalSpine';

/*
 * Notifications — the consequence ledger (Tim-ratified 2026-09-03).
 *
 * Law 7: pushes, not rooms. The web has no tray, so the bell is the tray and
 * this page is the tray unrolled: the Rides tab's rhythm log, with days in the
 * rail and rows spaced by the real gaps between pushes. Row = glyph · noun ·
 * the backend's title and the time · one value from the push's metadata. The
 * row is the tap and deep-links to the surface; it marks itself read. Unread
 * is ink with the cobalt dot on the time line; read is soft. The four alert
 * switches live on the Settings rail.
 */

const PAGE_SIZE = 20;
const IDLE_GAP_CAP_DAYS = 8;

interface LedgerRow {
  notification: Notification;
  push: PushRow;
  idleDays: number;
  day: { word: string; date: string } | null;
}

function localDayNumber(value: string): number | null {
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return null;
  return Math.floor(new Date(when.getFullYear(), when.getMonth(), when.getDate()).getTime() / 86_400_000);
}

function dayWord(day: number, today: number, value: string): string {
  if (day === today) return 'Today';
  if (day === today - 1) return 'Yesterday';
  return formatWeekday(value);
}

function buildLedger(notifications: Notification[], today: number): LedgerRow[] {
  const ordered = [...notifications].sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  );
  const rows: LedgerRow[] = [];
  let previousDay: number | null = null;
  for (const notification of ordered) {
    const day = localDayNumber(notification.createdAt);
    const idleDays = previousDay !== null && day !== null ? Math.max(0, previousDay - day - 1) : 0;
    const marks = day !== null && day !== previousDay;
    rows.push({
      notification,
      push: describePush(notification, formatTime(notification.createdAt)),
      idleDays: Math.min(IDLE_GAP_CAP_DAYS, idleDays),
      day: marks && day !== null
        ? { word: dayWord(day, today, notification.createdAt), date: formatMonthDay(notification.createdAt) }
        : null,
    });
    previousDay = day ?? previousDay;
  }
  return rows;
}

function LedgerSkeleton() {
  return (
    <div className="notifications-log__rows notifications-log__rows--loading" aria-label="Loading notifications">
      {Array.from({ length: PAGE_SIZE }, (_, item) => item).map((item) => (
        <div key={item} className="notifications-log__row notifications-log__row--loading">
          <span className="notifications-log__rail" aria-hidden="true" />
          <span className="notifications-log__glyph" aria-hidden="true" />
          <span className="notifications-log__identity">
            <Slot variant="text" className="notifications-log__skeleton-name" />
            <Slot variant="text" className="notifications-log__skeleton-sub" />
          </span>
          <Slot variant="number" className="notifications-log__skeleton-value" />
        </div>
      ))}
    </div>
  );
}

export default function Notifications() {
  const navigate = useNavigate();
  const [requestedLimit, setRequestedLimit] = useState(PAGE_SIZE);
  const { data, isLoading, isFetching, error, refetch } = useNotifications({ limit: requestedLimit });
  const markNotificationRead = useMarkNotificationRead();
  const markAllNotificationsRead = useMarkAllNotificationsRead();

  const notifications = data?.notifications ?? [];
  const hasMore = notifications.length >= requestedLimit;
  const initialLoading = isLoading && notifications.length === 0;
  const loadingMore = isFetching && notifications.length > 0 && requestedLimit > notifications.length;
  const errorMessage = error instanceof Error ? error.message : 'Could not load notifications';
  const unreadCount = data?.unreadCount ?? notifications.filter((notification) => !notification.read).length;

  const today = localDayNumber(new Date().toISOString()) ?? 0;
  const rows = useMemo(() => buildLedger(notifications, today), [notifications, today]);

  const open = (notification: Notification, push: PushRow) => {
    if (!notification.read) markNotificationRead.mutate(notification.id);
    if (push.path.startsWith('http://') || push.path.startsWith('https://')) {
      window.location.assign(push.path);
      return;
    }
    navigate(push.path);
  };

  const handleRowKeyDown = (notification: Notification, push: PushRow, event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    open(notification, push);
  };

  const handleActorClick = (push: PushRow, event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (push.actorPath) navigate(push.actorPath);
  };

  return (
    <PortalPage className="notifications-page" aria-busy={initialLoading || isFetching} aria-live="polite">
      <PortalFrame>
        <div className="notifications-log">
          <div className="notifications-log__header">
            <div className="notifications-log__heading">
              <h1 className="notifications-log__title">Notifications</h1>
              {unreadCount > 0 ? (
                <span className="notifications-log__count">
                  <strong>{formatInteger(unreadCount)}</strong> unread
                </span>
              ) : null}
            </div>
            <div className="notifications-log__actions">
              <Link className="notifications-log__word" to="/settings?tab=alerts">Alerts</Link>
              {unreadCount > 0 ? (
                <button
                  type="button"
                  className="notifications-log__word"
                  onClick={() => markAllNotificationsRead.mutate()}
                  disabled={markAllNotificationsRead.isPending}
                >
                  Clear unread
                </button>
              ) : null}
            </div>
          </div>

          {error && notifications.length > 0 ? (
            <div className="notifications-log__state" role="status">
              <span><strong>Last loaded.</strong> {errorMessage}</span>
              <button type="button" className="notifications-log__retry" onClick={() => { void refetch(); }} disabled={isFetching}>
                Try again
              </button>
            </div>
          ) : null}

          {initialLoading ? (
            <LedgerSkeleton />
          ) : error && notifications.length === 0 ? (
            <StateRow
              icon={<AlertTriangle size={34} aria-hidden="true" />}
              title="Could not load notifications"
              description={errorMessage}
              action={(
                <button type="button" className="notifications-log__retry" onClick={() => { void refetch(); }}>
                  Try again
                </button>
              )}
            />
          ) : notifications.length === 0 ? (
            <StateRow
              icon={<Bell size={34} aria-hidden="true" />}
              title="Nothing here yet"
              description="Ride activity will show up here."
            />
          ) : (
            <>
              <div className="notifications-log__rows">
                {rows.map(({ notification, push, idleDays, day }) => (
                  <div
                    key={notification.id}
                    className="notifications-log__row"
                    role="button"
                    tabIndex={0}
                    data-state={notification.read ? 'read' : 'unread'}
                    data-kind={push.kind}
                    data-stage1={notification.metadata?.stage1 === true ? 'notification' : undefined}
                    style={{ '--notifications-log-idle-days': idleDays } as CSSProperties}
                    onClick={() => open(notification, push)}
                    onKeyDown={(event) => handleRowKeyDown(notification, push, event)}
                  >
                    {day ? (
                      <span className="notifications-log__day">
                        <strong>{day.word}</strong>
                        <span>{day.date}</span>
                      </span>
                    ) : (
                      <span className="notifications-log__rail" aria-hidden="true" />
                    )}
                    <span className="notifications-log__glyph" aria-hidden="true">
                      <PushGlyph kind={push.kind} />
                    </span>
                    <span className="notifications-log__identity">
                      <strong className="notifications-log__name">
                        {push.actorName && push.actorPath ? (
                          <button
                            type="button"
                            className="notification-row__actor"
                            data-rider-path={push.actorPath}
                            onClick={(event) => handleActorClick(push, event)}
                          >
                            {push.actorName}
                          </button>
                        ) : push.noun}
                      </strong>
                      <span className="notifications-log__sub">{push.sub}</span>
                    </span>
                    {push.value ? (
                      <strong className="notifications-log__value" title={push.valueTitle}>{push.value}</strong>
                    ) : (
                      <span aria-hidden="true" />
                    )}
                  </div>
                ))}
              </div>

              {hasMore && !error ? (
                <button
                  type="button"
                  className="notifications-log__more"
                  onClick={() => setRequestedLimit((current) => current + PAGE_SIZE)}
                  disabled={loadingMore}
                >
                  {loadingMore ? 'Loading more' : 'Load more'}
                </button>
              ) : null}
            </>
          )}
        </div>
      </PortalFrame>
    </PortalPage>
  );
}
