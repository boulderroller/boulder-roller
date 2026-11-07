import { createHash } from 'crypto';
import { PublicKey, TransactionInstruction } from '@solana/web3.js';
import BN from 'bn.js';

// Test setup instructions compiled only into the isolated stage1-localnet
// program (cargo feature smoke-helpers). They are absent from the deployable
// IDL and binaries, so the localnet suites encode them directly.
export const SMOKE_HELPER_INSTRUCTIONS = [
  'admin_override_open_settlement_week',
  'admin_seed_pending_rewards',
  'admin_override_stake_eligibility',
] as const;
export const SMOKE_HELPERS_PRESENT = process.env.STAGE1_LOCALNET === '1';

export function smokeDiscriminator(name: string): Buffer {
  return createHash('sha256').update(`global:${name}`).digest().subarray(0, 8);
}

function u64(...values: BN[]): Buffer {
  return Buffer.concat(values.map((value) => value.toArrayLike(Buffer, 'le', 8)));
}

const writable = (pubkey: PublicKey) => ({ pubkey, isSigner: false, isWritable: true });
const readonly = (pubkey: PublicKey) => ({ pubkey, isSigner: false, isWritable: false });
const authorityMeta = (pubkey: PublicKey) => ({ pubkey, isSigner: true, isWritable: true });

export function adminOverrideOpenSettlementWeekIx(programId: PublicKey,
  accounts: { vault: PublicKey; programConfig: PublicKey; authority: PublicKey }, settlementWeek: BN) {
  return new TransactionInstruction({
    programId,
    keys: [writable(accounts.vault), readonly(accounts.programConfig), authorityMeta(accounts.authority)],
    data: Buffer.concat([smokeDiscriminator('admin_override_open_settlement_week'), u64(settlementWeek)]),
  });
}

export function adminSeedPendingRewardsIx(programId: PublicKey,
  accounts: { vault: PublicKey; vaultActivation: PublicKey; programConfig: PublicKey; authority: PublicKey },
  settlementWeek: BN, pendingRewards: BN) {
  return new TransactionInstruction({
    programId,
    keys: [writable(accounts.vault), readonly(accounts.vaultActivation), readonly(accounts.programConfig),
      authorityMeta(accounts.authority)],
    data: Buffer.concat([smokeDiscriminator('admin_seed_pending_rewards'), u64(settlementWeek, pendingRewards)]),
  });
}

export function adminOverrideStakeEligibilityIx(programId: PublicKey,
  accounts: { vault: PublicKey; vaultStake: PublicKey; programConfig: PublicKey; authority: PublicKey },
  eligibleFromEpoch: BN) {
  return new TransactionInstruction({
    programId,
    keys: [readonly(accounts.vault), writable(accounts.vaultStake), readonly(accounts.programConfig),
      authorityMeta(accounts.authority)],
    data: Buffer.concat([smokeDiscriminator('admin_override_stake_eligibility'), u64(eligibleFromEpoch)]),
  });
}
