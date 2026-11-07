import fs from 'fs';
import path from 'path';

import { deriveAttestationView } from '../../lib/attestation';
import { derivePostRideCascade } from '../../lib/postRideCascade';
import {
  recordStateLabelFromScanState,
  recordTargetLabel,
  rideRecordStatusLabel,
  rideRecordSubtitle,
} from '../../lib/recordDisplay';
import { deriveProcessingStages } from '../../lib/rideProcessing';

const riderSurfaceFiles = [
  '../HomeScreen.tsx',
  '../ProfileScreen.tsx',
  '../RiderDetailScreen.tsx',
  '../PostRideScreen.tsx',
  '../RideDetailScreen.tsx',
  '../ClimbDetailScreen.tsx',
  '../SearchScreen.tsx',
  '../NotificationsScreen.tsx',
  '../RecordScreen.tsx',
  '../../components/PostRideCascadePanel.tsx',
  '../../components/rider/RiderHeader.tsx',
  '../../components/rider/RiderRow.tsx',
  '../../components/rider/FollowButton.tsx',
  '../../components/rider/BeetleCardModule.tsx',
  '../../components/RideReviewBanner.tsx',
  '../../components/RideProcessingStages.tsx',
  '../../lib/attestation.ts',
  '../../lib/postRideCascade.ts',
  '../../lib/postRideDisplay.ts',
  '../../lib/rideDisplay.ts',
  '../../lib/rideLifecycleDisplay.ts',
  '../../lib/sensorDisplay.ts',
];

const bannedRiderCopy = [
  /climb consequences/i,
  /ride consequences/i,
  /raw recording/i,
  /processing status/i,
  /proof pending/i,
  /proof is/i,
  /final proof/i,
  /ride proof/i,
  /canonical/i,
  /attestation/i,
  /\bpda\b/i,
  /\bhash\b/i,
  /evidence/i,
  /deposited/i,
  /optional .*layer/i,
  /climb monument/i,
  /stewardship/i,
  /permanent glory/i,
  /finalized/i,
  /settled/i,
  /^You$/i,
  /Protocol Proof/i,
  /Proof state/i,
  /Ride hash/i,
  /Commitment/i,
  /Post-ride proof/i,
  /ride records?\b/i,
  /\brecord board\b/i,
  /^Board$/,
  /^Climb record$/i,
  /^Record and sharing$/i,
  /\b(?:record ready|app record|checking record|record is still checking|record pending|record unavailable|private record|chain record|record account|vault record|full record|rider record|record update|source record)\b/i,
  /transaction submitted/i,
  /\bgas\b/i,
  /\bharvest\b/i,
  /\bunstake\b/i,
];

function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');
}

function extractStringLiterals(source: string): string[] {
  const withoutComments = stripComments(source);
  const strings: string[] = [];
  const quotedPattern = /(['"])([^'"`\n]*?)\1/g;
  const templatePattern = /`([^`\n]*?)`/g;

  for (const line of withoutComments.split('\n')) {
    let match: RegExpExecArray | null;
    while ((match = quotedPattern.exec(line)) !== null) {
      const value = match[2];
      if (value.startsWith('.') || value.startsWith('http')) continue;
      strings.push(value);
    }
    while ((match = templatePattern.exec(line)) !== null) {
      strings.push(match[1].replace(/\$\{[^}]*\}/g, ''));
    }
  }

  return strings;
}

describe('rider-facing copy boundary', () => {
  test('rider surfaces avoid proof/protocol/internal copy', () => {
    const violations: string[] = [];

    for (const relativeFile of riderSurfaceFiles) {
      const filePath = path.resolve(__dirname, relativeFile);
      const source = fs.readFileSync(filePath, 'utf8');
      for (const text of extractStringLiterals(source)) {
        for (const banned of bannedRiderCopy) {
          if (banned.test(text)) {
            violations.push(`${relativeFile}: "${text}" matched ${banned}`);
          }
        }
      }
    }

    expect(violations).toEqual([]);
  });

  test('derived rider copy avoids proof/protocol/internal copy', () => {
    const derivedCopy = [
      deriveAttestationView(null).message,
      deriveAttestationView({
        attestationStatus: 'under_review',
        canonicalMatch: false,
        reviewReason: 'preliminary_hash_mismatch',
      } as any).message,
      deriveAttestationView({
        attestationStatus: 'attested',
        rideAttestationPda: 'pda',
      } as any).message,
      deriveAttestationView({
        attestationStatus: 'provisional',
        canonicalMatch: true,
        rideHashHex: 'hash',
      } as any).message,
      ...deriveProcessingStages({
        metrics: {},
        hasPatterns: true,
        hasLeaderboards: true,
        hasAchievements: true,
      } as any).map((stage) => stage.label),
      derivePostRideCascade({ uploadState: 'uploaded', status: null }).title,
      derivePostRideCascade({ uploadState: 'uploaded', status: null }).subtitle,
      ...derivePostRideCascade({
        uploadState: 'uploaded',
        status: {
          rideId: 'ride-1',
          status: 'completed',
          errorMessage: null,
          attestationStatus: 'attested',
          canonicalMatch: true,
          rideHashHex: 'hash',
          rideAttestationPda: 'pda',
          metrics: {
            tss: 72,
            kcals: null,
            distanceM: null,
            elevationGainM: null,
            durationSec: null,
            avgPowerW: null,
            normalizedPowerW: null,
          },
          earnings: {
            contractVersion: 'client.v1',
            truthSource: 'onchain',
            rideId: 'ride-1',
            calEarned: 72,
            dungEarned: 1,
          },
          hasLeaderboards: true,
        } as any,
      }).lines.flatMap((line) => [line.label, line.value].filter(Boolean)),
      rideRecordStatusLabel({ attestationStatus: 'attested' } as any, true),
      rideRecordSubtitle(null),
      ...['recorded', 'finalized', 'off_chain_only', 'pending', 'missing', 'failed', 'private']
        .map((state) => recordStateLabelFromScanState(state)),
      recordTargetLabel({ type: 'transaction', label: 'Transaction' } as any),
      recordTargetLabel({ type: 'account', label: 'Account' } as any),
      recordTargetLabel({ type: 'vault', label: 'Vault' } as any),
      recordTargetLabel({ type: 'proof', label: 'Verification' } as any),
    ].filter((text): text is string => typeof text === 'string');

    const violations: string[] = [];
    for (const text of derivedCopy) {
      for (const banned of bannedRiderCopy) {
        if (banned.test(text)) {
          violations.push(`derived copy: "${text}" matched ${banned}`);
        }
      }
    }

    expect(violations).toEqual([]);
  });
});
