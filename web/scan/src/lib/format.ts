function toBigInt(value: unknown): bigint | null {
  if (value === null || value === undefined || value === '') return null;
  try {
    return BigInt(String(value));
  } catch {
    return null;
  }
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

const BASE58_RE = /^[1-9A-HJ-NP-Za-km-z]+$/;

export function looksLikePubkey(value: unknown): value is string {
  return typeof value === 'string' && BASE58_RE.test(value) && value.length >= 32 && value.length <= 44;
}

export function looksLikeSignature(value: unknown): value is string {
  return typeof value === 'string' && BASE58_RE.test(value) && value.length > 44;
}

export function humanizeLabel(value: string): string {
  return value
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

export function shortenAddress(value: unknown, chars = 6, separator = '...'): string {
  const input = String(value ?? '');
  if (input.length <= chars * 2 + 3) return input || '—';
  return `${input.slice(0, chars)}${separator}${input.slice(-chars)}`;
}

export function formatCount(value: unknown): string {
  const parsed = toNumber(value);
  if (parsed === null) return '—';
  return parsed.toLocaleString();
}

export function formatEpoch(value: unknown): string {
  const parsed = toNumber(value);
  if (parsed === null) return '—';
  return `Epoch ${parsed.toLocaleString()}`;
}

export function formatSlot(value: unknown): string {
  const parsed = toNumber(value);
  if (parsed === null) return '—';
  return parsed.toLocaleString();
}

export function formatDuration(value: unknown): string {
  const seconds = toNumber(value);
  if (seconds === null) return '—';
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remainder = whole % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
  }
  return `${minutes}:${String(remainder).padStart(2, '0')}`;
}

export function formatTimestamp(value: unknown): string {
  if (typeof value === 'string' && value.trim()) {
    const numeric = toNumber(value);
    if (numeric === null) {
      const parsedDate = Date.parse(value);
      if (!Number.isNaN(parsedDate)) {
        return new Date(parsedDate).toLocaleString();
      }
      return '—';
    }
  }

  const parsed = toNumber(value);
  if (parsed === null || parsed <= 0) return '—';
  const timestampMs = parsed > 1_000_000_000_000 ? parsed : parsed * 1000;
  return new Date(timestampMs).toLocaleString();
}

export function formatAtomic(value: unknown, symbol?: string, decimals = 9, minimumFractionDigits = 0): string {
  const parsed = toBigInt(value);
  if (parsed === null) return '—';
  const negative = parsed < 0n;
  const absolute = negative ? parsed * -1n : parsed;
  const base = 10n ** BigInt(decimals);
  const whole = absolute / base;
  const fraction = absolute % base;
  const fractionText = fraction.toString().padStart(decimals, '0').replace(/0+$/, '').padEnd(minimumFractionDigits, '0');
  const maxFractionDigits = whole === 0n ? 6 : 3;

  let numberText = whole.toLocaleString();
  if (fractionText) {
    const visibleFraction = fractionText.slice(0, maxFractionDigits);
    if (whole === 0n && /^0+$/.test(visibleFraction) && fractionText.length > maxFractionDigits) {
      numberText = `< 0.${'0'.repeat(maxFractionDigits - 1)}1`;
    } else {
      numberText = `${whole.toLocaleString()}.${visibleFraction}`.replace(/\.$/, '');
    }
  }

  const signed = negative ? `-${numberText}` : numberText;
  return symbol ? `${signed} ${symbol}` : signed;
}

export function formatRawNumber(value: unknown): string {
  const parsed = toNumber(value);
  if (parsed === null) return '—';
  return parsed.toLocaleString();
}

export function formatElevationTenths(rawValue: unknown): string {
  const parsed = toNumber(rawValue);
  if (parsed === null) return '—';
  return `${(parsed / 10).toFixed(1)} m`;
}

export function formatDistanceMeters(rawValue: unknown): string {
  const parsed = toNumber(rawValue);
  if (parsed === null) return '—';
  if (parsed >= 1000) return `${(parsed / 1000).toFixed(2)} km`;
  return `${parsed.toLocaleString()} m`;
}

export function formatGradientBasisPoints(rawValue: unknown): string {
  const parsed = toNumber(rawValue);
  if (parsed === null) return '—';
  return `${(parsed / 100).toFixed(2)}%`;
}

const EVENT_LABELS: Record<string, string> = {
  VaultCreated: 'Climb Created',
  VaultCompleted: 'Climb Completed',
  VaultCompletedV2: 'Climb Completed',
  ClimbCompleted: 'Climb Completed',
  ClimbCompletedV2: 'Climb Completed',
  ClimbCompletionFlowAssigned: 'Settlement Flow Assigned',
  ClimbCompletionFlowAssignedV2: 'Settlement Flow Assigned',
  EpochRewardsDistributed: 'Rewards Distributed',
  CalTributed: 'CAL Tributed',
  CalStaked: 'Staked CAL',
  CalUnstaked: 'Unstaked CAL',
  DungMinted: 'DUNG Minted',
  DungBurned: 'DUNG Burned',
  LocalLegendElected: 'Legend Elected',
  BeetleCardUpgraded: 'BeetleCard Upgraded',
  KomUpdated: 'New KOM',
  LeaderboardUpdated: 'Leaderboard Updated',
  VaultActivated: 'Climb Activated',
  VaultAllocClaimed: 'Tribute Claimed',
};

export function humanizeEventName(name: string): string {
  return EVENT_LABELS[name] ?? formatStatus(name);
}

export function formatStatus(value: unknown): string {
  const input = String(value ?? '').trim();
  if (!input) return 'Unknown';
  return humanizeLabel(input);
}

/**
 * Format a timestamp as a relative time string ("2 hours ago", "3 days ago").
 * Returns null if the value cannot be parsed.
 */
export function formatRelativeTime(value: unknown): string | null {
  if (value === null || value === undefined || value === '' || value === 0) return null;
  let ms: number;
  if (typeof value === 'string') {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) {
      ms = parsed;
    } else {
      const num = Number(value);
      if (!Number.isFinite(num) || num <= 0) return null;
      ms = num > 1_000_000_000_000 ? num : num * 1000;
    }
  } else {
    const num = toNumber(value);
    if (num === null || num <= 0) return null;
    ms = num > 1_000_000_000_000 ? num : num * 1000;
  }
  const diff = Date.now() - ms;
  if (diff < 0) return 'just now';
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(months / 12);
  return `${years}y ago`;
}
