import { ExpoConfig, ConfigContext } from 'expo/config';

const DEFAULT_PRIVY_APP_ID = 'cmjp145cl008xl70clr2ho821';
const DEFAULT_PRIVY_CLIENT_ID = 'client-WY6UGQdegv84Ug3Gx9KnPFVkagwsCJ41YcPQ8oRJYoCqy';
const APP_ENV = process.env.APP_ENV ?? 'development';
const DEFAULT_API_URL = APP_ENV === 'development'
  ? 'http://localhost:8080'
  : 'https://api.boulderroller.xyz';
const UPDATE_CHANNEL = process.env.EAS_UPDATE_CHANNEL
  ?? (APP_ENV === 'production'
    ? 'production'
    : APP_ENV === 'development'
      ? 'development'
      : 'preview');

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'BoulderRoller',
  slug: 'boulderroller',
  scheme: 'boulderroller',
  version: '0.1.0',
  runtimeVersion: {
    policy: 'fingerprint',
  },
  updates: {
    url: 'https://u.expo.dev/317b4511-151c-4c11-8b21-7d06e6fa7092',
    requestHeaders: {
      'expo-channel-name': UPDATE_CHANNEL,
    },
    checkAutomatically: 'ON_LOAD',
    fallbackToCacheTimeout: 0,
  },
  orientation: 'portrait',
  icon: './assets/icon.png',
  userInterfaceStyle: 'dark',
  newArchEnabled: true,
  splash: {
    image: './assets/splash-icon.png',
    resizeMode: 'contain',
    backgroundColor: '#0a0a0a',
  },
  ios: {
    supportsTablet: false,
    bundleIdentifier: 'com.boulderroller.app',
    infoPlist: {
      NSLocationWhenInUseUsageDescription:
        'BoulderRoller uses your location to record cycling rides and detect climbs.',
      NSLocationAlwaysAndWhenInUseUsageDescription:
        'BoulderRoller needs background location access to record your ride while the screen is off.',
      NSBluetoothAlwaysUsageDescription:
        'BoulderRoller connects to your power meter, heart rate strap, and cadence sensors over Bluetooth.',
      CFBundleURLTypes: [
        {
          CFBundleURLSchemes: ['boulderroller', 'com.boulderroller.app'],
        },
      ],
      UIBackgroundModes: ['location', 'bluetooth-central'],
    },
  },
  android: {
    adaptiveIcon: {
      foregroundImage: './assets/adaptive-icon.png',
      backgroundColor: '#0a0a0a',
    },
    package: 'com.boulderroller.app',
    permissions: [
      'ACCESS_FINE_LOCATION',
      'ACCESS_COARSE_LOCATION',
      'ACCESS_BACKGROUND_LOCATION',
      'FOREGROUND_SERVICE',
      'FOREGROUND_SERVICE_LOCATION',
      'POST_NOTIFICATIONS',
      'BLUETOOTH',
      'BLUETOOTH_CONNECT',
      'BLUETOOTH_SCAN',
    ],
  },
  plugins: [
    'expo-secure-store',
    [
      'expo-sqlite',
      {
        // SQLCipher: enables encryption-at-rest for the SQLite store.
        // Passphrase is supplied at PRAGMA key time from expo-secure-store
        // (see services/database.ts initDatabase + services/secureStorage
        // getOrCreateDbEncryptionKey).
        useSQLCipher: true,
      },
    ],
    [
      'expo-location',
      {
        locationAlwaysAndWhenInUsePermission:
          'BoulderRoller needs background location access to record your ride while the screen is off.',
        locationWhenInUsePermission:
          'BoulderRoller uses your location to record cycling rides and detect climbs.',
        isAndroidBackgroundLocationEnabled: true,
        isAndroidForegroundServiceEnabled: true,
      },
    ],
    [
      'react-native-ble-plx',
      {
        // Central mode only — we scan and connect to sensors. No peripheral
        // advertising. The iOS plist keys above are explicit so config review
        // and generated native builds agree even before plugin introspection.
        isBackgroundEnabled: true,
        modes: ['central'],
        bluetoothAlwaysPermission:
          'BoulderRoller connects to your power meter, heart rate strap, and cadence sensors over Bluetooth.',
      },
    ],
    '@sentry/react-native',
  ],
  extra: {
    appEnv: APP_ENV,
    apiUrl: process.env.API_URL ?? DEFAULT_API_URL,
    updateChannel: UPDATE_CHANNEL,
    sentryDsn: process.env.SENTRY_DSN ?? '',
    privyAppId: process.env.PRIVY_APP_ID ?? DEFAULT_PRIVY_APP_ID,
    privyClientId: process.env.PRIVY_CLIENT_ID ?? DEFAULT_PRIVY_CLIENT_ID,
    buildNumber: process.env.EAS_BUILD_NUMBER ?? '1',
    eas: {
      projectId: '317b4511-151c-4c11-8b21-7d06e6fa7092',
    },
  },
});
