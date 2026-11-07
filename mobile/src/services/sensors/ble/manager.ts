/**
 * BLE sensor manager — wraps react-native-ble-plx's BleManager.
 *
 * Responsibilities:
 *   - Maintain a single BleManager singleton (Android limitation + iOS best practice)
 *   - Wait for the adapter to be powered on before scan/connect
 *   - Scan, filtering advertisements to devices offering at least one of our
 *     three target services (Power, HR, CSC)
 *   - Connect a device and return a concrete SensorSource for a requested kind
 *   - Clean shutdown (stop scan, destroy manager)
 *
 * The concrete Source implementations (PowerMeterSource, HeartRateSource,
 * CadenceSource) handle per-kind characteristic subscription and parsing.
 * The manager does not know what the data means — it just hands a connected
 * Device to the right Source class.
 */

import { Buffer } from 'buffer';
import { PermissionsAndroid, Platform } from 'react-native';
import * as Sentry from '@sentry/react-native';
import { BleManager, State } from 'react-native-ble-plx';
import type { Device, Subscription } from 'react-native-ble-plx';

import type { SensorKind } from '../types';
import { sensorRegistry } from '../registry';
import { PowerMeterSource } from './powerMeterSource';
import { HeartRateSource } from './heartRateSource';
import { CadenceSource } from './cadenceSource';

// ---------------------------------------------------------------------------
// GATT UUIDs (128-bit form — BLE standard requires full UUID at runtime)
// ---------------------------------------------------------------------------

export const CYCLING_POWER_SERVICE = '00001818-0000-1000-8000-00805f9b34fb';
export const HEART_RATE_SERVICE = '0000180d-0000-1000-8000-00805f9b34fb';
export const CYCLING_SPEED_CADENCE_SERVICE = '00001816-0000-1000-8000-00805f9b34fb';

export const POWER_MEASUREMENT_CHAR = '00002a63-0000-1000-8000-00805f9b34fb';
export const POWER_CONTROL_POINT_CHAR = '00002a66-0000-1000-8000-00805f9b34fb';
export const SENSOR_LOCATION_CHAR = '00002a5d-0000-1000-8000-00805f9b34fb';

export const HR_MEASUREMENT_CHAR = '00002a37-0000-1000-8000-00805f9b34fb';
export const BODY_SENSOR_LOCATION_CHAR = '00002a38-0000-1000-8000-00805f9b34fb';

export const CSC_MEASUREMENT_CHAR = '00002a5b-0000-1000-8000-00805f9b34fb';

const SCAN_SERVICE_UUIDS = [
  CYCLING_POWER_SERVICE,
  HEART_RATE_SERVICE,
  CYCLING_SPEED_CADENCE_SERVICE,
];

/**
 * connectToDevice timeout. Without this, a bad dial (device just out of
 * range, native BLE stack momentarily wedged) hangs indefinitely and the
 * pairing UI sits on an unrecoverable spinner. 10s is conservative — most
 * connects complete in <2s under normal conditions.
 */
const CONNECT_TIMEOUT_MS = 10_000;

/** First Android API level that requires runtime BLUETOOTH_* permissions. */
const ANDROID_RUNTIME_BT_PERMS_MIN_SDK = 31;

/**
 * Android 12+ (API 31+) requires runtime BLUETOOTH_SCAN and BLUETOOTH_CONNECT
 * grants — manifest declarations alone silently fail. iOS handles BLE perms
 * via the bluetooth-central UIBackgroundMode + NSBluetoothAlwaysUsageDescription
 * (the ble-plx Expo config plugin generates both).
 */
async function requestAndroidBlePermissions(): Promise<boolean> {
  if (Platform.OS !== 'android') return true;
  if (typeof Platform.Version !== 'number') return true;
  if (Platform.Version < ANDROID_RUNTIME_BT_PERMS_MIN_SDK) return true;

  const result = await PermissionsAndroid.requestMultiple([
    PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
    PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
  ]);
  return (
    result[PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN] ===
      PermissionsAndroid.RESULTS.GRANTED &&
    result[PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT] ===
      PermissionsAndroid.RESULTS.GRANTED
  );
}

/** Exported for tests only. */
export const _requestAndroidBlePermissions = requestAndroidBlePermissions;

// ---------------------------------------------------------------------------
// Base64 helpers — ble-plx hands/takes characteristic values as base64 strings
// ---------------------------------------------------------------------------

export function base64ToUint8Array(b64: string): Uint8Array {
  return new Uint8Array(Buffer.from(b64, 'base64'));
}

export function uint8ArrayToBase64(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString('base64');
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface DiscoveredDevice {
  id: string;
  name: string;
  rssi: number | null;
  /** Services advertised by the device (may be a subset of what it actually offers). */
  advertisedServiceUuids: string[];
  /** Which of our three kinds the device is advertising. */
  kinds: SensorKind[];
}

export type ConcreteSensorSource =
  | PowerMeterSource
  | HeartRateSource
  | CadenceSource;

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

class BleSensorManager {
  private manager: BleManager | null = null;
  private scanActive = false;
  private stateSubscription: Subscription | null = null;

  /**
   * Lazy init. The BleManager constructor acquires native resources — we hold
   * off until the app actually needs BLE (pairing screen open). Also wires
   * the adapter-state monitor so sources can be told to stop reporting
   * phantom values the moment Bluetooth goes away.
   */
  init(): BleManager {
    if (!this.manager) {
      this.manager = new BleManager();
      this.startAdapterMonitor();
    }
    return this.manager;
  }

  /**
   * Subscribe to adapter state changes. On any non-PoweredOn state,
   * walk the registry and tell every source to drop its cache. Users who
   * turn Bluetooth off mid-ride now stop producing phantom power samples
   * for the rest of the ride.
   */
  private startAdapterMonitor(): void {
    if (!this.manager || this.stateSubscription) return;
    this.stateSubscription = this.manager.onStateChange((state) => {
      if (state !== State.PoweredOn) {
        for (const source of sensorRegistry.all()) {
          source.markLost();
        }
      }
    }, false);
  }

  /**
   * Resolve when the BLE adapter is powered on, reject on timeout.
   * Handles cold-start when the adapter state is still 'Unknown'.
   */
  async waitForPoweredOn(timeoutMs = 5000): Promise<void> {
    const manager = this.init();
    const current = await manager.state();
    if (current === State.PoweredOn) return;
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        sub.remove();
        reject(new Error(`BLE not powered on after ${timeoutMs}ms (state=${current})`));
      }, timeoutMs);
      const sub = manager.onStateChange((newState) => {
        if (newState === State.PoweredOn) {
          clearTimeout(timer);
          sub.remove();
          resolve();
        }
      }, true);
    });
  }

  /**
   * Start scanning for devices offering any of our three services.
   * The callback is invoked once per advertisement packet; callers should
   * de-duplicate by device.id themselves.
   */
  async startScan(
    onDiscovered: (device: DiscoveredDevice) => void,
    onError?: (error: Error) => void,
  ): Promise<void> {
    if (this.scanActive) return;
    const manager = this.init();
    await this.waitForPoweredOn();

    const granted = await requestAndroidBlePermissions();
    if (!granted) {
      onError?.(
        new Error(
          'Bluetooth permission denied. Enable Bluetooth in Settings to pair sensors.',
        ),
      );
      return;
    }

    this.scanActive = true;
    manager.startDeviceScan(SCAN_SERVICE_UUIDS, null, (error, device) => {
      if (error) {
        onError?.(new Error(error.message ?? String(error)));
        return;
      }
      if (!device) return;

      const advertised = (device.serviceUUIDs ?? []).map((u) => u.toLowerCase());
      const kinds: SensorKind[] = [];
      if (advertised.includes(CYCLING_POWER_SERVICE)) kinds.push('power');
      if (advertised.includes(HEART_RATE_SERVICE)) kinds.push('heart_rate');
      if (advertised.includes(CYCLING_SPEED_CADENCE_SERVICE)) kinds.push('cadence');
      if (kinds.length === 0) return;

      onDiscovered({
        id: device.id,
        name: device.name ?? device.localName ?? 'Unknown device',
        rssi: device.rssi ?? null,
        advertisedServiceUuids: advertised,
        kinds,
      });
    });
  }

  stopScan(): void {
    if (!this.scanActive || !this.manager) return;
    this.manager.stopDeviceScan();
    this.scanActive = false;
  }

  /**
   * Connect to a device and return a concrete SensorSource for the requested
   * kind. If the device already has an open connection (e.g., a sibling kind
   * is also connected), the existing Device handle is reused.
   *
   * Caller is responsible for calling source.start() to begin the subscription.
   */
  async connect(deviceId: string, kind: SensorKind): Promise<ConcreteSensorSource> {
    const manager = this.init();
    await this.waitForPoweredOn();
    const granted = await requestAndroidBlePermissions();
    if (!granted) {
      throw new Error(
        'Bluetooth permission denied. Enable Bluetooth in Settings to pair sensors.',
      );
    }
    const device = await manager.connectToDevice(deviceId, {
      timeout: CONNECT_TIMEOUT_MS,
    });
    await device.discoverAllServicesAndCharacteristics();

    switch (kind) {
      case 'power':
        return new PowerMeterSource(device);
      case 'heart_rate':
        return new HeartRateSource(device);
      case 'cadence':
        return new CadenceSource(device);
    }
  }

  /**
   * Cancel the underlying BLE connection for a device. Sources bound to this
   * device should have their stop() called by the caller first to unsubscribe
   * cleanly — this is the last step.
   */
  async disconnect(deviceId: string): Promise<void> {
    if (!this.manager) return;
    try {
      await this.manager.cancelDeviceConnection(deviceId);
    } catch {
      // Already disconnected — ignore.
    }
  }

  /**
   * Re-audit registered sources after the app comes back to the foreground.
   * iOS may suspend BLE notifications under memory pressure or during long
   * backgrounding even with bluetooth-central declared. The TTL on getLatest
   * already prevents phantom values from feeding the recording surface, but
   * the source's own status flag would still read 'connected' and mislead
   * the UI. This sweep flips silent sources to 'disconnected' so the rider
   * sees that something needs attention.
   *
   * Telemetry: when sources are actually marked lost we send a Sentry
   * breadcrumb. We can't smoke-test iOS background suspension from jest,
   * so this is the only signal that will tell us empirically whether the
   * defensive sweep is doing anything in production.
   */
  auditStaleness(): void {
    const lost: string[] = [];
    for (const source of sensorRegistry.all()) {
      if (source.status === 'connected' && source.isStale()) {
        source.markLost();
        lost.push(`${source.deviceId}|${source.kind}`);
      }
    }
    if (lost.length > 0) {
      Sentry.captureMessage('BLE staleness audit marked sources lost', {
        level: 'info',
        extra: { lost },
      });
    }
  }

  /** Full shutdown — call on app background / unmount. */
  destroy(): void {
    if (!this.manager) return;
    this.stopScan();
    this.stateSubscription?.remove();
    this.stateSubscription = null;
    this.manager.destroy();
    this.manager = null;
  }

  /** Test-only: reset internal state without destroying the native manager. */
  _resetForTests(): void {
    this.manager = null;
    this.scanActive = false;
    this.stateSubscription = null;
  }
}

export const bleSensorManager = new BleSensorManager();
