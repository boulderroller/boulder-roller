import {
  buildLiveSensorDisplay,
  buildSensorReadinessDisplay,
  displayForConnectionStatus,
  friendlyBleError,
} from '../sensorDisplay';

describe('sensorDisplay', () => {
  test('translates connection states into rider-facing labels', () => {
    expect(displayForConnectionStatus('connected')).toEqual({
      label: 'Ready',
      tone: 'ready',
    });
    expect(displayForConnectionStatus('connecting')).toEqual({
      label: 'Connecting',
      tone: 'working',
    });
    expect(displayForConnectionStatus('error')).toEqual({
      label: 'Needs attention',
      tone: 'attention',
    });
    expect(displayForConnectionStatus('disconnected')).toEqual({
      label: 'Not nearby',
      tone: 'muted',
    });
  });

  test('builds compact pre-ride readiness summaries', () => {
    expect(buildSensorReadinessDisplay({
      connectedKinds: ['power', 'heart_rate'],
      pairedCount: 3,
    })).toEqual({
      label: 'Power · HR ready',
      detail: '2 connected · 3 paired',
      tone: 'ready',
    });

    expect(buildSensorReadinessDisplay({
      connectedKinds: [],
      pairedCount: 2,
      connectingCount: 1,
    })).toEqual({
      label: 'Connecting sensors',
      detail: '1 connecting · 2 paired',
      tone: 'working',
    });

    expect(buildSensorReadinessDisplay({
      connectedKinds: [],
      pairedCount: 0,
    })).toEqual({
      label: 'No sensors',
      detail: 'GPS-only ride',
      tone: 'muted',
    });

    expect(buildSensorReadinessDisplay({
      connectedKinds: [],
      pairedCount: 2,
    })).toEqual({
      label: 'Sensors not nearby',
      detail: '2 paired · rides use GPS only until they reconnect',
      tone: 'muted',
    });
  });

  test('keeps absent live sensor values unavailable instead of zero', () => {
    const items = buildLiveSensorDisplay({
      connectedKinds: ['power'],
      power: null,
      heartRate: null,
      cadence: null,
    });

    expect(items).toEqual([
      { label: 'Power', value: '--', unit: 'W', state: 'waiting' },
      { label: 'Heart', value: '--', unit: 'bpm', state: 'missing' },
      { label: 'Cadence', value: '--', unit: 'rpm', state: 'waiting' },
    ]);
  });

  test('formats live sensor samples when available', () => {
    const items = buildLiveSensorDisplay({
      connectedKinds: ['power', 'heart_rate', 'cadence'],
      power: { power_w: 214.4, timestamp_ms: 1 },
      heartRate: { heart_rate_bpm: 151, timestamp_ms: 1 },
      cadence: { cadence_rpm: 88.7, timestamp_ms: 1 },
    });

    expect(items.map((item) => item.value)).toEqual(['214', '151', '89']);
    expect(items.every((item) => item.state === 'live')).toBe(true);
  });

  test('maps raw BLE errors to calm recovery copy', () => {
    expect(friendlyBleError(new Error('Bluetooth permission denied'))).toBe(
      'Allow Bluetooth access in Settings, then try again.',
    );
    expect(friendlyBleError(new Error('BLE not powered on after 5000ms'))).toBe(
      'Turn on Bluetooth and keep the sensor awake, then try again.',
    );
    expect(friendlyBleError(new Error('Connection lost'))).toBe(
      'Keep the sensor awake and near your phone, then try again.',
    );
  });
});
