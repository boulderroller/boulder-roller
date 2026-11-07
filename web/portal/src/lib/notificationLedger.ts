import type { Notification } from './api';
import { formatInteger, formatMonthDay, formatOrdinal, formatRaceTime, formatTime, formatTokenAmount } from './formatters';
import { getPublicRiderDisplayName, getPublicRiderPath } from './riderIdentity';
import { stage1Amount } from './stage1';
import { stage1Copy } from './stage1Copy';

/*
 * The consequence ledger (Tim-ratified 2026-09-03, board "Notifications — the
 * consequence ledger" on the Night Ledger Rooms canvas).
 *
 * A push is a consequence of the loop: a seat won or lost, a settlement, a
 * ride counted. The row says the noun the push is about, the backend's title
 * and the time beneath it, and one trailing value read from the push's own
 * metadata. Nothing here composes a sentence; the strings are the backend's.
 */

export type PushKind =
  | 'entry'
  | 'seat-lost'
  | 'legend'
  | 'money'
  | 'ride'
  | 'attention'
  | 'kudos'
  | 'comment'
  | 'follow'
  | 'account'
  | 'system';

const KINDS: Record<string, PushKind> = {
  leaderboard_entered: 'entry',
  rank_changed: 'entry',
  record_rank_moved: 'entry',
  kom_achieved: 'entry',
  kom_beaten: 'entry',
  rank_moved: 'entry',
  leaderboard_bumped: 'seat-lost',
  local_legend_moved: 'legend',
  local_legend: 'legend',
  payout_received: 'money',
  stake_payout: 'money',
  legend_payout: 'money',
  staking_reward: 'money',
  settlement_finalized: 'money',
  settlement: 'money',
  ride_completed: 'ride',
  ride_finalized: 'ride',
  ride_failed: 'attention',
  kudos_created: 'kudos',
  ride_kudos: 'kudos',
  kudos: 'kudos',
  like: 'kudos',
  comment_created: 'comment',
  comment: 'comment',
  follow_created: 'follow',
  new_follower: 'follow',
  follow: 'follow',
  login_new_device: 'account',
  session_revoked: 'account',
  strava_revoked: 'account',
};

const SOCIAL_KINDS = new Set<PushKind>(['kudos', 'comment', 'follow']);
/** Kinds whose backend message is the information (a reason, a device). */
const MESSAGE_LED_KINDS = new Set<PushKind>(['attention', 'account']);

export function normalizeNotificationType(type: string | null | undefined): string {
  if (!type) return 'system';
  return type.replace(/([A-Z])/g, '_$1').toLowerCase();
}

export function resolveNotificationType(notification: Notification): string {
  return normalizeNotificationType(
    notification.notificationType
      ?? notification.eventType
      ?? notification.legacyType
      ?? null,
  );
}

export function pushKind(type: string): PushKind {
  return KINDS[type] ?? 'system';
}

export function notificationTargetPath(notification: Notification): string {
  const actionUrl = notification.actionUrl?.trim();
  if (actionUrl) return actionUrl;

  const target = notification.target;
  const targetId = target?.id ? encodeURIComponent(target.id) : null;
  if (!target?.type || !targetId) return '/notifications';

  switch (target.type) {
    case 'ride':
      return `/activities/${targetId}`;
    case 'climb':
    case 'record_board':
    case 'local_legend':
      return `/climbs/${targetId}`;
    case 'vault':
      return `/vaults/${targetId}`;
    case 'rider':
    case 'user':
      return `/riders/${targetId}`;
    case 'report':
      return `/notifications?reportId=${targetId}`;
    case 'proof':
      return `/notifications?proofId=${targetId}`;
    case 'scan_tx':
      return `/notifications?scanTx=${targetId}`;
    case 'scan_account':
      return `/notifications?scanAccount=${targetId}`;
    default:
      return '/notifications';
  }
}

export interface PushRow {
  kind: PushKind;
  /** The noun the push is about: the climb, the ride, the rider; the title when nothing names it. */
  noun: string;
  /** The backend's title (or message where that is the information), then the time. */
  sub: string;
  /** The one consequence the push carries, or nothing. */
  value: string | null;
  valueTitle?: string;
  actorName: string | null;
  actorPath: string | null;
  path: string;
}

type Metadata = NonNullable<Notification['metadata']>;

function metadataNumber(metadata: Metadata, ...keys: string[]): number | null {
  for (const key of keys) {
    const raw = metadata[key];
    const value = typeof raw === 'string' ? Number(raw) : raw;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function metadataString(metadata: Metadata, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = metadata[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function trimSentence(value: string): string {
  return value.trim().replace(/\.$/, '');
}

function pushValue(kind: PushKind, metadata: Metadata): string | null {
  switch (kind) {
    case 'entry': {
      const rank = metadataNumber(metadata, 'rank');
      if (rank != null) return formatOrdinal(rank);
      const seconds = metadataNumber(metadata, 'timeSeconds', 'time', 'timeInVaultS');
      return seconds != null ? formatRaceTime(seconds) : null;
    }
    case 'seat-lost': {
      // metadata.rank is not an authoritative resulting place. Even a retained
      // NotificationTransition.beforePlace needs the approved S08 qualifier,
      // which remains empty. Neither the event nor today's board supplies it.
      return null;
    }
    case 'money': {
      if (metadata.stage1 === true) return stage1Amount({ amount: metadata.amountBaseUnits, kind: metadata.kind as string, mint: metadata.mint as string });
      const amount = metadataNumber(metadata, 'payoutAmount', 'dungAmount', 'amount');
      return amount != null ? `${formatTokenAmount(amount)} DUNG` : null;
    }
    case 'ride': {
      const cal = metadataNumber(metadata, 'calEarned');
      return cal != null ? `${formatTokenAmount(cal)} CAL` : null;
    }
    default:
      return null;
  }
}

/** The row for one push. `when` is the time word the surface wants beside the title. */
export function describePush(notification: Notification, when: string): PushRow {
  const type = resolveNotificationType(notification);
  const kind = pushKind(type);
  const metadata: Metadata = notification.metadata ?? {};
  const title = metadata.stage1 === true ? stage1Copy.payoutNotification : notification.title?.trim() || '';
  const message = notification.message?.trim() || '';
  const targetLabel = notification.target?.label?.trim() || null;
  const social = SOCIAL_KINDS.has(kind);
  const actor = social && notification.actor ? notification.actor : null;
  const actorName = actor ? getPublicRiderDisplayName(actor) : null;
  const actorPath = actor ? getPublicRiderPath(actor) : null;

  const noun = actorName
    ?? metadataString(metadata, 'vaultName', 'climbName')
    ?? metadataString(metadata, 'rideTitle')
    ?? targetLabel
    ?? title;

  const lead = MESSAGE_LED_KINDS.has(kind)
    ? (message ? trimSentence(message) : title)
    : noun === title
      ? (message ? trimSentence(message) : null)
      : title;

  const week = kind === 'money' ? metadataNumber(metadata, 'settlementWeek', 'week') : null;
  const extra = social && targetLabel && targetLabel !== noun
    ? targetLabel
    : week != null
      ? ['Week', formatInteger(week)].join(' ')
      : null;

  return {
    kind,
    noun,
    sub: [lead, extra, when].filter(Boolean).join(' · '),
    value: pushValue(kind, metadata),
    ...(metadata.stage1 === true && typeof metadata.mint === 'string' ? { valueTitle: metadata.mint } : {}),
    actorName,
    actorPath,
    path: notificationTargetPath(notification),
  };
}

/** The bell's stamp: the time when the push is from today, otherwise its day. */
export function pushStamp(value: string, now: Date = new Date()): string {
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return '';
  const sameDay = when.getFullYear() === now.getFullYear()
    && when.getMonth() === now.getMonth()
    && when.getDate() === now.getDate();
  return sameDay ? formatTime(when) : formatMonthDay(when);
}
