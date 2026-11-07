/**
 * PairingScreen — BLE sensor cabinet.
 *
 * The mechanic is intentionally simple: paired sensors show whether they are
 * ready, nearby sensors can be paired, and BLE failures are translated into
 * rider-language instead of raw native exceptions.
 */

import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  SafeAreaView,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';

import { usePairingStore } from '../stores/pairingStore';
import type { SensorKind, SensorStatus } from '../services/sensors/types';
import type { DiscoveredDevice } from '../services/sensors/ble/manager';
import { sensorRegistry } from '../services/sensors/registry';
import {
  SENSOR_KIND_LABELS,
  displayForConnectionStatus,
  friendlyBleError,
  kindsLine,
  type SensorStatusDisplay,
} from '../lib/sensorDisplay';

export default function PairingScreen() {
  const navigation = useNavigation();
  const {
    discovered,
    known,
    connections,
    scanning,
    scanError,
    startScan,
    stopScan,
    connect,
    disconnect,
    forget,
    calibratePower,
  } = usePairingStore();

  const [busyKey, setBusyKey] = useState<string | null>(null);

  useEffect(() => {
    // Stop scanning when leaving the screen; avoid battery drain.
    return () => {
      stopScan();
    };
  }, [stopScan]);

  const handleConnect = async (device: DiscoveredDevice, kind: SensorKind) => {
    const key = `${device.id}|${kind}`;
    setBusyKey(key);
    try {
      await connect(device.id, kind, device.name);
    } catch (e) {
      Alert.alert('Sensor not ready', friendlyBleError(e));
    } finally {
      setBusyKey(null);
    }
  };

  const handleDisconnect = async (deviceId: string, kind: SensorKind) => {
    const key = `${deviceId}|${kind}`;
    setBusyKey(key);
    try {
      await disconnect(deviceId, kind);
    } finally {
      setBusyKey(null);
    }
  };

  const handleForget = (deviceId: string, kind: SensorKind, name: string) => {
    Alert.alert(
      'Forget sensor?',
      `${name} will need to be paired again next time.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Forget',
          style: 'destructive',
          onPress: () => forget(deviceId, kind),
        },
      ],
    );
  };

  const handleCalibrate = async (deviceId: string, name: string) => {
    try {
      const result = await calibratePower(deviceId);
      if (result.success) {
        const offset = (result.data as { offset?: number } | undefined)?.offset;
        Alert.alert(
          'Calibration complete',
          offset !== undefined ? `${name} offset ${offset}` : `${name} calibrated.`,
        );
      } else {
        Alert.alert(
          'Calibration failed',
          result.error
            ? friendlyBleError(result.error)
            : `Sensor returned code 0x${result.resultCode?.toString(16) ?? '??'}. Try again after waking it up.`,
        );
      }
    } catch (e) {
      Alert.alert('Calibration error', friendlyBleError(e));
    }
  };

  const discoveredList = Object.values(discovered).filter(
    (d) => !known.some((k) => k.id === d.id && d.kinds.includes(k.kind)),
  );

  const statusForKnown = (deviceId: string, kind: SensorKind): SensorStatus => {
    const conn = connections[`${deviceId}|${kind}`];
    const source = sensorRegistry.get(deviceId, kind);
    if (conn?.status === 'connected' && source?.status) {
      return source.status;
    }
    return conn?.status ?? 'disconnected';
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.topRow}>
          <View>
            <Text style={styles.title}>Sensors</Text>
            <Text style={styles.subtitle}>
              Power, heart rate, and cadence for honest ride evidence.
            </Text>
          </View>
          <TouchableOpacity
            style={styles.doneButton}
            onPress={() => navigation.goBack()}
            accessibilityLabel="Close sensor pairing"
          >
            <Text style={styles.doneButtonText}>Done</Text>
          </TouchableOpacity>
        </View>

        {scanError && (
          <View style={styles.errorBanner}>
            <Text style={styles.errorText}>{friendlyBleError(scanError)}</Text>
          </View>
        )}

        <View style={styles.section}>
          <View style={styles.sectionHeaderRow}>
            <Text style={styles.sectionHeader}>Paired sensors</Text>
          </View>

          {known.length === 0 ? (
            <Text style={styles.emptyText}>
              No sensors paired yet. Pairing is optional; GPS-only rides still save normally.
            </Text>
          ) : (
            known.map((dev) => {
              const key = `${dev.id}|${dev.kind}`;
              const status = statusForKnown(dev.id, dev.kind);
              const statusDisplay = displayForConnectionStatus(status);
              const isBusy = busyKey === key;
              return (
                <View key={key} style={styles.row}>
                  <View style={styles.rowHeader}>
                    <View style={styles.rowLeft}>
                      <Text style={styles.deviceName}>{dev.name}</Text>
                      <Text style={styles.deviceMeta}>{SENSOR_KIND_LABELS[dev.kind]}</Text>
                    </View>
                    <StatusPill display={statusDisplay} />
                  </View>
                  <View style={styles.rowActions}>
                    {dev.kind === 'power' && status === 'connected' && (
                      <TouchableOpacity
                        style={styles.actionBtn}
                        onPress={() => handleCalibrate(dev.id, dev.name)}
                        disabled={isBusy}
                      >
                        <Text style={styles.actionText}>Calibrate</Text>
                      </TouchableOpacity>
                    )}
                    {status === 'connected' ? (
                      <TouchableOpacity
                        style={styles.actionBtn}
                        onPress={() => handleDisconnect(dev.id, dev.kind)}
                        disabled={isBusy}
                      >
                        <Text style={styles.actionText}>
                          {isBusy ? '…' : 'Disconnect'}
                        </Text>
                      </TouchableOpacity>
                    ) : status === 'connecting' ? (
                      <ActivityIndicator color="#c4a035" />
                    ) : (
                      <TouchableOpacity
                        style={styles.actionBtn}
                        onPress={() =>
                          handleConnect(
                            {
                              id: dev.id,
                              name: dev.name,
                              rssi: null,
                              advertisedServiceUuids: [],
                              kinds: [dev.kind],
                            },
                            dev.kind,
                          )
                        }
                        disabled={isBusy}
                      >
                        <Text style={styles.actionText}>
                          {isBusy ? '…' : 'Reconnect'}
                        </Text>
                      </TouchableOpacity>
                    )}
                    <TouchableOpacity
                      style={styles.actionBtn}
                      onPress={() => handleForget(dev.id, dev.kind, dev.name)}
                    >
                      <Text style={styles.actionTextDestructive}>Forget</Text>
                    </TouchableOpacity>
                  </View>
                </View>
              );
            })
          )}
        </View>

        <View style={styles.section}>
          <View style={styles.sectionHeaderRow}>
            <Text style={styles.sectionHeader}>Available</Text>
            <TouchableOpacity
              style={styles.scanBtn}
              onPress={scanning ? stopScan : startScan}
            >
              <Text style={styles.scanBtnText}>
                {scanning ? 'Stop Scan' : 'Start Scan'}
              </Text>
            </TouchableOpacity>
          </View>

          {scanning && discoveredList.length === 0 && (
            <View style={styles.scanningRow}>
              <ActivityIndicator color="#c4a035" />
              <Text style={styles.scanningText}>Looking for sensors…</Text>
            </View>
          )}

          {!scanning && discoveredList.length === 0 && (
            <Text style={styles.emptyText}>
              Tap Start Scan to find your power meter, heart rate strap, or
              cadence sensor.
            </Text>
          )}

          {discoveredList.map((device) =>
            device.kinds.map((kind) => {
              const key = `${device.id}|${kind}`;
              const isBusy = busyKey === key;
              return (
                <View key={key} style={styles.row}>
                  <View style={styles.rowHeader}>
                    <View style={styles.rowLeft}>
                      <Text style={styles.deviceName}>{device.name}</Text>
                      <Text style={styles.deviceMeta}>
                        {SENSOR_KIND_LABELS[kind]}
                        {device.rssi != null ? ` · ${device.rssi} dBm` : ''}
                      </Text>
                    </View>
                    <StatusPill display={{ label: 'Nearby', tone: 'ready' }} />
                  </View>
                  <TouchableOpacity
                    style={styles.actionBtn}
                    onPress={() => handleConnect(device, kind)}
                    disabled={isBusy}
                  >
                    <Text style={styles.actionText}>
                      {isBusy ? '…' : 'Pair'}
                    </Text>
                  </TouchableOpacity>
                </View>
              );
            }),
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function StatusPill({ display }: { display: SensorStatusDisplay }) {
  return (
    <View style={[styles.statusPill, statusPillStyle(display.tone)]}>
      <Text style={[styles.statusPillText, statusPillTextStyle(display.tone)]}>
        {display.label}
      </Text>
    </View>
  );
}

function statusPillStyle(tone: SensorStatusDisplay['tone']) {
  switch (tone) {
    case 'ready':
      return styles.statusPill_ready;
    case 'working':
      return styles.statusPill_working;
    case 'attention':
      return styles.statusPill_attention;
    case 'muted':
    default:
      return styles.statusPill_muted;
  }
}

function statusPillTextStyle(tone: SensorStatusDisplay['tone']) {
  switch (tone) {
    case 'ready':
      return styles.statusPillText_ready;
    case 'working':
      return styles.statusPillText_working;
    case 'attention':
      return styles.statusPillText_attention;
    case 'muted':
    default:
      return styles.statusPillText_muted;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  scrollContent: {
    padding: 16,
    paddingBottom: 48,
  },
  topRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 16,
    marginBottom: 24,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#e5e5e5',
  },
  subtitle: {
    fontSize: 13,
    lineHeight: 18,
    color: '#8a8a8a',
    marginTop: 4,
    maxWidth: 260,
  },
  doneButton: {
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#333',
    backgroundColor: '#141414',
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  doneButtonText: {
    color: '#e5e5e5',
    fontSize: 13,
    fontWeight: '700',
  },
  errorBanner: {
    backgroundColor: '#2a1010',
    borderColor: '#5a2020',
    borderWidth: 1,
    borderRadius: 6,
    padding: 12,
    marginBottom: 16,
  },
  errorText: {
    color: '#e5aaaa',
    fontSize: 14,
  },
  section: {
    marginBottom: 24,
  },
  sectionHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  sectionHeader: {
    fontSize: 14,
    fontWeight: '600',
    color: '#999',
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  scanBtn: {
    backgroundColor: '#c4a035',
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 4,
  },
  scanBtnText: {
    color: '#0a0a0a',
    fontSize: 13,
    fontWeight: '600',
  },
  row: {
    paddingVertical: 14,
    gap: 10,
    borderBottomColor: '#222',
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  rowHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
  },
  rowLeft: {
    flex: 1,
    minWidth: 0,
  },
  rowActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 8,
  },
  deviceName: {
    fontSize: 15,
    color: '#e5e5e5',
    fontWeight: '500',
  },
  deviceMeta: {
    fontSize: 12,
    color: '#888',
    marginTop: 2,
  },
  statusPill: {
    borderRadius: 999,
    paddingHorizontal: 9,
    paddingVertical: 5,
    borderWidth: StyleSheet.hairlineWidth,
    minWidth: 82,
    alignItems: 'center',
  },
  statusPill_ready: {
    backgroundColor: 'rgba(74, 222, 128, 0.12)',
    borderColor: 'rgba(74, 222, 128, 0.35)',
  },
  statusPill_working: {
    backgroundColor: 'rgba(196, 160, 53, 0.13)',
    borderColor: 'rgba(196, 160, 53, 0.38)',
  },
  statusPill_muted: {
    backgroundColor: 'rgba(120, 120, 120, 0.1)',
    borderColor: '#303030',
  },
  statusPill_attention: {
    backgroundColor: 'rgba(239, 68, 68, 0.12)',
    borderColor: 'rgba(239, 68, 68, 0.36)',
  },
  statusPillText: {
    fontSize: 11,
    fontWeight: '800',
  },
  statusPillText_ready: {
    color: '#86efac',
  },
  statusPillText_working: {
    color: '#d7b955',
  },
  statusPillText_muted: {
    color: '#8a8a8a',
  },
  statusPillText_attention: {
    color: '#fca5a5',
  },
  actionBtn: {
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderColor: '#333',
    borderWidth: 1,
    borderRadius: 4,
  },
  actionText: {
    fontSize: 13,
    color: '#e5e5e5',
  },
  actionTextDestructive: {
    fontSize: 13,
    color: '#e58080',
  },
  scanningRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 16,
  },
  scanningText: {
    color: '#888',
    fontSize: 14,
  },
  emptyText: {
    color: '#666',
    fontSize: 14,
    fontStyle: 'italic',
    paddingVertical: 12,
  },
});
