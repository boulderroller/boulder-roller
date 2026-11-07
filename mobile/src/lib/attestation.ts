/**
 * Ride proof state — UI-layer scaffolding.
 *
 * Four lifecycle states the rider can see in post-ride UX. Exactly one
 * applies to a given ride at a given time.
 *
 *   uploaded    — file reached the backend; no proof verdict yet
 *   provisional — processed by the server, final proof still catching up
 *   attested    — verified result available for deeper inspection
 *   under_review — flagged for manual inspection (anti-sybil, data integrity)
 *
 * The DERIVATION consumes the backend RideStatus attestation contract:
 * canonical hash comparison, review reason, and on-chain RideAttestation
 * PDA. Mobile is a read surface here; it does not invent attestation state.
 */

import type { RideStatus } from './api';

export type AttestationState = 'uploaded' | 'provisional' | 'attested' | 'under_review';

export interface RideAttestationView {
  state: AttestationState;
  /**
   * Optional rider-readable note to show alongside the state. Raw hashes,
   * PDA addresses, and transaction ids belong behind the BoulderScan off-ramp,
   * not in the mobile ride detail flow.
   */
  message?: string;
}

const UPLOADED_DEFAULT: RideAttestationView = { state: 'uploaded' };

function hasText(value: string | null | undefined): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function reviewMessage(reason: string | null | undefined): string {
  if (!hasText(reason)) {
    return 'This ride needs a review before it counts.';
  }

  const trimmed = reason.trim();
  if (trimmed === 'preliminary_hash_mismatch') {
    return 'This ride needs a review before it counts.';
  }

  return trimmed.includes('_')
    ? 'This ride needs a review before it counts.'
    : trimmed;
}

/**
 * Derive the proof view from a server RideStatus response.
 *
 * Null status → 'uploaded' as the safe default (upload complete, but
 * we have no server signal either way yet).
 */
export function deriveAttestationView(
  status: RideStatus | null,
): RideAttestationView {
  if (!status) return UPLOADED_DEFAULT;

  if (status.attestationStatus === 'under_review' || status.canonicalMatch === false) {
    return {
      state: 'under_review',
      message: reviewMessage(status.reviewReason),
    };
  }

  if (status.attestationStatus === 'attested' || hasText(status.rideAttestationPda)) {
    return {
      state: 'attested',
      message: 'Verification complete.',
    };
  }

  if (
    status.attestationStatus === 'provisional' ||
    status.canonicalMatch === true ||
    hasText(status.rideHashHex) ||
    hasText(status.preliminaryRideHashHex)
  ) {
    return {
      state: 'provisional',
      message: 'Still checking this ride.',
    };
  }

  return UPLOADED_DEFAULT;
}
