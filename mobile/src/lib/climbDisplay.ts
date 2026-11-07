import type {
  ClimbSummary,
  RecordBoard,
  RecordBoardEntry,
  ResolvedLink,
} from './api';
import { formatTokenAmount } from './chain';
import type { StatClusterItem } from '../components/surfaces/StatCluster';
import { bestScanTarget, hasResolvedBoulderScanTarget } from './linkActions';
import { recordStateLabelFromLink } from './recordDisplay';

export interface ClimbDetailDisplayModel {
  title: string;
  subtitle?: string | null;
  heroStats: StatClusterItem[];
  heroStateLine: string;
  heroStatusLabel: string | null;
  boulderScanSubtitle: string;
  boulderScanTargetLabel: string;
  boulderScanCtaLabel: string | null;
  topTimesSubtitle: string;
  vaultValue: string;
  vaultMeta: string;
}

export function formatClimbDistance(lengthM: number | null | undefined): string {
  return `${((lengthM ?? 0) / 1000).toFixed(1)} km`;
}

export function formatClimbVert(elevGainM: number | null | undefined): string {
  return `${Math.round(elevGainM ?? 0)} m`;
}

export function formatClimbGrade(avgGradientPct: number | null | undefined): string {
  return `${(avgGradientPct ?? 0).toFixed(1)}%`;
}

export function isPositiveClimbCal(value: string | null | undefined): boolean {
  if (!value || !/^[0-9]+$/.test(value)) return false;
  return BigInt(value) > 0n;
}

export function compareClimbCalBaseUnits(left: string, right: string): number {
  const leftAmount = /^[0-9]+$/.test(left) ? BigInt(left) : 0n;
  const rightAmount = /^[0-9]+$/.test(right) ? BigInt(right) : 0n;
  if (leftAmount < rightAmount) return -1;
  if (leftAmount > rightAmount) return 1;
  return 0;
}

export function formatClimbCal(amountBaseUnits: string | null | undefined): string {
  if (!amountBaseUnits || !/^[0-9]+$/.test(amountBaseUnits)) return '0';
  const [whole, fraction = ''] = formatTokenAmount(amountBaseUnits, 9).split('.');
  const groupedWhole = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const visibleFraction = fraction.slice(0, 2).replace(/0+$/, '');
  if (visibleFraction) return `${groupedWhole}.${visibleFraction}`;
  if (whole === '0' && fraction) return '<0.01';
  return groupedWhole;
}

export function formatClimbTime(seconds?: number | null): string {
  if (seconds == null || seconds <= 0) return '—';
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}:${remaining.toString().padStart(2, '0')}`;
}

export function previewRecordEntries(board: RecordBoard | null): RecordBoardEntry[] {
  const entries = board?.entries?.length ? board.entries : (board?.leaderboard ?? []);
  return entries.slice(0, 3);
}

export function buildClimbHeroStats(climb: ClimbSummary): StatClusterItem[] {
  return [
    { label: 'Distance', value: formatClimbDistance(climb.lengthM) },
    { label: 'Vert', value: formatClimbVert(climb.elevGainM) },
    { label: 'Grade', value: formatClimbGrade(climb.avgGradientPct) },
  ];
}

export function climbStateLine(climb: ClimbSummary): string {
  if (climb.hasVault) {
    return isPositiveClimbCal(climb.totalStakedBaseUnits)
      ? `Balance • ${formatClimbCal(climb.totalStakedBaseUnits)} CAL deposited`
      : 'Balance open';
  }
  if ((climb.totalCompletions ?? 0) > 0) {
    return `${climb.totalCompletions} rides`;
  }
  return 'First ride sets the line';
}

export function buildClimbDetailDisplayModel(input: {
  climb: ClimbSummary;
  leaderboard: RecordBoard | null;
  resolvedLink: ResolvedLink | null;
  komLabel: string;
}): ClimbDetailDisplayModel {
  const { climb, leaderboard, resolvedLink, komLabel } = input;
  const scanTarget = bestScanTarget(resolvedLink);
  const canOpenScan = hasResolvedBoulderScanTarget(resolvedLink);
  const hasTopTime = leaderboard?.komTimeS != null && leaderboard.komTimeS > 0;
  return {
    title: climb.name || 'Unnamed Climb',
    subtitle: climb.region,
    heroStats: buildClimbHeroStats(climb),
    heroStateLine: climbStateLine(climb),
    heroStatusLabel: climb.hasVault ? 'Balance' : null,
    boulderScanSubtitle: recordStateLabelFromLink(resolvedLink) ?? 'Checking',
    boulderScanTargetLabel: scanTarget?.label ?? 'BoulderScan pending',
    boulderScanCtaLabel: canOpenScan ? 'Open BoulderScan' : null,
    topTimesSubtitle: hasTopTime ? `Fastest ${komLabel} • ${formatClimbTime(leaderboard?.komTimeS)}` : 'No top time yet',
    vaultValue: climb.hasVault
      ? isPositiveClimbCal(climb.totalStakedBaseUnits)
        ? `${formatClimbCal(climb.totalStakedBaseUnits)} CAL`
        : 'Open'
      : 'No vault',
    vaultMeta: `${(climb.totalCompletions ?? 0).toLocaleString()} rides here`,
  };
}
