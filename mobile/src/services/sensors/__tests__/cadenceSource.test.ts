import { CadenceSource } from '../ble/cadenceSource';
import {
  CYCLING_SPEED_CADENCE_SERVICE,
  CSC_MEASUREMENT_CHAR,
  uint8ArrayToBase64,
} from '../ble/manager';

type MonitorCallback = (error: unknown, char: { value?: string | null } | null) => void;
type DisconnectCallback = (error: unknown, device: unknown) => void;

function makeMockDevice() {
  const subs: Array<{ cb: MonitorCallback; remove: jest.Mock }> = [];
  let disconnectCb: DisconnectCallback | null = null;
  const monitor = jest.fn((_svc: string, _char: string, cb: MonitorCallback) => {
    const remove = jest.fn();
    subs.push({ cb, remove });
    return { remove };
  });
  const onDisconnected = jest.fn((cb: DisconnectCallback) => {
    disconnectCb = cb;
    return { remove: jest.fn() };
  });
  return {
    device: {
      id: 'csc-1',
      name: 'Wahoo RPM',
      localName: null,
      monitorCharacteristicForService: monitor,
      onDisconnected,
    } as unknown as ConstructorParameters<typeof CadenceSource>[0],
    subs,
    fire: (value: string) => {
      subs[0].cb(null, { value });
    },
    fireError: (error: unknown) => {
      subs[0].cb(error, null);
    },
    fireDisconnect: () => {
      if (!disconnectCb) throw new Error('No disconnect listener');
      disconnectCb(null, {} as never);
    },
  };
}

function u16le(v: number): [number, number] {
  return [v & 0xff, (v >> 8) & 0xff];
}

describe('CadenceSource', () => {
  test('subscribes to CSC Measurement on start', async () => {
    const { device, subs } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();
    expect(subs.length).toBe(1);
  });

  test('first packet cannot compute cadence; second yields 120 rpm', async () => {
    const { device, fire } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    // flags = 0x02 (crank rev present)
    // Packet 1: revs=100, last event=1.0s (1024 in 1/1024 s)
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    expect(source.getLatest()).toBeNull();

    // Packet 2: revs=102, last event=2.0s (2048 in 1/1024 s) → 2 revs / 1 s * 60 = 120 rpm
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    expect(source.getLatest()?.cadence_rpm).toBeCloseTo(120, 1);
  });

  test('computes wheel-based speed when wheel fields are present', async () => {
    const { device, fire } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    const flags = 0x03; // wheel + crank
    // Packet 1: wheel=100 revs, event=1.0s, crank=50 revs, event=1.0s
    fire(
      uint8ArrayToBase64(
        new Uint8Array([
          flags,
          ...u16le(100),
          0,
          0, // uint32 wheel revs (100)
          ...u16le(1024),
          ...u16le(50),
          ...u16le(1024),
        ]),
      ),
    );
    // Packet 2: wheel=102 (+2 revs × 2.105 m = 4.21 m), event=2.0s
    // → speed = 4.21 m / 1 s = 4.21 m/s
    fire(
      uint8ArrayToBase64(
        new Uint8Array([
          flags,
          ...u16le(102),
          0,
          0,
          ...u16le(2048),
          ...u16le(52),
          ...u16le(2048),
        ]),
      ),
    );

    const latest = source.getLatest();
    expect(latest).not.toBeNull();
    expect(latest!.wheel_speed_mps).toBeCloseTo(4.21, 1);
  });

  test('stop clears state', async () => {
    const { device, fire, subs } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    expect(source.getLatest()).not.toBeNull();

    await source.stop();
    expect(source.getLatest()).toBeNull();
    expect(subs[0].remove).toHaveBeenCalled();
  });

  test('getLatest returns null after STALE_TTL_MS', async () => {
    const { device, fire } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    const nowSpy = jest.spyOn(Date, 'now');
    let now = 1_000_000;
    nowSpy.mockImplementation(() => now);

    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    expect(source.getLatest()?.cadence_rpm).toBeCloseTo(120, 1);

    now += 4_900; // just under 5s TTL
    expect(source.getLatest()).not.toBeNull();

    now += 200; // past TTL
    expect(source.getLatest()).toBeNull();

    nowSpy.mockRestore();
  });

  test('onDisconnected event triggers markLost', async () => {
    const { device, fire, fireDisconnect, subs } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    expect(source.getLatest()).not.toBeNull();

    const subRemove = subs[0].remove;
    fireDisconnect();

    expect(source.getLatest()).toBeNull();
    expect(source.status).toBe('disconnected');
    expect(subRemove).toHaveBeenCalled();
  });

  test('setWheelCircumference overrides the default for wheel-speed math', async () => {
    const { device, fire } = makeMockDevice();
    const source = new CadenceSource(device);
    source.setWheelCircumference(2.5); // MTB 29er-ish
    await source.start();

    const flags = 0x03; // wheel + crank
    // Packet 1: wheel=100, crank=50, both at event=1.0s
    fire(
      uint8ArrayToBase64(
        new Uint8Array([
          flags,
          ...u16le(100),
          0,
          0,
          ...u16le(1024),
          ...u16le(50),
          ...u16le(1024),
        ]),
      ),
    );
    // Packet 2: wheel=102 (+2 revs × 2.5m = 5.0m), event=2.0s → 5.0 m/s
    fire(
      uint8ArrayToBase64(
        new Uint8Array([
          flags,
          ...u16le(102),
          0,
          0,
          ...u16le(2048),
          ...u16le(52),
          ...u16le(2048),
        ]),
      ),
    );

    expect(source.getLatest()?.wheel_speed_mps).toBeCloseTo(5.0, 1);
  });

  // -----------------------------------------------------------------------
  // Parity with the power-slice disconnection / staleness hardening.
  // These guard the §4.2 absence-vs-zero contract end-to-end for cadence.
  // -----------------------------------------------------------------------

  test('markLost is idempotent (can be called multiple times safely)', async () => {
    const { device, fire, subs } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    expect(source.getLatest()).not.toBeNull();

    // First markLost: clears cache, removes sub, flips status.
    source.markLost();
    const subRemove = subs[0].remove;
    expect(subRemove).toHaveBeenCalledTimes(1);
    expect(source.getLatest()).toBeNull();
    expect(source.status).toBe('disconnected');

    // Second and third markLost calls must not throw, not double-call remove.
    expect(() => source.markLost()).not.toThrow();
    expect(() => source.markLost()).not.toThrow();
    expect(source.getLatest()).toBeNull();
    expect(source.status).toBe('disconnected');

    // stop() then markLost() still safe.
    await source.stop();
    expect(() => source.markLost()).not.toThrow();
  });

  test('isStale is false before any sample arrives (still connecting, not stale)', async () => {
    const { device } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    expect(source.isStale()).toBe(false);
    expect(source.getLatest()).toBeNull();
  });

  test('isStale flips true after STALE_TTL_MS once a sample has arrived', async () => {
    const { device, fire } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    const nowSpy = jest.spyOn(Date, 'now');
    let now = 1_000_000;
    nowSpy.mockImplementation(() => now);

    expect(source.isStale()).toBe(false);

    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    // First packet doesn't populate latest (needs two for delta).
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    expect(source.isStale()).toBe(false);

    now += 4_900;
    expect(source.isStale()).toBe(false);

    now += 200; // past 5s TTL
    expect(source.isStale()).toBe(true);

    nowSpy.mockRestore();
  });

  test('disconnection cleanly clears cached sample and status (no phantom values)', async () => {
    const { device, fire, fireDisconnect } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    // Populate latest via two packets.
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    const beforeDrop = source.getLatest();
    expect(beforeDrop).not.toBeNull();
    expect(beforeDrop!.cadence_rpm).toBeCloseTo(120, 1);

    fireDisconnect();

    const afterDrop = source.getLatest();
    expect(afterDrop).toBeNull();
    // Disconnected ≠ zero cadence.
    expect(afterDrop).not.toEqual(expect.objectContaining({ cadence_rpm: 0 }));
    expect(source.status).toBe('disconnected');
  });

  test('notification error after disconnect does not resurrect cached sample', async () => {
    const { device, fire, fireError, fireDisconnect } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    fireDisconnect();
    expect(source.getLatest()).toBeNull();

    fireError(new Error('stale subscription'));
    expect(source.getLatest()).toBeNull();
  });

  test('stale cache returns null rather than a 0-cadence sample object', async () => {
    // §4.2 pin: once past TTL, null wins — never a lingering object whose
    // fields happen to compute to 0. Keeps the recording pipeline honest.
    const { device, fire } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    const nowSpy = jest.spyOn(Date, 'now');
    let now = 1_000_000;
    nowSpy.mockImplementation(() => now);

    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(102), ...u16le(2048)])));
    expect(source.getLatest()).not.toBeNull();

    now += 5_500; // past TTL
    const stale = source.getLatest();
    expect(stale).toBeNull();
    expect(stale).not.toEqual(expect.objectContaining({ cadence_rpm: 0 }));

    nowSpy.mockRestore();
  });

  test('first packet only — no latest until two packets have deltas', async () => {
    const { device, fire } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    // Pre-first-sample is "no data" not "lost data" — isStale must not claim stale.
    expect(source.getLatest()).toBeNull();
    expect(source.isStale()).toBe(false);

    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    // One packet alone: nothing to delta against yet.
    expect(source.getLatest()).toBeNull();
    expect(source.isStale()).toBe(false);
  });

  test('rider coasting: crank count static across packets yields 0 cadence, not null', async () => {
    // Coasting = pedals not turning, sensor still notifying with identical
    // crank_revolution_count but advancing event time. Cadence is a real 0.
    const { device, fire } = makeMockDevice();
    const source = new CadenceSource(device);
    await source.start();

    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(1024)])));
    fire(uint8ArrayToBase64(new Uint8Array([0x02, ...u16le(100), ...u16le(2048)])));

    const latest = source.getLatest();
    expect(latest).not.toBeNull();
    expect(latest!.cadence_rpm).toBe(0);
  });
});
