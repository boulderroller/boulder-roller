/**
 * Seed Vault availability detection.
 *
 * On a Seeker (or any Android device with the Seed Vault system app /
 * Simulator APK installed), MWA's authorize flow automatically routes to
 * Seed Vault — the native wallet there implements the MWA protocol. So
 * for the common signing path, mwaWallet.ts already gets the Seed Vault
 * double-tap UX for free on supported hardware.
 *
 * This module exists for the subset of flows that want to know whether
 * Seed Vault is available (to surface UI affordances, enable privileged
 * features later like direct derivation-path picking, etc.). Direct
 * Seed Vault API integration beyond availability is future work — it
 * needs real-hardware QA against a Seeker or the Seed Vault Simulator
 * APK, which jest cannot simulate.
 */

import { Platform } from 'react-native';
import { SeedVault } from '@solana-mobile/seed-vault-lib';

/**
 * True when the device can surface the native Seed Vault UX. Returns
 * false on iOS and on Android devices that don't have the Seed Vault
 * system app (including most non-Seeker phones). allowSimulated=true
 * accepts the Seed Vault Simulator APK — the standard dev path without
 * a Seeker.
 */
export async function isSeedVaultAvailable(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  try {
    return await SeedVault.isSeedVaultAvailable(true);
  } catch {
    // Native bridge errors on devices without Seed Vault libraries at all.
    // Treat as "not available" rather than surfacing the raw error.
    return false;
  }
}
