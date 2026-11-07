/**
 * Ride Recovery Modal
 *
 * Shown on app launch when an interrupted ride is detected in SQLite.
 * Options: Save & Upload / Resume / Discard
 *
 * "Resume" is only shown if the ride was interrupted less than 30 minutes ago.
 * Per GPS_INTEGRITY spec Section 3.4.
 */

import React, { useState } from 'react';
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Alert,
} from 'react-native';

export interface InterruptedRide {
  id: string;
  startedAt: number;
  durationMs: number;
  distanceM: number;
  elevationGainM: number;
  sampleCount: number;
  status: 'recording' | 'paused';
}

interface RideRecoveryModalProps {
  ride: InterruptedRide;
  onSaveAndUpload: (rideId: string) => void;
  onResume?: (rideId: string) => void;
  onDiscard: (rideId: string) => void;
}

const MAX_RESUME_GAP_MS = 30 * 60 * 1000; // 30 minutes (used when onResume is provided)

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

function formatDistance(meters: number): string {
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(1)} km`;
  }
  return `${Math.round(meters)} m`;
}

function formatDate(timestamp: number): string {
  const date = new Date(timestamp);
  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export default function RideRecoveryModal({
  ride,
  onSaveAndUpload,
  onResume,
  onDiscard,
}: RideRecoveryModalProps) {
  const [visible, setVisible] = useState(true);

  const timeSinceRide = Date.now() - (ride.startedAt + ride.durationMs);
  const canResume = onResume != null && timeSinceRide < MAX_RESUME_GAP_MS;

  const handleSave = () => {
    setVisible(false);
    onSaveAndUpload(ride.id);
  };

  const handleResume = () => {
    if (!onResume) return;
    setVisible(false);
    onResume(ride.id);
  };

  const handleDiscard = () => {
    Alert.alert(
      'Discard Ride?',
      'This will permanently delete your ride data.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Discard',
          style: 'destructive',
          onPress: () => {
            setVisible(false);
            onDiscard(ride.id);
          },
        },
      ],
    );
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      statusBarTranslucent
    >
      <View style={styles.overlay}>
        <View style={styles.modal}>
          <Text style={styles.title}>Unfinished Ride Found</Text>
          <Text style={styles.subtitle}>
            You have an unfinished ride from{'\n'}
            {formatDate(ride.startedAt)}
          </Text>

          <View style={styles.statsRow}>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{formatDuration(ride.durationMs)}</Text>
              <Text style={styles.statLabel}>Duration</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{formatDistance(ride.distanceM)}</Text>
              <Text style={styles.statLabel}>Distance</Text>
            </View>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{Math.round(ride.elevationGainM)} m</Text>
              <Text style={styles.statLabel}>Elevation</Text>
            </View>
          </View>

          <TouchableOpacity style={styles.primaryButton} onPress={handleSave}>
            <Text style={styles.primaryButtonText}>Save & Upload</Text>
          </TouchableOpacity>

          {canResume && (
            <TouchableOpacity style={styles.secondaryButton} onPress={handleResume}>
              <Text style={styles.secondaryButtonText}>Resume Ride</Text>
            </TouchableOpacity>
          )}

          <TouchableOpacity style={styles.discardButton} onPress={handleDiscard}>
            <Text style={styles.discardButtonText}>Discard</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  modal: {
    backgroundColor: '#1a1a1a',
    borderRadius: 16,
    padding: 24,
    width: '100%',
    maxWidth: 360,
    alignItems: 'center',
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: '#e5e5e5',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    color: '#888',
    textAlign: 'center',
    marginBottom: 20,
    lineHeight: 20,
  },
  statsRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    width: '100%',
    marginBottom: 24,
    paddingHorizontal: 8,
  },
  stat: {
    alignItems: 'center',
  },
  statValue: {
    fontSize: 18,
    fontWeight: '600',
    color: '#e5e5e5',
    marginBottom: 2,
  },
  statLabel: {
    fontSize: 11,
    color: '#666',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  primaryButton: {
    backgroundColor: '#c4a035',
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 32,
    width: '100%',
    alignItems: 'center',
    marginBottom: 10,
  },
  primaryButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#0a0a0a',
  },
  secondaryButton: {
    backgroundColor: '#222',
    borderRadius: 8,
    paddingVertical: 14,
    paddingHorizontal: 32,
    width: '100%',
    alignItems: 'center',
    marginBottom: 10,
  },
  secondaryButtonText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#e5e5e5',
  },
  discardButton: {
    paddingVertical: 12,
    width: '100%',
    alignItems: 'center',
  },
  discardButtonText: {
    fontSize: 14,
    color: '#666',
  },
});
