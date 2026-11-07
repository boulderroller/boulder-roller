// Jest setup -- runs before each test suite

// Mock expo-secure-store (used by auth token persistence + DB encryption key)
jest.mock('expo-secure-store', () => {
  // Simple in-memory store so getOrCreateDbEncryptionKey survives the
  // first-call/second-call round-trip in the same suite.
  const store = new Map<string, string>();
  return {
    getItemAsync: jest.fn(async (key: string) => store.get(key) ?? null),
    setItemAsync: jest.fn(async (key: string, value: string) => {
      store.set(key, value);
    }),
    deleteItemAsync: jest.fn(async (key: string) => {
      store.delete(key);
    }),
    WHEN_UNLOCKED_THIS_DEVICE_ONLY: 6,
  };
});

// Mock expo-constants
jest.mock('expo-constants', () => ({
  default: {
    expoConfig: {
      extra: {
        apiUrl: 'http://localhost:8080',
        sentryDsn: '',
        privyAppId: 'cmjp145cl008xl70clr2ho821',
        privyClientId: 'client-WY6UGQdegv84Ug3Gx9KnPFVkagwsCJ41YcPQ8oRJYoCqy',
        buildNumber: '1',
      },
    },
  },
}));

// Mock @sentry/react-native
jest.mock('@sentry/react-native', () => ({
  init: jest.fn(),
  wrap: jest.fn((component: unknown) => component),
  captureException: jest.fn(),
  captureMessage: jest.fn(),
  setUser: jest.fn(),
  setContext: jest.fn(),
  addBreadcrumb: jest.fn(),
  startTransaction: jest.fn(() => ({
    startChild: jest.fn(() => ({ finish: jest.fn() })),
    finish: jest.fn(),
  })),
  Severity: {
    Info: 'info',
    Warning: 'warning',
    Error: 'error',
  },
}));

// Mock @react-navigation/native
jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: () => ({
      navigate: jest.fn(),
      goBack: jest.fn(),
      reset: jest.fn(),
    }),
    useRoute: () => ({
      params: {},
    }),
  };
});

// Mock @privy-io/expo
jest.mock('@privy-io/expo', () => ({
  PrivyProvider: ({ children }: { children: unknown }) => children,
  usePrivy: jest.fn(() => ({
    isReady: true,
    authenticated: false,
    user: null,
    login: jest.fn(),
    logout: jest.fn(),
    getAccessToken: jest.fn(),
  })),
  useEmbeddedWallet: () => ({
    wallets: [],
  }),
  useEmbeddedSolanaWallet: jest.fn(() => ({
    status: 'not-created',
    wallets: [],
    create: jest.fn(),
  })),
  useLoginWithOAuth: () => ({
    login: jest.fn(),
    state: { status: 'initial' },
  }),
  useLoginWithEmail: jest.fn(() => ({
    sendCode: jest.fn(),
    loginWithCode: jest.fn(),
  })),
}));

// Mock @react-native-community/netinfo
jest.mock('@react-native-community/netinfo', () => ({
  addEventListener: jest.fn(() => jest.fn()),
  fetch: jest.fn().mockResolvedValue({
    isConnected: true,
    isInternetReachable: true,
  }),
}));

jest.mock('react-native-maps', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require('react');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require('react-native');

  function MapViewMock({ children, style, testID }: { children?: unknown; style?: unknown; testID?: string }) {
    return React.createElement(View, { style, testID }, children);
  }

  return {
    __esModule: true,
    default: MapViewMock,
    Polyline: () => null,
  };
});

// -----------------------------------------------------------------------
// Phase 1 mocks — GPS Recording + SQLite + Upload
// -----------------------------------------------------------------------

// Mock expo-location
jest.mock('expo-location', () => ({
  hasServicesEnabledAsync: jest.fn().mockResolvedValue(true),
  getForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted', canAskAgain: true }),
  getBackgroundPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted', canAskAgain: true }),
  requestForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted' }),
  requestBackgroundPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted' }),
  getCurrentPositionAsync: jest.fn().mockResolvedValue({
    coords: {
      latitude: 39.9526,
      longitude: -75.1652,
      altitude: 15.0,
      accuracy: 5.0,
      altitudeAccuracy: 3.0,
      heading: 90.0,
      speed: 8.0,
    },
    timestamp: Date.now(),
  }),
  watchPositionAsync: jest.fn().mockResolvedValue({ remove: jest.fn() }),
  startLocationUpdatesAsync: jest.fn().mockResolvedValue(undefined),
  stopLocationUpdatesAsync: jest.fn().mockResolvedValue(undefined),
  hasStartedLocationUpdatesAsync: jest.fn().mockResolvedValue(false),
  Accuracy: {
    Lowest: 1,
    Low: 2,
    Balanced: 3,
    High: 4,
    Highest: 5,
    BestForNavigation: 6,
  },
  ActivityType: {
    Fitness: 3,
  },
  LocationAccuracy: {
    Lowest: 1,
    Low: 2,
    Balanced: 3,
    High: 4,
    Highest: 5,
    BestForNavigation: 6,
  },
}));

// Mock expo-task-manager
jest.mock('expo-task-manager', () => ({
  defineTask: jest.fn(),
  isTaskDefined: jest.fn().mockReturnValue(false),
  isTaskRegisteredAsync: jest.fn().mockResolvedValue(false),
  unregisterTaskAsync: jest.fn().mockResolvedValue(undefined),
}));

// Mock expo-sqlite
const mockDb = {
  runSync: jest.fn().mockReturnValue({ changes: 0 }),
  getFirstSync: jest.fn().mockReturnValue(null),
  getAllSync: jest.fn().mockReturnValue([]),
  execSync: jest.fn(),
  runAsync: jest.fn().mockResolvedValue({ changes: 0 }),
  getFirstAsync: jest.fn().mockResolvedValue(null),
  getAllAsync: jest.fn().mockResolvedValue([]),
  execAsync: jest.fn().mockResolvedValue(undefined),
  withTransactionSync: jest.fn((fn: () => void) => fn()),
  withTransactionAsync: jest.fn(async (fn: () => Promise<void>) => fn()),
  closeSync: jest.fn(),
};
jest.mock('expo-sqlite', () => ({
  openDatabaseSync: jest.fn().mockReturnValue(mockDb),
  openDatabaseAsync: jest.fn().mockResolvedValue(mockDb),
}));

// Bootstrap the encrypted DB singleton before any test runs. Production code
// requires initDatabase() to be awaited at app boot; tests get the same
// guarantee here so individual suites don't have to think about it.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { initDatabase: _initDatabase } = require('./src/services/database');
beforeAll(async () => {
  await _initDatabase();
});

// Mock expo-file-system
jest.mock('expo-file-system', () => ({
  documentDirectory: '/mock/documents/',
  makeDirectoryAsync: jest.fn().mockResolvedValue(undefined),
  writeAsStringAsync: jest.fn().mockResolvedValue(undefined),
  readAsStringAsync: jest.fn().mockResolvedValue('<gpx></gpx>'),
  getInfoAsync: jest.fn().mockResolvedValue({ exists: true, size: 1000, isDirectory: false }),
  deleteAsync: jest.fn().mockResolvedValue(undefined),
  EncodingType: {
    UTF8: 'utf8',
    Base64: 'base64',
  },
}));

// Mock expo-crypto
jest.mock('expo-crypto', () => ({
  digest: jest.fn().mockResolvedValue(new Uint8Array(32).buffer),
  digestStringAsync: jest.fn().mockResolvedValue('mock-sha256-hash-abcdef1234567890'),
  CryptoDigestAlgorithm: {
    SHA256: 'SHA-256',
  },
  randomUUID: jest.fn(() => '00000000-0000-4000-8000-000000000000'),
  getRandomBytesAsync: jest.fn(async (n: number) => new Uint8Array(n)),
}));

// Mock @react-native-async-storage/async-storage (used by zustand persist)
jest.mock('@react-native-async-storage/async-storage', () => ({
  __esModule: true,
  default: {
    getItem: jest.fn().mockResolvedValue(null),
    setItem: jest.fn().mockResolvedValue(undefined),
    removeItem: jest.fn().mockResolvedValue(undefined),
    clear: jest.fn().mockResolvedValue(undefined),
    getAllKeys: jest.fn().mockResolvedValue([]),
    multiGet: jest.fn().mockResolvedValue([]),
    multiSet: jest.fn().mockResolvedValue(undefined),
    multiRemove: jest.fn().mockResolvedValue(undefined),
  },
}));

// Mock react-native-ble-plx. Tests that need interactivity override
// specific methods with mockImplementation in their beforeEach.
jest.mock('react-native-ble-plx', () => {
  const State = {
    Unknown: 'Unknown',
    Resetting: 'Resetting',
    Unsupported: 'Unsupported',
    Unauthorized: 'Unauthorized',
    PoweredOff: 'PoweredOff',
    PoweredOn: 'PoweredOn',
  };
  return {
    BleManager: jest.fn().mockImplementation(() => ({
      state: jest.fn().mockResolvedValue(State.PoweredOn),
      onStateChange: jest.fn((cb: (s: string) => void, emitCurrentState: boolean) => {
        if (emitCurrentState) cb(State.PoweredOn);
        return { remove: jest.fn() };
      }),
      startDeviceScan: jest.fn(),
      stopDeviceScan: jest.fn(),
      connectToDevice: jest.fn(),
      cancelDeviceConnection: jest.fn().mockResolvedValue(undefined),
      destroy: jest.fn(),
    })),
    State,
  };
});
