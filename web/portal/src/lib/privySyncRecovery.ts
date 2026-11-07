import { ApiError } from './api';
import { formatAuthError } from './auth-errors';

export type PrivySyncRecovery = 'invite_required' | 'invite_invalid' | null;

export interface PrivySyncFailureState {
  message: string;
  recovery: PrivySyncRecovery;
  clearInvite: boolean;
  shouldLogout: boolean;
}

export function getAuthErrorCode(error: unknown): string | null {
  if (error instanceof ApiError && error.detail) {
    const nested = error.detail.error;
    if (nested && typeof nested === 'object') {
      const code = (nested as Record<string, unknown>).code;
      if (typeof code === 'string') return code;
    }

    const code = error.detail.code;
    if (typeof code === 'string') return code;
  }

  if (error instanceof Error) {
    const message = error.message;
    for (const code of ['invite_required', 'invite_invalid', 'invite_expired', 'invite_used']) {
      if (message.includes(code)) return code;
    }
  }

  return null;
}

export function getPrivySyncFailureState(error: unknown): PrivySyncFailureState {
  const code = getAuthErrorCode(error);

  if (code === 'invite_required') {
    return {
      message: 'Invite required.',
      recovery: 'invite_required',
      clearInvite: false,
      shouldLogout: false,
    };
  }

  if (code === 'invite_invalid' || code === 'invite_expired' || code === 'invite_used') {
    return {
      message: 'That invite is not active.',
      recovery: 'invite_invalid',
      clearInvite: true,
      shouldLogout: false,
    };
  }

  if (error instanceof ApiError && error.retryable) {
    return {
      message: 'Connection issue. Try again.',
      recovery: null,
      clearInvite: false,
      shouldLogout: false,
    };
  }

  const message = formatAuthError(error);

  return {
    message: message === 'Something went wrong. Please try again. If the problem persists, contact support.'
      ? "Couldn't finish sign-in."
      : message,
    recovery: null,
    clearInvite: false,
    shouldLogout: true,
  };
}
