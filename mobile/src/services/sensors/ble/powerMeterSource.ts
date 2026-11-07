/**
 * PowerMeterSource — concrete SensorSource for Cycling Power Service (0x1818).
 *
 * Subscribes to Power Measurement notifications and Power Control Point
 * indications on construction. Parses incoming bytes through
 * parsePowerMeasurement / parsePowerCPResponse. Cadence is derived from
 * crank revolution deltas across successive packets (uint16 wraparound
 * handled).
 *
 * Control Point command round-trip uses a pending-promise pattern: write
 * the request, wait for a matching indication (or spec-mandated 30 s
 * timeout), resolve with parsed data.
 */

import type { Device, Subscription } from 'react-native-ble-plx';

import type {
  SensorSource,
  SensorStatus,
  PowerSample,
  SensorCommand,
  SensorCommandResponse,
} from '../types';
import {
  parsePowerMeasurement,
  type ParsedPowerMeasurement,
} from './parsers/powerMeasurement';
import {
  buildPowerCPRequest,
  parsePowerCPResponse,
  parseOffsetCompensationResult,
  parseSensorLocationsList,
  parseEnhancedOffsetCompensationResult,
  POWER_CP_OPCODE,
  POWER_CP_RESULT,
} from './parsers/powerControlPoint';
import {
  CYCLING_POWER_SERVICE,
  POWER_MEASUREMENT_CHAR,
  POWER_CONTROL_POINT_CHAR,
  base64ToUint8Array,
  uint8ArrayToBase64,
} from './manager';

const CP_COMMAND_TIMEOUT_MS = 30_000;
/** Stale threshold — power meters advertise ~4 Hz, so 2 s = 8 missed samples. */
const STALE_TTL_MS = 2_000;

export class PowerMeterSource implements SensorSource<PowerSample> {
  readonly kind = 'power' as const;
  readonly deviceId: string;
  readonly deviceName: string;
  status: SensorStatus = 'connected';

  private device: Device;
  private measurementSub: Subscription | null = null;
  private cpSub: Subscription | null = null;
  private disconnectSub: Subscription | null = null;
  private latest: PowerSample | null = null;
  private lastReceivedAtMs = 0;
  private prevCrankRevs: number | null = null;
  private prevCrankEventMs: number | null = null;
  private pendingCommand: {
    opCode: number;
    resolve: (r: SensorCommandResponse) => void;
    timeout: ReturnType<typeof setTimeout>;
  } | null = null;

  constructor(device: Device) {
    this.device = device;
    this.deviceId = device.id;
    this.deviceName = device.name ?? device.localName ?? 'Power Meter';
  }

  async start(): Promise<void> {
    this.measurementSub = this.device.monitorCharacteristicForService(
      CYCLING_POWER_SERVICE,
      POWER_MEASUREMENT_CHAR,
      (error, char) => {
        if (error || !char?.value) return;
        try {
          const parsed = parsePowerMeasurement(base64ToUint8Array(char.value));
          const cadence = this.computeCadenceFromRevs(parsed);
          this.latest = {
            power_w: parsed.power_w,
            pedal_balance_pct: parsed.pedal_balance_pct,
            cadence_rpm: cadence ?? undefined,
            accumulated_energy_kj: parsed.accumulated_energy_kj,
            timestamp_ms: Date.now(),
          };
          this.lastReceivedAtMs = Date.now();
        } catch (e) {
          console.warn('[PowerMeterSource] Measurement parse error:', e);
        }
      },
    );

    // Subscribe to Control Point now so responses land in the right place
    // even if the user triggers a calibration the moment they pair.
    this.cpSub = this.device.monitorCharacteristicForService(
      CYCLING_POWER_SERVICE,
      POWER_CONTROL_POINT_CHAR,
      (error, char) => {
        if (error || !char?.value) return;
        try {
          const resp = parsePowerCPResponse(base64ToUint8Array(char.value));
          this.handleCPResponse(resp);
        } catch (e) {
          console.warn('[PowerMeterSource] Control Point parse error:', e);
        }
      },
    );

    // Listen for BLE-level disconnect so we can stop reporting phantom
    // values the moment the device drops us.
    this.disconnectSub = this.device.onDisconnected(() => {
      this.markLost();
    });

    this.status = 'connected';
  }

  async stop(): Promise<void> {
    this.markLost();
    this.disconnectSub?.remove();
    this.disconnectSub = null;
    this.prevCrankRevs = null;
    this.prevCrankEventMs = null;
  }

  markLost(): void {
    this.latest = null;
    this.lastReceivedAtMs = 0;
    this.status = 'disconnected';
    this.measurementSub?.remove();
    this.cpSub?.remove();
    this.measurementSub = null;
    this.cpSub = null;
    if (this.pendingCommand) {
      clearTimeout(this.pendingCommand.timeout);
      this.pendingCommand.resolve({
        success: false,
        error: 'Device disconnected',
      });
      this.pendingCommand = null;
    }
  }

  getLatest(): PowerSample | null {
    if (!this.latest) return null;
    if (Date.now() - this.lastReceivedAtMs > STALE_TTL_MS) return null;
    return this.latest;
  }

  isStale(): boolean {
    if (this.lastReceivedAtMs === 0) return false;
    return Date.now() - this.lastReceivedAtMs > STALE_TTL_MS;
  }

  async sendCommand(cmd: SensorCommand): Promise<SensorCommandResponse> {
    const opCode = (() => {
      switch (cmd.type) {
        case 'start_offset_compensation':
          return POWER_CP_OPCODE.START_OFFSET_COMPENSATION;
        case 'start_enhanced_offset_compensation':
          return POWER_CP_OPCODE.START_ENHANCED_OFFSET_COMPENSATION;
        case 'request_sensor_location':
          return POWER_CP_OPCODE.REQUEST_SENSOR_LOCATIONS;
      }
    })();

    const requestBytes = buildPowerCPRequest(opCode);

    return new Promise<SensorCommandResponse>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pendingCommand = null;
        reject(
          new Error(
            `Power CP command 0x${opCode.toString(16)} timed out after ${CP_COMMAND_TIMEOUT_MS}ms`,
          ),
        );
      }, CP_COMMAND_TIMEOUT_MS);

      this.pendingCommand = { opCode, resolve, timeout };

      this.device
        .writeCharacteristicWithResponseForService(
          CYCLING_POWER_SERVICE,
          POWER_CONTROL_POINT_CHAR,
          uint8ArrayToBase64(requestBytes),
        )
        .catch((err) => {
          clearTimeout(timeout);
          this.pendingCommand = null;
          reject(err instanceof Error ? err : new Error(String(err)));
        });
    });
  }

  private handleCPResponse(resp: {
    requestOpCode: number;
    resultCode: number;
    parameter?: Uint8Array;
  }): void {
    if (!this.pendingCommand) return;
    if (resp.requestOpCode !== this.pendingCommand.opCode) return;

    clearTimeout(this.pendingCommand.timeout);
    const success = resp.resultCode === POWER_CP_RESULT.SUCCESS;
    let data: unknown;
    let error: string | undefined;
    if (success && resp.parameter) {
      try {
        switch (resp.requestOpCode) {
          case POWER_CP_OPCODE.START_OFFSET_COMPENSATION:
            data = { offset: parseOffsetCompensationResult(resp.parameter) };
            break;
          case POWER_CP_OPCODE.START_ENHANCED_OFFSET_COMPENSATION:
            data = parseEnhancedOffsetCompensationResult(resp.parameter);
            break;
          case POWER_CP_OPCODE.REQUEST_SENSOR_LOCATIONS:
            data = { locations: parseSensorLocationsList(resp.parameter) };
            break;
        }
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      }
    }

    this.pendingCommand.resolve({ success, resultCode: resp.resultCode, data, error });
    this.pendingCommand = null;
  }

  /**
   * Derive cadence from the Power Measurement's crank revolution fields
   * across successive packets. Handles uint16 wraparound for both the
   * revolution counter and the 1/1024 s event-time counter.
   */
  private computeCadenceFromRevs(parsed: ParsedPowerMeasurement): number | null {
    if (
      parsed.crank_revolution_count == null ||
      parsed.last_crank_event_time_s == null
    ) {
      return null;
    }
    const currRevs = parsed.crank_revolution_count;
    const currEventUnits = parsed.last_crank_event_time_s * 1024; // back to raw uint16

    if (this.prevCrankRevs === null || this.prevCrankEventMs === null) {
      this.prevCrankRevs = currRevs;
      this.prevCrankEventMs = currEventUnits;
      return null; // need 2 samples
    }

    const revDelta = (currRevs - this.prevCrankRevs + 0x10000) & 0xffff;
    const eventDelta = (currEventUnits - this.prevCrankEventMs + 0x10000) & 0xffff;
    this.prevCrankRevs = currRevs;
    this.prevCrankEventMs = currEventUnits;

    if (eventDelta <= 0 || revDelta === 0) return null;
    const timeDeltaS = eventDelta / 1024;
    return (revDelta / timeDeltaS) * 60;
  }
}
