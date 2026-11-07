/**
 * Recording State Store (Zustand)
 *
 * State machine for ride recording lifecycle:
 *   idle -> recording -> paused -> stopping -> saving -> idle
 *
 * This store holds the live UI state during a ride. SQLite is the
 * source of truth for persistence; this store is the reactive layer
 * for screen rendering.
 *
 * Per MOBILE_PHASE0_RESOLUTIONS.md: recordingStore state machine spec.
 */

import { create } from 'zustand';

const MAX_LIVE_ROUTE_POINTS = 5000;

export type RecordingStatus =
  | 'idle'
  | 'recording'
  | 'paused'
  | 'stopping'
  | 'saving';

export interface LiveRoutePoint {
  latitude: number;
  longitude: number;
}

export interface LiveStats {
  elapsedMs: number;
  distanceM: number;
  elevationGainM: number;
  currentSpeedMps: number;
  maxSpeedMps: number;
  sampleCount: number;
  currentLocation: LiveRoutePoint | null;
  routePoint: LiveRoutePoint;
}

interface RecordingState {
  // Status
  status: RecordingStatus;

  // Current ride metadata
  rideId: string | null;
  startedAt: number | null;      // wallclock epoch ms
  elapsedMs: number;             // monotonic elapsed (excludes pauses)
  distanceM: number;             // cumulative haversine distance
  elevationGainM: number;        // cumulative positive elevation
  currentSpeedMps: number;       // latest GPS speed
  maxSpeedMps: number;           // peak speed
  sampleCount: number;           // accepted GPS samples
  currentLocation: LiveRoutePoint | null;
  routePoints: LiveRoutePoint[];  // accepted GPS samples for live map trace
  rejectedSamples: Record<string, number>;

  // GPS buffer state
  bufferSize: number;            // samples in current buffer (0-10)

  // Actions
  startRide: (rideId: string) => void;
  pauseRide: () => void;
  resumeRide: () => void;
  stopRide: () => void;
  setSaving: () => void;
  updateLiveStats: (stats: Partial<LiveStats>) => void;
  incrementRejection: (reason: string) => void;
  incrementBuffer: () => void;
  resetBuffer: () => void;
  reset: () => void;
}

const initialState = {
  status: 'idle' as RecordingStatus,
  rideId: null as string | null,
  startedAt: null as number | null,
  elapsedMs: 0,
  distanceM: 0,
  elevationGainM: 0,
  currentSpeedMps: 0,
  maxSpeedMps: 0,
  sampleCount: 0,
  currentLocation: null as LiveRoutePoint | null,
  routePoints: [] as LiveRoutePoint[],
  rejectedSamples: {} as Record<string, number>,
  bufferSize: 0,
};

export const useRecordingStore = create<RecordingState>((set) => ({
  ...initialState,

  startRide: (rideId: string) =>
    set({
      status: 'recording',
      rideId,
      startedAt: Date.now(),
      elapsedMs: 0,
      distanceM: 0,
      elevationGainM: 0,
      currentSpeedMps: 0,
      maxSpeedMps: 0,
      sampleCount: 0,
      currentLocation: null,
      routePoints: [],
      rejectedSamples: {},
      bufferSize: 0,
    }),

  pauseRide: () =>
    set((state) => {
      if (state.status !== 'recording') return state;
      return { ...state, status: 'paused' };
    }),

  resumeRide: () =>
    set((state) => {
      if (state.status !== 'paused') return state;
      return { ...state, status: 'recording' };
    }),

  stopRide: () =>
    set((state) => {
      if (state.status !== 'recording' && state.status !== 'paused') return state;
      return { ...state, status: 'stopping' };
    }),

  setSaving: () =>
    set((state) => {
      if (state.status !== 'stopping') return state;
      return { ...state, status: 'saving' };
    }),

  updateLiveStats: (stats: Partial<LiveStats>) =>
    set((state) => ({
      ...state,
      ...(stats.elapsedMs !== undefined && { elapsedMs: stats.elapsedMs }),
      ...(stats.distanceM !== undefined && { distanceM: stats.distanceM }),
      ...(stats.elevationGainM !== undefined && { elevationGainM: stats.elevationGainM }),
      ...(stats.currentSpeedMps !== undefined && { currentSpeedMps: stats.currentSpeedMps }),
      ...(stats.maxSpeedMps !== undefined && {
        maxSpeedMps: Math.max(state.maxSpeedMps, stats.maxSpeedMps),
      }),
      ...(stats.sampleCount !== undefined && { sampleCount: stats.sampleCount }),
      ...(stats.currentLocation !== undefined && { currentLocation: stats.currentLocation }),
      ...(stats.routePoint !== undefined && {
        routePoints: [...state.routePoints, stats.routePoint].slice(-MAX_LIVE_ROUTE_POINTS),
      }),
    })),

  incrementRejection: (reason: string) =>
    set((state) => ({
      ...state,
      rejectedSamples: {
        ...state.rejectedSamples,
        [reason]: (state.rejectedSamples[reason] ?? 0) + 1,
      },
    })),

  incrementBuffer: () =>
    set((state) => ({ ...state, bufferSize: state.bufferSize + 1 })),

  resetBuffer: () =>
    set((state) => ({ ...state, bufferSize: 0 })),

  reset: () => set(initialState),
}));
