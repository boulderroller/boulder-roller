import { getStateFromPath } from '@react-navigation/native';

import { linking } from '../linking';

jest.mock('expo-linking', () => ({
  createURL: jest.fn(() => 'boulderroller://'),
}));

describe('mobile linking', () => {
  test('registers native and public URL prefixes', () => {
    expect(linking.prefixes).toEqual(expect.arrayContaining([
      'boulderroller://',
      'com.boulderroller.app://',
      'https://boulderroller.app',
    ]));
  });

  test('maps tab links to the tab navigator', () => {
    expect(getStateFromPath('/record', linking.config as any)?.routes[0]).toMatchObject({
      name: 'Tabs',
      state: {
        routes: [{ name: 'Record' }],
      },
    });
  });

  test('maps search links to the search screen', () => {
    expect(getStateFromPath('/search', linking.config as any)?.routes[0]).toMatchObject({
      name: 'Search',
    });
  });

  test('maps rider profile links to RiderDetail', () => {
    const state = getStateFromPath('/riders/tim', linking.config as any);

    expect(state?.routes[0]).toMatchObject({
      name: 'RiderDetail',
      params: { identifier: 'tim' },
    });

    expect(getStateFromPath('/rider/tim', linking.config as any)?.routes[0]).toMatchObject({
      name: 'RiderDetail',
      params: { identifier: 'tim' },
    });
  });

  test('maps ride and climb detail links to detail screens', () => {
    expect(getStateFromPath('/rides/ride-123', linking.config as any)?.routes[0]).toMatchObject({
      name: 'RideDetail',
      params: { rideId: 'ride-123' },
    });
    expect(getStateFromPath('/activities/ride-123', linking.config as any)?.routes[0]).toMatchObject({
      name: 'RideDetail',
      params: { rideId: 'ride-123' },
    });

    expect(getStateFromPath('/climbs/climb-456', linking.config as any)?.routes[0]).toMatchObject({
      name: 'ClimbDetail',
      params: { climbId: 'climb-456' },
    });
    expect(getStateFromPath('/segments/climb-456', linking.config as any)?.routes[0]).toMatchObject({
      name: 'ClimbDetail',
      params: { climbId: 'climb-456' },
    });
    expect(getStateFromPath('/climbs/climb-456/local-legend', linking.config as any)?.routes[0]).toMatchObject({
      name: 'ClimbDetail',
      params: { climbId: 'climb-456' },
    });
  });

  test('maps climb leaderboard links to leaderboard screen', () => {
    expect(getStateFromPath('/climbs/climb-456/leaderboard', linking.config as any)?.routes[0]).toMatchObject({
      name: 'ClimbLeaderboard',
      params: { climbId: 'climb-456' },
    });
  });
});
