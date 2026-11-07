import type { ResolvedLink, RideStatus, ScanTarget } from './api';

function hasText(value: string | null | undefined): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

export function countedCalLabel(status: RideStatus | null | undefined): string {
  if (status?.effortPolicy?.thresholdEconomyState === 'held') return 'Held';
  const cal = status?.earnings?.calEarned ?? status?.calEarned;
  if (cal == null) return 'Pending';
  return `+${Math.round(cal)}`;
}

function shortHash(value: string | null | undefined): string {
  if (!hasText(value)) return 'Pending';
  return `${value.slice(0, 10)}...`;
}

export function rideRecordStatusLabel(
  status: RideStatus | null | undefined,
  hasServerRide = false,
): string {
  if (!status) return hasServerRide ? 'Checking' : 'On device';
  if (status.attestationStatus === 'under_review' || status.canonicalMatch === false) {
    return 'Needs review';
  }
  if (status.effortPolicy?.thresholdEconomyState === 'held') {
    return status.attestationStatus === 'attested' ? 'Verified' : 'Checking';
  }
  if (hasText(status.finalizedAt) || hasText(status.earnings?.finalizedAt)) {
    return 'Counted';
  }
  if (
    status.attestationStatus === 'attested' ||
    hasText(status.rideAttestationPda) ||
    hasText(status.rideAttestationTxSignature)
  ) {
    return 'Verified';
  }
  if (
    status.attestationStatus === 'provisional' ||
    status.canonicalMatch === true ||
    hasText(status.rideHashHex) ||
    hasText(status.preliminaryRideHashHex)
  ) {
    return 'Checking';
  }
  return hasServerRide ? 'Checking' : 'On device';
}

export function rideRecordSubtitle(status: RideStatus | null | undefined): string {
  if (!status) return 'Waiting for verification';
  if (status.effortPolicy?.thresholdEconomyState === 'held') {
    return 'Held — clears when your Threshold is established.';
  }
  if (status.attestationStatus === 'under_review' || status.canonicalMatch === false) {
    return 'Needs review before it counts';
  }
  if (status.attestationStatus === 'attested' || hasText(status.finalizedAt)) {
    return 'What counted on this ride';
  }
  return 'Checking what counted';
}

export function rideRecordRows(status: RideStatus | null | undefined): [string, string][] {
  if (!status) return [];
  const held = status.effortPolicy?.thresholdEconomyState === 'held';
  return [
    ['Status', rideRecordStatusLabel(status, true)],
    [held ? 'CAL' : 'Counted CAL', countedCalLabel(status)],
    ['Ride file', shortHash(status.rideHashHex ?? status.preliminaryRideHashHex)],
    ['Chain', shortHash(status.attestationCommitmentHex ?? status.rideAttestationTxSignature)],
  ];
}

export function recordStateLabelFromScanState(state: string | null | undefined): string {
  switch (state) {
    case 'recorded':
    case 'finalized':
      return 'BoulderScan ready';
    case 'off_chain_only':
      return 'App only';
    case 'pending':
      return 'BoulderScan pending';
    case 'missing':
      return 'Not in BoulderScan yet';
    case 'failed':
      return 'BoulderScan unavailable';
    case 'private':
      return 'Private';
    default:
      return 'Checking';
  }
}

export function recordStateLabelFromLink(link: ResolvedLink | null | undefined): string | null {
  if (!link) return null;
  return recordStateLabelFromScanState(link.scanState);
}

export function recordTargetLabel(target: ScanTarget | null | undefined): string | null {
  if (!target) return null;
  switch (target.type) {
    case 'transaction':
      return 'Transaction';
    case 'account':
    case 'wallet':
      return 'Account';
    case 'vault':
      return 'Vault';
    case 'proof':
      return 'Verification';
    default:
      return target.label.replace(/\battestation\b/gi, 'verification');
  }
}
