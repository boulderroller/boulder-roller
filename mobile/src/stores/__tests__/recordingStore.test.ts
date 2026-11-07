/**
 * Recording Store Tests
 *
 * Tests the state machine transitions:
 *   idle -> recording -> paused -> stopping -> saving -> idle
 *
 * Also tests guard conditions (invalid transitions are no-ops).
 */

import { useRecordingStore } from '../recordingStore';

describe('recordingStore', () => {
  beforeEach(() => {
    useRecordingStore.getState().reset();
  });

  describe('initial state', () => {
    test('starts in idle status', () => {
      const state = useRecordingStore.getState();
      expect(state.status).toBe('idle');
      expect(state.rideId).toBeNull();
      expect(state.startedAt).toBeNull();
      expect(state.elapsedMs).toBe(0);
      expect(state.distanceM).toBe(0);
      expect(state.elevationGainM).toBe(0);
      expect(state.currentSpeedMps).toBe(0);
      expect(state.maxSpeedMps).toBe(0);
      expect(state.sampleCount).toBe(0);
      expect(state.currentLocation).toBeNull();
      expect(state.routePoints).toEqual([]);
      expect(state.bufferSize).toBe(0);
    });
  });

  describe('startRide', () => {
    test('transitions from idle to recording', () => {
      useRecordingStore.getState().startRide('ride-123');
      const state = useRecordingStore.getState();
      expect(state.status).toBe('recording');
      expect(state.rideId).toBe('ride-123');
      expect(state.startedAt).toBeGreaterThan(0);
      expect(state.elapsedMs).toBe(0);
      expect(state.distanceM).toBe(0);
    });

    test('resets all stats when starting a new ride', () => {
      // Set some stats first
      useRecordingStore.getState().startRide('old-ride');
      useRecordingStore.getState().updateLiveStats({
        distanceM: 5000,
        elevationGainM: 100,
        sampleCount: 50,
        currentLocation: { latitude: 40, longitude: -75 },
        routePoint: { latitude: 40, longitude: -75 },
      });

      // Start new ride — should reset
      useRecordingStore.getState().startRide('new-ride');
      const state = useRecordingStore.getState();
      expect(state.rideId).toBe('new-ride');
      expect(state.distanceM).toBe(0);
      expect(state.elevationGainM).toBe(0);
      expect(state.sampleCount).toBe(0);
      expect(state.currentLocation).toBeNull();
      expect(state.routePoints).toEqual([]);
    });
  });

  describe('pauseRide', () => {
    test('transitions from recording to paused', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().pauseRide();
      expect(useRecordingStore.getState().status).toBe('paused');
    });

    test('is a no-op when idle', () => {
      useRecordingStore.getState().pauseRide();
      expect(useRecordingStore.getState().status).toBe('idle');
    });

    test('is a no-op when already paused', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().pauseRide();
      useRecordingStore.getState().pauseRide(); // second pause
      expect(useRecordingStore.getState().status).toBe('paused');
    });
  });

  describe('resumeRide', () => {
    test('transitions from paused to recording', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().pauseRide();
      useRecordingStore.getState().resumeRide();
      expect(useRecordingStore.getState().status).toBe('recording');
    });

    test('is a no-op when recording', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().resumeRide();
      expect(useRecordingStore.getState().status).toBe('recording');
    });

    test('is a no-op when idle', () => {
      useRecordingStore.getState().resumeRide();
      expect(useRecordingStore.getState().status).toBe('idle');
    });
  });

  describe('stopRide', () => {
    test('transitions from recording to stopping', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().stopRide();
      expect(useRecordingStore.getState().status).toBe('stopping');
    });

    test('transitions from paused to stopping', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().pauseRide();
      useRecordingStore.getState().stopRide();
      expect(useRecordingStore.getState().status).toBe('stopping');
    });

    test('is a no-op when idle', () => {
      useRecordingStore.getState().stopRide();
      expect(useRecordingStore.getState().status).toBe('idle');
    });

    test('is a no-op when already stopping', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().stopRide();
      useRecordingStore.getState().stopRide();
      expect(useRecordingStore.getState().status).toBe('stopping');
    });
  });

  describe('setSaving', () => {
    test('transitions from stopping to saving', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().stopRide();
      useRecordingStore.getState().setSaving();
      expect(useRecordingStore.getState().status).toBe('saving');
    });

    test('is a no-op when recording', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().setSaving();
      expect(useRecordingStore.getState().status).toBe('recording');
    });
  });

  describe('reset', () => {
    test('returns to idle with all values cleared', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().updateLiveStats({
        distanceM: 5000,
        elevationGainM: 200,
        sampleCount: 100,
        currentLocation: { latitude: 40, longitude: -75 },
        routePoint: { latitude: 40, longitude: -75 },
      });
      useRecordingStore.getState().reset();

      const state = useRecordingStore.getState();
      expect(state.status).toBe('idle');
      expect(state.rideId).toBeNull();
      expect(state.startedAt).toBeNull();
      expect(state.distanceM).toBe(0);
      expect(state.sampleCount).toBe(0);
      expect(state.currentLocation).toBeNull();
      expect(state.routePoints).toEqual([]);
    });
  });

  describe('updateLiveStats', () => {
    test('updates individual stats', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().updateLiveStats({ distanceM: 1000 });
      expect(useRecordingStore.getState().distanceM).toBe(1000);
      expect(useRecordingStore.getState().elevationGainM).toBe(0);
    });

    test('updates multiple stats at once', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().updateLiveStats({
        distanceM: 5000,
        elevationGainM: 150,
        currentSpeedMps: 8.5,
        sampleCount: 50,
        currentLocation: { latitude: 40, longitude: -75 },
        routePoint: { latitude: 40, longitude: -75 },
      });
      const state = useRecordingStore.getState();
      expect(state.distanceM).toBe(5000);
      expect(state.elevationGainM).toBe(150);
      expect(state.currentSpeedMps).toBe(8.5);
      expect(state.sampleCount).toBe(50);
      expect(state.currentLocation).toEqual({ latitude: 40, longitude: -75 });
      expect(state.routePoints).toEqual([{ latitude: 40, longitude: -75 }]);
    });

    test('maxSpeed is always the maximum seen', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().updateLiveStats({ maxSpeedMps: 10 });
      useRecordingStore.getState().updateLiveStats({ maxSpeedMps: 5 });
      expect(useRecordingStore.getState().maxSpeedMps).toBe(10);
      useRecordingStore.getState().updateLiveStats({ maxSpeedMps: 15 });
      expect(useRecordingStore.getState().maxSpeedMps).toBe(15);
    });

    test('appends live route points', () => {
      useRecordingStore.getState().startRide('ride-123');
      useRecordingStore.getState().updateLiveStats({
        currentLocation: { latitude: 40, longitude: -75 },
        routePoint: { latitude: 40, longitude: -75 },
      });
      useRecordingStore.getState().updateLiveStats({
        currentLocation: { latitude: 40.001, longitude: -75.001 },
        routePoint: { latitude: 40.001, longitude: -75.001 },
      });

      expect(useRecordingStore.getState().currentLocation).toEqual({
        latitude: 40.001,
        longitude: -75.001,
      });
      expect(useRecordingStore.getState().routePoints).toEqual([
        { latitude: 40, longitude: -75 },
        { latitude: 40.001, longitude: -75.001 },
      ]);
    });
  });

  describe('buffer management', () => {
    test('incrementBuffer increases bufferSize', () => {
      useRecordingStore.getState().incrementBuffer();
      useRecordingStore.getState().incrementBuffer();
      expect(useRecordingStore.getState().bufferSize).toBe(2);
    });

    test('resetBuffer sets bufferSize to 0', () => {
      useRecordingStore.getState().incrementBuffer();
      useRecordingStore.getState().incrementBuffer();
      useRecordingStore.getState().resetBuffer();
      expect(useRecordingStore.getState().bufferSize).toBe(0);
    });
  });

  describe('rejection tracking', () => {
    test('incrementRejection tracks by reason', () => {
      useRecordingStore.getState().incrementRejection('null_island');
      useRecordingStore.getState().incrementRejection('null_island');
      useRecordingStore.getState().incrementRejection('low_accuracy');
      const state = useRecordingStore.getState();
      expect(state.rejectedSamples['null_island']).toBe(2);
      expect(state.rejectedSamples['low_accuracy']).toBe(1);
    });
  });

  describe('full lifecycle', () => {
    test('idle -> recording -> paused -> recording -> stopping -> saving -> idle', () => {
      const { getState } = useRecordingStore;

      expect(getState().status).toBe('idle');

      getState().startRide('ride-full');
      expect(getState().status).toBe('recording');

      getState().pauseRide();
      expect(getState().status).toBe('paused');

      getState().resumeRide();
      expect(getState().status).toBe('recording');

      getState().stopRide();
      expect(getState().status).toBe('stopping');

      getState().setSaving();
      expect(getState().status).toBe('saving');

      getState().reset();
      expect(getState().status).toBe('idle');
      expect(getState().rideId).toBeNull();
    });
  });
});
