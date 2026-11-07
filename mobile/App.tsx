/**
 * BoulderRoller Mobile -- App Entry Point
 *
 * Provider hierarchy (outer to inner):
 *   0. Sentry.wrap(App) -- performance monitoring + crash capture
 *   1. SafeAreaProvider -- device inset measurements
 *   2. ErrorBoundary -- catches any React render error below it
 *   3. QueryClientProvider -- TanStack Query cache + client
 *   4. PrivyProvider -- Privy SDK initialization
 *   5. PrivyAuthBridge -- syncs Privy auth to backend JWT to Zustand
 *   6. AuthInitializer -- hydrates Zustand from SecureStore, starts refresh timer
 *   7. NavigationContainer -- React Navigation root
 *   8. RootNavigator -- reads useAuthStore to render AuthStack or TabNavigator
 */

import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { QueryClientProvider } from '@tanstack/react-query';
import { PrivyProvider } from '@privy-io/expo';
import * as Sentry from '@sentry/react-native';

import { queryClient } from './src/lib/queryClient';
import { PRIVY_APP_ID, PRIVY_CLIENT_ID } from './src/constants/config';
import { ErrorBoundary } from './src/components/ErrorBoundary';
import PrivyAuthBridge from './src/components/PrivyAuthBridge';
import AuthInitializer from './src/components/AuthInitializer';
import RootNavigator from './src/navigation/RootNavigator';
import { linking } from './src/navigation/linking';
import { initSentry } from './src/lib/sentry';
import { mobileColors } from './src/theme/tokens';

// Initialize Sentry before any React rendering
initSentry();

// Diagnostic: verify config is threaded through at runtime
if (__DEV__) {
  console.warn('[boot] PRIVY_APP_ID=', PRIVY_APP_ID, 'PRIVY_CLIENT_ID=', PRIVY_CLIENT_ID);
}

// Ensure auth service module executes to wire refresh handlers
import './src/services/authService';

const navigationTheme = {
  dark: false,
  colors: {
    primary: mobileColors.accent,
    background: mobileColors.canvas,
    card: mobileColors.surfaceStrong,
    text: mobileColors.text,
    border: mobileColors.border,
    notification: mobileColors.accent,
  },
  fonts: {
    regular: { fontFamily: 'System', fontWeight: '400' as const },
    medium: { fontFamily: 'System', fontWeight: '500' as const },
    bold: { fontFamily: 'System', fontWeight: '700' as const },
    heavy: { fontFamily: 'System', fontWeight: '900' as const },
  },
};

// Privy mobile SDK config — loginMethods and embeddedWallets.createOnLogin
// are configured in the Privy dashboard, not in the SDK config.
// The mobile SDK config only supports customAuth, mfa, and embedded options.
const privyConfig = {};

function App() {
  return (
    <SafeAreaProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <PrivyProvider appId={PRIVY_APP_ID} clientId={PRIVY_CLIENT_ID} config={privyConfig}>
            <PrivyAuthBridge>
              <AuthInitializer>
                <NavigationContainer theme={navigationTheme} linking={linking}>
                  <StatusBar style="light" />
                  <RootNavigator />
                </NavigationContainer>
              </AuthInitializer>
            </PrivyAuthBridge>
          </PrivyProvider>
        </QueryClientProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}

export default Sentry.wrap(App);
