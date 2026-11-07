import { HeartRateSource } from '../ble/heartRateSource';
import {
  HEART_RATE_SERVICE,
  HR_MEASUREMENT_CHAR,
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
      id: 'hr-1',
      name: 'Garmin HRM-Pro',
      localName: null,
      monitorCharacteristicForService: monitor,
      onDisconnected,
    } as unknown as ConstructorParameters<typeof HeartRateSource>[0],
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

describe('HeartRateSource', () => {
  test('subscribes to HR Measurement on start', async () => {
    const { device, subs } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    expect(subs.length).toBe(1);
    expect(source.status).toBe('connected');
  });

  test('parses uint8 HR with RR intervals', async () => {
    const { device, fire } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    // flags bit 4 = RR present, HR=152 (uint8), RR=[400, 395] in 1/1024 s
    const bytes = new Uint8Array([0x10, 152, ...u16le(400), ...u16le(395)]);
    fire(uint8ArrayToBase64(bytes));

    const latest = source.getLatest();
    expect(latest!.heart_rate_bpm).toBe(152);
    expect(latest!.rr_intervals_ms).toHaveLength(2);
  });

  test('clears cache on stop', async () => {
    const { device, fire, subs } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    fire(uint8ArrayToBase64(new Uint8Array([0x00, 140])));
    expect(source.getLatest()).not.toBeNull();

    await source.stop();
    expect(source.getLatest()).toBeNull();
    expect(subs[0].remove).toHaveBeenCalled();
    expect(source.status).toBe('disconnected');
  });

  test('handles malformed payloads gracefully', async () => {
    const { device, fire } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();
    expect(() => fire(uint8ArrayToBase64(new Uint8Array([])))).not.toThrow();
    expect(source.getLatest()).toBeNull();
  });

  test('getLatest returns null after STALE_TTL_MS since last notification', async () => {
    const { device, fire } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    const nowSpy = jest.spyOn(Date, 'now');
    let now = 1_000_000;
    nowSpy.mockImplementation(() => now);

    fire(uint8ArrayToBase64(new Uint8Array([0x00, 140])));
    expect(source.getLatest()?.heart_rate_bpm).toBe(140);

    now += 2_900; // still under 3s TTL
    expect(source.getLatest()?.heart_rate_bpm).toBe(140);

    now += 200; // 3.1s — stale
    expect(source.getLatest()).toBeNull();

    nowSpy.mockRestore();
  });

  test('onDisconnected event triggers markLost', async () => {
    const { device, fire, fireDisconnect, subs } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    fire(uint8ArrayToBase64(new Uint8Array([0x00, 140])));
    expect(source.getLatest()).not.toBeNull();

    const subRemove = subs[0].remove;
    fireDisconnect();

    expect(source.getLatest()).toBeNull();
    expect(source.status).toBe('disconnected');
    expect(subRemove).toHaveBeenCalled();
  });

  // -----------------------------------------------------------------------
  // Parity with the power-slice disconnection / staleness hardening.
  // These guard the §4.2 absence-vs-zero contract end-to-end for HR.
  // -----------------------------------------------------------------------

  test('markLost is idempotent (can be called multiple times safely)', async () => {
    const { device, fire, subs } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    fire(uint8ArrayToBase64(new Uint8Array([0x00, 148])));
    expect(source.getLatest()).not.toBeNull();

    // First markLost: clears cache, removes sub, flips status.
    source.markLost();
    const subRemove = subs[0].remove;
    expect(subRemove).toHaveBeenCalledTimes(1);
    expect(source.getLatest()).toBeNull();
    expect(source.status).toBe('disconnected');

    // Second markLost: must not throw, must not re-call remove on a cleared sub.
    expect(() => source.markLost()).not.toThrow();
    expect(source.getLatest()).toBeNull();
    expect(source.status).toBe('disconnected');

    // Third markLost after stop(): still idempotent.
    await source.stop();
    expect(() => source.markLost()).not.toThrow();
  });

  test('isStale is false before any sample arrives (still connecting, not stale)', async () => {
    const { device } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    // No samples fired. Pre-first-sample is "no data" not "lost data".
    expect(source.isStale()).toBe(false);
    expect(source.getLatest()).toBeNull();
  });

  test('isStale flips true after STALE_TTL_MS once a sample has arrived', async () => {
    const { device, fire } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    const nowSpy = jest.spyOn(Date, 'now');
    let now = 1_000_000;
    nowSpy.mockImplementation(() => now);

    expect(source.isStale()).toBe(false);

    fire(uint8ArrayToBase64(new Uint8Array([0x00, 140])));
    expect(source.isStale()).toBe(false);

    now += 2_900;
    expect(source.isStale()).toBe(false);

    now += 200; // past 3s TTL
    expect(source.isStale()).toBe(true);

    nowSpy.mockRestore();
  });

  test('disconnection cleanly clears cached sample and status (no phantom values)', async () => {
    const { device, fire, fireDisconnect } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    // Real HR sample cached
    fire(uint8ArrayToBase64(new Uint8Array([0x00, 165])));
    expect(source.getLatest()!.heart_rate_bpm).toBe(165);

    fireDisconnect();

    // After disconnect, getLatest strictly null. No lingering 165.
    const afterDisconnect = source.getLatest();
    expect(afterDisconnect).toBeNull();
    // The disconnected state must not be confused with "zero HR".
    expect(afterDisconnect).not.toEqual({ heart_rate_bpm: 0 });
    expect(source.status).toBe('disconnected');
  });

  test('notification error after disconnect does not resurrect cached sample', async () => {
    const { device, fire, fireError, fireDisconnect } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    fire(uint8ArrayToBase64(new Uint8Array([0x00, 140])));
    fireDisconnect();
    expect(source.getLatest()).toBeNull();

    // A stray error notification after disconnect must not re-populate latest.
    fireError(new Error('stale subscription'));
    expect(source.getLatest()).toBeNull();
  });

  test('stale cache returns null but preserves the raw bpm to 0-distinction', async () => {
    // After TTL expires, getLatest returns null — never a sample object with
    // zero bpm. This pins the §4.2 contract: absence ≠ zero, even under
    // staleness.
    const { device, fire } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    const nowSpy = jest.spyOn(Date, 'now');
    let now = 1_000_000;
    nowSpy.mockImplementation(() => now);

    fire(uint8ArrayToBase64(new Uint8Array([0x00, 155])));
    expect(source.getLatest()?.heart_rate_bpm).toBe(155);

    now += 3_500; // past TTL
    const stale = source.getLatest();
    expect(stale).toBeNull();
    expect(stale).not.toEqual(expect.objectContaining({ heart_rate_bpm: 0 }));

    nowSpy.mockRestore();
  });

  test('genuine zero bpm sample is preserved (resting / firmware reported 0)', async () => {
    // §4.2 absence-vs-zero also in the other direction: if the HR monitor
    // actively reports 0 bpm (contact lost, firmware reports 0, or a paused
    // strap), we preserve that value rather than laundering it to null. The
    // contact flag is how upper layers should distinguish the cases.
    const { device, fire } = makeMockDevice();
    const source = new HeartRateSource(device);
    await source.start();

    // flags = SENSOR_CONTACT_SUPPORTED (bit 2), contact not detected (bit 1 clear)
    fire(uint8ArrayToBase64(new Uint8Array([0x04, 0])));
    const latest = source.getLatest();
    expect(latest).not.toBeNull();
    expect(latest!.heart_rate_bpm).toBe(0);
    expect(latest!.sensor_contact).toBe(false);
  });
});
