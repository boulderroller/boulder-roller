import type {
  AppNotification,
  FeedActivity,
  LinkTarget,
  LinkTargetType,
  PrimaryAction,
  SocialReport,
} from './api';

type LooseTargetType = LinkTargetType | string | null | undefined;

function stringValue(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return null;
}

function metadataString(metadata: Record<string, unknown> | null | undefined, keys: string[]): string | null {
  for (const key of keys) {
    const value = stringValue(metadata?.[key]);
    if (value) return value;
  }
  return null;
}

export function normalizeTargetType(type: LooseTargetType): LinkTargetType | null {
  const normalized = String(type ?? '').trim().toLowerCase().replace(/-/g, '_');
  if (!normalized) return null;
  if (normalized === 'user' || normalized === 'profile' || normalized === 'rider') return 'rider';
  if (normalized === 'ride' || normalized === 'activity') return 'ride';
  if (normalized === 'ride_media' || normalized === 'photo' || normalized === 'media') return 'ride_media';
  if (normalized === 'vault' || normalized === 'segment' || normalized === 'climb') return 'climb';
  if (normalized === 'leaderboard' || normalized === 'recordboard' || normalized === 'record_board') {
    return 'record_board';
  }
  if (normalized === 'legend' || normalized === 'locallegend' || normalized === 'local_legend') {
    return 'local_legend';
  }
  if (normalized === 'proof' || normalized === 'scan_tx' || normalized === 'scan_account') {
    return normalized;
  }
  if (normalized === 'report' || normalized === 'comment' || normalized === 'feed_event') {
    return normalized;
  }
  if (
    normalized === 'settlement'
    || normalized === 'device'
    || normalized === 'session'
    || normalized === 'connected_app'
    || normalized === 'integration'
  ) {
    return 'feed_event';
  }
  return null;
}

export function canonicalTarget(
  target: {
    type?: LooseTargetType;
    id?: string | number | null;
    label?: string | null;
    source?: string | null;
    metadata?: Record<string, unknown>;
  } | null | undefined,
): LinkTarget | null {
  const type = normalizeTargetType(target?.type);
  const id = stringValue(target?.id);
  if (!type || !id) return null;
  return {
    contractVersion: 'target_action.v1',
    type,
    id,
    ...(target?.label ? { label: target.label } : {}),
    ...(target?.source ? { source: target.source } : {}),
    ...(target?.metadata ? { metadata: target.metadata } : {}),
  };
}

export function isBoulderScanTargetType(type: LooseTargetType): boolean {
  const normalized = normalizeTargetType(type);
  return normalized === 'proof' || normalized === 'scan_tx' || normalized === 'scan_account';
}

export function primaryActionForTarget(target: LinkTarget | null | undefined): PrimaryAction {
  switch (normalizeTargetType(target?.type)) {
    case 'rider':
      return 'open_rider';
    case 'ride':
    case 'ride_media':
      return 'open_ride';
    case 'climb':
    case 'record_board':
    case 'local_legend':
      return 'open_climb';
    case 'proof':
    case 'scan_tx':
    case 'scan_account':
      return 'open_scan';
    case 'report':
      return 'open_report';
    case 'comment':
      return 'open_comment';
    case 'feed_event':
      return 'open_feed_event';
    default:
      return 'unavailable';
  }
}

export function targetFromFeedActivity(activity: FeedActivity): LinkTarget | null {
  const direct = canonicalTarget(activity.target);
  if (direct) return direct;

  const metadata = (activity.metadata ?? {}) as Record<string, unknown>;
  const rideId = metadataString(metadata, ['rideId', 'ride_id']);
  if (rideId) return canonicalTarget({ type: 'ride', id: rideId, source: 'feed.metadata' });
  const climbId = metadataString(metadata, ['climbId', 'climb_id', 'vaultId', 'vault_id']);
  if (climbId) return canonicalTarget({ type: 'climb', id: climbId, source: 'feed.metadata' });
  const riderId = metadataString(metadata, ['riderId', 'userId', 'user_id']);
  if (riderId) return canonicalTarget({ type: 'rider', id: riderId, source: 'feed.metadata' });
  return null;
}

export function targetFromNotification(notification: AppNotification): LinkTarget | null {
  const direct = canonicalTarget(notification.target);
  const metadata = notification.metadata ?? {};
  if (direct?.type !== 'comment') {
    if (direct) return direct;
  }

  const targetType = normalizeTargetType(metadataString(metadata, ['targetType', 'target_type']));
  const targetId = metadataString(metadata, ['targetId', 'target_id']);
  if (targetType && targetId) return canonicalTarget({ type: targetType, id: targetId, source: 'notification.metadata' });

  const reportId = metadataString(metadata, ['reportId', 'report_id']);
  if (reportId) return canonicalTarget({ type: 'report', id: reportId, source: 'notification.metadata' });

  const rideId = metadataString(metadata, [
    'rideId',
    'ride_id',
    'serverRideId',
    'server_ride_id',
    'activityId',
    'activity_id',
  ]);
  if (rideId) return canonicalTarget({ type: 'ride', id: rideId, source: 'notification.metadata' });

  if (direct) return direct;

  const climbId = metadataString(metadata, [
    'climbId',
    'climb_id',
    'vaultId',
    'vault_id',
  ]);
  if (climbId) return canonicalTarget({ type: 'climb', id: climbId, source: 'notification.metadata' });

  const userId = metadataString(metadata, [
    'userId',
    'user_id',
    'riderId',
    'rider_id',
    'profileId',
    'profile_id',
    'followerId',
    'follower_id',
  ]);
  if (userId) return canonicalTarget({ type: 'rider', id: userId, source: 'notification.metadata' });
  return null;
}

export function targetFromReport(report: SocialReport): LinkTarget | null {
  const direct = canonicalTarget(report.target);
  const metadata = {
    ...(report.moderationMetadata ?? {}),
    ...(direct?.metadata ?? {}),
  };
  const rideId = metadataString(metadata, ['rideId', 'ride_id', 'serverRideId', 'server_ride_id']);
  if (direct?.type === 'ride_media' && rideId) {
    return canonicalTarget({
      type: 'ride',
      id: rideId,
      source: 'moderation.report.media',
      metadata,
    });
  }

  if (direct) return direct;

  if (normalizeTargetType(report.targetType) === 'ride_media' && rideId) {
    return canonicalTarget({
      type: 'ride',
      id: rideId,
      source: 'moderation.report.metadata',
      metadata,
    });
  }

  return canonicalTarget({
    type: report.targetType,
    id: report.targetId,
    source: 'moderation.report',
  });
}
