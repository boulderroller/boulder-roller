import {
  canonicalTarget,
  isBoulderScanTargetType,
  primaryActionForTarget,
  targetFromNotification,
  targetFromReport,
} from '../targetActions';
import type { AppNotification, SocialReport } from '../api';

function notification(overrides: Partial<AppNotification>): AppNotification {
  return {
    id: 'notification-1',
    notificationType: 'system',
    title: 'Alert',
    message: 'Message',
    read: false,
    createdAt: '2026-05-01T12:00:00Z',
    ...overrides,
  };
}

describe('targetActions', () => {
  test('normalizes loose target aliases to canonical target refs', () => {
    expect(canonicalTarget({ type: 'user', id: 'user-1' })).toMatchObject({
      contractVersion: 'target_action.v1',
      type: 'rider',
      id: 'user-1',
    });
    expect(canonicalTarget({ type: 'local-legend', id: 'climb-1' })).toMatchObject({
      type: 'local_legend',
      id: 'climb-1',
    });
    expect(canonicalTarget({ type: 'settlement', id: '7:116' })).toMatchObject({
      type: 'feed_event',
      id: '7:116',
    });
  });

  test('maps targets to primary actions and scan affordances', () => {
    expect(primaryActionForTarget({ type: 'ride', id: 'ride-1' })).toBe('open_ride');
    expect(primaryActionForTarget({ type: 'ride_media', id: 'photo-1' })).toBe('open_ride');
    expect(primaryActionForTarget({ type: 'scan_tx', id: 'tx-1' })).toBe('open_scan');
    expect(isBoulderScanTargetType('proof')).toBe(true);
    expect(isBoulderScanTargetType('ride')).toBe(false);
  });

  test('prefers ride metadata over direct comment notifications', () => {
    expect(targetFromNotification(notification({
      target: { type: 'comment', id: 'comment-1' },
      metadata: { ride_id: 'ride-1' },
    }))).toMatchObject({ type: 'ride', id: 'ride-1' });
  });

  test('turns reports into navigable canonical targets', () => {
    const report = {
      id: 'report-1',
      reporterId: 'viewer',
      targetType: 'user',
      targetId: 'user-2',
      reason: 'spam',
      status: 'open',
      createdAt: '2026-05-01T12:00:00Z',
    } as SocialReport;

    expect(targetFromReport(report)).toMatchObject({ type: 'rider', id: 'user-2' });
  });

  test('maps ride media reports to their parent ride when metadata is present', () => {
    const report = {
      id: 'report-2',
      reporterId: 'viewer',
      targetType: 'ride_media',
      targetId: 'photo-1',
      target: {
        type: 'ride_media',
        id: 'photo-1',
        metadata: { rideId: 'ride-1', mediaId: 'photo-1' },
      },
      reason: 'privacy',
      status: 'open',
      createdAt: '2026-05-01T12:00:00Z',
    } as SocialReport;

    expect(targetFromReport(report)).toMatchObject({
      type: 'ride',
      id: 'ride-1',
      metadata: { rideId: 'ride-1', mediaId: 'photo-1' },
    });
  });

  test('does not turn vault signatures into climb route ids', () => {
    expect(targetFromNotification(notification({
      metadata: {
        vault_signature: 'a'.repeat(64),
      },
    }))).toBeNull();

    expect(targetFromNotification(notification({
      metadata: {
        vault_signature: 'a'.repeat(64),
        vault_id: 7,
      },
    }))).toMatchObject({ type: 'climb', id: '7' });
  });
});
