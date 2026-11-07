import { BorshAccountsCoder } from '@coral-xyz/anchor';
import { PublicKey, Keypair } from '@solana/web3.js';
import BN from 'bn.js';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const anchorRoot = resolve(here, '..');
const fixtureRoot = resolve(anchorRoot, 'tests/fixtures/lp_custody');
const idl = JSON.parse(readFileSync(resolve(anchorRoot, 'idl/boulder_rollers.json'), 'utf8'));
const coder = new BorshAccountsCoder(idl);

const PROGRAM_ID = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
const TOKEN_PROGRAM_ID = new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA');
const VAULT_ID = 515_151;
const CAL = 1_000_000_000n;
const RECORDED_LP = 100n * CAL;
const WALLET_LP = 41n * CAL;
const BALANCE_LP = 61n * CAL;
const TOTAL_LP = WALLET_LP + BALANCE_LP;

const rider = Keypair.fromSeed(Uint8Array.from({ length: 32 }, () => 7));
const walletSource = Keypair.fromSeed(Uint8Array.from({ length: 32 }, () => 8)).publicKey;
const u64 = (value) => new BN(value.toString()).toArrayLike(Buffer, 'le', 8);
const pda = (seed, ...parts) => PublicKey.findProgramAddressSync(
  [Buffer.from(seed), ...parts],
  PROGRAM_ID,
);

const [vault, vaultBump] = pda('vault', u64(VAULT_ID));
const [vaultStake, stakeBump] = pda('vault_stake', rider.publicKey.toBuffer(), u64(VAULT_ID));
const [vaultActivation, activationBump] = pda('vault_activation', u64(VAULT_ID));
const [vaultLpMint] = pda('vault_lp', u64(VAULT_ID));
const [riderBalanceAuthority] = pda('rider_balance_auth', rider.publicKey.toBuffer());
const [balanceSource] = pda(
  'rider_balance_token',
  rider.publicKey.toBuffer(),
  vaultLpMint.toBuffer(),
);
const [position] = pda('vault_position_lp', rider.publicKey.toBuffer(), u64(VAULT_ID));

function fixedBytes(value, length) {
  const output = Buffer.alloc(length);
  Buffer.from(value).copy(output, 0, 0, length);
  return [...output];
}

function tokenMintData() {
  const data = Buffer.alloc(82);
  data.writeUInt32LE(1, 0);
  vault.toBuffer().copy(data, 4);
  data.writeBigUInt64LE(TOTAL_LP, 36);
  data[44] = 9;
  data[45] = 1;
  data.writeUInt32LE(1, 46);
  vault.toBuffer().copy(data, 50);
  return data;
}

function tokenAccountData(authority, amount) {
  const data = Buffer.alloc(165);
  vaultLpMint.toBuffer().copy(data, 0);
  authority.toBuffer().copy(data, 32);
  data.writeBigUInt64LE(amount, 64);
  data[108] = 1;
  return data;
}

function writeFixture(name, pubkey, data, owner) {
  const fixture = {
    pubkey: pubkey.toBase58(),
    account: {
      lamports: 10_000_000,
      data: [Buffer.from(data).toString('base64'), 'base64'],
      owner: owner.toBase58(),
      executable: false,
      rentEpoch: 0,
    },
  };
  writeFileSync(
    resolve(fixtureRoot, `${name}.json`),
    `${JSON.stringify(fixture, null, 2)}\n`,
  );
}

mkdirSync(fixtureRoot, { recursive: true });

writeFixture('vault', vault, await coder.encode('Vault', {
  id: new BN(VAULT_ID),
  signature: fixedBytes('legacy-lp-custody', 64),
  signatureHash: fixedBytes('legacy-lp-custody', 32),
  minter: rider.publicKey,
  mintEpoch: new BN(1),
  rightsExpiresEpoch: new BN(0),
  komHolder: PublicKey.default,
  komTimeS: 0,
  komSetEpoch: new BN(0),
  name: fixedBytes('Legacy LP Fixture', 64),
  avatarIpfs: fixedBytes('', 46),
  slogan: fixedBytes('', 128),
  calTributeAccumulated: new BN(0),
  calTributeAccumulatedNext: new BN(0),
  totalCalBurned: new BN(0),
  totalDungEmitted: new BN(0),
  totalCompletions: new BN(0),
  totalCalStaked: new BN(TOTAL_LP.toString()),
  stakerCount: 1,
  rewardPerTokenStored: new BN(0),
  lastUpdateTime: new BN(0),
  rewardRate: new BN(0),
  pendingRewards: new BN(0),
  pendingRewardsNextWeek: new BN(0),
  openSettlementWeek: new BN(0),
  carryRecordRoyalty: new BN(0),
  carryStakers: new BN(0),
  carryLocalLegend: new BN(0),
  carryPol: new BN(0),
  carryTreasury: new BN(0),
  totalStaked: new BN(TOTAL_LP.toString()),
  lastDistributionEpoch: new BN(0),
  vertM: 100,
  distanceM: 1_000,
  avgGradientPct: 1000,
  createdAt: new BN(0),
  bump: vaultBump,
}), PROGRAM_ID);

writeFixture('vault_stake', vaultStake, await coder.encode('VaultStake', {
  user: rider.publicKey,
  vaultId: new BN(VAULT_ID),
  calStaked: new BN(RECORDED_LP.toString()),
  lpTokens: new BN(RECORDED_LP.toString()),
  stakedAt: new BN(1),
  pendingEffectiveWeekPlusOne: new BN(0),
  effectiveLpTokens: new BN(RECORDED_LP.toString()),
  rewardsEarned: new BN(0),
  pendingLpTokens: new BN(0),
  bump: stakeBump,
}), PROGRAM_ID);

writeFixture('vault_activation', vaultActivation, await coder.encode('VaultActivation', {
  vaultId: new BN(VAULT_ID),
  isActive: true,
  seedCompletionsWritten: 0,
  leaderboardSeeded: true,
  createdAt: new BN(0),
  activatedAt: new BN(1),
  lastSeedAt: new BN(1),
  seedGeneration: 2,
  seedCutoffAt: new BN(0),
  economicsStartEpoch: new BN(1),
  matchedUsers: 0,
  matchedCompletions: 0,
  evidenceHash: [...Buffer.alloc(32)],
  bump: activationBump,
}), PROGRAM_ID);

writeFixture('vault_lp_mint', vaultLpMint, tokenMintData(), TOKEN_PROGRAM_ID);
writeFixture(
  'wallet_lp_source',
  walletSource,
  tokenAccountData(rider.publicKey, WALLET_LP),
  TOKEN_PROGRAM_ID,
);
writeFixture(
  'balance_lp_source',
  balanceSource,
  tokenAccountData(riderBalanceAuthority, BALANCE_LP),
  TOKEN_PROGRAM_ID,
);

const manifest = {
  vaultId: VAULT_ID,
  riderSeedByte: 7,
  rider: rider.publicKey.toBase58(),
  vault: vault.toBase58(),
  vaultStake: vaultStake.toBase58(),
  vaultActivation: vaultActivation.toBase58(),
  vaultLpMint: vaultLpMint.toBase58(),
  walletSource: walletSource.toBase58(),
  balanceSource: balanceSource.toBase58(),
  riderBalanceAuthority: riderBalanceAuthority.toBase58(),
  position: position.toBase58(),
  recordedLp: RECORDED_LP.toString(),
  walletLp: WALLET_LP.toString(),
  balanceLp: BALANCE_LP.toString(),
  totalLp: TOTAL_LP.toString(),
};
writeFileSync(resolve(fixtureRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
process.stdout.write(`${JSON.stringify(manifest, null, 2)}\n`);
