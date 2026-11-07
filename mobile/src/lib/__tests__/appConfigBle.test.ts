import appConfig from '../../../app.config';

describe('app.config BLE readiness', () => {
  test('threads the native Privy client id for iOS passwordless auth', () => {
    const config = appConfig({ config: {} } as never);

    expect(config.extra?.privyAppId).toBe('cmjp145cl008xl70clr2ho821');
    expect(config.extra?.privyClientId).toBe('client-WY6UGQdegv84Ug3Gx9KnPFVkagwsCJ41YcPQ8oRJYoCqy');
  });

  test('declares iPhone Bluetooth permission and central background mode explicitly', () => {
    const config = appConfig({ config: {} } as never);
    const infoPlist = config.ios?.infoPlist as Record<string, unknown>;

    expect(infoPlist.NSBluetoothAlwaysUsageDescription).toBe(
      'BoulderRoller connects to your power meter, heart rate strap, and cadence sensors over Bluetooth.',
    );
    expect(infoPlist.UIBackgroundModes).toEqual(
      expect.arrayContaining(['location', 'bluetooth-central']),
    );
    expect(config.plugins).toEqual(
      expect.arrayContaining([
        [
          'react-native-ble-plx',
          expect.objectContaining({
            isBackgroundEnabled: true,
            modes: ['central'],
          }),
        ],
      ]),
    );
  });
});
