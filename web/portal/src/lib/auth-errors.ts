/**
 * Maps backend error codes/messages to user-friendly messages with actionable guidance
 */

interface AuthErrorInfo {
  message: string;
  action?: string;
}

function extractAuthErrorCode(error: unknown): string | null {
  if (!error || typeof error !== 'object') {
    return null;
  }

  const withDetail = error as { detail?: unknown };
  if (withDetail.detail && typeof withDetail.detail === 'object') {
    const detail = withDetail.detail as Record<string, unknown>;
    if (typeof detail.code === 'string' && detail.code.trim()) {
      return detail.code;
    }

    const nested = detail.error;
    if (nested && typeof nested === 'object') {
      const nestedRecord = nested as Record<string, unknown>;
      if (typeof nestedRecord.code === 'string' && nestedRecord.code.trim()) {
        return nestedRecord.code;
      }
    }
  }

  // Privy SDK errors (PrivyApiError) carry the code at the top level.
  const withCode = error as { code?: unknown; privyErrorCode?: unknown };
  if (typeof withCode.code === 'string' && withCode.code.trim()) {
    return withCode.code;
  }
  if (typeof withCode.privyErrorCode === 'string' && withCode.privyErrorCode.trim()) {
    return withCode.privyErrorCode;
  }

  return null;
}

/**
 * True when the login provider refused to create an account for this
 * email (signup disabled without an invite). The rider needs the invite
 * path, not another code.
 */
export function isSignupRefusedError(error: unknown): boolean {
  return extractAuthErrorCode(error) === 'allowlist_rejected';
}

// Backend error codes and their friendly messages
const ERROR_MAP: Record<string, AuthErrorInfo> = {
  // Nonce errors
  nonce_not_found: {
    message: 'Your session expired.',
    action: 'Please try signing in again.',
  },
  nonce_wallet_mismatch: {
    message: 'Wallet mismatch detected.',
    action: 'Please use the same wallet you started with.',
  },
  device_mismatch: {
    message: 'Device mismatch detected.',
    action: 'Please try signing in again from this device.',
  },
  nonce_used: {
    message: 'This sign-in request was already used.',
    action: 'Please try signing in again.',
  },
  nonce_expired: {
    message: 'Your sign-in request expired.',
    action: 'Please try again - requests are valid for 5 minutes.',
  },

  // Invite code errors
  invite_required: {
    message: 'An invite code is required.',
    action: 'Please enter your invite code to continue.',
  },
  invite_invalid: {
    message: 'This invite code is not valid.',
    action: 'Please check your code and try again.',
  },
  invite_expired: {
    message: 'This invite code has expired.',
    action: 'Please request a new invite code.',
  },
  invite_used: {
    message: 'This invite code has already been used.',
    action: 'Each code can only be used once.',
  },

  // Privy-side errors (raised by the login provider before our backend is reached)
  allowlist_rejected: {
    message: 'Invite required to continue.',
    action: 'Enter your invite code.',
  },
  invalid_credentials: {
    message: "That code didn't match.",
    action: 'Use the code from the newest email, or send a fresh one.',
  },
  email_lookup_unavailable: {
    message: 'Could not check this email.',
    action: 'Please try again.',
  },

  // Privy errors
  privy_disabled: {
    message: 'Email login is temporarily unavailable.',
    action: 'Please try connecting with a wallet instead.',
  },
  privy_invalid: {
    message: 'Email login verification failed.',
    action: 'Please try signing in again.',
  },
  privy_no_wallet: {
    message: 'Could not create your wallet.',
    action: 'Please try again or use a different login method.',
  },
  privy_wallet_mismatch: {
    message: 'Wallet address mismatch.',
    action: 'Please try signing in again.',
  },

  // Signature errors
  signature_invalid: {
    message: 'Wallet signature verification failed.',
    action: 'Please ensure you approved the correct message in your wallet.',
  },

  // Generic errors
  session_expired: {
    message: 'Your session has expired.',
    action: 'Please sign in again to continue.',
  },
  unauthorized: {
    message: 'You are not authorized.',
    action: 'Please sign in to continue.',
  },
  network_error: {
    message: 'Unable to connect to the server.',
    action: 'Please check your internet connection and try again.',
  },
};

/**
 * Parses an error and returns a user-friendly message
 */
export function getAuthErrorMessage(error: unknown): AuthErrorInfo {
  const backendCode = extractAuthErrorCode(error);
  if (backendCode && ERROR_MAP[backendCode]) {
    return ERROR_MAP[backendCode];
  }

  // Handle Error objects
  if (error instanceof Error) {
    const errorText = error.message.toLowerCase();

    // Check for known error codes in the message
    for (const [code, info] of Object.entries(ERROR_MAP)) {
      if (errorText.includes(code.replace(/_/g, ' ')) || errorText.includes(code)) {
        return info;
      }
    }

    // Check for network errors
    if (errorText.includes('fetch') || errorText.includes('network') || errorText.includes('failed to fetch')) {
      return ERROR_MAP.network_error;
    }

    // Check for unauthorized
    if (errorText.includes('unauthorized') || errorText.includes('401')) {
      return ERROR_MAP.unauthorized;
    }

    // Check for invite-related errors
    if (errorText.includes('invite')) {
      if (errorText.includes('invalid') || errorText.includes('not found')) {
        return ERROR_MAP.invite_invalid;
      }
      if (errorText.includes('expired')) {
        return ERROR_MAP.invite_expired;
      }
      if (errorText.includes('used') || errorText.includes('redeemed')) {
        return ERROR_MAP.invite_used;
      }
      return ERROR_MAP.invite_required;
    }

    // Check for signature errors
    if (errorText.includes('signature')) {
      return ERROR_MAP.signature_invalid;
    }

    // Check for nonce errors
    if (errorText.includes('nonce')) {
      if (errorText.includes('expired')) {
        return ERROR_MAP.nonce_expired;
      }
      return ERROR_MAP.nonce_not_found;
    }
  }

  // Default fallback
  return {
    message: 'Something went wrong.',
    action: 'Please try again. If the problem persists, contact support.',
  };
}

/**
 * Formats error info into a single string for display
 */
export function formatAuthError(error: unknown): string {
  const info = getAuthErrorMessage(error);
  return info.action ? `${info.message} ${info.action}` : info.message;
}
