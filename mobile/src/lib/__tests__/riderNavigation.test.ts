import {
  publicRiderIdentity,
  riderProfileRouteParams,
  riderProfileRouteParamsFromIdentifier,
} from '../riderNavigation';

describe('rider profile navigation helpers', () => {
  test('routes public rider identity by username without carrying wallet into display identity', () => {
    const route = riderProfileRouteParams({
      id: 'user-1',
      wallet: 'WalletAAAA111111111111111111111111111111',
      username: '@tim',
      displayName: 'Tim',
      avatarUrl: 'https://example.test/avatar.png',
    }, { backLabel: 'Home' });

    expect(route).toEqual({
      identifier: 'tim',
      backLabel: 'Home',
      initialIdentity: {
        id: 'user-1',
        username: 'tim',
        displayName: 'Tim',
        avatarUrl: 'https://example.test/avatar.png',
        isPublic: undefined,
      },
    });
  });

  test('falls back to opaque user id before wallet for public surfaces', () => {
    expect(riderProfileRouteParams({
      id: 'user-2',
      wallet: 'WalletBBBB111111111111111111111111111111',
    })).toEqual({
      identifier: 'user-2',
      initialIdentity: {
        id: 'user-2',
        username: null,
        displayName: null,
        avatarUrl: null,
        isPublic: undefined,
      },
    });
  });

  test('keeps wallet out of public rider identity unless explicitly allowed for legacy lookup', () => {
    expect(publicRiderIdentity({
      wallet: 'WalletCCCC111111111111111111111111111111',
    })).toEqual({
      id: null,
      username: null,
      displayName: null,
      avatarUrl: null,
      isPublic: undefined,
    });

    expect(riderProfileRouteParams({
      wallet: 'WalletCCCC111111111111111111111111111111',
    })).toBeNull();

    expect(riderProfileRouteParams({
      wallet: 'WalletCCCC111111111111111111111111111111',
    }, { allowWalletFallback: true })?.identifier).toBe('WalletCCCC111111111111111111111111111111');
  });

  test('normalizes opaque target identifiers from reports and notifications', () => {
    expect(riderProfileRouteParamsFromIdentifier('user-3', null, { backLabel: 'Alerts' })).toEqual({
      identifier: 'user-3',
      backLabel: 'Alerts',
      initialIdentity: {
        id: null,
        username: null,
        displayName: null,
        avatarUrl: null,
        isPublic: undefined,
      },
    });
  });
});
