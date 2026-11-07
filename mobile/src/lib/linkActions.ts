import { Alert, Linking, Share } from 'react-native';

import type { LinkSharePayload, ResolvedLink, ScanTarget } from './api';

const SCAN_TARGET_TYPE_RANK: Record<string, number> = {
  transaction: 0,
  proof: 1,
  account: 2,
  wallet: 3,
  vault: 4,
};

const SCAN_TARGET_STATE_RANK: Record<string, number> = {
  finalized: 0,
  recorded: 1,
  pending: 2,
  failed: 3,
  private: 4,
  missing: 5,
  off_chain_only: 6,
};

export function scanStateLabel(state?: ResolvedLink['scanState'] | ScanTarget['state'] | null): string {
  switch (state) {
    case 'pending':
      return 'Pending';
    case 'recorded':
      return 'Recorded';
    case 'finalized':
      return 'Finalized';
    case 'missing':
      return 'Missing';
    case 'failed':
      return 'Failed';
    case 'off_chain_only':
      return 'Off-chain only';
    case 'private':
      return 'Private';
    default:
      return 'Checking';
  }
}

export function bestScanTarget(link: ResolvedLink | null): ScanTarget | null {
  return bestScanTargetFromTargets(link?.scanTargets);
}

export function bestScanTargetFromTargets(targets?: ScanTarget[] | null): ScanTarget | null {
  if (!targets?.length) return null;
  return [...targets].sort((left, right) => {
    const leftStateRank = SCAN_TARGET_STATE_RANK[left.state] ?? 99;
    const rightStateRank = SCAN_TARGET_STATE_RANK[right.state] ?? 99;
    if (leftStateRank !== rightStateRank) return leftStateRank - rightStateRank;
    return (SCAN_TARGET_TYPE_RANK[left.type] ?? 99) - (SCAN_TARGET_TYPE_RANK[right.type] ?? 99);
  })[0] ?? null;
}

function isScanUrl(url: string | null | undefined): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    const path = parsed.pathname.replace(/\/+$/, '');
    return host === 'scan.boulderroller.xyz' && path.length > 0;
  } catch {
    return false;
  }
}

export function resolvedBoulderScanUrl(
  link: ResolvedLink | null,
  fallbackUrl?: string | null,
): string | null {
  const targetUrl = bestScanTarget(link)?.url;
  if (targetUrl) return targetUrl;
  if (isScanUrl(link?.externalUrl)) return link?.externalUrl ?? null;
  if (isScanUrl(fallbackUrl)) return fallbackUrl ?? null;
  if (isScanUrl(link?.canonicalUrl)) return link?.canonicalUrl ?? null;
  return null;
}

export function hasResolvedBoulderScanTarget(link: ResolvedLink | null): boolean {
  return resolvedBoulderScanUrl(link) != null;
}

export async function openResolvedProof(link: ResolvedLink | null, fallbackUrl?: string): Promise<void> {
  const url = resolvedBoulderScanUrl(link, fallbackUrl);
  if (!url) {
    Alert.alert('BoulderScan unavailable', 'No scan target yet.');
    return;
  }
  await Linking.openURL(url);
}

export async function shareResolvedPayload(payload: LinkSharePayload): Promise<void> {
  await Share.share({
    title: payload.title,
    message: `${payload.text}\n${payload.url}`,
    url: payload.url,
  });
}
