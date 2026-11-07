import { targetFromNotification } from '../../lib/targetActions';
import type { AppNotification } from '../../lib/api';

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

describe('targetFromNotification', () => {
  test('routes explicit user targets to rider detail', () => {
    expect(targetFromNotification(notification({
      target: { type: 'user' as never, id: 'user-1' },
    }))).toMatchObject({ type: 'rider', id: 'user-1' });
  });

  test('routes climb aliases to climb detail targets', () => {
    expect(targetFromNotification(notification({
      target: { type: 'local-legend' as never, id: 'vault-42' },
    }))).toMatchObject({ type: 'local_legend', id: 'vault-42' });
    expect(targetFromNotification(notification({
      metadata: { vault_signature: 'vault-sig-1' },
    }))).toBeNull();
    expect(targetFromNotification(notification({
      metadata: { vault_id: 'vault-42' },
    }))).toMatchObject({ type: 'climb', id: 'vault-42' });
  });

  test('falls back from comment-style targets to ride metadata', () => {
    expect(targetFromNotification(notification({
      target: { type: 'comment', id: 'comment-1' },
      metadata: { ride_id: 'ride-1' },
    }))).toMatchObject({ type: 'ride', id: 'ride-1' });
  });

  test('supports target_type and target_id metadata', () => {
    expect(targetFromNotification(notification({
      metadata: { target_type: 'record_board', target_id: 'climb-1' },
    }))).toMatchObject({ type: 'record_board', id: 'climb-1' });
  });
});
