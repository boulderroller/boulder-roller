import type { ClimbSummary, RecordBoard, ResolvedLink } from '../api';
import {
  buildClimbDetailDisplayModel,
  climbStateLine,
  formatClimbCal,
  formatClimbTime,
  previewRecordEntries,
} from '../climbDisplay';

const climb: ClimbSummary = {
  contractVersion: 'client.v1',
  truthSource: 'projected',
  id: 'climb-1',
  name: 'Manayunk Wall',
  lengthM: 1200,
  elevGainM: 140,
  avgGradientPct: 9.1,
  region: 'Philadelphia',
  vaultId: 77,
  vaultSignature: 'abc',
  hasVault: true,
  totalStaked: '1700',
  totalStakedBaseUnits: '1700000000000',
  totalCalStaked: '1700',
  totalCalStakedBaseUnits: '1700000000000',
  totalCompletions: 44,
};

const leaderboard: RecordBoard = {
  contractVersion: 'client.v1',
  truthSource: 'projected',
  climbId: 'climb-1',
  entries: [
    { rank: 1, wallet: 'WalletAAAA1111', bestTimeSeconds: 300 },
    { rank: 2, wallet: 'WalletBBBB2222', bestTimeSeconds: 320 },
    { rank: 3, wallet: 'WalletCCCC3333', bestTimeSeconds: 340 },
    { rank: 4, wallet: 'WalletDDDD4444', bestTimeSeconds: 360 },
  ],
  leaderboard: [],
  komHolder: 'WalletAAAA1111',
  komTimeS: 300,
};

const resolvedLink: ResolvedLink = {
  contractVersion: 'link.v1',
  status: 'resolved',
  target: { type: 'climb', id: 'climb-1' },
  webPath: '/climbs/climb-1',
  canonicalUrl: 'https://boulderroller.app/climbs/climb-1',
  appUrl: 'boulderroller://climbs/climb-1',
  title: 'Manayunk Wall',
  description: 'Climb on Boulder Roller.',
  access: { canView: true, reason: 'protocol_public', protocolPublic: true, requiresAuth: false },
  metadata: {},
  scanState: 'recorded',
  scanTargets: [
    {
      contractVersion: 'scan.v1',
      type: 'vault',
      id: '77',
      state: 'recorded',
      label: 'Vault 77',
      url: 'https://scan.boulderroller.xyz/vault/77',
      source: 'backend',
    },
  ],
  share: {
    title: 'Manayunk Wall',
    text: 'Climb on Boulder Roller.',
    url: 'https://boulderroller.app/climbs/climb-1',
  },
  openGraph: {
    title: 'Manayunk Wall',
    text: 'Climb on Boulder Roller.',
    url: 'https://boulderroller.app/climbs/climb-1',
    type: 'climb',
  },
};

describe('buildClimbDetailDisplayModel', () => {
  test('summarizes climb identity, vault state, record, and top time copy', () => {
    const model = buildClimbDetailDisplayModel({
      climb,
      leaderboard,
      resolvedLink,
      komLabel: '@tim',
    });

    expect(model.title).toBe('Manayunk Wall');
    expect(model.subtitle).toBe('Philadelphia');
    expect(model.heroStatusLabel).toBe('Balance');
    expect(model.heroStateLine).toBe('Balance • 1,700 CAL deposited');
    expect(model.heroStats).toEqual([
      { label: 'Distance', value: '1.2 km' },
      { label: 'Vert', value: '140 m' },
      { label: 'Grade', value: '9.1%' },
    ]);
    expect(model.boulderScanSubtitle).toBe('BoulderScan ready');
    expect(model.boulderScanTargetLabel).toBe('Vault 77');
    expect(model.boulderScanCtaLabel).toBe('Open BoulderScan');
    expect(model.topTimesSubtitle).toBe('Fastest @tim • 5:00');
    expect(model.vaultValue).toBe('1,700 CAL');
    expect(model.vaultMeta).toBe('44 rides here');
  });

  test('handles unvaulted climbs without inventing a vault state', () => {
    const model = buildClimbDetailDisplayModel({
      climb: {
        ...climb,
        hasVault: false,
        totalStaked: '0',
        totalStakedBaseUnits: '0',
        totalCalStaked: '0',
        totalCalStakedBaseUnits: '0',
        totalCompletions: 0,
        vaultId: null,
        vaultSignature: null,
      },
      leaderboard: null,
      resolvedLink: null,
      komLabel: 'Rider',
    });

    expect(model.heroStatusLabel).toBeNull();
    expect(model.heroStateLine).toBe('First ride sets the line');
    expect(model.boulderScanSubtitle).toBe('Checking');
    expect(model.boulderScanTargetLabel).toBe('BoulderScan pending');
    expect(model.boulderScanCtaLabel).toBeNull();
    expect(model.topTimesSubtitle).toBe('No top time yet');
    expect(model.vaultValue).toBe('No vault');
  });
});

describe('climb display helpers', () => {
  test('formats CAL/time and limits board previews', () => {
    expect(formatClimbCal('12345000000000')).toBe('12,345');
    expect(formatClimbCal('1')).toBe('<0.01');
    expect(formatClimbTime(312)).toBe('5:12');
    expect(previewRecordEntries(leaderboard).map((entry) => entry.rank)).toEqual([1, 2, 3]);
    expect(climbStateLine({ ...climb, hasVault: false, totalCompletions: 9 })).toBe('9 rides');
  });
});
