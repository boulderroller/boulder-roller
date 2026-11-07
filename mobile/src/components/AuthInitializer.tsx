/**
 * AuthInitializer Component
 *
 * On mount, hydrates the Zustand auth store from SecureStore and starts
 * the proactive refresh timer. Shows a loading screen until initialization
 * is complete.
 *
 * Also:
 * - Checks for interrupted rides (crash recovery) on startup
 * - Resets failed_auth uploads after successful re-login
 * - Starts the upload queue processor
 * - Listens to AppState changes for token refresh on foreground
 */

import React, { useEffect, useRef, useState } from 'react';
import { AppState, AppStateStatus, View, ActivityIndicator, StyleSheet } from 'react-native';

import { initializeAuth } from '../services/authService';
import { tokenRefreshManager } from '../services/tokenRefreshManager';
import {
  getCurrentLocalRideOwnerKey,
  localRideOwnerKeyForWallet,
  useAuthStore,
} from '../stores/authStore';
import { getDatabase, initDatabase } from '../services/database';
import { startQueueProcessor, retryAuthFailedUploads, processQueue } from '../services/uploadQueue';
import {
  detectInterruptedRide,
  saveInterruptedRide,
  discardInterruptedRide,
} from '../services/crashRecovery';
import { usePairingStore } from '../stores/pairingStore';
import { bleSensorManager } from '../services/sensors/ble/manager';
import RideRecoveryModal, { type InterruptedRide } from './RideRecoveryModal';
import { mobileColors } from '../theme/tokens';
import { suspendRecordingForAccountBoundary } from '../services/gpsRecording';

interface AuthInitializerProps {
  children: React.ReactNode;
}

const STARTUP_TIMEOUT_MS = 12_000;

function withStartupTimeout<T>(promise: Promise<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error(`Startup timed out after ${STARTUP_TIMEOUT_MS}ms`));
    }, STARTUP_TIMEOUT_MS);

    promise
      .then(resolve, reject)
      .finally(() => clearTimeout(timeout));
  });
}

export default function AuthInitializer({ children }: AuthInitializerProps) {
  const [initialized, setInitialized] = useState(false);
  const [interruptedRide, setInterruptedRide] = useState<InterruptedRide | null>(null);
  const [interruptedRideOwnerKey, setInterruptedRideOwnerKey] = useState<string | null>(null);
  const startupCompleteRef = useRef(false);
  const renderedOwnerKey = useAuthStore((state) =>
    state.status === 'authenticated' || state.status === 'refreshing'
      ? localRideOwnerKeyForWallet(state.wallet)
      : null,
  );

  useEffect(() => {
    let cancelled = false;

    const init = async () => {
      // Open the encrypted SQLite singleton FIRST. Every other init step
      // below (crash recovery check, upload queue, sensor reconnect) reads
      // or writes the DB. SQLCipher key fetch is async (expo-secure-store
      // has no sync API).
      await initDatabase();
      await initializeAuth();
      if (!cancelled) {
        checkForInterruptedRide();
      }
      startQueueProcessor();
      retryAuthFailedUploads();
      // Best-effort reconnect of sensors the user paired in a previous
      // session. Fires against any hardware that's in range and powered
      // on. Failures per-device are swallowed inside reconnectKnown.
      usePairingStore.getState().reconnectKnown().catch((err) => {
        console.warn('[AuthInitializer] Sensor reconnect error:', err);
      });
    };
    withStartupTimeout(init())
      .catch((err) => {
        console.warn('[AuthInitializer] Startup failed or timed out:', err);
        if (useAuthStore.getState().status === 'loading') {
          useAuthStore.getState().setUnauthenticated();
        }
      })
      .finally(() => {
        startupCompleteRef.current = true;
        if (!cancelled) {
          setInitialized(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Handle app coming to foreground — refresh timer may have been killed by OS
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState: AppStateStatus) => {
      if (nextState === 'active') {
        const { status, tokenExpiresAt } = useAuthStore.getState();
        if (status === 'authenticated' && tokenExpiresAt) {
          if (tokenRefreshManager.isRefreshDue()) {
            tokenRefreshManager.refresh();
          } else {
            tokenRefreshManager.schedule();
          }
        }
        // Process upload queue on foreground
        processQueue();
        // Audit BLE sources — iOS may have suspended notifications during
        // background. Sources that have gone silent get flipped to lost so
        // the UI stops claiming a green connection that no longer flows.
        bleSensorManager.auditStaleness();
      }
    });

    return () => subscription.remove();
  }, []);

  // Tear down sensor connections on logout so the next user (or the
  // same user re-authing) never inherits a live BLE session.
  useEffect(() => {
    let prev = useAuthStore.getState().status;
    let prevOwnerKey = getCurrentLocalRideOwnerKey();
    const unsubscribe = useAuthStore.subscribe((state) => {
      const leavingAuthedState = prev === 'authenticated' || prev === 'refreshing';
      const nextOwnerKey = getCurrentLocalRideOwnerKey();
      const ownerChanged = nextOwnerKey !== prevOwnerKey;
      if (ownerChanged) {
        // Never carry A's recovery summary through a logged-out frame or into
        // B's session. The render path also checks the captured owner key.
        setInterruptedRide(null);
        setInterruptedRideOwnerKey(null);

        const teardown = prevOwnerKey !== null
          ? suspendRecordingForAccountBoundary().catch((err) => {
              console.warn('[AuthInitializer] Recorder teardown on account change failed:', err);
            })
          : Promise.resolve();

        if (nextOwnerKey !== null && startupCompleteRef.current) {
          void teardown.then(() => {
            if (getCurrentLocalRideOwnerKey() === nextOwnerKey) {
              checkForInterruptedRide();
            }
          });
        }
      }
      if (leavingAuthedState && state.status === 'unauthenticated') {
        usePairingStore
          .getState()
          .disconnectAll()
          .catch((err) =>
            console.warn('[AuthInitializer] Sensor teardown on logout failed:', err),
          );
      }
      prev = state.status;
      prevOwnerKey = nextOwnerKey;
    });
    return unsubscribe;
  }, []);

  function checkForInterruptedRide(): void {
    try {
      const ownerKey = getCurrentLocalRideOwnerKey();
      if (!ownerKey) {
        setInterruptedRide(null);
        setInterruptedRideOwnerKey(null);
        return;
      }
      // detectInterruptedRide stamps had_crash_recovery=1 on the ride row
      // before returning. Without routing through this helper, the
      // breadcrumb column stays 0 and the recovery lineage is invisible.
      const recovered = detectInterruptedRide();
      if (!recovered) {
        setInterruptedRide(null);
        setInterruptedRideOwnerKey(null);
        return;
      }

      const db = getDatabase();
      const lastSample = db.getFirstSync<{ t_offset_ms: number }>(
        `SELECT MAX(g.t_offset_ms) as t_offset_ms
         FROM gps_samples g
         INNER JOIN rides r ON r.id = g.ride_id
         WHERE g.ride_id = ? AND r.owner_key = ?`,
        [recovered.id, ownerKey],
      );
      const durationMs =
        lastSample && lastSample.t_offset_ms > recovered.duration_ms
          ? lastSample.t_offset_ms
          : recovered.duration_ms;

      setInterruptedRide({
        id: recovered.id,
        startedAt: recovered.started_at,
        durationMs,
        distanceM: recovered.distance_m,
        elevationGainM: recovered.elevation_gain_m,
        sampleCount: recovered.sample_count,
        status: recovered.status as 'recording' | 'paused',
      });
      setInterruptedRideOwnerKey(ownerKey);
    } catch (err) {
      console.error('[AuthInitializer] Crash recovery check failed:', err);
    }
  }

  async function handleSaveAndUpload(rideId: string): Promise<void> {
    try {
      // saveInterruptedRide computes and stamps preliminary_ride_hash +
      // parser_version BEFORE enqueue, so recovered rides carry the same
      // device-side attestation stamping as cleanly-stopped rides.
      await saveInterruptedRide(rideId);
    } catch (err) {
      console.error('[AuthInitializer] Save & upload failed:', err);
    }
    setInterruptedRide(null);
    setInterruptedRideOwnerKey(null);
  }

  // Resume removed for v1 — complex to hydrate recording state from SQLite.
  // Save & Upload is safe and preserves all recorded data.

  function handleDiscard(rideId: string): void {
    try {
      discardInterruptedRide(rideId);
    } catch (err) {
      console.error('[AuthInitializer] Discard failed:', err);
    }
    setInterruptedRide(null);
    setInterruptedRideOwnerKey(null);
  }

  // Show loading screen until auth state is resolved
  if (!initialized) {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" color={mobileColors.accent} />
      </View>
    );
  }

  return (
    <>
      {interruptedRide && interruptedRideOwnerKey === renderedOwnerKey && (
        <RideRecoveryModal
          ride={interruptedRide}
          onSaveAndUpload={handleSaveAndUpload}
          onDiscard={handleDiscard}
        />
      )}
      {children}
    </>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    backgroundColor: mobileColors.canvas,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
