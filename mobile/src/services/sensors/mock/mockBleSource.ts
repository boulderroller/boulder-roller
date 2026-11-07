/**
 * MockBleSource — fixture-driven SensorSource for tests and dev.
 *
 * Emits scripted samples on a schedule, implements the full SensorSource
 * contract (including Control Point commands). Used by Jest smoke tests
 * to drive the recording pipeline end-to-end without hardware.
 */

import type {
  SensorSource,
  SensorStatus,
  SensorKind,
  SensorSample,
  SensorCommand,
  SensorCommandResponse,
} from '../types';

export interface MockBleSourceConfig<T extends SensorSample> {
  kind: SensorKind;
  deviceId: string;
  deviceName: string;
  /** Pre-scripted sample stream. */
  samples: T[];
  /** Emission period in ms. Ignored if using advance() for deterministic tests. */
  intervalMs: number;
  /** Replay samples indefinitely when exhausted. Default: false. */
  loop?: boolean;
}

export class MockBleSource<T extends SensorSample> implements SensorSource<T> {
  readonly kind: SensorKind;
  readonly deviceId: string;
  readonly deviceName: string;
  status: SensorStatus = 'disconnected';

  private samples: T[];
  private intervalMs: number;
  private loop: boolean;
  private index = 0;
  private latest: T | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  /** Command log — tests inspect this to verify control point traffic. */
  readonly commandLog: SensorCommand[] = [];

  constructor(cfg: MockBleSourceConfig<T>) {
    this.kind = cfg.kind;
    this.deviceId = cfg.deviceId;
    this.deviceName = cfg.deviceName;
    this.samples = cfg.samples;
    this.intervalMs = cfg.intervalMs;
    this.loop = cfg.loop ?? false;
  }

  async start(): Promise<void> {
    this.status = 'connected';
    this.index = 0;
    this.latest = null;
    this.timer = setInterval(() => this.tick(), this.intervalMs);
  }

  async stop(): Promise<void> {
    this.markLost();
  }

  markLost(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.status = 'disconnected';
    this.latest = null;
  }

  getLatest(): T | null {
    return this.latest;
  }

  isStale(): boolean {
    // Mock source doesn't track wall-clock freshness — tests that need
    // staleness behavior should use a real source with a Date.now spy.
    return false;
  }

  /** Test-only: step one sample forward deterministically, bypassing the timer. */
  advance(): T | null {
    this.tick();
    return this.latest;
  }

  private tick(): void {
    if (this.index >= this.samples.length) {
      if (this.loop) {
        this.index = 0;
      } else {
        return;
      }
    }
    this.latest = this.samples[this.index];
    this.index++;
  }

  async sendCommand(cmd: SensorCommand): Promise<SensorCommandResponse> {
    this.commandLog.push(cmd);
    // Mock always succeeds with canned data per command type.
    switch (cmd.type) {
      case 'start_offset_compensation':
        return { success: true, resultCode: 0x01, data: { offset: 42 } };
      case 'start_enhanced_offset_compensation':
        return {
          success: true,
          resultCode: 0x01,
          data: { offset: 42, manufacturerId: 0x00ff },
        };
      case 'request_sensor_location':
        return { success: true, resultCode: 0x01, data: { locations: [5, 6] } };
    }
  }
}
