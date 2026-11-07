/**
 * BoulderRoller Mobile -- App Configuration
 *
 * Reads from Constants.expoConfig.extra for environment-specific values
 * (set via app.config.ts + EAS build profiles). Falls back to defaults
 * for local development.
 */

import Constants from 'expo-constants';

const extra = Constants.expoConfig?.extra ?? {};
const DEFAULT_PRIVY_APP_ID = 'cmjp145cl008xl70clr2ho821';
const DEFAULT_PRIVY_CLIENT_ID = 'client-WY6UGQdegv84Ug3Gx9KnPFVkagwsCJ41YcPQ8oRJYoCqy';
const APP_ENV: string = extra.appEnv ?? (__DEV__ ? 'development' : 'production');
const DEFAULT_API_URL = APP_ENV === 'development'
  ? 'http://localhost:8080'
  : 'https://api.boulderroller.xyz';

// Environment-configurable values
export const API_URL: string = extra.apiUrl ?? DEFAULT_API_URL;
export const PRIVY_APP_ID: string = extra.privyAppId ?? DEFAULT_PRIVY_APP_ID;
export const PRIVY_CLIENT_ID: string = extra.privyClientId ?? DEFAULT_PRIVY_CLIENT_ID;
export const SENTRY_DSN: string = extra.sentryDsn ?? '';

// Solana -- stays devnet until mainnet launch
export const SOLANA_RPC_URL = __DEV__
  ? 'https://api.devnet.solana.com'
  : 'https://api.devnet.solana.com';

export const SOLANA_PROGRAM_ID = 'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH';

// SPL Token Mints (devnet) — from protocol/anchor/addresses.devnet.json
export const CAL_MINT = '4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh';
export const DUNG_MINT = 'CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk';

// H3 resolution for tile projection (NEVER change -- would corrupt all tile data)
export const H3_RESOLUTION = 10;

// App metadata
export const APP_VERSION = '0.1.0';
export const APP_NAME = 'BoulderRoller';
