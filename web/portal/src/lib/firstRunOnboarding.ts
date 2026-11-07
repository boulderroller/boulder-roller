const FIRST_RIDE_PENDING_KEY = 'br_first_ride_pending';

interface FirstRidePendingState {
  userId: string;
}

function readPendingState(): FirstRidePendingState | null {
  try {
    const raw = window.localStorage.getItem(FIRST_RIDE_PENDING_KEY);
    if (!raw) return null;

    const state = JSON.parse(raw) as Partial<FirstRidePendingState>;
    if (typeof state.userId !== 'string' || !state.userId) {
      window.localStorage.removeItem(FIRST_RIDE_PENDING_KEY);
      return null;
    }

    return { userId: state.userId };
  } catch {
    return null;
  }
}

export function hasFirstRidePending(userId: string | null | undefined) {
  if (!userId || typeof window === 'undefined') return false;
  return readPendingState()?.userId === userId;
}

export function markFirstRidePending(userId: string) {
  if (!userId || typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(FIRST_RIDE_PENDING_KEY, JSON.stringify({ userId }));
  } catch {
    // The current onboarding screen still carries the step if storage is unavailable.
  }
}

export function clearFirstRidePending(userId: string | null | undefined) {
  if (!userId || typeof window === 'undefined') return;
  if (readPendingState()?.userId !== userId) return;

  try {
    window.localStorage.removeItem(FIRST_RIDE_PENDING_KEY);
  } catch {
    // No persistent marker is available to clear.
  }
}
