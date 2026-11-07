import { expect } from 'chai';
import * as crypto from 'crypto';
import { PublicKey } from '@solana/web3.js';

import {
  assertMigrationOutcome,
  CURRENT_LOCAL_LEGEND_SIZE,
  inspectLocalLegend,
  LEGACY_LOCAL_LEGEND_SIZE,
  type LocalLegendSnapshot,
} from '../scripts/migrate_local_legends.js';

const PROGRAM_ID = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');

function discriminator(name: string): Buffer {
  return crypto.createHash('sha256').update(`account:${name}`).digest().subarray(0, 8);
}

function u64(value: number): Buffer {
  const data = Buffer.alloc(8);
  data.writeBigUInt64LE(BigInt(value));
  return data;
}

function legacyFixture(vaultId = 0): { pubkey: PublicKey; bump: number; data: Buffer } {
  const [pubkey, bump] = PublicKey.findProgramAddressSync(
    [Buffer.from('local_legend'), u64(vaultId)],
    PROGRAM_ID,
  );
  const data = Buffer.alloc(LEGACY_LOCAL_LEGEND_SIZE);
  discriminator('LocalLegend').copy(data, 0);
  u64(vaultId).copy(data, 8);
  new PublicKey(new Uint8Array(32).fill(7)).toBuffer().copy(data, 16);
  u64(0).copy(data, 48);
  u64(13).copy(data, 56);
  u64(21).copy(data, 64);
  data.writeUInt32LE(0, 72);
  new PublicKey(new Uint8Array(32).fill(8)).toBuffer().copy(data, 76);
  data.writeUInt32LE(0, 108);
  u64(987_654_321).copy(data, 112);
  data[120] = 1;
  data[121] = bump;
  return { pubkey, bump, data };
}

function snapshot(
  vaultId: number,
  pubkey: PublicKey,
  data: Buffer,
  bump: number,
  lamports: number,
): LocalLegendSnapshot {
  return {
    vaultId,
    pubkey,
    data,
    lamports,
    layout: inspectLocalLegend(data, vaultId, bump),
    sha256: crypto.createHash('sha256').update(data).digest('hex'),
  };
}

describe('Local Legend migration operator proof', () => {
  it('accepts only the exact inserted bootstrap byte and relocated bump', () => {
    const { pubkey, bump, data } = legacyFixture();
    const before = snapshot(0, pubkey, data, bump, 9000);
    expect(before.layout).to.deep.equal({ kind: 'legacy', isBootstrap: true, bump });

    const migrated = Buffer.alloc(CURRENT_LOCAL_LEGEND_SIZE);
    data.copy(migrated);
    migrated[121] = 1;
    migrated[122] = bump;
    const after = snapshot(0, pubkey, migrated, bump, 10_000);

    expect(() => assertMigrationOutcome(before, after, 10_000)).not.to.throw();
  });

  it('rejects any economic-field mutation and leaves current accounts byte-idempotent', () => {
    const { pubkey, bump, data } = legacyFixture();
    const before = snapshot(0, pubkey, data, bump, 10_000);
    const migrated = Buffer.alloc(CURRENT_LOCAL_LEGEND_SIZE);
    data.copy(migrated);
    migrated[121] = 1;
    migrated[122] = bump;

    const changedEarned = Buffer.from(migrated);
    changedEarned[112] ^= 1;
    expect(() => assertMigrationOutcome(
      before,
      snapshot(0, pubkey, changedEarned, bump, 10_000),
      10_000,
    )).to.throw('changed before byte 121');

    const current = snapshot(0, pubkey, migrated, bump, 10_000);
    expect(() => assertMigrationOutcome(current, current, 10_000)).not.to.throw();
    const changedCurrent = snapshot(0, pubkey, Buffer.from(migrated), bump, 10_001);
    expect(() => assertMigrationOutcome(current, changedCurrent, 10_000))
      .to.throw('changed during migration');
  });

  it('rejects noncanonical and unexpected layouts before submission', () => {
    const { bump, data } = legacyFixture();
    const noncanonical = Buffer.from(data);
    noncanonical[120] = 2;
    expect(() => inspectLocalLegend(noncanonical, 0, bump)).to.throw('is_active');
    expect(() => inspectLocalLegend(data.subarray(0, 121), 0, bump)).to.throw('length 121');
    expect(() => inspectLocalLegend(data, 1, bump)).to.throw('does not match');
    expect(() => inspectLocalLegend(data, 0, bump - 1)).to.throw('bump mismatch');
  });
});
