/**
 * RecordScreen — GPS Ride Recording
 *
 * Three states:
 *   - Pre-ride: GPS status indicator + start button
 *   - During ride: elapsed time, distance, elevation, speed + controls
 *   - Post-ride redirect: navigates to PostRideScreen
 *
 * Uses expo-location for GPS tracking.
 * Product shape: a live cockpit. Map UI should use a real native map layer,
 * not decorative stand-ins.
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Alert,
  ActivityIndicator,
  AppState,
  Linking,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { randomUUID } from 'expo-crypto';
import * as Location from 'expo-location';
import MapView, { Polyline, type LatLng, type Region } from 'react-native-maps';

import TopTabBar from '../components/navigation/TopTabBar';
import SectionCard from '../components/surfaces/SectionCard';
import StatCluster, { type StatClusterItem } from '../components/surfaces/StatCluster';
import { useRecordingStore, type LiveRoutePoint } from '../stores/recordingStore';
import { usePairingStore } from '../stores/pairingStore';
import { getDatabase, createRide, deleteRide, getRide, updateRide } from '../services/database';
import {
  getLocationPermissionBlocker,
  requestLocationPermissions,
  startRecording,
  stopRecording,
  pauseRecording,
  resumeRecording,
  discardRecording,
  type LocationPermissionBlocker,
  type LocationPermissionState,
} from '../services/gpsRecording';
import { sensorRegistry } from '../services/sensors/registry';
import type { SensorKind } from '../services/sensors/types';
import { enqueueRide } from '../services/uploadQueue';
import {
  buildLiveSensorDisplay,
  buildSensorReadinessDisplay,
  type LiveSensorDisplayItem,
  type SensorDisplayTone,
} from '../lib/sensorDisplay';
import { isIncompleteRide, incompleteRideReason } from '../lib/rideCompletion';
import { recordRideValidationEvent } from '../lib/rideValidation';
import { mobileMapColors } from '../theme/map';

// ---------------------------------------------------------------------------
// Formatting utilities
// ---------------------------------------------------------------------------

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

function formatDistance(meters: number): string {
  if (meters >= 1000) {
    return (meters / 1000).toFixed(1);
  }
  return (meters / 1000).toFixed(2);
}

function formatSpeed(mps: number): string {
  // Convert m/s to km/h
  return (mps * 3.6).toFixed(1);
}

function formatElevation(meters: number): string {
  return Math.round(meters).toString();
}

function buildLiveStats(
  distanceM: number,
  currentSpeedMps: number,
  elevationGainM: number,
): StatClusterItem[] {
  return [
    { label: 'Distance', value: `${formatDistance(distanceM)} km` },
    { label: 'Speed', value: `${formatSpeed(currentSpeedMps)} km/h` },
    { label: 'Elevation', value: `${formatElevation(elevationGainM)} m` },
  ];
}

function regionFor(point: LatLng): Region {
  return {
    latitude: point.latitude,
    longitude: point.longitude,
    latitudeDelta: 0.014,
    longitudeDelta: 0.014,
  };
}

function latestRoutePoint(routePoints: LiveRoutePoint[]): LiveRoutePoint | null {
  return routePoints.length > 0 ? routePoints[routePoints.length - 1] : null;
}

function pointFromLocation(location: Location.LocationObject | null): LiveRoutePoint | null {
  if (!location) return null;
  return {
    latitude: location.coords.latitude,
    longitude: location.coords.longitude,
  };
}

function locationStatusText(permissions: LocationPermissionState | null): string {
  if (!permissions) return 'Checking GPS...';
  if (!permissions.servicesEnabled) return 'Location Services off';
  if (!permissions.foreground) return 'Location permission needed';
  if (!permissions.background && permissions.backgroundStatus === 'denied' && !permissions.backgroundCanAskAgain) {
    return 'Always Location needed';
  }
  return 'GPS ready';
}

function locationHint(permissions: LocationPermissionState | null): string | null {
  if (!permissions) return null;
  if (!permissions.servicesEnabled) return 'Turn on iPhone Location Services, then return to BoulderRoller.';
  if (!permissions.foreground) return 'Allow BoulderRoller to use location while recording rides.';
  if (!permissions.background && permissions.backgroundStatus === 'denied' && !permissions.backgroundCanAskAgain) {
    return 'Allow Always Location in Settings so rides keep tracking when the screen locks.';
  }
  return null;
}

function showLocationAlert(blocker: LocationPermissionBlocker): void {
  const openSettings = () => {
    Linking.openSettings().catch((err) => {
      console.error('[RecordScreen] Failed to open Settings:', err);
    });
  };

  if (blocker === 'services_disabled') {
    Alert.alert(
      'Location Services Off',
      'Turn on iPhone Location Services, then return to BoulderRoller.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Open Settings', onPress: openSettings },
      ],
    );
    return;
  }

  if (blocker === 'background_permission') {
    Alert.alert(
      'Always Location Needed',
      'Set BoulderRoller location access to Always so ride recording can keep tracking if the screen locks.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Open Settings', onPress: openSettings },
      ],
    );
    return;
  }

  Alert.alert(
    'Location Permission Needed',
    'Allow BoulderRoller to use location while recording rides.',
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Open Settings', onPress: openSettings },
    ],
  );
}

function RecordMapLayer({
  center,
  routePoints,
}: {
  center: LiveRoutePoint | null;
  routePoints: LiveRoutePoint[];
}) {
  if (!center) return null;

  return (
    <View style={styles.mapLayer} pointerEvents="none">
      <MapView
        testID="record-map"
        style={styles.map}
        region={regionFor(center)}
        scrollEnabled={false}
        zoomEnabled={false}
        rotateEnabled={false}
        pitchEnabled={false}
        showsCompass={false}
        showsScale={false}
        showsUserLocation
        showsMyLocationButton={false}
        mapType="mutedStandard"
        userInterfaceStyle="light"
        loadingEnabled
        loadingBackgroundColor={mobileMapColors.base}
        loadingIndicatorColor={mobileMapColors.route}
        tintColor={mobileMapColors.route}
      >
        {routePoints.length > 1 ? (
          <Polyline
            coordinates={routePoints}
            strokeColor={mobileMapColors.route}
            strokeWidth={4}
            lineCap="round"
            lineJoin="round"
          />
        ) : null}
      </MapView>
      <View style={styles.mapScrim} />
    </View>
  );
}

function uniqueKinds(kinds: SensorKind[]): SensorKind[] {
  return Array.from(new Set(kinds));
}

function SensorReadinessPill({
  label,
  detail,
  tone,
  onPress,
}: {
  label: string;
  detail: string;
  tone: SensorDisplayTone;
  onPress: () => void;
}) {
  return (
    <TouchableOpacity
      style={[styles.sensorIndicator, sensorIndicatorStyle(tone)]}
      onPress={onPress}
      activeOpacity={0.82}
      testID="record-sensor-readiness"
      accessibilityLabel="Sensor readiness"
    >
      <View style={[styles.sensorDot, sensorDotStyle(tone)]} />
      <View style={styles.sensorIndicatorTextWrap}>
        <Text style={styles.sensorIndicatorLabel}>{label}</Text>
        <Text style={styles.sensorIndicatorDetail}>{detail}</Text>
      </View>
    </TouchableOpacity>
  );
}

function SensorLiveStrip({ items }: { items: LiveSensorDisplayItem[] }) {
  return (
    <View style={styles.sensorLiveStrip} testID="record-live-sensors">
      {items.map((item) => (
        <View key={item.label} style={styles.sensorLiveCell}>
          <Text
            style={[
              styles.sensorLiveValue,
              item.state !== 'live' && styles.sensorLiveValueMissing,
            ]}
            testID={`record-live-sensor-${item.label.toLowerCase()}`}
          >
            {item.value}
          </Text>
          <Text style={styles.sensorLiveUnit}>{item.unit}</Text>
          <Text style={styles.sensorLiveLabel}>{item.label}</Text>
        </View>
      ))}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function RecordScreen() {
  const navigation = useNavigation();
  const status = useRecordingStore((s) => s.status);
  const elapsedMs = useRecordingStore((s) => s.elapsedMs);
  const distanceM = useRecordingStore((s) => s.distanceM);
  const elevationGainM = useRecordingStore((s) => s.elevationGainM);
  const currentSpeedMps = useRecordingStore((s) => s.currentSpeedMps);
  const sampleCount = useRecordingStore((s) => s.sampleCount);
  const currentLocation = useRecordingStore((s) => s.currentLocation);
  const routePoints = useRecordingStore((s) => s.routePoints);
  const pairedCount = usePairingStore((s) => s.known.length);
  const connections = usePairingStore((s) => s.connections);

  const [locationPermissions, setLocationPermissions] = useState<LocationPermissionState | null>(null);
  const [starting, setStarting] = useState(false);
  const [idleMapCenter, setIdleMapCenter] = useState<LiveRoutePoint | null>(null);
  const gpsReady = Boolean(locationPermissions?.servicesEnabled && locationPermissions.foreground);
  const currentLocationHint = locationHint(locationPermissions);

  const checkPermissions = useCallback(async (options?: { requestBackground?: boolean }) => {
    const permissions = await requestLocationPermissions(options);
    setLocationPermissions(permissions);
    return permissions;
  }, []);

  // Check GPS permissions on mount.
  useEffect(() => {
    void checkPermissions();
  }, [checkPermissions]);

  // Re-check after returning from iOS Settings so the start button cannot stay
  // stuck behind a stale denied state.
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState === 'active') {
        void checkPermissions();
      }
    });
    return () => subscription.remove();
  }, [checkPermissions]);

  useEffect(() => {
    let cancelled = false;
    if (!gpsReady || status !== 'idle') return;

    (async () => {
      try {
        const lastKnown = await Location.getLastKnownPositionAsync();
        const location = lastKnown ?? await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        if (!cancelled) {
          setIdleMapCenter(pointFromLocation(location));
        }
      } catch {
        if (!cancelled) setIdleMapCenter(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [gpsReady, status]);

  // Handle start
  const handleStart = useCallback(async () => {
    if (starting) return;
    setStarting(true);
    let newRideId: string | null = null;
    const db = getDatabase();

    try {
      const permissions = await checkPermissions({ requestBackground: true });
      const blocker = getLocationPermissionBlocker(permissions, { requireBackground: true });
      if (blocker) {
        showLocationAlert(blocker);
        return;
      }

      newRideId = randomUUID();
      createRide(db, newRideId, Date.now());
      useRecordingStore.getState().startRide(newRideId);
      await startRecording(newRideId);
    } catch (err) {
      console.error('[RecordScreen] Start error:', err);
      if (newRideId) {
        try {
          deleteRide(db, newRideId);
        } catch (deleteErr) {
          console.error('[RecordScreen] Failed to clean up ride after start error:', deleteErr);
        }
      }
      Alert.alert('Error', 'Failed to start recording. Please try again.');
      useRecordingStore.getState().reset();
    } finally {
      setStarting(false);
    }
  }, [checkPermissions, starting]);

  // Handle pause/resume
  const handlePauseResume = useCallback(() => {
    if (status === 'recording') {
      pauseRecording('manual');
    } else if (status === 'paused') {
      resumeRecording();
    }
  }, [status]);

  // Handle stop
  const handleStop = useCallback(() => {
    Alert.alert(
      'End Ride?',
      'Stop recording and save your ride?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'End Ride',
          onPress: async () => {
            try {
              const stoppedRideId = await stopRecording();
              if (!stoppedRideId) return;

              useRecordingStore.getState().setSaving();
              const db = getDatabase();
              const ride = getRide(db, stoppedRideId);
              if (ride && isIncompleteRide({
                distanceM: ride.distance_m,
                durationMs: ride.duration_ms,
                sampleCount: ride.sample_count,
              })) {
                const reason = incompleteRideReason({
                  distanceM: ride.distance_m,
                  durationMs: ride.duration_ms,
                  sampleCount: ride.sample_count,
                });
                updateRide(db, stoppedRideId, {
                  status: 'incomplete',
                  notes: reason,
                });
                recordRideValidationEvent(db, stoppedRideId, 'recording_incomplete', {
                  reason,
                  distanceM: ride.distance_m,
                  durationMs: ride.duration_ms,
                  sampleCount: ride.sample_count,
                });
              } else {
                enqueueRide(stoppedRideId);
              }

              useRecordingStore.getState().reset();
              (navigation as { navigate: (screen: string, params: { rideId: string }) => void })
                .navigate('PostRide', { rideId: stoppedRideId });
            } catch (err) {
              console.error('[RecordScreen] Stop error:', err);
              Alert.alert('Error', 'Failed to save ride. Please try again.');
            }
          },
        },
      ],
    );
  }, [navigation]);

  // Handle discard
  const handleDiscard = useCallback(() => {
    Alert.alert(
      'Discard Ride?',
      'This will permanently delete all ride data.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Discard',
          style: 'destructive',
          onPress: async () => {
            await discardRecording();
          },
        },
      ],
    );
  }, []);

  const pairingConnectedKinds = uniqueKinds(
    Object.values(connections)
      .filter((c) => c.status === 'connected')
      .map((c) => c.kind),
  );
  const registeredSources = sensorRegistry.all();
  const runtimeConnectedKinds = registeredSources.length > 0
    ? uniqueKinds(
        registeredSources
          .filter((source) => source.status === 'connected')
          .map((source) => source.kind),
      )
    : pairingConnectedKinds;
  const connectingCount = Object.values(connections).filter(
    (c) => c.status === 'connecting',
  ).length;
  const attentionCount = Object.values(connections).filter(
    (c) => c.status === 'error',
  ).length + registeredSources.filter((source) => source.status === 'error').length;
  const sensorReadiness = buildSensorReadinessDisplay({
    connectedKinds: runtimeConnectedKinds,
    pairedCount,
    connectingCount,
    attentionCount,
  });
  const liveSensorItems = buildLiveSensorDisplay({
    connectedKinds: runtimeConnectedKinds,
    power: sensorRegistry.getLatestPower(),
    heartRate: sensorRegistry.getLatestHeartRate(),
    cadence: sensorRegistry.getLatestCadence(),
  });

  // Render pre-ride state
  if (status === 'idle') {
    const mapCenter = idleMapCenter;

    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.cockpit}>
          <RecordMapLayer center={mapCenter} routePoints={[]} />
          <TopTabBar
            title="Record"
            testIdPrefix="record"
            onPressSearch={() => (navigation as { navigate: (screen: string) => void }).navigate('Search')}
            onPressProfile={() => (navigation as { navigate: (screen: string) => void }).navigate('Profile')}
          />

          <View style={styles.readyContent}>
            <View style={styles.readinessRow}>
              <View style={styles.gpsIndicator}>
                <View style={[styles.gpsDot, gpsReady ? styles.gpsDotReady : styles.gpsDotNotReady]} />
                <Text style={styles.gpsText}>
                  {locationStatusText(locationPermissions)}
                </Text>
              </View>
              <SensorReadinessPill
                label={sensorReadiness.label}
                detail={sensorReadiness.detail}
                tone={sensorReadiness.tone}
                onPress={() => (navigation as { navigate: (screen: string) => void }).navigate('Pairing')}
              />
            </View>

            <Text style={styles.readyTitle}>Ready</Text>

            <TouchableOpacity
              style={[styles.startButton, starting && styles.startButtonDisabled]}
              onPress={handleStart}
              disabled={starting}
            >
              {starting ? (
                <ActivityIndicator color="#0a0a0a" />
              ) : (
                <Text style={styles.startButtonText}>{gpsReady ? 'Start ride' : 'Check location'}</Text>
              )}
            </TouchableOpacity>

            {currentLocationHint && (
              <Text style={styles.permissionHint}>
                {currentLocationHint}
              </Text>
            )}
          </View>
        </View>
      </SafeAreaView>
    );
  }

  // Render stopping/saving state
  if (status === 'stopping' || status === 'saving') {
    const mapCenter = currentLocation ?? latestRoutePoint(routePoints) ?? idleMapCenter;

    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.cockpit}>
          <RecordMapLayer center={mapCenter} routePoints={routePoints} />
          <TopTabBar
            title="Record"
            testIdPrefix="record"
            onPressSearch={() => (navigation as { navigate: (screen: string) => void }).navigate('Search')}
            onPressProfile={() => (navigation as { navigate: (screen: string) => void }).navigate('Profile')}
          />
          <View style={styles.savingContainer}>
            <SectionCard style={styles.savingCard}>
              <ActivityIndicator size="large" color="#c4a035" />
              <Text style={styles.savingText}>Saving ride</Text>
              <StatCluster items={buildLiveStats(distanceM, currentSpeedMps, elevationGainM)} />
            </SectionCard>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  // Render recording/paused state
  const mapCenter = currentLocation ?? latestRoutePoint(routePoints) ?? idleMapCenter;

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <View style={styles.cockpit}>
        <RecordMapLayer center={mapCenter} routePoints={routePoints} />
        <View style={styles.liveTopBar}>
          <View style={styles.statusPill}>
            <View style={[styles.statusDot, status === 'paused' ? styles.statusPaused : styles.statusRecording]} />
            <Text style={styles.statusText}>
              {status === 'paused' ? 'Paused' : 'Recording'}
            </Text>
          </View>
          <Text style={styles.sampleCountText}>
            {sampleCount > 0 ? 'GPS locked' : 'Finding GPS'}
          </Text>
        </View>

        <View style={styles.liveContent}>
          <Text style={styles.timerText}>{formatDuration(elapsedMs)}</Text>

          <SectionCard style={styles.liveStatsCard}>
            <StatCluster items={buildLiveStats(distanceM, currentSpeedMps, elevationGainM)} />
          </SectionCard>

          <SensorLiveStrip items={liveSensorItems} />

          <View style={styles.integrityStrip}>
            <View style={styles.integrityItem}>
              <Text style={styles.integrityLabel}>GPS</Text>
              <Text style={styles.integrityValue}>
                {sampleCount > 0 ? 'Tracking' : 'Waiting'}
              </Text>
            </View>
            <View style={styles.integrityDivider} />
            <View style={styles.integrityItem}>
              <Text style={styles.integrityLabel}>Sensors</Text>
              <Text style={styles.integrityValue} numberOfLines={1}>
                {sensorReadiness.label}
              </Text>
            </View>
            <View style={styles.integrityDivider} />
            <View style={styles.integrityItem}>
              <Text style={styles.integrityLabel}>Saved</Text>
              <Text style={styles.integrityValue}>On device</Text>
            </View>
          </View>
        </View>

        <View style={styles.controlsContainer}>
          <TouchableOpacity style={styles.discardControl} onPress={handleDiscard}>
            <Text style={styles.discardControlText}>Discard</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.controlButton, status === 'paused' ? styles.resumeButton : styles.pauseButton]}
            onPress={handlePauseResume}
          >
            <Text style={styles.controlButtonText}>
              {status === 'paused' ? 'Resume' : 'Pause'}
            </Text>
          </TouchableOpacity>

          <TouchableOpacity style={styles.stopButton} onPress={handleStop}>
            <Text style={styles.stopButtonText}>Stop</Text>
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
}

function sensorIndicatorStyle(tone: SensorDisplayTone) {
  switch (tone) {
    case 'ready':
      return styles.sensorIndicatorReady;
    case 'working':
      return styles.sensorIndicatorWorking;
    case 'attention':
      return styles.sensorIndicatorAttention;
    case 'muted':
    default:
      return styles.sensorIndicatorMuted;
  }
}

function sensorDotStyle(tone: SensorDisplayTone) {
  switch (tone) {
    case 'ready':
      return styles.sensorDotReady;
    case 'working':
      return styles.sensorDotWorking;
    case 'attention':
      return styles.sensorDotAttention;
    case 'muted':
    default:
      return styles.sensorDotMuted;
  }
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  cockpit: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  mapLayer: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: mobileMapColors.base,
  },
  map: {
    ...StyleSheet.absoluteFillObject,
  },
  mapScrim: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: mobileMapColors.liveScrim,
  },

  // Pre-ride
  readyContent: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 28,
    paddingBottom: 80,
  },
  readinessRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 10,
    marginBottom: 24,
  },
  gpsIndicator: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#2a2a2a',
    backgroundColor: 'rgba(20, 20, 20, 0.84)',
    paddingHorizontal: 11,
    paddingVertical: 7,
  },
  gpsDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 8,
  },
  gpsDotReady: {
    backgroundColor: '#4ade80',
  },
  gpsDotNotReady: {
    backgroundColor: '#ef4444',
  },
  gpsText: {
    fontSize: 14,
    color: '#c6c6c6',
    fontWeight: '600',
  },
  sensorIndicator: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 11,
    paddingVertical: 7,
    maxWidth: '100%',
  },
  sensorIndicatorReady: {
    borderColor: 'rgba(74, 222, 128, 0.35)',
    backgroundColor: 'rgba(18, 45, 28, 0.78)',
  },
  sensorIndicatorWorking: {
    borderColor: 'rgba(196, 160, 53, 0.4)',
    backgroundColor: 'rgba(55, 45, 20, 0.78)',
  },
  sensorIndicatorMuted: {
    borderColor: '#2a2a2a',
    backgroundColor: 'rgba(20, 20, 20, 0.84)',
  },
  sensorIndicatorAttention: {
    borderColor: 'rgba(239, 68, 68, 0.35)',
    backgroundColor: 'rgba(55, 20, 20, 0.78)',
  },
  sensorDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 8,
  },
  sensorDotReady: {
    backgroundColor: '#4ade80',
  },
  sensorDotWorking: {
    backgroundColor: '#c4a035',
  },
  sensorDotMuted: {
    backgroundColor: '#777',
  },
  sensorDotAttention: {
    backgroundColor: '#ef4444',
  },
  sensorIndicatorTextWrap: {
    maxWidth: 230,
  },
  sensorIndicatorLabel: {
    fontSize: 13,
    color: '#d6d6d6',
    fontWeight: '800',
  },
  sensorIndicatorDetail: {
    fontSize: 11,
    color: '#8a8a8a',
    marginTop: 1,
  },
  readyTitle: {
    color: '#f2f2f2',
    fontSize: 52,
    fontWeight: '700',
    letterSpacing: 0,
  },
  startButton: {
    alignSelf: 'flex-start',
    borderRadius: 999,
    backgroundColor: '#c4a035',
    paddingHorizontal: 28,
    paddingVertical: 17,
    marginTop: 32,
  },
  startButtonDisabled: {
    backgroundColor: '#333',
  },
  startButtonText: {
    fontSize: 17,
    fontWeight: '800',
    color: '#0a0a0a',
  },
  permissionHint: {
    fontSize: 13,
    color: '#ef4444',
    marginTop: 18,
  },

  // Recording status
  liveTopBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 14,
    paddingBottom: 10,
  },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: 999,
    backgroundColor: 'rgba(20, 20, 20, 0.86)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#2a2a2a',
    paddingHorizontal: 11,
    paddingVertical: 7,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  statusRecording: {
    backgroundColor: '#ef4444',
  },
  statusPaused: {
    backgroundColor: '#f59e0b',
  },
  statusText: {
    fontSize: 13,
    fontWeight: '700',
    color: '#d6d6d6',
  },
  sampleCountText: {
    fontSize: 12,
    color: '#8a8a8a',
    fontWeight: '700',
  },

  // Timer
  liveContent: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 20,
    paddingBottom: 30,
  },
  timerText: {
    fontSize: 62,
    fontWeight: '200',
    color: '#e5e5e5',
    fontVariant: ['tabular-nums'],
    textAlign: 'center',
  },
  liveStatsCard: {
    padding: 16,
    backgroundColor: 'rgba(20, 20, 20, 0.9)',
  },
  sensorLiveStrip: {
    flexDirection: 'row',
    alignSelf: 'stretch',
    alignItems: 'stretch',
    borderRadius: 18,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#242424',
    backgroundColor: 'rgba(12, 12, 12, 0.86)',
    marginTop: 12,
    overflow: 'hidden',
  },
  sensorLiveCell: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 10,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: '#242424',
  },
  sensorLiveValue: {
    color: '#f0f0f0',
    fontSize: 22,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  sensorLiveValueMissing: {
    color: '#606060',
  },
  sensorLiveUnit: {
    color: '#8a8a8a',
    fontSize: 10,
    fontWeight: '800',
    marginTop: 1,
  },
  sensorLiveLabel: {
    color: '#6f6f6f',
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
    marginTop: 6,
  },
  integrityStrip: {
    flexDirection: 'row',
    alignSelf: 'center',
    alignItems: 'center',
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#2a2a2a',
    backgroundColor: 'rgba(20, 20, 20, 0.84)',
    marginTop: 14,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  integrityItem: {
    alignItems: 'center',
    minWidth: 84,
  },
  integrityDivider: {
    width: StyleSheet.hairlineWidth,
    height: 26,
    backgroundColor: '#2a2a2a',
  },
  integrityLabel: {
    color: '#6f6f6f',
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  integrityValue: {
    color: '#d6d6d6',
    fontSize: 13,
    fontWeight: '700',
    marginTop: 3,
  },

  // Controls
  controlsContainer: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingBottom: 22,
    paddingTop: 10,
  },
  discardControl: {
    paddingVertical: 12,
    paddingHorizontal: 16,
  },
  discardControlText: {
    fontSize: 14,
    color: '#8a8a8a',
    fontWeight: '600',
  },
  controlButton: {
    width: 80,
    height: 80,
    borderRadius: 40,
    justifyContent: 'center',
    alignItems: 'center',
  },
  pauseButton: {
    backgroundColor: '#333',
  },
  resumeButton: {
    backgroundColor: '#c4a035',
  },
  controlButtonText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#e5e5e5',
  },
  stopButton: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#ef4444',
    justifyContent: 'center',
    alignItems: 'center',
  },
  stopButtonText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#fff',
  },

  // Saving
  savingContainer: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  savingCard: {
    padding: 18,
    alignItems: 'stretch',
  },
  savingText: {
    fontSize: 22,
    fontWeight: '700',
    color: '#ededed',
    marginTop: 16,
    marginBottom: 18,
    textAlign: 'center',
  },
});
