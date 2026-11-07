/**
 * BoulderRoller Mobile -- Error Classification
 *
 * Every error falls into one of four categories. This classification
 * determines what the user sees and what the system does.
 *
 * TRANSIENT   -- Auto-retry with backoff. Toast/banner: "Connection issue, retrying..."
 * RECOVERABLE -- Inline error state with "Retry" button. No auto-retry.
 * AUTH        -- Clear tokens, navigate to auth root.
 * FATAL       -- Full-screen error boundary. Report to Sentry as exception.
 */

export type ErrorClassification = 'TRANSIENT' | 'RECOVERABLE' | 'AUTH' | 'FATAL';

export interface ClassifiedError {
  classification: ErrorClassification;
  message: string;
  retryable: boolean;
  originalError: unknown;
}

/**
 * Classify an error into one of the four categories.
 *
 * @param error - The error to classify. May be an ApiError, a native Error, or unknown.
 * @returns A ClassifiedError with a user-facing message and retry guidance.
 */
export function classifyError(error: unknown): ClassifiedError {
  // Import-free check for ApiError shape to avoid circular deps
  if (isApiErrorShape(error)) {
    switch (error.type) {
      case 'session_expired':
        return {
          classification: 'AUTH',
          message: 'Your session has expired. Please sign in again.',
          retryable: false,
          originalError: error,
        };

      case 'auth_rejected':
        // Credentials were wrong (e.g. invalid invite code, bad signature).
        // Not transient — retrying with the same credentials won't help.
        return {
          classification: 'AUTH',
          message: 'Authentication failed. Please try signing in again.',
          retryable: false,
          originalError: error,
        };

      case 'network_error':
        return {
          classification: 'TRANSIENT',
          message: 'Connection issue. Retrying...',
          retryable: true,
          originalError: error,
        };

      case 'server_error':
        return {
          classification: 'TRANSIENT',
          message: 'Service temporarily unavailable. Please try again.',
          retryable: true,
          originalError: error,
        };

      default:
        return {
          classification: 'RECOVERABLE',
          message: 'Something went wrong. Please try again.',
          retryable: true,
          originalError: error,
        };
    }
  }

  // Native TypeError / RangeError etc. in rendering = FATAL
  if (error instanceof TypeError || error instanceof RangeError) {
    return {
      classification: 'FATAL',
      message: 'The app encountered an unexpected error.',
      retryable: false,
      originalError: error,
    };
  }

  // Generic Error
  if (error instanceof Error) {
    // Network-related errors (fetch failures)
    if (
      error.message.includes('Network request failed') ||
      error.message.includes('Failed to fetch') ||
      error.message.includes('timeout')
    ) {
      return {
        classification: 'TRANSIENT',
        message: 'Connection issue. Retrying...',
        retryable: true,
        originalError: error,
      };
    }

    return {
      classification: 'RECOVERABLE',
      message: error.message || 'Something went wrong.',
      retryable: true,
      originalError: error,
    };
  }

  // Unknown error shape
  return {
    classification: 'FATAL',
    message: 'An unexpected error occurred.',
    retryable: false,
    originalError: error,
  };
}

/**
 * Type guard: checks if the value looks like an ApiError
 * (has type and retryable fields) without importing ApiError directly.
 */
function isApiErrorShape(
  error: unknown,
): error is { type: string; retryable: boolean; statusCode?: number; message: string } {
  return (
    error !== null &&
    typeof error === 'object' &&
    'type' in error &&
    'retryable' in error &&
    typeof (error as Record<string, unknown>).type === 'string'
  );
}

/**
 * Returns a user-friendly error message for display in banners/toasts.
 * Strips technical details and stack traces.
 */
export function getUserMessage(error: unknown): string {
  return classifyError(error).message;
}

/**
 * Checks if an error is retryable.
 */
export function isRetryable(error: unknown): boolean {
  return classifyError(error).retryable;
}
