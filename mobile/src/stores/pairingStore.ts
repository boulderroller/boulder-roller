/**
 * Pairing store — the bridge between the pairing UI and the BLE stack.
 *
 * Responsibilities:
 *   - Track runtime state (discovered devices during scan, active connections)
 *   - Persist the list of known devices across app launches (AsyncStorage)
 *   - Orchestrate actions: scan, connect, disconnect, forget, reconnect
 *   - Keep sensorRegistry in sync with connection state so the recording
 *     surface's snapshot-on-tick merge sees live sensor data
 *
 * A device may expose multiple kinds (Wahoo Kickr = power + CSC + FMS). We
 * pair per kind, so a single Device can carry multiple connections. The
 * underlying BLE connection is only cancelled when the last kind for that
 * device is disconnected.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Sentry from '@sentry/react-native';

import type { SensorKind, SensorStatus, SensorCommandResponse } from '../services/sensors/types';
import {
  bleSensorManager,
  type DiscoveredDevice,
} from '../services/sensors/ble/manager';
import { CadenceSource } from '../services/sensors/ble/cadenceSource';
import { sensorRegistry } from '../services/sensors/registry';

export interface KnownDevice {
  id: string;
  name: string;
  kind: SensorKind;
  lastConnectedAt: number | null;
  /**
   * Wheel circumference in meters — only relevant for cadence sensors that
   * also report wheel-revolution data (some CSC sensors + smart trainers).
   * Undefined means "use the CadenceSource default (700x25c, 2.105m)".
   */
  wheelCircumferenceM?: number;
}

export interface ActiveConnection {
  deviceId: string;
  kind: SensorKind;
  deviceName: string;
  status: SensorStatus;
}

interface PairingState {
  /** Discovered during active scan. Cleared at scan start. Not persisted. */
  discovered: Record<string, DiscoveredDevice>;
  /** Devices the user has paired at least once. Persisted. */
  known: KnownDevice[];
  /** Currently-connecting / connected sources. Keyed by `${deviceId}|${kind}`. */
  connections: Record<string, ActiveConnection>;
  scanning: boolean;
  scanError: string | null;
}

interface PairingActions {
  startScan: () => Promise<void>;
  stopScan: () => void;
  connect: (deviceId: string, kind: SensorKind, deviceName: string) => Promise<void>;
  disconnect: (deviceId: string, kind: SensorKind) => Promise<void>;
  /** Close every live connection but leave `known` intact. Called on logout. */
  disconnectAll: () => Promise<void>;
  forget: (deviceId: string, kind: SensorKind) => Promise<void>;
  reconnectKnown: () => Promise<void>;
  calibratePower: (deviceId: string) => Promise<SensorCommandResponse>;
  setWheelCircumference: (deviceId: string, meters: number) => void;
}

/** Physically plausible wheel circumference range (meters). */
const MIN_WHEEL_M = 1.0;
const MAX_WHEEL_M = 3.0;

type PairingStore = PairingState & PairingActions;

function connKey(deviceId: string, kind: SensorKind): string {
  return `${deviceId}|${kind}`;
}

const initialState: PairingState = {
  discovered: {},
  known: [],
  connections: {},
  scanning: false,
  scanError: null,
};

// ---------------------------------------------------------------------------
// Selectors — computed values that callers pass to usePairingStore().
// Keeps derivation logic in one place and avoids each caller re-computing.
// ---------------------------------------------------------------------------

/** True when at least one source is in the connected state. */
export function selectHasConnectedSensors(state: PairingState): boolean {
  return Object.values(state.connections).some((c) => c.status === 'connected');
}

/** De-duplicated list of kinds currently connected. */
export function selectConnectedKinds(state: PairingState): SensorKind[] {
  return Array.from(
    new Set(
      Object.values(state.connections)
        .filter((c) => c.status === 'connected')
        .map((c) => c.kind),
    ),
  );
}

/** Count of distinct (deviceId, kind) pairs currently connected. */
export function selectConnectedCount(state: PairingState): number {
  return Object.values(state.connections).filter((c) => c.status === 'connected').length;
}

export const usePairingStore = create<PairingStore>()(
  persist(
    (set, get) => ({
      ...initialState,

      startScan: async () => {
        if (get().scanning) return;
        set({ scanning: true, scanError: null, discovered: {} });
        try {
          await bleSensorManager.startScan(
            (device) => {
              set((state) => ({
                discovered: { ...state.discovered, [device.id]: device },
              }));
            },
            (error) => {
              set({ scanning: false, scanError: error.message });
            },
          );
        } catch (e) {
          set({
            scanning: false,
            scanError: e instanceof Error ? e.message : String(e),
          });
        }
      },

      stopScan: () => {
        bleSensorManager.stopScan();
        set({ scanning: false });
      },

      connect: async (deviceId, kind, deviceName) => {
        const key = connKey(deviceId, kind);
        set((state) => ({
          connections: {
            ...state.connections,
            [key]: { deviceId, kind, deviceName, status: 'connecting' },
          },
        }));
        try {
          const source = await bleSensorManager.connect(deviceId, kind);
          // Apply any persisted per-device setting (currently only cadence
          // sensors carry one — wheel circumference — but the hook is here
          // for future device-specific config).
          if (source instanceof CadenceSource) {
            const configured = get().known.find(
              (k) => k.id === deviceId && k.kind === 'cadence',
            )?.wheelCircumferenceM;
            if (configured !== undefined) {
              source.setWheelCircumference(configured);
            }
          }
          await source.start();
          sensorRegistry.add(source);
          set((state) => {
            const now = Date.now();
            const existingKnown = state.known.find(
              (k) => k.id === deviceId && k.kind === kind,
            );
            const known = existingKnown
              ? state.known.map((k) =>
                  k.id === deviceId && k.kind === kind
                    ? { ...k, lastConnectedAt: now, name: deviceName }
                    : k,
                )
              : [...state.known, { id: deviceId, name: deviceName, kind, lastConnectedAt: now }];
            return {
              connections: {
                ...state.connections,
                [key]: { deviceId, kind, deviceName, status: 'connected' },
              },
              known,
            };
          });
        } catch (e) {
          set((state) => ({
            connections: {
              ...state.connections,
              [key]: { deviceId, kind, deviceName, status: 'error' },
            },
          }));
          throw e;
        }
      },

      disconnect: async (deviceId, kind) => {
        const key = connKey(deviceId, kind);
        const source = sensorRegistry.get(deviceId, kind);
        if (source) {
          // source.stop() runs markLost(). Below we also call
          // bleSensorManager.disconnect(deviceId), which causes ble-plx
          // to fire device.onDisconnected → which the source listens for
          // and ALSO calls markLost(). Double-fire is intentional and safe:
          // markLost is idempotent (interface contract). The two paths
          // exist so a graceful user-initiated disconnect, an unexpected
          // BLE drop, and an adapter-state change all converge on the same
          // cleanup.
          await source.stop();
          sensorRegistry.remove(deviceId, kind);
        }
        // Build next connections state synchronously so we can check whether
        // other kinds for this device remain connected.
        const { [key]: _removed, ...remaining } = get().connections;
        const stillConnected = Object.values(remaining).some(
          (c) => c.deviceId === deviceId,
        );
        if (!stillConnected) {
          // Last kind for this device — cancel the underlying BLE connection.
          await bleSensorManager.disconnect(deviceId);
        }
        set({ connections: remaining });
      },

      forget: async (deviceId, kind) => {
        await get().disconnect(deviceId, kind);
        set((state) => ({
          known: state.known.filter(
            (k) => !(k.id === deviceId && k.kind === kind),
          ),
        }));
      },

      reconnectKnown: async () => {
        const known = get().known;
        // No paired devices → don't touch the BLE stack at all. Avoids
        // triggering the iOS permission prompt for users who never open
        // the pairing screen.
        if (known.length === 0) return;
        // Sequential: some BLE stacks flake on parallel connect attempts.
        let successes = 0;
        for (const dev of known) {
          try {
            await get().connect(dev.id, dev.kind, dev.name);
            successes++;
          } catch {
            // Device may be out of range, off, or paired to another phone.
            // Leave it in `known` so the user can retry later.
          }
        }
        // All-fail signals a likely environment problem (BLE off, permission
        // revoked, hardware all out of range). Worth a breadcrumb so we can
        // tell the difference between "no sensors paired" and "everything
        // failed" in production.
        if (successes === 0) {
          Sentry.captureMessage('Sensor reconnect failed for all known devices', {
            level: 'warning',
            extra: { knownCount: known.length },
          });
        }
      },

      disconnectAll: async () => {
        // Snapshot before iterating — disconnect() mutates `connections`.
        const current = Object.values(get().connections);
        for (const conn of current) {
          try {
            await get().disconnect(conn.deviceId, conn.kind);
          } catch (err) {
            console.warn(
              `[PairingStore] Disconnect of ${conn.deviceId}|${conn.kind} failed:`,
              err,
            );
          }
        }
        // Also clear transient discovery state so a fresh pairing session
        // doesn't see stale scan results from the logged-out session.
        set({ discovered: {}, scanning: false, scanError: null });
      },

      calibratePower: async (deviceId) => {
        const source = sensorRegistry.get(deviceId, 'power');
        if (!source || source.kind !== 'power' || !source.sendCommand) {
          throw new Error(`No power meter connected at ${deviceId}`);
        }
        return source.sendCommand({ type: 'start_offset_compensation' });
      },

      setWheelCircumference: (deviceId, meters) => {
        if (!Number.isFinite(meters) || meters < MIN_WHEEL_M || meters > MAX_WHEEL_M) {
          console.warn(
            `[PairingStore] Rejected wheel circumference ${meters}m ` +
              `(expected ${MIN_WHEEL_M}-${MAX_WHEEL_M}m)`,
          );
          return;
        }
        // Persist to the known-device entry for future connects.
        set((state) => ({
          known: state.known.map((k) =>
            k.id === deviceId && k.kind === 'cadence'
              ? { ...k, wheelCircumferenceM: meters }
              : k,
          ),
        }));
        // Apply immediately to the live source, if any.
        const source = sensorRegistry.get(deviceId, 'cadence');
        if (source instanceof CadenceSource) {
          source.setWheelCircumference(meters);
        }
      },
    }),
    {
      name: 'pairing',
      storage: createJSONStorage(() => AsyncStorage),
      // Runtime state (scan progress, discovered devices, live connections)
      // is not worth persisting — it is rebuilt on app launch via
      // reconnectKnown(). Only the `known` list survives restart.
      partialize: (state) => ({ known: state.known }),
    },
  ),
);
