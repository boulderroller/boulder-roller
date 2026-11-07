import { PowerMeterSource } from '../ble/powerMeterSource';
import {
  CYCLING_POWER_SERVICE,
  POWER_MEASUREMENT_CHAR,
  POWER_CONTROL_POINT_CHAR,
  uint8ArrayToBase64,
} from '../ble/manager';
import { POWER_CP_OPCODE } from '../ble/parsers/powerControlPoint';

type MonitorCallback = (error: unknown, char: { value?: string | null } | null) => void;
type DisconnectCallback = (error: unknown, device: unknown) => void;

function makeMockDevice() {
  const subscriptions: Array<{ service: string; char: string; cb: MonitorCallback; remove: jest.Mock }> = [];
  let disconnectCb: DisconnectCallback | null = null;
  const disconnectRemove = jest.fn();
  const monitor = jest.fn((service: string, char: string, cb: MonitorCallback) => {
    const remove = jest.fn();
    subscriptions.push({ service, char, cb, remove });
    return { remove };
  });
  const write = jest.fn().mockResolvedValue({});
  const onDisconnected = jest.fn((cb: DisconnectCallback) => {
    disconnectCb = cb;
    return { remove: disconnectRemove };
  });
  return {
    device: {
      id: 'pm-1',
      name: 'Stages LR',
      localName: null,
      monitorCharacteristicForService: monitor,
      writeCharacteristicWithResponseForService: write,
      onDisconnected,
    } as unknown as ConstructorParameters<typeof PowerMeterSource>[0],
    subscriptions,
    monitor,
    write,
    disconnectRemove,
    fire: (service: string, char: string, value: string | null, error: unknown = null) => {
      const sub = subscriptions.find((s) => s.service === service && s.char === char);
      if (!sub) throw new Error(`No subscription for ${service}/${char}`);
      sub.cb(error, value == null ? null : { value });
    },
    fireDisconnect: () => {
      if (!disconnectCb) throw new Error('No disconnect listener registered');
      disconnectCb(null, {} as never);
    },
  };
}

function u16le(v: number): [number, number] {
  return [v & 0xff, (v >> 8) & 0xff];
}
function s16le(v: number): [number, number] {
  const u = v < 0 ? v + 0x10000 : v;
  return u16le(u);
}

describe('PowerMeterSource', () => {
  test('subscribes to measurement and control point on start', async () => {
    const { device, monitor } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    expect(monitor).toHaveBeenCalledTimes(2);
    expect(monitor).toHaveBeenCalledWith(
      CYCLING_POWER_SERVICE,
      POWER_MEASUREMENT_CHAR,
      expect.any(Function),
    );
    expect(monitor).toHaveBeenCalledWith(
      CYCLING_POWER_SERVICE,
      POWER_CONTROL_POINT_CHAR,
      expect.any(Function),
    );
  });

  test('updates latest when a measurement notification fires', async () => {
    const { device, fire } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    // flags=0, power=240
    const bytes = new Uint8Array([0, 0, ...s16le(240)]);
    fire(CYCLING_POWER_SERVICE, POWER_MEASUREMENT_CHAR, uint8ArrayToBase64(bytes));

    const latest = source.getLatest();
    expect(latest).not.toBeNull();
    expect(latest!.power_w).toBe(240);
  });

  test('ignores error notifications without crashing', async () => {
    const { device, fire } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    fire(
      CYCLING_POWER_SERVICE,
      POWER_MEASUREMENT_CHAR,
      null,
      new Error('disconnected'),
    );
    expect(source.getLatest()).toBeNull();
  });

  test('derives cadence from two successive crank revolution samples', async () => {
    const { device, fire } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    // Two packets 1s apart with 3 crank revolutions between them → 180 rpm
    const flags = 0x0020; // crank rev present
    // Packet 1: revs=100, event=1.0s in 1/1024 units = 1024
    fire(
      CYCLING_POWER_SERVICE,
      POWER_MEASUREMENT_CHAR,
      uint8ArrayToBase64(
        new Uint8Array([
          ...u16le(flags),
          ...s16le(200),
          ...u16le(100),
          ...u16le(1024),
        ]),
      ),
    );
    expect(source.getLatest()?.cadence_rpm).toBeUndefined();

    // Packet 2: revs=103, event=2.0s (2048 in 1/1024 units)
    fire(
      CYCLING_POWER_SERVICE,
      POWER_MEASUREMENT_CHAR,
      uint8ArrayToBase64(
        new Uint8Array([
          ...u16le(flags),
          ...s16le(210),
          ...u16le(103),
          ...u16le(2048),
        ]),
      ),
    );
    const cadence = source.getLatest()?.cadence_rpm;
    expect(cadence).toBeCloseTo(180, 1);
  });

  test('stop unsubscribes both characteristics and clears cache', async () => {
    const { device, subscriptions } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    const measurementRemove = subscriptions[0].remove;
    const cpRemove = subscriptions[1].remove;

    await source.stop();

    expect(measurementRemove).toHaveBeenCalled();
    expect(cpRemove).toHaveBeenCalled();
    expect(source.getLatest()).toBeNull();
    expect(source.status).toBe('disconnected');
  });

  test('sendCommand resolves with parsed result when CP response indication arrives', async () => {
    const { device, fire, write } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    const cmdPromise = source.sendCommand({ type: 'start_offset_compensation' });

    // Verify we wrote the opCode request
    expect(write).toHaveBeenCalledWith(
      CYCLING_POWER_SERVICE,
      POWER_CONTROL_POINT_CHAR,
      expect.any(String),
    );

    // Simulate indication: [0x20, 0x0C (opCode), 0x01 (success), offset int16 = 42]
    fire(
      CYCLING_POWER_SERVICE,
      POWER_CONTROL_POINT_CHAR,
      uint8ArrayToBase64(
        new Uint8Array([
          0x20,
          POWER_CP_OPCODE.START_OFFSET_COMPENSATION,
          0x01,
          ...s16le(42),
        ]),
      ),
    );

    const result = await cmdPromise;
    expect(result.success).toBe(true);
    expect((result.data as { offset: number }).offset).toBe(42);
  });

  test('sendCommand handles error response code', async () => {
    const { device, fire } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    const cmdPromise = source.sendCommand({ type: 'start_offset_compensation' });

    // Op Code Not Supported
    fire(
      CYCLING_POWER_SERVICE,
      POWER_CONTROL_POINT_CHAR,
      uint8ArrayToBase64(
        new Uint8Array([0x20, POWER_CP_OPCODE.START_OFFSET_COMPENSATION, 0x02]),
      ),
    );

    const result = await cmdPromise;
    expect(result.success).toBe(false);
    expect(result.resultCode).toBe(0x02);
  });

  test('getLatest returns null after STALE_TTL_MS since last notification', async () => {
    const { device, fire } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    const nowSpy = jest.spyOn(Date, 'now');
    let now = 1_000_000;
    nowSpy.mockImplementation(() => now);

    fire(
      CYCLING_POWER_SERVICE,
      POWER_MEASUREMENT_CHAR,
      uint8ArrayToBase64(new Uint8Array([0, 0, ...s16le(240)])),
    );
    expect(source.getLatest()?.power_w).toBe(240);

    now += 1_500; // 1.5s — still fresh (TTL 2s)
    expect(source.getLatest()?.power_w).toBe(240);

    now += 1_000; // 2.5s total — stale
    expect(source.getLatest()).toBeNull();

    nowSpy.mockRestore();
  });

  test('isStale tracks the same TTL as getLatest', async () => {
    const { device, fire } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    const nowSpy = jest.spyOn(Date, 'now');
    let now = 1_000_000;
    nowSpy.mockImplementation(() => now);

    // No samples yet — not stale (just hasn't received data)
    expect(source.isStale()).toBe(false);

    fire(
      CYCLING_POWER_SERVICE,
      POWER_MEASUREMENT_CHAR,
      uint8ArrayToBase64(new Uint8Array([0, 0, ...s16le(240)])),
    );
    expect(source.isStale()).toBe(false);

    now += 2_500; // past TTL
    expect(source.isStale()).toBe(true);

    nowSpy.mockRestore();
  });

  test('onDisconnected event triggers markLost', async () => {
    const { device, fire, fireDisconnect, subscriptions } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    fire(
      CYCLING_POWER_SERVICE,
      POWER_MEASUREMENT_CHAR,
      uint8ArrayToBase64(new Uint8Array([0, 0, ...s16le(240)])),
    );
    expect(source.getLatest()).not.toBeNull();

    const measurementRemove = subscriptions[0].remove;
    const cpRemove = subscriptions[1].remove;

    fireDisconnect();

    expect(source.getLatest()).toBeNull();
    expect(source.status).toBe('disconnected');
    expect(measurementRemove).toHaveBeenCalled();
    expect(cpRemove).toHaveBeenCalled();
  });

  test('pending CP command resolves with failure when device disconnects', async () => {
    const { device, fireDisconnect } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    const cmdPromise = source.sendCommand({ type: 'start_offset_compensation' });
    fireDisconnect();
    const result = await cmdPromise;
    expect(result.success).toBe(false);
    expect(result.error).toMatch(/disconnected/i);
  });

  test('sendCommand ignores response for a different opCode', async () => {
    const { device, fire } = makeMockDevice();
    const source = new PowerMeterSource(device);
    await source.start();

    const cmdPromise = source.sendCommand({ type: 'start_offset_compensation' });

    // Response for a different opcode — should not resolve the pending command
    fire(
      CYCLING_POWER_SERVICE,
      POWER_CONTROL_POINT_CHAR,
      uint8ArrayToBase64(
        new Uint8Array([0x20, POWER_CP_OPCODE.REQUEST_SENSOR_LOCATIONS, 0x01, 5, 6]),
      ),
    );

    let resolved = false;
    cmdPromise.then(
      () => {
        resolved = true;
      },
      () => {
        resolved = true;
      },
    );
    await new Promise((r) => setImmediate(r));
    expect(resolved).toBe(false);

    // Clean up pending
    await source.stop();
  });
});
