import * as Sentry from '@sentry/react-native';

import { SENTRY_DSN } from '../constants/config';

export function initSentry() {
  Sentry.init({
    dsn: SENTRY_DSN,
    enabled: SENTRY_DSN !== '',
    tracesSampleRate: __DEV__ ? 1.0 : 0.2,
    debug: __DEV__,
  });
}
