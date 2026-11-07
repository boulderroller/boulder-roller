import * as anchor from '@coral-xyz/anchor';
import { expect } from 'chai';
import * as crypto from 'crypto';
import {
  AuthorityType,
  createMint,
  createAssociatedTokenAccountIdempotentInstruction,
  getAccount,
  getAssociatedTokenAddressSync,
  getMint,
  mintTo,
  setAuthority,
  TOKEN_PROGRAM_ID,
  transfer,
} from '@solana/spl-token';
import {
  AddressLookupTableProgram,
  ComputeBudgetProgram,
  Keypair,
  LAMPORTS_PER_SOL,
  PublicKey,
  sendAndConfirmTransaction,
  SystemProgram,
  SYSVAR_RENT_PUBKEY,
  Transaction,
  TransactionInstruction,
  TransactionMessage,
  VersionedTransaction,
} from '@solana/web3.js';
import BN from 'bn.js';
import boulderRollersIdl from '../idl/boulder_rollers.json' with { type: 'json' };
import {
  CURRENT_PROGRAM_VERSION,
  PREVIOUS_PROGRAM_VERSION,
} from '../generated-program-version.js';
import {
  adminOverrideOpenSettlementWeekIx,
  adminOverrideStakeEligibilityIx,
  adminSeedPendingRewardsIx,
  SMOKE_HELPER_INSTRUCTIONS,
  SMOKE_HELPERS_PRESENT,
  smokeDiscriminator,
} from './helpers/smoke_helpers.js';

// Stable fixture keys make main/release compute comparable. PDA bump searches
// otherwise add a random multiple of 1,500 CU per inventory account.
const fixtureSequence = new Map<string, number>();
function settlementFixtureKey(label: string): Keypair {
  const n = fixtureSequence.get(label) ?? 0; fixtureSequence.set(label, n + 1);
  return Keypair.fromSeed(crypto.createHash('sha256').update(`BR-settlement-fixture-v1:${label}:${n}`).digest());
}

const provider = anchor.AnchorProvider.env();
anchor.setProvider(provider);

const LOCALNET_TEST_BUILD = process.env.STAGE1_LOCALNET === '1';
const PROGRAM_ID = new PublicKey(LOCALNET_TEST_BUILD
  ? '5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt'
  : 'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
const program = new anchor.Program(boulderRollersIdl as anchor.Idl, PROGRAM_ID, provider);
const wallet = provider.wallet as anchor.Wallet;
// The SPL convenience helper swallows every creation error. Preserve the
// actual local transaction failure and wait for confirmed account visibility.
async function getOrCreateAssociatedTokenAccount(connection: anchor.web3.Connection, payer: Keypair,
  mint: PublicKey, owner: PublicKey, allowOwnerOffCurve = false) {
  const address = getAssociatedTokenAddressSync(mint, owner, allowOwnerOffCurve);
  if (!await connection.getAccountInfo(address, 'confirmed')) {
    await sendAndConfirmTransaction(connection, new Transaction().add(
      createAssociatedTokenAccountIdempotentInstruction(payer.publicKey, address, owner, mint)), [payer],
      {commitment: 'confirmed', preflightCommitment: 'confirmed'});
  }
  const account = await getAccount(connection, address, 'confirmed');
  expect(account.mint.equals(mint)).to.equal(true);
  expect(account.owner.equals(owner)).to.equal(true);
  return account;
}
const BPF_UPGRADEABLE_LOADER_ID = new PublicKey('BPFLoaderUpgradeab1e11111111111111111111111');

const EPOCH_ANCHOR = 1_704_110_400;
const EPOCH_DURATION_SECONDS = 604_800;
const DUNG = 1_000_000_000n;
const CAL = 1_000_000_000n;
const MIN_CAL_STAKE = 100n * CAL;
const HARVEST_FEE_BPS = 500n;
const VAULT_CREATION_CAL_DEPOSIT = 1000n;
const VAULT_CREATION_CAL_PAYMENT = 1000n * CAL;
const VAULT_CREATION_USDC_PAYMENT = 2_000_000n;
const CLIMB_CAL_TRIBUTE = 1_000_000_000_000n - VAULT_CREATION_CAL_DEPOSIT;

function calTributeBudget(calEarned: bigint) {
  return calEarned;
}

const DISTRIBUTION_CONFIG = {
  leaderboardShareBps: new BN(5500),
  stakerShareBps: new BN(2700),
  localLegendShareBps: new BN(300),
  polShareBps: new BN(500),
  protocolFeeBps: new BN(1000),
};
const SETTLEMENT_COMPUTE_UNIT_LIMIT = 450_000;
const SETTLEMENT_PRIORITY_FEE_MICRO_LAMPORTS = 50_000;
const SETTLEMENT_COMPUTE_PROVEN_INVENTORY = 10;
const SETTLEMENT_MIN_COMPUTE_HEADROOM = 100_000;
const SETTLEMENT_REVIEWED_PACKET_BYTES = 900;
const SOLANA_PACKET_DATA_SIZE = 1232;
const STAKER_REMAINDER_POLICY_MARKER = 0x5354414b45520001n;
const LEGACY_LOCAL_LEGEND_FIXTURE_VAULT_ID = 424_242;
const LEGACY_LOCAL_LEGEND_FIXTURE = new PublicKey(
  LOCALNET_TEST_BUILD ? 'AJ8GKxmqNtWsdiAso8F4ysrpiYvw8SK8HC2w7SMLV8FT'
    : 'AZBtJszKNqY2wGhuDhr9vi4QDQLhrEXEQYSM385fSmDL',
);
// The localnet fixture changes only its program-derived address/owner/bump;
// every economic byte and the original deployable fixture stay unchanged.
const LEGACY_LOCAL_LEGEND_FIXTURE_SHA256 = LOCALNET_TEST_BUILD
  ? '3d9e38f2fb180a1045f07d5e26a99315acf41a02244a2d1ff2917399e50d8cce'
  : '2b13dcbeb9c21930b43d09440bece945ca315cd77ec5fe95730028f3734fbef7';
const LEGACY_LP_FIXTURE_VAULT_ID = 515_151;
const LEGACY_LP_RECORDED = 100n * CAL;
const LEGACY_LP_WALLET_RESTORE = 40n * CAL;
const LEGACY_LP_BALANCE_SOURCE = 61n * CAL;
const BALANCE_VAULT_OPERATION_DOMAIN = Buffer.from('BR_BALANCE_VAULT_OPERATION_V1');
const BALANCE_VAULT_OPERATION_KIND = {
  createVault: 0,
  depositCal: 1,
  withdrawCal: 2,
} as const;

function pda(seed: string, ...parts: Buffer[]) {
  return PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], program.programId);
}

function u64(value: number | bigint | BN) {
  const bn = BN.isBN(value) ? value : new BN(value.toString());
  return bn.toArrayLike(Buffer, 'le', 8);
}

function i64(value: number | bigint | BN) {
  const bn = BN.isBN(value) ? value : new BN(value.toString());
  return bn.toTwos(64).toArrayLike(Buffer, 'le', 8);
}

function u16be(value: number) {
  const bytes = Buffer.alloc(2);
  bytes.writeUInt16BE(value);
  return bytes;
}

function completionEvidenceV2(
  rideAttestation: PublicKey,
  vault: PublicKey,
  completionTimeS: number,
  calTribute: bigint,
) {
  const time = Buffer.alloc(4);
  time.writeUInt32LE(completionTimeS);
  return Array.from(
    crypto.createHash('sha256').update(Buffer.concat([
      Buffer.from('BR_CLIMB_COMPLETION_V2'),
      rideAttestation.toBuffer(),
      vault.toBuffer(),
      time,
      u64(calTribute),
    ])).digest(),
  );
}

function findProgramConfig() {
  return pda('program_config');
}

async function fetchProgramDataAddress(): Promise<PublicKey> {
  const programAccount = await provider.connection.getAccountInfo(PROGRAM_ID);
  if (!programAccount?.executable) {
    throw new Error('test program account is missing or not executable');
  }
  if (!programAccount.owner.equals(BPF_UPGRADEABLE_LOADER_ID)) {
    throw new Error(`test program is not upgradeable-loader owned: ${programAccount.owner.toBase58()}`);
  }
  const loaderStateTag = programAccount.data.readUInt32LE(0);
  if (loaderStateTag !== 2) {
    throw new Error(`test program account is not an upgradeable Program state: ${loaderStateTag}`);
  }
  return new PublicKey(programAccount.data.subarray(4, 36));
}

function findVaultCounter() {
  return pda('vault_counter');
}

function findClimb(commitmentHash: Buffer) {
  return pda('climb', commitmentHash);
}

function findClimbVersionIndex(canonId: Buffer, canonVersion: number) {
  return pda('climb_version', canonId, u16be(canonVersion));
}

function findVault(vaultId: number | BN) {
  return pda('vault', u64(vaultId));
}

function findLocalLegend(vaultId: number | BN) {
  return pda('local_legend', u64(vaultId));
}

function findVaultActivation(vaultId: number | BN) {
  return pda('vault_activation', u64(vaultId));
}

function findVaultLeaderboard(vaultId: number | BN) {
  return pda('vault_leaderboard', u64(vaultId));
}

function findVaultCompletion(rider: PublicKey, vaultId: number | BN) {
  return pda('vault_completion', rider.toBuffer(), u64(vaultId));
}

function findVaultLpMint(vaultId: number | BN) {
  return pda('vault_lp', u64(vaultId));
}

function findVaultCalEscrow(vaultId: number | BN) {
  return pda('vault_cal_escrow', u64(vaultId));
}

function findVaultStake(staker: PublicKey, vaultId: number | BN) {
  return pda('vault_stake', staker.toBuffer(), u64(vaultId));
}

function findVaultPositionLp(rider: PublicKey, vaultId: number | BN) {
  return pda('vault_position_lp', rider.toBuffer(), u64(vaultId));
}

function findRiderBalance(rider: PublicKey) {
  return pda('rider_balance', rider.toBuffer());
}

function findRiderBalanceAuthority(rider: PublicKey) {
  return pda('rider_balance_auth', rider.toBuffer());
}

function findBalanceVaultAuthority(rider: PublicKey) {
  return pda('balance_vault_auth', rider.toBuffer());
}

function findRiderBalanceToken(rider: PublicKey, mint: PublicKey) {
  return pda('rider_balance_token', rider.toBuffer(), mint.toBuffer());
}

function findRideAttestation(rider: PublicKey, rideHash: Buffer) {
  return pda('ride_attestation', rider.toBuffer(), rideHash);
}

function findRideTributeBudget(rideAttestation: PublicKey) {
  return pda('ride_tribute_budget', rideAttestation.toBuffer());
}

function findRiderSoul(rider: PublicKey) {
  return pda('rider_soul', rider.toBuffer());
}

function findCalMintReceipt(rideAttestation: PublicKey, rider: PublicKey) {
  return pda('cal_mint_receipt', rideAttestation.toBuffer(), rider.toBuffer());
}

function findClimbCompletionReceipt(rideAttestation: PublicKey, vault: PublicKey) {
  return pda('climb_completion_receipt', rideAttestation.toBuffer(), vault.toBuffer());
}

function findCalMintAuth() {
  return pda('cal_mint_auth');
}

function findDungMintAuth() {
  return pda('dung_mint_auth');
}

function findDungMintState() {
  return pda('dung_mint_state');
}

function currentEpoch(unixSeconds = Math.floor(Date.now() / 1000)) {
  return Math.floor((unixSeconds - EPOCH_ANCHOR) / EPOCH_DURATION_SECONDS);
}

function epochStart(epoch: number) {
  return EPOCH_ANCHOR + epoch * EPOCH_DURATION_SECONDS;
}

function hash32(label: string) {
  return crypto.createHash('sha256').update(label).digest();
}

function canonCommitmentFrom(
  canonId: Buffer,
  canonVersion: number,
  canonicalProfileHash: Buffer,
) {
  const commitment = Buffer.alloc(64);
  commitment[0] = 0x01;
  canonId.copy(commitment, 1);
  commitment.writeUInt16BE(canonVersion, 17);
  canonicalProfileHash.copy(commitment, 32);
  const commitmentHash = crypto.createHash('sha256').update(commitment).digest();
  return { canonId, canonicalProfileHash, commitment, commitmentHash };
}

function canonCommitment(label: string, canonVersion = 1) {
  return canonCommitmentFrom(
    hash32(`canon:${label}`).subarray(0, 16),
    canonVersion,
    hash32(`profile:${label}:v${canonVersion}`),
  );
}

function bn(value: bigint | number) {
  return new BN(value.toString());
}

function bnToBigInt(value: BN) {
  return BigInt(value.toString());
}

function balanceVaultOperationId(
  rider: PublicKey,
  operationAuthority: PublicKey,
  kind: number,
  vaultId: number | bigint | BN,
  primaryAmount: number | bigint | BN,
  secondaryAmount: number | bigint | BN,
  generation: number | bigint | BN,
  nonce: number | bigint | BN,
  expiresAt: number | bigint | BN,
) {
  return crypto.createHash('sha256').update(Buffer.concat([
    BALANCE_VAULT_OPERATION_DOMAIN,
    PROGRAM_ID.toBuffer(),
    rider.toBuffer(),
    operationAuthority.toBuffer(),
    Buffer.from([kind]),
    u64(vaultId),
    u64(primaryAmount),
    u64(secondaryAmount),
    u64(generation),
    u64(nonce),
    i64(expiresAt),
  ])).digest();
}

async function airdrop(pubkey: PublicKey, lamports = 2 * LAMPORTS_PER_SOL) {
  const sig = await provider.connection.requestAirdrop(pubkey, lamports);
  const blockhash = await provider.connection.getLatestBlockhash();
  await provider.connection.confirmTransaction({ signature: sig, ...blockhash }, 'confirmed');
}

async function getConfirmedTransaction(signature: string) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const transaction = await provider.connection.getTransaction(signature, {
      commitment: 'confirmed',
      maxSupportedTransactionVersion: 0,
    });
    if (transaction) {
      return transaction;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return null;
}

async function isRejected(promise: Promise<unknown>) {
  try {
    await promise;
    return false;
  } catch (_) {
    return true;
  }
}

async function expectRejected(promise: Promise<unknown>, expectedError?: string) {
  let rejected = false;
  let rejection: unknown;
  try {
    await promise;
  } catch (error) {
    rejected = true;
    rejection = error;
  }
  expect(rejected, 'expected promise to reject').to.equal(true);
  if (expectedError) {
    const transactionLogs = (rejection as { logs?: unknown } | null)?.logs;
    // Anchor's ProgramError retains the numeric code but has an empty Error
    // message when confirmed logs are not yet indexed. Match the same IDL code.
    const codedError = rejection instanceof anchor.ProgramError ? rejection : null;
    const errorName = program.idl.errors?.find(({ code }) => code === codedError?.code)?.name;
    const message = [
      rejection instanceof Error ? rejection.message : String(rejection),
      errorName,
      ...(Array.isArray(transactionLogs) ? transactionLogs : []),
    ].filter(Boolean).join('\n');
    expect(
      message,
      `expected rejection to include ${expectedError}; received: ${message}`,
    ).to.include(expectedError);
  }
}

describe('Boulder Rollers protocol truths', () => {
  const founder = settlementFixtureKey('site-0');
  const rider = settlementFixtureKey('site-1');
  const attacker = settlementFixtureKey('site-2');
  const balanceVaultOperationSigner = settlementFixtureKey('site-3');
  const rotatedBalanceVaultOperationSigner = settlementFixtureKey('site-4');
  let activeBalanceVaultOperationSigner = balanceVaultOperationSigner;
  const eligibleStaker = settlementFixtureKey('site-5');
  const immatureStaker = settlementFixtureKey('site-6');
  const inactiveStaker = settlementFixtureKey('site-7');
  const polOwner = settlementFixtureKey('site-8');
  const treasuryOwner = settlementFixtureKey('site-9');
  const usdcTreasuryOwner = settlementFixtureKey('site-10');

  let calMint: PublicKey;
  let dungMint: PublicKey;
  let usdcMint: PublicKey;
  let programConfig: PublicKey;
  let dungMintState: PublicKey;
  let vaultCounter: PublicKey;
  let climb: PublicKey;
  let vaultId: number;
  let vault: PublicKey;
  let vaultActivation: PublicKey;
  let vaultLeaderboard: PublicKey;
  let localLegend: PublicKey;
  let vaultLpMint: PublicKey;
  let vaultCalEscrow: PublicKey;
  let vaultStake: PublicKey;
  let riderBalance: PublicKey;
  let riderBalanceAuthority: PublicKey;
  let balanceVaultAuthority: PublicKey;
  let riderBalanceCalToken: PublicKey;
  let riderBalanceLpToken: PublicKey;
  let riderPositionLpToken: PublicKey;
  let riderBalanceUsdcToken: PublicKey;
  let rideAttestation: PublicKey;
  let riderSoul: PublicKey;
  let calMintReceipt: PublicKey;
  let climbCompletionReceipt: PublicKey;
  let riderCalAta: PublicKey;
  let riderDungAta: PublicKey;
  let riderUsdcAta: PublicKey;
  let attackerDungAta: PublicKey;
  let founderCalAta: PublicKey;
  let founderDungAta: PublicKey;
  let founderUsdcAta: PublicKey;
  let polAta: PublicKey;
  let treasuryAta: PublicKey;
  let usdcTreasuryAta: PublicKey;
  let riderLpAta: PublicKey;
  let settlementWeek: number;
  let completedAt: number;
  let activationSeedCutoff: number;
  const rideHash = hash32('truths:test:ride');
  const attestationCommitment = hash32('truths:test:attestation');
  const balanceVaultPolicyHash = hash32('truths:balance-vault-authority:v1');

  async function configureBalanceVaultOperationSigner(
    authority: PublicKey,
  ): Promise<void> {
    await program.methods
      .configureBalanceVaultAuthority(
        authority,
        Array.from(balanceVaultPolicyHash),
        new BN(Math.floor(Date.now() / 1000) + (6 * 24 * 60 * 60)),
      )
      .accounts({
        riderBalance,
        rider: rider.publicKey,
        balanceVaultAuthority,
        sponsorAuthority: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .signers([rider])
      .rpc();
  }

  async function balanceVaultAuthorization(
    kind: number,
    operationVaultId: number | bigint | BN,
    primaryAmount: number | bigint | BN,
    secondaryAmount: number | bigint | BN = 0,
    operationAuthority = activeBalanceVaultOperationSigner.publicKey,
    expiresAtOverride?: number,
  ): Promise<any> {
    const session = await (program.account as any).balanceVaultAuthority.fetch(
      balanceVaultAuthority,
    ) as any;
    const expiresAt = expiresAtOverride ?? Math.min(
      session.expiresAt.toNumber(),
      Math.floor(Date.now() / 1000) + 300,
    );
    const operationId = balanceVaultOperationId(
      rider.publicKey,
      operationAuthority,
      kind,
      operationVaultId,
      primaryAmount,
      secondaryAmount,
      session.generation,
      session.nextNonce,
      expiresAt,
    );
    return {
      operationId: Array.from(operationId),
      generation: session.generation,
      nonce: session.nextNonce,
      expiresAt: new BN(expiresAt),
    };
  }

  async function ensureSettlementEconomicPreconditions(): Promise<void> {
    const calEarned = 20_000n * CAL;

    if (await provider.connection.getAccountInfo(rideAttestation) === null) {
      await program.methods
        .recordRide(
          Array.from(rideHash),
          Array.from(attestationCommitment),
          1,
          1,
          new BN(completedAt),
          new BN(completedAt - 3600),
          20_000,
          42_000,
          900,
          bn(calEarned),
          1,
        )
        .accounts({
          rideAttestation,
          riderSoul,
          rider: rider.publicKey,
          programConfig,
          authority: wallet.publicKey,
          payer: wallet.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .rpc();
    }

    if (await provider.connection.getAccountInfo(calMintReceipt) === null) {
      await program.methods
        .creditCal(bn(calEarned))
        .accounts({
          rideAttestation,
          calMintReceipt,
          rider: rider.publicKey,
          programConfig,
          authority: wallet.publicKey,
          calMint,
          calMintAuth: findCalMintAuth()[0],
          destination: riderCalAta,
          payer: wallet.publicKey,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId,
        })
        .rpc();
    }

    const balanceCal = await getAccount(provider.connection, riderBalanceCalToken);
    if (balanceCal.amount < MIN_CAL_STAKE) {
      await transfer(
        provider.connection,
        wallet.payer,
        riderCalAta,
        riderBalanceCalToken,
        rider,
        MIN_CAL_STAKE - balanceCal.amount,
      );
    }

    if (await provider.connection.getAccountInfo(climbCompletionReceipt) === null) {
      const [rideTributeBudget] = findRideTributeBudget(rideAttestation);
      await program.methods
        .recordClimbCompletionV2(
          1_615,
          bn(CLIMB_CAL_TRIBUTE),
          completionEvidenceV2(
            rideAttestation,
            vault,
            1_615,
            CLIMB_CAL_TRIBUTE,
          ),
        )
        .accounts({
          rideAttestation,
          climbCompletionReceipt,
          vault,
          vaultCompletion: findVaultCompletion(rider.publicKey, vaultId)[0],
          vaultLeaderboard,
          vaultActivation,
          rider: rider.publicKey,
          programConfig,
          authority: wallet.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .remainingAccounts([{
          pubkey: rideTributeBudget,
          isWritable: true,
          isSigner: false,
        }])
        .rpc();
    }

    expect(
      (await getAccount(provider.connection, riderBalanceCalToken)).amount >= MIN_CAL_STAKE,
    ).to.equal(true);
    const leaderboard = await program.account.vaultLeaderboard.fetch(vaultLeaderboard) as any;
    expect(leaderboard.entries).to.have.length(1);
    expect(leaderboard.entries[0].user.toBase58()).to.equal(rider.publicKey.toBase58());
  }

  async function measureZeroStakeSettlementComputeUnits(): Promise<number> {
    const vaultAccount = await program.account.vault.fetch(vault) as any;
    expect(vaultAccount.stakerCount).to.equal(0);

    const settlement = program.methods
      .distributeEpochRewards(new BN(settlementWeek), DISTRIBUTION_CONFIG)
      .accounts({
        vault,
        vaultLeaderboard,
        localLegend,
        vaultActivation,
        polAccount: polAta,
        protocolTreasury: treasuryAta,
        dungMint,
        dungMintState,
        programConfig,
        backendAuthority: wallet.publicKey,
        dungMintAuth: findDungMintAuth()[0],
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .remainingAccounts([
        { pubkey: riderDungAta, isWritable: true, isSigner: false },
        { pubkey: founderDungAta, isWritable: true, isSigner: false },
      ]);
    const simulation = await provider.simulate(await settlement.transaction()) as any;
    return simulation.unitsConsumed as number;
  }

  async function registerCanonClimbVersion(
    identity: ReturnType<typeof canonCommitmentFrom>,
    canonVersion: number,
    name: string,
    vertM: number,
    distanceM: number,
    avgGradientPct: number,
    recordContinuityPolicy: any,
    predecessorClimb: PublicKey | null,
  ) {
    const [climbPda] = findClimb(identity.commitmentHash);
    const [climbVersionIndex] = findClimbVersionIndex(identity.canonId, canonVersion);
    await program.methods
      .registerRatifiedClimb({
        commitmentHash: Array.from(identity.commitmentHash),
        canonId: Array.from(identity.canonId),
        canonVersion,
        canonicalProfileHash: Array.from(identity.canonicalProfileHash),
        name,
        vertM,
        distanceM,
        avgGradientPct,
        recordContinuityPolicy,
      })
      .accounts({
        climb: climbPda,
        climbVersionIndex,
        predecessorClimb,
        programConfig,
        admin: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      } as any)
      .rpc();
    return { climb: climbPda, climbVersionIndex, ...identity };
  }

  async function registerCanonClimb(
    label: string,
    name: string,
    vertM: number,
    distanceM: number,
    avgGradientPct: number,
  ) {
    return registerCanonClimbVersion(
      canonCommitment(label),
      1,
      name,
      vertM,
      distanceM,
      avgGradientPct,
      { newRecordBoard: {} },
      null,
    );
  }

  async function createTestVaultFromCanon(accounts: {
    vault: PublicKey;
    climb: PublicKey;
    vaultLeaderboard: PublicKey;
    localLegend: PublicKey;
    vaultActivation: PublicKey;
  }): Promise<void> {
    await program.methods
      .createVaultWithUsdc()
      .accounts({
        vaultCounter,
        ...accounts,
        sponsorAuthority: wallet.publicKey,
        creator: founder.publicKey,
        creatorCalAccount: founderCalAta,
        protocolUsdcAccount: usdcTreasuryAta,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .remainingAccounts([
        { pubkey: calMint, isWritable: true, isSigner: false },
        { pubkey: programConfig, isWritable: false, isSigner: false },
        { pubkey: founderUsdcAta, isWritable: true, isSigner: false },
      ])
      .signers([founder])
      .rpc();
  }

  async function primeHistoricalSettlementWeek(
    vaultAddress: PublicKey,
    activationAddress: PublicKey,
    week: number,
  ): Promise<void> {
    await provider.sendAndConfirm(new Transaction().add(adminOverrideOpenSettlementWeekIx(
      program.programId, { vault: vaultAddress, programConfig, authority: wallet.publicKey },
      new BN(week),
    )));
    await provider.sendAndConfirm(new Transaction().add(adminSeedPendingRewardsIx(
      program.programId,
      { vault: vaultAddress, vaultActivation: activationAddress, programConfig, authority: wallet.publicKey },
      new BN(week),
      bn(1),
    )));
  }

  before(async function () {
    // The settlement story rewinds a fresh vault into a finalizable week with
    // test setup instructions that only the isolated localnet program carries.
    if (!SMOKE_HELPERS_PRESENT) this.skip();
    await Promise.all([
      airdrop(founder.publicKey),
      airdrop(rider.publicKey),
      airdrop(attacker.publicKey),
      airdrop(eligibleStaker.publicKey),
      airdrop(immatureStaker.publicKey),
      airdrop(inactiveStaker.publicKey),
      airdrop(polOwner.publicKey),
      airdrop(treasuryOwner.publicKey),
      airdrop(usdcTreasuryOwner.publicKey),
    ]);

    [programConfig] = findProgramConfig();
    [dungMintState] = findDungMintState();
    [vaultCounter] = findVaultCounter();
    calMint = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 9);
    dungMint = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 9);
    usdcMint = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 6);

    const [calMintAuth] = findCalMintAuth();
    const [dungMintAuth] = findDungMintAuth();

    riderCalAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      calMint,
      rider.publicKey,
    )).address;
    riderDungAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      dungMint,
      rider.publicKey,
    )).address;
    riderUsdcAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      usdcMint,
      rider.publicKey,
    )).address;
    attackerDungAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      dungMint,
      attacker.publicKey,
    )).address;
    founderDungAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      dungMint,
      founder.publicKey,
    )).address;
    founderCalAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      calMint,
      founder.publicKey,
    )).address;
    founderUsdcAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      usdcMint,
      founder.publicKey,
    )).address;
    polAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      dungMint,
      polOwner.publicKey,
    )).address;
    treasuryAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      dungMint,
      treasuryOwner.publicKey,
    )).address;
    usdcTreasuryAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      usdcMint,
      usdcTreasuryOwner.publicKey,
    )).address;

    await program.methods
      .initializeProgramConfig(wallet.publicKey)
      .accounts({
        programConfig,
        program: PROGRAM_ID,
        programData: await fetchProgramDataAddress(),
        admin: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const initializedConfig = await program.account.programConfig.fetch(programConfig) as any;
    expect(initializedConfig.programVersion).to.equal(CURRENT_PROGRAM_VERSION);
    expect(PREVIOUS_PROGRAM_VERSION).to.equal(CURRENT_PROGRAM_VERSION - 1);
    await expectRejected(
      program.methods
        .advanceProgramVersion(CURRENT_PROGRAM_VERSION - 1, CURRENT_PROGRAM_VERSION)
        .accounts({ programConfig, admin: attacker.publicKey })
        .signers([attacker])
        .rpc(),
      'UnauthorizedAdmin',
    );
    await expectRejected(
      program.methods
        .advanceProgramVersion(CURRENT_PROGRAM_VERSION - 1, CURRENT_PROGRAM_VERSION)
        .accounts({ programConfig, admin: wallet.publicKey })
        .rpc(),
      'StaleProgramVersion',
    );
    await expectRejected(
      program.methods
        .advanceProgramVersion(CURRENT_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION)
        .accounts({ programConfig, admin: wallet.publicKey })
        .rpc(),
      'RegressiveProgramVersion',
    );
    await expectRejected(
      program.methods
        .advanceProgramVersion(CURRENT_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION + 2)
        .accounts({ programConfig, admin: wallet.publicKey })
        .rpc(),
      'SkippedProgramVersion',
    );
    await expectRejected(
      program.methods
        .advanceProgramVersion(CURRENT_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION + 1)
        .accounts({ programConfig, admin: wallet.publicKey })
        .rpc(),
      'UnsupportedProgramVersion',
    );

    await program.methods
      .configureMints(calMint, dungMint)
      .accounts({
        programConfig,
        admin: wallet.publicKey,
      })
      .rpc();

    await program.methods
      .configureTreasuryAccounts(polAta, treasuryAta)
      .accounts({
        programConfig,
        admin: wallet.publicKey,
      })
      .rpc();

    await expectRejected(program.methods
      .configureUsdcPayment(bn(0))
      .accounts({
        programConfig,
        admin: wallet.publicKey,
        usdcMint,
        usdcTreasuryTokenAccount: usdcTreasuryAta,
      })
      .rpc());

    await program.methods
      .configureUsdcPayment(bn(VAULT_CREATION_USDC_PAYMENT))
      .accounts({
        programConfig,
        admin: wallet.publicKey,
        usdcMint,
        usdcTreasuryTokenAccount: usdcTreasuryAta,
      })
      .rpc();

    await setAuthority(
      provider.connection,
      wallet.payer,
      calMint,
      wallet.publicKey,
      AuthorityType.MintTokens,
      calMintAuth,
    );
    await setAuthority(
      provider.connection,
      wallet.payer,
      dungMint,
      wallet.publicKey,
      AuthorityType.MintTokens,
      dungMintAuth,
    );

    const vaultFundingRideHash = hash32('truths:test:v4b-vault-funding');
    const [vaultFundingAttestation] = findRideAttestation(
      founder.publicKey,
      vaultFundingRideHash,
    );
    const vaultFundingCompletedAt = Math.floor(Date.now() / 1000) - 60;
    const vaultFundingCal = 10_000n * CAL;
    await program.methods
      .recordRide(
        Array.from(vaultFundingRideHash),
        Array.from(hash32('truths:test:v4b-vault-funding-attestation')),
        1,
        1,
        new BN(vaultFundingCompletedAt),
        new BN(vaultFundingCompletedAt - 3600),
        10_000,
        42_000,
        900,
        bn(vaultFundingCal),
        0,
      )
      .accounts({
        rideAttestation: vaultFundingAttestation,
        riderSoul: findRiderSoul(founder.publicKey)[0],
        rider: founder.publicKey,
        programConfig,
        authority: wallet.publicKey,
        payer: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    await program.methods
      .creditCal(bn(vaultFundingCal))
      .accounts({
        rideAttestation: vaultFundingAttestation,
        calMintReceipt: findCalMintReceipt(
          vaultFundingAttestation,
          founder.publicKey,
        )[0],
        rider: founder.publicKey,
        programConfig,
        authority: wallet.publicKey,
        calMint,
        calMintAuth: findCalMintAuth()[0],
        destination: founderCalAta,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    await mintTo(
      provider.connection,
      wallet.payer,
      usdcMint,
      founderUsdcAta,
      wallet.payer,
      VAULT_CREATION_USDC_PAYMENT * 10n,
    );

    await expectRejected(program.methods
      .initializeDungMintState()
      .accounts({
        dungMintState,
        programConfig,
        authority: attacker.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .signers([attacker])
      .simulate());

    await program.methods
      .initializeDungMintState()
      .accounts({
        dungMintState,
        programConfig,
        authority: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    const initializedDungState = await program.account.dungMintState.fetch(dungMintState) as any;
    const emissionStartWeek = initializedDungState.lastHalvingEpoch.toNumber();
    expect(initializedDungState.reservationPolicyVersion).to.equal(1);

    await program.methods
      .initializeVaultCounter()
      .accounts({
        vaultCounter,
        authority: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const counter = await program.account.vaultCounter.fetch(vaultCounter) as { count: BN };
    vaultId = counter.count.toNumber();
    [vault] = findVault(vaultId);
    [vaultActivation] = findVaultActivation(vaultId);
    [vaultLeaderboard] = findVaultLeaderboard(vaultId);
    [localLegend] = findLocalLegend(vaultId);
    [vaultLpMint] = findVaultLpMint(vaultId);
    [vaultCalEscrow] = findVaultCalEscrow(vaultId);
    [vaultStake] = findVaultStake(rider.publicKey, vaultId);
    [riderBalance] = findRiderBalance(rider.publicKey);
    [riderBalanceAuthority] = findRiderBalanceAuthority(rider.publicKey);
    [balanceVaultAuthority] = findBalanceVaultAuthority(rider.publicKey);
    [riderBalanceCalToken] = findRiderBalanceToken(rider.publicKey, calMint);
    [riderBalanceLpToken] = findRiderBalanceToken(rider.publicKey, vaultLpMint);
    [riderPositionLpToken] = findVaultPositionLp(rider.publicKey, vaultId);
    [riderBalanceUsdcToken] = findRiderBalanceToken(rider.publicKey, usdcMint);

    climb = (await registerCanonClimb(
      'truths:test:climb',
      'Protocol Truths Climb',
      480,
      6200,
      775,
    )).climb;
    await createTestVaultFromCanon({
      vault,
      climb,
      vaultLeaderboard,
      localLegend,
      vaultActivation,
    });
    const cleanActivation = await program.account.vaultActivation.fetch(vaultActivation) as any;
    activationSeedCutoff = cleanActivation.seedCutoffAt.toNumber();

    settlementWeek = emissionStartWeek;
    completedAt = epochStart(settlementWeek) + 12 * 60 * 60;

    await primeHistoricalSettlementWeek(vault, vaultActivation, settlementWeek);

    await program.methods
      .initializeVaultLpMint()
      .accounts({
        vault,
        vaultLpMint,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .rpc();

    await program.methods
      .initializeVaultPositionLp()
      .accounts({
        vault,
        rider: rider.publicKey,
        vaultStake,
        vaultLpMint,
        positionLpAccount: riderPositionLpToken,
        sponsorAuthority: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const emptyPosition = await getAccount(provider.connection, riderPositionLpToken);
    expect(emptyPosition.amount).to.equal(0n);
    expect(emptyPosition.isFrozen).to.equal(true);
    expect(emptyPosition.owner.toBase58()).to.equal(vaultStake.toBase58());

    await program.methods
      .initializeVaultCalEscrow()
      .accounts({
        vault,
        programConfig,
        vaultCalEscrow,
        calMint,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .rpc();

    await program.methods
      .initializeRiderBalance()
      .accounts({
        riderBalance,
        rider: rider.publicKey,
        payer: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    await configureBalanceVaultOperationSigner(balanceVaultOperationSigner.publicKey);

    await program.methods
      .initializeRiderBalanceToken()
      .accounts({
        riderBalance,
        rider: rider.publicKey,
        riderBalanceAuthority,
        riderBalanceToken: riderBalanceCalToken,
        mint: calMint,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .rpc();

    await program.methods
      .initializeRiderBalanceToken()
      .accounts({
        riderBalance,
        rider: rider.publicKey,
        riderBalanceAuthority,
        riderBalanceToken: riderBalanceUsdcToken,
        mint: usdcMint,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .rpc();

    await program.methods
      .initializeRiderBalanceToken()
      .accounts({
        riderBalance,
        rider: rider.publicKey,
        riderBalanceAuthority,
        riderBalanceToken: riderBalanceLpToken,
        mint: vaultLpMint,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .rpc();

    riderLpAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      vaultLpMint,
      rider.publicKey,
    )).address;

    [rideAttestation] = findRideAttestation(rider.publicKey, rideHash);
    [riderSoul] = findRiderSoul(rider.publicKey);
    [calMintReceipt] = findCalMintReceipt(rideAttestation, rider.publicKey);
    [climbCompletionReceipt] = findClimbCompletionReceipt(rideAttestation, vault);
  });

  it('keeps current Local Legend migration admin-gated and byte-idempotent', async () => {
    const before = await provider.connection.getAccountInfo(localLegend, 'confirmed');
    expect(before).to.not.equal(null);

    await expectRejected(
      program.methods
        .migrateLocalLegend(new BN(vaultId))
        .accounts({
          localLegend,
          authority: attacker.publicKey,
          payer: attacker.publicKey,
          programConfig,
          systemProgram: SystemProgram.programId,
        })
        .signers([attacker])
        .rpc(),
      'UnauthorizedAdmin',
    );

    const afterRejected = await provider.connection.getAccountInfo(localLegend, 'confirmed');
    expect(afterRejected).to.not.equal(null);
    expect(afterRejected!.lamports).to.equal(before!.lamports);
    expect(afterRejected!.data.equals(before!.data)).to.equal(true);

    await program.methods
      .migrateLocalLegend(new BN(vaultId))
      .accounts({
        localLegend,
        authority: wallet.publicKey,
        payer: wallet.publicKey,
        programConfig,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const after = await provider.connection.getAccountInfo(localLegend, 'confirmed');
    expect(after).to.not.equal(null);
    expect(after!.lamports).to.equal(before!.lamports);
    expect(after!.data.equals(before!.data)).to.equal(true);
    const decoded = await program.account.localLegend.fetch(localLegend) as any;
    expect(decoded.isBootstrap).to.equal(true);
  });

  it('migrates a legacy Local Legend on-chain without changing economic bytes', async () => {
    const [derivedFixture, fixtureBump] = findLocalLegend(LEGACY_LOCAL_LEGEND_FIXTURE_VAULT_ID);
    expect(derivedFixture.equals(LEGACY_LOCAL_LEGEND_FIXTURE)).to.equal(true);
    expect(fixtureBump).to.equal(LOCALNET_TEST_BUILD ? 255 : 253);

    const before = await provider.connection.getAccountInfo(
      LEGACY_LOCAL_LEGEND_FIXTURE,
      'confirmed',
    );
    expect(before).to.not.equal(null);
    expect(before!.data.length).to.equal(122);
    expect(crypto.createHash('sha256').update(before!.data).digest('hex'))
      .to.equal(LEGACY_LOCAL_LEGEND_FIXTURE_SHA256);
    expect(await isRejected(
      program.account.localLegend.fetch(LEGACY_LOCAL_LEGEND_FIXTURE),
    )).to.equal(true);

    const migrationSignature = await program.methods
      .migrateLocalLegend(new BN(LEGACY_LOCAL_LEGEND_FIXTURE_VAULT_ID))
      .accounts({
        localLegend: LEGACY_LOCAL_LEGEND_FIXTURE,
        authority: wallet.publicKey,
        payer: wallet.publicKey,
        programConfig,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    const migrationTransaction = await getConfirmedTransaction(migrationSignature);
    expect(migrationTransaction).to.not.equal(null);

    const after = await provider.connection.getAccountInfo(
      LEGACY_LOCAL_LEGEND_FIXTURE,
      {
        commitment: 'confirmed',
        minContextSlot: migrationTransaction!.slot,
      },
    );
    expect(after).to.not.equal(null);
    expect(after!.data.length).to.equal(123);
    expect(after!.data.subarray(0, 121).equals(before!.data.subarray(0, 121))).to.equal(true);
    expect(after!.data[121]).to.equal(1);
    expect(after!.data[122]).to.equal(before!.data[121]);
    expect(after!.lamports).to.equal(
      Math.max(
        before!.lamports,
        await provider.connection.getMinimumBalanceForRentExemption(123),
      ),
    );

    const decoded = program.coder.accounts.decode('LocalLegend', after!.data) as any;
    expect(decoded.vaultId.toNumber()).to.equal(LEGACY_LOCAL_LEGEND_FIXTURE_VAULT_ID);
    expect(decoded.electionPeriod.toNumber()).to.equal(0);
    expect(decoded.termStartEpoch.toNumber()).to.equal(131);
    expect(decoded.termEndEpoch.toNumber()).to.equal(139);
    expect(decoded.completionsAtElection).to.equal(0);
    expect(decoded.totalEarned.toNumber()).to.equal(123_456_789);
    expect(decoded.isActive).to.equal(true);
    expect(decoded.isBootstrap).to.equal(true);
    expect(decoded.bump).to.equal(fixtureBump);

    const rerunSignature = await program.methods
      .migrateLocalLegend(new BN(LEGACY_LOCAL_LEGEND_FIXTURE_VAULT_ID))
      .accounts({
        localLegend: LEGACY_LOCAL_LEGEND_FIXTURE,
        authority: wallet.publicKey,
        payer: wallet.publicKey,
        programConfig,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    const rerunTransaction = await getConfirmedTransaction(rerunSignature);
    expect(rerunTransaction).to.not.equal(null);

    const afterRerun = await provider.connection.getAccountInfo(
      LEGACY_LOCAL_LEGEND_FIXTURE,
      {
        commitment: 'confirmed',
        minContextSlot: rerunTransaction!.slot,
      },
    );
    expect(afterRerun).to.not.equal(null);
    expect(afterRerun!.lamports).to.equal(after!.lamports);
    expect(afterRerun!.data.equals(after!.data)).to.equal(true);
  });

  it('commits the vault activation audit boundary before live economics', async () => {
    const activation = await program.account.vaultActivation.fetch(vaultActivation) as any;
    const seededVault = await program.account.vault.fetch(vault) as any;

    expect(activation.isActive).to.equal(true);
    expect(activation.seedGeneration).to.equal(2);
    expect(activation.seedCutoffAt.toNumber()).to.equal(activationSeedCutoff);
    expect(activation.economicsStartEpoch.toNumber()).to.be.greaterThan(0);
    expect(activation.matchedUsers).to.equal(0);
    expect(activation.matchedCompletions).to.equal(0);
    const expectedEmptyHistoryEvidence = crypto.createHash('sha256').update(Buffer.concat([
      Buffer.from('BR_VAULT_EMPTY_HISTORY_V2'),
      climb.toBuffer(),
      vault.toBuffer(),
    ])).digest();
    expect(Buffer.from(activation.evidenceHash).equals(expectedEmptyHistoryEvidence)).to.equal(true);
    expect(activation.leaderboardSeeded).to.equal(true);
    expect(bnToBigInt(seededVault.totalCompletions)).to.equal(0n);
    expect(seededVault.climb.toBase58()).to.equal(climb.toBase58());
    expect(seededVault.komHolder.toBase58()).to.equal(PublicKey.default.toBase58());
    expect(seededVault.komTimeS).to.equal(0);
  });

  it('records a canonical ride attestation and mints CAL exactly once through its receipt', async () => {
    const calEarned = 20_000n * CAL;

    await program.methods
      .recordRide(
        Array.from(rideHash),
        Array.from(attestationCommitment),
        1,
        1,
        new BN(completedAt),
        new BN(completedAt - 3600),
        20_000,
        42_000,
        900,
        bn(calEarned),
        1,
      )
      .accounts({
        rideAttestation,
        riderSoul,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        payer: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const attestation = await program.account.rideAttestation.fetch(rideAttestation) as any;
    expect(Buffer.from(attestation.rideHash).equals(rideHash)).to.equal(true);
    expect(attestation.rider.toBase58()).to.equal(rider.publicKey.toBase58());
    expect(attestation.economicEpoch.toNumber()).to.equal(settlementWeek);
    expect(bnToBigInt(attestation.calEarned)).to.equal(calEarned);

    await program.methods
      .creditCal(bn(calEarned))
      .accounts({
        rideAttestation,
        calMintReceipt,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        calMint,
        calMintAuth: findCalMintAuth()[0],
        destination: riderCalAta,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const calAccount = await getAccount(provider.connection, riderCalAta);
    expect(calAccount.amount).to.equal(calEarned);

    await transfer(
      provider.connection,
      wallet.payer,
      riderCalAta,
      riderBalanceCalToken,
      rider,
      MIN_CAL_STAKE,
    );

    const balanceCalAccount = await getAccount(provider.connection, riderBalanceCalToken);
    expect(balanceCalAccount.amount).to.equal(MIN_CAL_STAKE);

    await expectRejected(program.methods
      .creditCal(bn(calEarned))
      .accounts({
        rideAttestation,
        calMintReceipt,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        calMint,
        calMintAuth: findCalMintAuth()[0],
        destination: riderCalAta,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .rpc());
  });

  it('bounds one ride attestation: CAL by its declared TSS, TSS by its duration', async () => {
    // A fresh rider keeps the boundary ride out of every later total.
    const boundedRider = Keypair.generate().publicKey;
    const boundedHash = hash32('truths:test:bounded-ride');
    const boundedAttestation = findRideAttestation(boundedRider, boundedHash)[0];
    const hourStart = completedAt - 3600;
    const recordBounded = (totalTss: number, calEarned: bigint) => program.methods
      .recordRide(
        Array.from(boundedHash),
        Array.from(attestationCommitment),
        1,
        1,
        new BN(completedAt),
        new BN(hourStart),
        totalTss,
        42_000,
        900,
        bn(calEarned),
        1,
      )
      .accounts({
        rideAttestation: boundedAttestation,
        riderSoul: findRiderSoul(boundedRider)[0],
        rider: boundedRider,
        programConfig,
        authority: wallet.publicKey,
        payer: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    // One whole CAL per TSS: 250 TSS cannot carry 251 CAL.
    await expectRejected(recordBounded(250, 251n * CAL), 'RideCalExceedsTss');
    // IF 40 sustains 160,000 TSS in one hour, and no more.
    await expectRejected(recordBounded(160_001, 0n), 'RideTssExceedsDuration');
    // The exact ceiling, with the backend's sub-CAL remainder, is admitted.
    const ceilingCal = 160_000n * CAL + (CAL - 1n);
    await recordBounded(160_000, ceilingCal);
    const attestation = await program.account.rideAttestation.fetch(boundedAttestation) as any;
    expect(attestation.totalTss).to.equal(160_000);
    expect(bnToBigInt(attestation.calEarned)).to.equal(ceilingCal);
  });

  it('rejects a custom LP mint destination before creating a position', async () => {
    const attackerLpAccount = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      vaultLpMint,
      attacker.publicKey,
    )).address;
    const riderCalBefore = (await getAccount(provider.connection, riderCalAta)).amount;
    const attackerLpBefore = (await getAccount(provider.connection, attackerLpAccount)).amount;

    await expectRejected(program.methods
      .stakeCalInVault(bn(MIN_CAL_STAKE))
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        programConfig,
        sponsorAuthority: wallet.publicKey,
        staker: rider.publicKey,
        stakerCalAta: riderCalAta,
        vaultCalEscrow,
        vaultLpMint,
        stakerLpAccount: attackerLpAccount,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([rider])
      .rpc());

    expect((await getAccount(provider.connection, riderCalAta)).amount).to.equal(riderCalBefore);
    expect((await getAccount(provider.connection, attackerLpAccount)).amount).to.equal(attackerLpBefore);
    expect(await provider.connection.getAccountInfo(vaultStake)).to.equal(null);
  });

  it.skip('V4-A-only 617-byte fixture: restores split legacy LP incrementally and quarantines drift until exact', async () => {
    const legacyRider = Keypair.fromSeed(Uint8Array.from({ length: 32 }, () => 7));
    const legacyWalletSource = Keypair.fromSeed(
      Uint8Array.from({ length: 32 }, () => 8),
    ).publicKey;
    const [legacyVault] = findVault(LEGACY_LP_FIXTURE_VAULT_ID);
    const [legacyVaultStake] = findVaultStake(
      legacyRider.publicKey,
      LEGACY_LP_FIXTURE_VAULT_ID,
    );
    const [legacyActivation] = findVaultActivation(LEGACY_LP_FIXTURE_VAULT_ID);
    const [legacyLpMint] = findVaultLpMint(LEGACY_LP_FIXTURE_VAULT_ID);
    const [legacyBalanceAuthority] = findRiderBalanceAuthority(legacyRider.publicKey);
    const [legacyBalanceSource] = findRiderBalanceToken(
      legacyRider.publicKey,
      legacyLpMint,
    );
    const [legacyPosition] = findVaultPositionLp(
      legacyRider.publicKey,
      LEGACY_LP_FIXTURE_VAULT_ID,
    );
    const [legacyCalEscrow] = findVaultCalEscrow(LEGACY_LP_FIXTURE_VAULT_ID);
    const legacyCalDestination = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      calMint,
      legacyRider.publicKey,
    )).address;

    expect(legacyVault.toBase58()).to.equal(
      'HDJtP54A1U5kqJc2J4UvhfzMxnzVT8Yz4a9fY61sY7Wm',
    );
    expect(legacyWalletSource.toBase58()).to.equal(
      '2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1',
    );
    expect(await provider.connection.getAccountInfo(legacyPosition)).to.equal(null);

    await program.methods
      .initializeVaultCalEscrow()
      .accounts({
        vault: legacyVault,
        programConfig,
        vaultCalEscrow: legacyCalEscrow,
        calMint,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY,
      })
      .rpc();
    await transfer(
      provider.connection,
      wallet.payer,
      riderCalAta,
      legacyCalEscrow,
      rider,
      102n * CAL,
    );

    await program.methods
      .restoreVaultLpCustody(bn(LEGACY_LP_WALLET_RESTORE))
      .accounts({
        vault: legacyVault,
        vaultStake: legacyVaultStake,
        rider: legacyRider.publicKey,
        vaultLpMint: legacyLpMint,
        sourceAuthority: legacyRider.publicKey,
        sourceLpAccount: legacyWalletSource,
        positionLpAccount: legacyPosition,
        sponsorAuthority: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([legacyRider])
      .rpc();

    const partialPosition = await getAccount(provider.connection, legacyPosition);
    expect(partialPosition.amount).to.equal(LEGACY_LP_WALLET_RESTORE);
    expect(partialPosition.isFrozen).to.equal(true);
    expect((await getAccount(provider.connection, legacyWalletSource)).amount).to.equal(1n * CAL);

    await expectRejected(
      program.methods
        .unstakeCalFromVault(bn(1n))
        .accounts({
          vault: legacyVault,
          vaultStake: legacyVaultStake,
          vaultActivation: legacyActivation,
          programConfig,
          staker: legacyRider.publicKey,
          stakerCalAta: legacyCalDestination,
          vaultCalEscrow: legacyCalEscrow,
          calMint,
          vaultLpMint: legacyLpMint,
          stakerLpAccount: legacyPosition,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .signers([legacyRider])
        .rpc(),
      'LpCustodyAmountMismatch',
    );

    await expectRejected(transfer(
      provider.connection,
      wallet.payer,
      legacyWalletSource,
      legacyPosition,
      legacyRider,
      1n,
    ));
    expect((await getAccount(provider.connection, legacyWalletSource)).amount).to.equal(1n * CAL);
    expect((await getAccount(provider.connection, legacyPosition)).amount)
      .to.equal(LEGACY_LP_WALLET_RESTORE);

    const balanceBeforeOverfill = (
      await getAccount(provider.connection, legacyBalanceSource)
    ).amount;
    await expectRejected(
      program.methods
        .restoreBalanceVaultLpCustody(bn(LEGACY_LP_BALANCE_SOURCE))
        .accounts({
          vault: legacyVault,
          vaultStake: legacyVaultStake,
          rider: legacyRider.publicKey,
          riderBalanceAuthority: legacyBalanceAuthority,
          vaultLpMint: legacyLpMint,
          riderBalanceLpAccount: legacyBalanceSource,
          positionLpAccount: legacyPosition,
          sponsorAuthority: wallet.publicKey,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId,
        })
        .rpc(),
      'LpCustodyAmountMismatch',
    );
    expect((await getAccount(provider.connection, legacyBalanceSource)).amount)
      .to.equal(balanceBeforeOverfill);
    expect((await getAccount(provider.connection, legacyPosition)).amount)
      .to.equal(LEGACY_LP_WALLET_RESTORE);

    await program.methods
      .restoreBalanceVaultLpCustody(bn(60n * CAL))
      .accounts({
        vault: legacyVault,
        vaultStake: legacyVaultStake,
        rider: legacyRider.publicKey,
        riderBalanceAuthority: legacyBalanceAuthority,
        vaultLpMint: legacyLpMint,
        riderBalanceLpAccount: legacyBalanceSource,
        positionLpAccount: legacyPosition,
        sponsorAuthority: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const sealedPosition = await getAccount(provider.connection, legacyPosition);
    expect(sealedPosition.amount).to.equal(LEGACY_LP_RECORDED);
    expect(sealedPosition.isFrozen).to.equal(true);
    expect(sealedPosition.owner.toBase58()).to.equal(legacyVaultStake.toBase58());
    expect((await getAccount(provider.connection, legacyBalanceSource)).amount).to.equal(1n * CAL);

    const destinationBefore = (
      await getAccount(provider.connection, legacyCalDestination)
    ).amount;
    await program.methods
      .unstakeCalFromVault(bn(LEGACY_LP_RECORDED))
      .accounts({
        vault: legacyVault,
        vaultStake: legacyVaultStake,
        vaultActivation: legacyActivation,
        programConfig,
        staker: legacyRider.publicKey,
        stakerCalAta: legacyCalDestination,
        vaultCalEscrow: legacyCalEscrow,
        calMint,
        vaultLpMint: legacyLpMint,
        stakerLpAccount: legacyPosition,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([legacyRider])
      .rpc();

    const restoredStake = await program.account.vaultStake.fetch(legacyVaultStake) as any;
    expect((await getAccount(provider.connection, legacyPosition)).amount).to.equal(0n);
    expect((await getAccount(provider.connection, legacyPosition)).isFrozen).to.equal(true);
    expect((await getAccount(provider.connection, legacyCalDestination)).amount - destinationBefore)
      .to.equal(LEGACY_LP_RECORDED - (LEGACY_LP_RECORDED * 50n / 10_000n));
    expect((await getAccount(provider.connection, legacyCalEscrow)).amount).to.equal(2n * CAL);
    expect((await getMint(provider.connection, legacyLpMint)).supply).to.equal(2n * CAL);
    expect(bnToBigInt(restoredStake.calStaked)).to.equal(0n);
    expect(bnToBigInt(restoredStake.lpTokens)).to.equal(0n);
  });

  it('activates a Vault only from one ratified Climb and blocks legacy seeding', async () => {
    const counter = await program.account.vaultCounter.fetch(vaultCounter) as { count: BN };
    const cleanVaultId = counter.count.toNumber();
    const [cleanVault] = findVault(cleanVaultId);
    const [cleanLocalLegend] = findLocalLegend(cleanVaultId);
    const [cleanActivation] = findVaultActivation(cleanVaultId);
    const registered = await registerCanonClimb(
      'truths:test:clean-vault',
      'Clean Canon Vault',
      300,
      3000,
      500,
    );

    await createTestVaultFromCanon({
      vault: cleanVault,
      climb: registered.climb,
      vaultLeaderboard: findVaultLeaderboard(cleanVaultId)[0],
      localLegend: cleanLocalLegend,
      vaultActivation: cleanActivation,
    });

    const activation = await program.account.vaultActivation.fetch(cleanActivation) as any;
    const activatedClimb = await (program.account as any).climb.fetch(registered.climb) as any;
    const createdVault = await program.account.vault.fetch(cleanVault) as any;
    expect(activation.isActive).to.equal(true);
    expect(activation.seedGeneration).to.equal(2);
    expect(activation.leaderboardSeeded).to.equal(true);
    expect(Buffer.from(activation.evidenceHash).equals(Buffer.alloc(32))).to.equal(false);
    expect(activatedClimb.vault.toBase58()).to.equal(cleanVault.toBase58());
    expect(createdVault.climb.toBase58()).to.equal(registered.climb.toBase58());
    expect(Buffer.from(createdVault.signature).equals(registered.commitment)).to.equal(true);
    expect(createdVault.vertM).to.equal(300);
    expect(createdVault.distanceM).to.equal(3000);
    expect(createdVault.avgGradientPct).to.equal(500);

    await expectRejected(
      program.methods
        .adminReplaceVaultLeaderboard([])
        .accounts({
          vault: cleanVault,
          vaultLeaderboard: findVaultLeaderboard(cleanVaultId)[0],
          vaultActivation: cleanActivation,
          programConfig,
          authority: wallet.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .rpc(),
      'VaultAlreadyActive',
    );
    await expectRejected(
      program.methods
        .adminActivateVault(
          new BN(cleanVaultId),
          new BN(0),
          PublicKey.default,
          0,
          new BN(0),
          2,
          new BN(activationSeedCutoff),
          0,
          0,
          Array.from(hash32('must-not-replace-chain-activation')),
        )
        .accounts({
          vault: cleanVault,
          vaultActivation: cleanActivation,
          programConfig,
          authority: wallet.publicKey,
        })
        .rpc(),
      'VaultAlreadyActive',
    );

    const nextCounter = await program.account.vaultCounter.fetch(vaultCounter) as { count: BN };
    const duplicateVaultId = nextCounter.count.toNumber();
    await expectRejected(
      createTestVaultFromCanon({
        vault: findVault(duplicateVaultId)[0],
        climb: registered.climb,
        vaultLeaderboard: findVaultLeaderboard(duplicateVaultId)[0],
        localLegend: findLocalLegend(duplicateVaultId)[0],
        vaultActivation: findVaultActivation(duplicateVaultId)[0],
      }),
      'ClimbAlreadyActivated',
    );
    await expectRejected(
      createTestVaultFromCanon({
        vault: findVault(duplicateVaultId)[0],
        climb: programConfig,
        vaultLeaderboard: findVaultLeaderboard(duplicateVaultId)[0],
        localLegend: findLocalLegend(duplicateVaultId)[0],
        vaultActivation: findVaultActivation(duplicateVaultId)[0],
      }),
    );
  });

  it('registers only exact admin-ratified v1 and successor canon lineage', async () => {
    const genesis = await registerCanonClimb(
      'truths:test:lineage',
      'Lineage Genesis',
      350,
      3_500,
      600,
    );
    await expectRejected(
      registerCanonClimbVersion(
        canonCommitmentFrom(genesis.canonId, 3, hash32('profile:lineage:skipped-v3')),
        3,
        'Skipped Revision',
        352,
        3_500,
        602,
        { newRecordBoard: {} },
        genesis.climb,
      ),
      'InvalidCanonLineage',
    );
    await expectRejected(
      registerCanonClimbVersion(
        canonCommitment('truths:test:wrong-lineage', 2),
        2,
        'Wrong Lineage',
        352,
        3_500,
        602,
        { newRecordBoard: {} },
        genesis.climb,
      ),
      'InvalidCanonLineage',
    );

    const successorIdentity = canonCommitmentFrom(
      genesis.canonId,
      2,
      hash32('profile:truths:test:lineage:v2'),
    );
    await expectRejected(
      registerCanonClimbVersion(
        successorIdentity,
        2,
        'False Carry Revision',
        351,
        3_500,
        601,
        { carryRecordsForward: {} },
        genesis.climb,
      ),
      'RecordContinuityUnavailable',
    );
    const successor = await registerCanonClimbVersion(
      successorIdentity,
      2,
      'Lineage Revision',
      351,
      3_500,
      601,
      { newRecordBoard: {} },
      genesis.climb,
    );
    const successorAccount = await (program.account as any).climb.fetch(successor.climb) as any;
    expect(successorAccount.canonVersion).to.equal(2);
    expect(successorAccount.predecessorClimb.toBase58()).to.equal(genesis.climb.toBase58());
    expect(successorAccount.successorClimb.toBase58()).to.equal(PublicKey.default.toBase58());
    expect(successorAccount.recordContinuityPolicy).to.deep.equal({ newRecordBoard: {} });
    const persistedGenesis = await (program.account as any).climb.fetch(genesis.climb) as any;
    expect(persistedGenesis.successorClimb.toBase58()).to.equal(successor.climb.toBase58());

    await expectRejected(
      registerCanonClimbVersion(
        canonCommitmentFrom(genesis.canonId, 3, hash32('profile:lineage:branch-v3')),
        3,
        'Branch Revision',
        352,
        3_500,
        602,
        { newRecordBoard: {} },
        genesis.climb,
      ),
      'CanonSuccessorAlreadyRegistered',
    );

    const counter = await program.account.vaultCounter.fetch(vaultCounter) as { count: BN };
    const staleVaultId = counter.count.toNumber();
    await expectRejected(
      createTestVaultFromCanon({
        vault: findVault(staleVaultId)[0],
        climb: genesis.climb,
        vaultLeaderboard: findVaultLeaderboard(staleVaultId)[0],
        localLegend: findLocalLegend(staleVaultId)[0],
        vaultActivation: findVaultActivation(staleVaultId)[0],
      }),
      'StaleClimbVersion',
    );
    await expectRejected(
      registerCanonClimbVersion(
        canonCommitment('truths:test:invalid-genesis-policy'),
        1,
        'Invalid Genesis',
        352,
        3_500,
        602,
        { carryRecordsForward: {} },
        null,
      ),
      'RecordContinuityUnavailable',
    );

    const mismatched = canonCommitment('truths:test:mismatched-commitment');
    mismatched.commitmentHash = hash32('not-the-d12-commitment-hash');
    await expectRejected(
      registerCanonClimbVersion(
        mismatched,
        1,
        'Mismatched Commitment',
        352,
        3_500,
        602,
        { newRecordBoard: {} },
        null,
      ),
      'InvalidCanonCommitment',
    );

    const unauthorized = canonCommitment('truths:test:unauthorized-registration');
    await expectRejected(
      program.methods
        .registerRatifiedClimb({
          commitmentHash: Array.from(unauthorized.commitmentHash),
          canonId: Array.from(unauthorized.canonId),
          canonVersion: 1,
          canonicalProfileHash: Array.from(unauthorized.canonicalProfileHash),
          name: 'Unauthorized Climb',
          vertM: 400,
          distanceM: 4_000,
          avgGradientPct: 700,
          recordContinuityPolicy: { newRecordBoard: {} },
        })
        .accounts({
          climb: findClimb(unauthorized.commitmentHash)[0],
          climbVersionIndex: findClimbVersionIndex(unauthorized.canonId, 1)[0],
          predecessorClimb: null,
          programConfig,
          admin: attacker.publicKey,
          systemProgram: SystemProgram.programId,
        } as any)
        .signers([attacker])
        .rpc(),
      'UnauthorizedAdmin',
    );
  });

  it('anchors a climb completion to the ride and structurally blocks replay', async () => {
    const [rideTributeBudget] = findRideTributeBudget(rideAttestation);
    const completionEvidenceHash = completionEvidenceV2(
      rideAttestation,
      vault,
      1_615,
      CLIMB_CAL_TRIBUTE,
    );
    const nuisancePrefund = await provider.connection.getMinimumBalanceForRentExemption(0);
    await provider.sendAndConfirm(
      new anchor.web3.Transaction().add(
        SystemProgram.transfer({
          fromPubkey: wallet.publicKey,
          toPubkey: rideTributeBudget,
          lamports: nuisancePrefund,
        }),
      ),
    );

    const budgetBeforeMismatch = await provider.connection.getAccountInfo(rideTributeBudget);
    await expectRejected(
      program.methods
        .recordClimbCompletionV2(
          1_615,
          bn(CLIMB_CAL_TRIBUTE),
          completionEvidenceV2(
            rideAttestation,
            vault,
            1_615,
            CLIMB_CAL_TRIBUTE + 1n,
          ),
        )
        .accounts({
          rideAttestation,
          climbCompletionReceipt,
          vault,
          vaultCompletion: findVaultCompletion(rider.publicKey, vaultId)[0],
          vaultLeaderboard,
          vaultActivation,
          rider: rider.publicKey,
          programConfig,
          authority: wallet.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .remainingAccounts([{
          pubkey: rideTributeBudget,
          isWritable: true,
          isSigner: false,
        }])
        .rpc(),
      'Completion evidence hash does not bind the exact V2 tribute fields',
    );
    expect(await provider.connection.getAccountInfo(climbCompletionReceipt)).to.equal(null);
    const budgetAfterMismatch = await provider.connection.getAccountInfo(rideTributeBudget);
    expect(budgetAfterMismatch?.lamports).to.equal(budgetBeforeMismatch?.lamports);
    expect(Buffer.from(budgetAfterMismatch?.data ?? [])).to.deep.equal(
      Buffer.from(budgetBeforeMismatch?.data ?? []),
    );

    await expectRejected(
      program.methods
        .recordClimbCompletionV2(1_615, bn(CLIMB_CAL_TRIBUTE), completionEvidenceHash)
        .accounts({
          rideAttestation,
          climbCompletionReceipt,
          vault,
          vaultCompletion: findVaultCompletion(rider.publicKey, vaultId)[0],
          vaultLeaderboard,
          vaultActivation,
          rider: rider.publicKey,
          programConfig,
          authority: wallet.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .rpc(),
      'Ride tribute budget account is missing or invalid',
    );

    await program.methods
      .recordClimbCompletionV2(1_615, bn(CLIMB_CAL_TRIBUTE), completionEvidenceHash)
      .accounts({
        rideAttestation,
        climbCompletionReceipt,
        vault,
        vaultCompletion: findVaultCompletion(rider.publicKey, vaultId)[0],
        vaultLeaderboard,
        vaultActivation,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .remainingAccounts([{
        pubkey: rideTributeBudget,
        isWritable: true,
        isSigner: false,
      }])
      .rpc();

    const budget = await program.account.rideTributeBudget.fetch(rideTributeBudget) as any;
    expect(bnToBigInt(budget.calBudget)).to.equal(calTributeBudget(20_000n * CAL));
    expect(bnToBigInt(budget.totalCalTributed)).to.equal(CLIMB_CAL_TRIBUTE);

    const vaultAccount = await program.account.vault.fetch(vault) as any;
    expect(vaultAccount.komHolder.toBase58()).to.equal(rider.publicKey.toBase58());
    expect(vaultAccount.komTimeS).to.equal(1_615);
    expect(vaultAccount.komSetEpoch.toNumber()).to.equal(settlementWeek);

    const receipt = await program.account.climbCompletionReceiptV2.fetch(climbCompletionReceipt) as any;
    expect(receipt.evidenceVersion).to.equal(2);
    expect(bnToBigInt(receipt.calTributed)).to.equal(CLIMB_CAL_TRIBUTE);
    expect(Buffer.from(receipt.completionEvidenceHash)).to.deep.equal(
      Buffer.from(completionEvidenceHash),
    );

    const leaderboard = await program.account.vaultLeaderboard.fetch(vaultLeaderboard) as any;
    expect(leaderboard.entries).to.have.length(1);
    expect(leaderboard.entries[0].user.toBase58()).to.equal(rider.publicKey.toBase58());
    expect(leaderboard.entries[0].timeS).to.equal(1_615);
    expect(leaderboard.entries[0].recordedAt.toNumber()).to.equal(completedAt);

    await expectRejected(program.methods
      .recordClimbCompletionV2(1_615, bn(CLIMB_CAL_TRIBUTE), completionEvidenceHash)
      .accounts({
        rideAttestation,
        climbCompletionReceipt,
        vault,
        vaultCompletion: findVaultCompletion(rider.publicKey, vaultId)[0],
        vaultLeaderboard,
        vaultActivation,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .remainingAccounts([{
        pubkey: findRideTributeBudget(rideAttestation)[0],
        isWritable: true,
        isSigner: false,
      }])
      .rpc());
  });

  it('records and pays a delayed ride through the receipt-backed path', async () => {
    const counter = await program.account.vaultCounter.fetch(vaultCounter) as { count: BN };
    const lateVaultId = counter.count.toNumber();
    const [lateVault] = findVault(lateVaultId);
    const [lateActivation] = findVaultActivation(lateVaultId);
    const [lateLeaderboard] = findVaultLeaderboard(lateVaultId);
    const [lateLegend] = findLocalLegend(lateVaultId);
    const lateCompletedAt = completedAt - (10 * 24 * 60 * 60);
    const lateRideHash = hash32('truths:late-ride:lifetime-flow');
    const lateCommitment = hash32('truths:late-ride:attestation');
    const [lateRideAttestation] = findRideAttestation(rider.publicKey, lateRideHash);
    const [lateRideTributeBudget] = findRideTributeBudget(lateRideAttestation);
    const [lateCalReceipt] = findCalMintReceipt(lateRideAttestation, rider.publicKey);
    const [lateCompletionReceipt] = findClimbCompletionReceipt(lateRideAttestation, lateVault);
    const lateCalEarned = 20_000n * CAL;
    const lateCalTribute = (2n * DUNG * 1_000n) - VAULT_CREATION_CAL_DEPOSIT;

    const lateClimb = (await registerCanonClimb(
      'truths:late-ride:lifetime-flow',
      'Delayed Ride Climb',
      410,
      4_100,
      1_000,
    )).climb;
    await createTestVaultFromCanon({
      vault: lateVault,
      climb: lateClimb,
      vaultLeaderboard: lateLeaderboard,
      localLegend: lateLegend,
      vaultActivation: lateActivation,
    });

    await primeHistoricalSettlementWeek(
      lateVault,
      lateActivation,
      settlementWeek,
    );

    await program.methods
      .recordRide(
        Array.from(lateRideHash),
        Array.from(lateCommitment),
        1,
        1,
        new BN(lateCompletedAt),
        new BN(lateCompletedAt - 3_600),
        20_000,
        32_000,
        700,
        bn(lateCalEarned),
        1,
      )
      .accounts({
        rideAttestation: lateRideAttestation,
        riderSoul,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        payer: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const lateAttestation = await program.account.rideAttestation.fetch(lateRideAttestation) as any;
    expect(lateAttestation.economicEpoch.toNumber()).to.be.at.most(settlementWeek - 2);

    await program.methods
      .recordClimbCompletionV2(
        900,
        bn(lateCalTribute),
        completionEvidenceV2(lateRideAttestation, lateVault, 900, lateCalTribute),
      )
      .accounts({
        rideAttestation: lateRideAttestation,
        climbCompletionReceipt: lateCompletionReceipt,
        vault: lateVault,
        vaultCompletion: findVaultCompletion(rider.publicKey, lateVaultId)[0],
        vaultLeaderboard: lateLeaderboard,
        vaultActivation: lateActivation,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .remainingAccounts([{
        pubkey: lateRideTributeBudget,
        isWritable: true,
        isSigner: false,
      }])
      .rpc();

    const completionReceipt = await program.account.climbCompletionReceiptV2.fetch(
      lateCompletionReceipt,
    ) as any;
    expect(completionReceipt.rideAttestation.toBase58()).to.equal(
      lateRideAttestation.toBase58(),
    );
    const lateBudgetAfterFirst = await program.account.rideTributeBudget.fetch(
      lateRideTributeBudget,
    ) as any;
    expect(bnToBigInt(lateBudgetAfterFirst.calBudget)).to.equal(
      calTributeBudget(lateCalEarned),
    );
    expect(bnToBigInt(lateBudgetAfterFirst.totalCalTributed)).to.equal(lateCalTribute);
    await program.methods
      .verifyRideTributeBudget()
      .accounts({
        rideAttestation: lateRideAttestation,
        rideTributeBudget: lateRideTributeBudget,
      })
      .rpc();

    const lateBudgetRemainder = calTributeBudget(lateCalEarned) - lateCalTribute;
    await expectRejected(
      program.methods
        .recordClimbCompletionV2(
          901,
          bn(lateBudgetRemainder + 1n),
          completionEvidenceV2(
            lateRideAttestation,
            vault,
            901,
            lateBudgetRemainder + 1n,
          ),
        )
        .accounts({
          rideAttestation: lateRideAttestation,
          climbCompletionReceipt: findClimbCompletionReceipt(lateRideAttestation, vault)[0],
          vault,
          vaultCompletion: findVaultCompletion(rider.publicKey, vaultId)[0],
          vaultLeaderboard,
          vaultActivation,
          rider: rider.publicKey,
          programConfig,
          authority: wallet.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .remainingAccounts([{
          pubkey: lateRideTributeBudget,
          isWritable: true,
          isSigner: false,
        }])
        .rpc(),
      'Ride aggregate tribute exceeds ratified CAL tribute budget',
    );
    const lateBudgetAfterRejection = await program.account.rideTributeBudget.fetch(
      lateRideTributeBudget,
    ) as any;
    expect(bnToBigInt(lateBudgetAfterRejection.totalCalTributed)).to.equal(lateCalTribute);

    const calBefore = (await getAccount(provider.connection, riderCalAta)).amount;
    await program.methods
      .creditCal(bn(lateCalEarned))
      .accounts({
        rideAttestation: lateRideAttestation,
        calMintReceipt: lateCalReceipt,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        calMint,
        calMintAuth: findCalMintAuth()[0],
        destination: riderCalAta,
        payer: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    const calAfter = (await getAccount(provider.connection, riderCalAta)).amount;
    expect(calAfter - calBefore).to.equal(lateCalEarned);

    const lateBoard = await program.account.vaultLeaderboard.fetch(lateLeaderboard) as any;
    expect(lateBoard.entries.map((entry: any) => entry.timeS)).to.deep.equal([900]);
    expect(lateBoard.entries[0].recordedAt.toNumber()).to.equal(lateCompletedAt);

    const lateVaultBefore = await program.account.vault.fetch(lateVault) as any;
    expect(lateVaultBefore.openSettlementWeek.toNumber()).to.equal(settlementWeek);
    expect(bnToBigInt(lateVaultBefore.pendingRewards)).to.equal(2n * DUNG);
    expect(bnToBigInt(lateVaultBefore.calTributeAccumulated)).to.equal(0n);
    expect(bnToBigInt(lateVaultBefore.pendingRewardsNextWeek)).to.equal(0n);
    expect(bnToBigInt(lateVaultBefore.calTributeAccumulatedNext)).to.equal(0n);

    const recordRoyalty = 2n * DUNG * (5_500n + 2_700n) / 10_000n;
    const expectedRiderRoyalty = recordRoyalty;
    const riderDungBefore = (await getAccount(provider.connection, riderDungAta)).amount;
    const attackerDungBefore = (await getAccount(provider.connection, attackerDungAta)).amount;
    const recipientByUser = new Map([
      [rider.publicKey.toBase58(), riderDungAta],
      [attacker.publicKey.toBase58(), attackerDungAta],
    ]);
    const recipientAccounts = lateBoard.entries.map((entry: any) => ({
      pubkey: recipientByUser.get(entry.user.toBase58())!,
      isWritable: true,
      isSigner: false,
    }));

    await program.methods
      .distributeEpochRewards(new BN(settlementWeek), DISTRIBUTION_CONFIG)
      .accounts({
        vault: lateVault,
        vaultLeaderboard: lateLeaderboard,
        localLegend: lateLegend,
        vaultActivation: lateActivation,
        polAccount: polAta,
        protocolTreasury: treasuryAta,
        dungMint,
        dungMintState,
        programConfig,
        backendAuthority: wallet.publicKey,
        dungMintAuth: findDungMintAuth()[0],
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .remainingAccounts([
        ...recipientAccounts,
        { pubkey: founderDungAta, isWritable: true, isSigner: false },
      ])
      .rpc();

    expect((await getAccount(provider.connection, riderDungAta)).amount - riderDungBefore)
      .to.equal(expectedRiderRoyalty);
    expect((await getAccount(provider.connection, attackerDungAta)).amount - attackerDungBefore)
      .to.equal(0n);
  });

  it('pools tied Record Board positions into equal on-chain DUNG payouts', async () => {
    const counter = await program.account.vaultCounter.fetch(vaultCounter) as { count: BN };
    const tieVaultId = counter.count.toNumber();
    const [tieVault] = findVault(tieVaultId);
    const [tieActivation] = findVaultActivation(tieVaultId);
    const [tieLeaderboard] = findVaultLeaderboard(tieVaultId);
    const [tieLegend] = findLocalLegend(tieVaultId);
    const tieClimb = (await registerCanonClimb(
      'truths:tied-record-board',
      'Tied Record Board Climb',
      400,
      4_000,
      1_000,
    )).climb;

    await createTestVaultFromCanon({
      vault: tieVault,
      climb: tieClimb,
      vaultLeaderboard: tieLeaderboard,
      localLegend: tieLegend,
      vaultActivation: tieActivation,
    });

    await primeHistoricalSettlementWeek(
      tieVault,
      tieActivation,
      settlementWeek,
    );

    const attackerTieRideHash = hash32('truths:tied-record-board:attacker-ride');
    const [attackerTieAttestation] = findRideAttestation(attacker.publicKey, attackerTieRideHash);
    const [attackerTieBudget] = findRideTributeBudget(attackerTieAttestation);
    await program.methods
      .recordRide(
        Array.from(attackerTieRideHash),
        Array.from(hash32('truths:tied-record-board:attacker-attestation')),
        1,
        1,
        new BN(completedAt + 1),
        new BN(completedAt - 3_599),
        1_000,
        42_000,
        900,
        bn(1_000n * CAL),
        1,
      )
      .accounts({
        rideAttestation: attackerTieAttestation,
        riderSoul: findRiderSoul(attacker.publicKey)[0],
        rider: attacker.publicKey,
        programConfig,
        authority: wallet.publicKey,
        payer: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    await program.methods
      .recordClimbCompletionV2(
        1_615,
        bn(0),
        completionEvidenceV2(attackerTieAttestation, tieVault, 1_615, 0n),
      )
      .accounts({
        rideAttestation: attackerTieAttestation,
        climbCompletionReceipt: findClimbCompletionReceipt(attackerTieAttestation, tieVault)[0],
        vault: tieVault,
        vaultCompletion: findVaultCompletion(attacker.publicKey, tieVaultId)[0],
        vaultLeaderboard: tieLeaderboard,
        vaultActivation: tieActivation,
        rider: attacker.publicKey,
        programConfig,
        authority: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .remainingAccounts([{
        pubkey: attackerTieBudget,
        isWritable: true,
        isSigner: false,
      }])
      .rpc();

    await program.methods
      .recordClimbCompletionV2(
        1_615,
        bn(CLIMB_CAL_TRIBUTE),
        completionEvidenceV2(
          rideAttestation,
          tieVault,
          1_615,
          CLIMB_CAL_TRIBUTE,
        ),
      )
      .accounts({
        rideAttestation,
        climbCompletionReceipt: findClimbCompletionReceipt(rideAttestation, tieVault)[0],
        vault: tieVault,
        vaultCompletion: findVaultCompletion(rider.publicKey, tieVaultId)[0],
        vaultLeaderboard: tieLeaderboard,
        vaultActivation: tieActivation,
        rider: rider.publicKey,
        programConfig,
        authority: wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .remainingAccounts([{
        pubkey: findRideTributeBudget(rideAttestation)[0],
        isWritable: true,
        isSigner: false,
      }])
      .rpc();

    const board = await program.account.vaultLeaderboard.fetch(tieLeaderboard) as any;
    expect(board.entries.map((entry: any) => entry.timeS)).to.deep.equal([1_615, 1_615]);

    const tieVaultBefore = await program.account.vault.fetch(tieVault) as any;
    const pendingRewards = bnToBigInt(tieVaultBefore.pendingRewards);
    const recordRoyalty = pendingRewards * (5_500n + 2_700n) / 10_000n;
    const expectedEach = recordRoyalty / 2n;
    const riderBefore = (await getAccount(provider.connection, riderDungAta)).amount;
    const attackerBefore = (await getAccount(provider.connection, attackerDungAta)).amount;
    const tieRecipientByUser = new Map([
      [rider.publicKey.toBase58(), riderDungAta],
      [attacker.publicKey.toBase58(), attackerDungAta],
    ]);
    const tieRecipientAccounts = board.entries.map((entry: any) => {
      const recipient = tieRecipientByUser.get(entry.user.toBase58());
      expect(recipient, `missing tied recipient for ${entry.user.toBase58()}`).to.not.equal(undefined);
      return { pubkey: recipient!, isWritable: true, isSigner: false };
    });

    const emptySettlement = program.methods
      .distributeEpochRewards(new BN(settlementWeek), DISTRIBUTION_CONFIG)
      .accounts({
        vault: tieVault,
        vaultLeaderboard: tieLeaderboard,
        localLegend: tieLegend,
        vaultActivation: tieActivation,
        polAccount: polAta,
        protocolTreasury: treasuryAta,
        dungMint,
        dungMintState,
        programConfig,
        backendAuthority: wallet.publicKey,
        dungMintAuth: findDungMintAuth()[0],
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .remainingAccounts([
        ...tieRecipientAccounts,
        { pubkey: founderDungAta, isWritable: true, isSigner: false },
      ]);
    const emptySettlementSimulation = await provider.simulate(
      await emptySettlement.transaction(),
    ) as any;
    const tiedSettlementComputeUnits = emptySettlementSimulation.unitsConsumed as number;
    expect(tiedSettlementComputeUnits).to.be.greaterThan(0);
    expect(tiedSettlementComputeUnits).to.be.lessThan(
      SETTLEMENT_COMPUTE_UNIT_LIMIT,
    );
    await emptySettlement.rpc();

    const riderAfter = (await getAccount(provider.connection, riderDungAta)).amount;
    const attackerAfter = (await getAccount(provider.connection, attackerDungAta)).amount;
    const tieVaultAfter = await program.account.vault.fetch(tieVault) as any;

    expect(riderAfter - riderBefore).to.equal(expectedEach);
    expect(attackerAfter - attackerBefore).to.equal(expectedEach);
    expect(bnToBigInt(tieVaultAfter.carryRecordRoyalty)).to.equal(
      recordRoyalty - (2n * expectedEach),
    );
  });

  it('settles the open week into record board, staker, legend, POL, treasury, and harvestable DUNG', async () => {
    await ensureSettlementEconomicPreconditions();
    const emptySettlementComputeUnits = await measureZeroStakeSettlementComputeUnits();
    expect(emptySettlementComputeUnits).to.be.greaterThan(0);
    expect(emptySettlementComputeUnits).to.be.lessThan(
      SETTLEMENT_COMPUTE_UNIT_LIMIT,
    );

    await expectRejected(program.methods
      .depositCalFromBalance(
        bn(MIN_CAL_STAKE),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.depositCal,
          vaultId,
          MIN_CAL_STAKE,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: attacker.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        sponsorAuthority: wallet.publicKey,
        programConfig,
        riderBalanceCalAccount: riderBalanceCalToken,
        vaultCalEscrow,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc());

    await program.methods
      .setRiderBalanceStatus({ locked: {} } as any)
      .accounts({
        riderBalance,
        programConfig,
        admin: wallet.publicKey,
      })
      .rpc();

    await expectRejected(program.methods
      .depositCalFromBalance(
        bn(MIN_CAL_STAKE),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.depositCal,
          vaultId,
          MIN_CAL_STAKE,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        sponsorAuthority: wallet.publicKey,
        programConfig,
        riderBalanceCalAccount: riderBalanceCalToken,
        vaultCalEscrow,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc());

    await program.methods
      .setRiderBalanceStatus({ active: {} } as any)
      .accounts({
        riderBalance,
        programConfig,
        admin: wallet.publicKey,
      })
      .rpc();

    await expectRejected(
      program.methods
        .depositCalFromBalance(
          bn(MIN_CAL_STAKE),
          await balanceVaultAuthorization(
            BALANCE_VAULT_OPERATION_KIND.depositCal,
            vaultId,
            MIN_CAL_STAKE,
          ),
        )
        .accounts({
          vault,
          vaultStake,
          vaultActivation,
          rider: rider.publicKey,
          riderBalance,
          riderBalanceAuthority,
          balanceVaultAuthority,
          operationAuthority: activeBalanceVaultOperationSigner.publicKey,
          sponsorAuthority: wallet.publicKey,
          programConfig,
          riderBalanceCalAccount: riderBalanceCalToken,
          vaultCalEscrow,
          vaultLpMint,
          riderBalanceLpAccount: riderPositionLpToken,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId,
        })
        .signers([activeBalanceVaultOperationSigner])
        .rpc(),
      'InvalidBalanceVaultAuthority',
    );

    await configureBalanceVaultOperationSigner(activeBalanceVaultOperationSigner.publicKey);

    const balanceDepositAccounts = {
      vault,
      vaultStake,
      vaultActivation,
      rider: rider.publicKey,
      riderBalance,
      riderBalanceAuthority,
      balanceVaultAuthority,
      operationAuthority: activeBalanceVaultOperationSigner.publicKey,
      sponsorAuthority: wallet.publicKey,
      programConfig,
      riderBalanceCalAccount: riderBalanceCalToken,
      vaultCalEscrow,
      vaultLpMint,
      riderBalanceLpAccount: riderPositionLpToken,
      tokenProgram: TOKEN_PROGRAM_ID,
      systemProgram: SystemProgram.programId,
    };

    const validSignerAuthorization = await balanceVaultAuthorization(
      BALANCE_VAULT_OPERATION_KIND.depositCal,
      vaultId,
      MIN_CAL_STAKE,
    );
    await expectRejected(
      program.methods
        .depositCalFromBalance(bn(MIN_CAL_STAKE), validSignerAuthorization)
        .accounts({
          ...balanceDepositAccounts,
          operationAuthority: attacker.publicKey,
        })
        .signers([attacker])
        .rpc(),
      'InvalidBalanceVaultAuthority',
    );

    const wrongAmountAuthorization = await balanceVaultAuthorization(
      BALANCE_VAULT_OPERATION_KIND.depositCal,
      vaultId,
      MIN_CAL_STAKE + 1n,
    );
    await expectRejected(
      program.methods
        .depositCalFromBalance(bn(MIN_CAL_STAKE), wrongAmountAuthorization)
        .accounts(balanceDepositAccounts)
        .signers([activeBalanceVaultOperationSigner])
        .rpc(),
      'InvalidBalanceVaultOperation',
    );

    const expiredAuthorization = await balanceVaultAuthorization(
      BALANCE_VAULT_OPERATION_KIND.depositCal,
      vaultId,
      MIN_CAL_STAKE,
      0,
      activeBalanceVaultOperationSigner.publicKey,
      Math.floor(Date.now() / 1000) - 1,
    );
    await expectRejected(
      program.methods
        .depositCalFromBalance(bn(MIN_CAL_STAKE), expiredAuthorization)
        .accounts(balanceDepositAccounts)
        .signers([activeBalanceVaultOperationSigner])
        .rpc(),
      'BalanceVaultOperationExpired',
    );

    await expectRejected(program.methods
      .depositCalFromBalance(
        bn(MIN_CAL_STAKE),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.depositCal,
          vaultId,
          MIN_CAL_STAKE,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        sponsorAuthority: wallet.publicKey,
        programConfig,
        riderBalanceCalAccount: riderBalanceCalToken,
        vaultCalEscrow,
        vaultLpMint,
        riderBalanceLpAccount: riderLpAta,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc());

    await expectRejected(program.methods
      .depositCalFromBalance(
        bn(MIN_CAL_STAKE),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.depositCal,
          vaultId,
          MIN_CAL_STAKE,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        sponsorAuthority: wallet.publicKey,
        programConfig,
        riderBalanceCalAccount: riderCalAta,
        vaultCalEscrow,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc());

    const balanceCalBeforeDeposit = (await getAccount(provider.connection, riderBalanceCalToken)).amount;
    const vaultCalBeforeDeposit = (await getAccount(provider.connection, vaultCalEscrow)).amount;

    const successfulDepositAuthorization = await balanceVaultAuthorization(
      BALANCE_VAULT_OPERATION_KIND.depositCal,
      vaultId,
      MIN_CAL_STAKE,
    );
    await program.methods
      .depositCalFromBalance(bn(MIN_CAL_STAKE), successfulDepositAuthorization)
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        sponsorAuthority: wallet.publicKey,
        programConfig,
        riderBalanceCalAccount: riderBalanceCalToken,
        vaultCalEscrow,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc();

    await expectRejected(
      program.methods
        .depositCalFromBalance(bn(MIN_CAL_STAKE), successfulDepositAuthorization)
        .accounts({
          vault,
          vaultStake,
          vaultActivation,
          rider: rider.publicKey,
          riderBalance,
          riderBalanceAuthority,
          balanceVaultAuthority,
          operationAuthority: activeBalanceVaultOperationSigner.publicKey,
          sponsorAuthority: wallet.publicKey,
          programConfig,
          riderBalanceCalAccount: riderBalanceCalToken,
          vaultCalEscrow,
          vaultLpMint,
          riderBalanceLpAccount: riderPositionLpToken,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId,
        })
        .signers([activeBalanceVaultOperationSigner])
        .rpc(),
      'BalanceVaultOperationReplay',
    );

    const balanceCalAfterDeposit = (await getAccount(provider.connection, riderBalanceCalToken)).amount;
    const vaultCalAfterDeposit = (await getAccount(provider.connection, vaultCalEscrow)).amount;
    const positionLpAfterDeposit = await getAccount(provider.connection, riderPositionLpToken);
    const balanceLpAfterDeposit = (await getAccount(provider.connection, riderBalanceLpToken)).amount;
    const walletLpAfterDeposit = (await getAccount(provider.connection, riderLpAta)).amount;
    const stakeAfterDeposit = await program.account.vaultStake.fetch(vaultStake) as any;

    expect(balanceCalBeforeDeposit - balanceCalAfterDeposit).to.equal(MIN_CAL_STAKE);
    expect(vaultCalAfterDeposit - vaultCalBeforeDeposit).to.equal(MIN_CAL_STAKE);
    expect(positionLpAfterDeposit.amount).to.equal(MIN_CAL_STAKE);
    expect(positionLpAfterDeposit.isFrozen).to.equal(true);
    expect(positionLpAfterDeposit.owner.toBase58()).to.equal(vaultStake.toBase58());
    expect(balanceLpAfterDeposit).to.equal(0n);
    expect(walletLpAfterDeposit).to.equal(0n);
    expect(stakeAfterDeposit.user.toBase58()).to.equal(rider.publicKey.toBase58());
    expect(bnToBigInt(stakeAfterDeposit.calStaked)).to.equal(MIN_CAL_STAKE);
    expect(bnToBigInt(stakeAfterDeposit.lpTokens)).to.equal(MIN_CAL_STAKE);

    const createDirectStake = async (staker: Keypair) => {
      const calAccount = (await getOrCreateAssociatedTokenAccount(
        provider.connection,
        wallet.payer,
        calMint,
        staker.publicKey,
      )).address;
      const [stakeAccount] = findVaultStake(staker.publicKey, vaultId);
      const [lpAccount] = findVaultPositionLp(staker.publicKey, vaultId);

      await program.methods
        .initializeVaultPositionLp()
        .accounts({
          vault,
          rider: staker.publicKey,
          vaultStake: stakeAccount,
          vaultLpMint,
          positionLpAccount: lpAccount,
          sponsorAuthority: wallet.publicKey,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId,
        })
        .rpc();

      await transfer(
        provider.connection,
        wallet.payer,
        riderCalAta,
        calAccount,
        rider,
        MIN_CAL_STAKE,
      );
      await program.methods
        .stakeCalInVault(bn(MIN_CAL_STAKE))
        .accounts({
          vault,
          vaultStake: stakeAccount,
          vaultActivation,
          programConfig,
          sponsorAuthority: wallet.publicKey,
          staker: staker.publicKey,
          stakerCalAta: calAccount,
          vaultCalEscrow,
          vaultLpMint,
          stakerLpAccount: lpAccount,
          tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId,
        })
        .signers([staker])
        .rpc();

      const sealedLpAccount = await getAccount(provider.connection, lpAccount);
      expect(sealedLpAccount.amount).to.equal(MIN_CAL_STAKE);
      expect(sealedLpAccount.isFrozen).to.equal(true);
      expect(sealedLpAccount.owner.toBase58()).to.equal(stakeAccount.toBase58());

      return { stakeAccount, calAccount, lpAccount };
    };

    const eligiblePosition = await createDirectStake(eligibleStaker);
    const immaturePosition = await createDirectStake(immatureStaker);
    const inactivePosition = await createDirectStake(inactiveStaker);

    const attackerLpAccount = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      vaultLpMint,
      attacker.publicKey,
    )).address;
    const eligibleLpBeforeTransfer = (
      await getAccount(provider.connection, eligiblePosition.lpAccount)
    ).amount;
    await expectRejected(transfer(
      provider.connection,
      wallet.payer,
      eligiblePosition.lpAccount,
      attackerLpAccount,
      eligibleStaker,
      1n,
    ));
    expect((await getAccount(provider.connection, eligiblePosition.lpAccount)).amount)
      .to.equal(eligibleLpBeforeTransfer);

    await provider.sendAndConfirm(new Transaction().add(adminOverrideStakeEligibilityIx(
      program.programId, { vault, vaultStake: inactivePosition.stakeAccount, programConfig, authority: wallet.publicKey },
      new BN(settlementWeek),
    )));

    await program.methods
      .unstakeCalFromVault(bn(MIN_CAL_STAKE))
      .accounts({
        vault,
        vaultStake: inactivePosition.stakeAccount,
        vaultActivation,
        programConfig,
        staker: inactiveStaker.publicKey,
        stakerCalAta: inactivePosition.calAccount,
        vaultCalEscrow,
        calMint,
        vaultLpMint,
        stakerLpAccount: inactivePosition.lpAccount,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([inactiveStaker])
      .rpc();

    await provider.sendAndConfirm(new Transaction().add(adminOverrideStakeEligibilityIx(
      program.programId, { vault, vaultStake, programConfig, authority: wallet.publicKey },
      new BN(settlementWeek),
    )));

    await provider.sendAndConfirm(new Transaction().add(adminOverrideStakeEligibilityIx(
      program.programId, { vault, vaultStake: eligiblePosition.stakeAccount, programConfig, authority: wallet.publicKey },
      new BN(settlementWeek),
    )));

    for (let index = 0; index < 9; index += 1) {
      const boardRider = settlementFixtureKey('site-11');
      const boardRideHash = hash32(`truths:settlement-board:${index}`);
      const [boardRideAttestation] = findRideAttestation(
        boardRider.publicKey,
        boardRideHash,
      );
      const [boardRiderSoul] = findRiderSoul(boardRider.publicKey);
      const [boardRideTributeBudget] = findRideTributeBudget(boardRideAttestation);
      const boardTimeS = 1_700 + index;
      await program.methods
        .recordRide(
          Array.from(boardRideHash),
          Array.from(hash32(`truths:settlement-board:attestation:${index}`)),
          1,
          1,
          new BN(completedAt + index + 1),
          new BN(completedAt - 3_600 + index + 1),
          20_000,
          42_000,
          900,
          bn(20_000n * CAL),
          1,
        )
        .accounts({
          rideAttestation: boardRideAttestation,
          riderSoul: boardRiderSoul,
          rider: boardRider.publicKey,
          programConfig,
          authority: wallet.publicKey,
          payer: wallet.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .rpc();
      await program.methods
        .recordClimbCompletionV2(
          boardTimeS,
          bn(CLIMB_CAL_TRIBUTE),
          completionEvidenceV2(
            boardRideAttestation,
            vault,
            boardTimeS,
            CLIMB_CAL_TRIBUTE,
          ),
        )
        .accounts({
          rideAttestation: boardRideAttestation,
          climbCompletionReceipt: findClimbCompletionReceipt(
            boardRideAttestation,
            vault,
          )[0],
          vault,
          vaultCompletion: findVaultCompletion(boardRider.publicKey, vaultId)[0],
          vaultLeaderboard,
          vaultActivation,
          rider: boardRider.publicKey,
          programConfig,
          authority: wallet.publicKey,
          systemProgram: SystemProgram.programId,
        })
        .remainingAccounts([{
          pubkey: boardRideTributeBudget,
          isWritable: true,
          isSigner: false,
        }])
        .rpc();
    }

    const vaultBeforeDistribution = await program.account.vault.fetch(vault) as any;
    const settlementLeaderboard = await program.account.vaultLeaderboard.fetch(
      vaultLeaderboard,
    ) as any;
    expect(settlementLeaderboard.entries).to.have.length(10);
    expect(settlementLeaderboard.entries[0].user.toBase58()).to.equal(
      rider.publicKey.toBase58(),
    );
    const leaderboardRecipientAtas: PublicKey[] = [];
    for (const entry of settlementLeaderboard.entries) {
      leaderboardRecipientAtas.push((await getOrCreateAssociatedTokenAccount(
        provider.connection,
        wallet.payer,
        dungMint,
        entry.user,
      )).address);
    }
    const immatureBeforeDistribution = await program.account.vaultStake.fetch(
      immaturePosition.stakeAccount,
    ) as any;
    const inactiveBeforeDistribution = await program.account.vaultStake.fetch(
      inactivePosition.stakeAccount,
    ) as any;
    expect(vaultBeforeDistribution.stakerCount).to.equal(4);
    expect(
      immatureBeforeDistribution.pendingEffectiveWeekPlusOne.toNumber() - 1,
    ).to.be.greaterThan(settlementWeek);
    expect(bnToBigInt(immatureBeforeDistribution.effectiveLpTokens)).to.equal(0n);
    expect(bnToBigInt(inactiveBeforeDistribution.calStaked)).to.equal(0n);
    expect(bnToBigInt(inactiveBeforeDistribution.lpTokens)).to.equal(0n);
    expect(bnToBigInt(inactiveBeforeDistribution.effectiveLpTokens)).to.equal(MIN_CAL_STAKE);

    const pendingRewards = bnToBigInt(vaultBeforeDistribution.pendingRewards);
    expect(pendingRewards > 1n * DUNG).to.equal(true);
    const mintStateBeforeDistribution = await program.account.dungMintState.fetch(dungMintState) as any;
    const leaderboardBalancesBeforeDistribution = await Promise.all(
      leaderboardRecipientAtas.map(async (address) =>
        (await getAccount(provider.connection, address)).amount
      ),
    );
    const riderDungBeforeDistribution = leaderboardBalancesBeforeDistribution[0];
    const founderDungBeforeDistribution = (await getAccount(provider.connection, founderDungAta)).amount;
    const polBeforeDistribution = (await getAccount(provider.connection, polAta)).amount;
    const treasuryBeforeDistribution = (await getAccount(provider.connection, treasuryAta)).amount;
    const distributeWith = (
      stakeAccounts: PublicKey[],
      distributionConfig = DISTRIBUTION_CONFIG,
      computeUnitLimit = SETTLEMENT_COMPUTE_UNIT_LIMIT,
    ) => program.methods
        .distributeEpochRewards(new BN(settlementWeek), distributionConfig)
        .accounts({
          vault,
          vaultLeaderboard,
          localLegend,
          vaultActivation,
          polAccount: polAta,
          protocolTreasury: treasuryAta,
          dungMint,
          dungMintState,
          programConfig,
          backendAuthority: wallet.publicKey,
          dungMintAuth: findDungMintAuth()[0],
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .remainingAccounts([
          ...leaderboardRecipientAtas.map((pubkey) => ({
            pubkey,
            isWritable: true,
            isSigner: false,
          })),
          { pubkey: founderDungAta, isWritable: true, isSigner: false },
          ...stakeAccounts.map((pubkey) => ({ pubkey, isWritable: true, isSigner: false })),
        ])
        .preInstructions([
          ComputeBudgetProgram.setComputeUnitLimit({ units: computeUnitLimit }),
          ComputeBudgetProgram.setComputeUnitPrice({
            microLamports: SETTLEMENT_PRIORITY_FEE_MICRO_LAMPORTS,
          }),
        ]);
    const completeStakeInventory = [
      vaultStake,
      eligiblePosition.stakeAccount,
      immaturePosition.stakeAccount,
      inactivePosition.stakeAccount,
    ];
    const typicalAtDefaultRejected = await isRejected(
      distributeWith(
        completeStakeInventory,
        DISTRIBUTION_CONFIG,
        200_000,
      ).simulate(),
    );
    const typicalSettlementSimulation = await provider.simulate(
      await distributeWith(
        completeStakeInventory,
        DISTRIBUTION_CONFIG,
        SETTLEMENT_COMPUTE_UNIT_LIMIT,
      ).transaction(),
    ) as any;
    const typicalSettlementComputeUnits = typicalSettlementSimulation.unitsConsumed as number;
    expect(typicalSettlementComputeUnits).to.be.greaterThan(
      emptySettlementComputeUnits,
    );
    const additionalStakers = Array.from(
      {
        length:
          SETTLEMENT_COMPUTE_PROVEN_INVENTORY - completeStakeInventory.length,
      },
      () => settlementFixtureKey('site-12'),
    );
    await Promise.all(
      additionalStakers.map((staker) => airdrop(staker.publicKey)),
    );
    const additionalPositions = [];
    for (const staker of additionalStakers) {
      const position = await createDirectStake(staker);
      additionalPositions.push(position);
      await provider.sendAndConfirm(new Transaction().add(adminOverrideStakeEligibilityIx(
        program.programId, { vault, vaultStake: position.stakeAccount, programConfig, authority: wallet.publicKey },
        new BN(settlementWeek),
      )));
    }
    const maximumStakeInventory = [
      ...completeStakeInventory,
      ...additionalPositions.map((position) => position.stakeAccount),
    ];
    const vaultAtMaximumInventory = await program.account.vault.fetch(vault) as any;
    expect(vaultAtMaximumInventory.stakerCount).to.equal(
      SETTLEMENT_COMPUTE_PROVEN_INVENTORY,
    );
    const maximumDistributionTransaction = await distributeWith(
      maximumStakeInventory,
    ).transaction();
    const lookupAddresses = Array.from(new Map(
      maximumDistributionTransaction.instructions
        .flatMap((instruction) => instruction.keys)
        .filter((account) => !account.isSigner)
        .map((account) => [account.pubkey.toBase58(), account.pubkey]),
    ).values());
    const settlementFeePayer = settlementFixtureKey('site-13');
    await airdrop(settlementFeePayer.publicKey);
    const recentLookupTableSlot = await provider.connection.getSlot('finalized');
    const [createLookupTableInstruction, lookupTableAddress] =
      AddressLookupTableProgram.createLookupTable({
        authority: settlementFeePayer.publicKey,
        payer: settlementFeePayer.publicKey,
        recentSlot: recentLookupTableSlot,
      });
    await sendAndConfirmTransaction(
      provider.connection,
      new Transaction().add(createLookupTableInstruction),
      [settlementFeePayer],
      { commitment: 'confirmed' },
    );
    for (let offset = 0; offset < lookupAddresses.length; offset += 20) {
      await sendAndConfirmTransaction(
        provider.connection,
        new Transaction().add(AddressLookupTableProgram.extendLookupTable({
          lookupTable: lookupTableAddress,
          authority: settlementFeePayer.publicKey,
          payer: settlementFeePayer.publicKey,
          addresses: lookupAddresses.slice(offset, offset + 20),
        })),
        [settlementFeePayer],
        { commitment: 'confirmed' },
      );
    }

    let settlementLookupTable = null;
    let lookupTableObservation = 'lookup table not found';
    for (let attempt = 0; attempt < 300; attempt += 1) {
      const lookupResponse = await provider.connection.getAddressLookupTable(
        lookupTableAddress,
        { commitment: 'finalized' },
      );
      const currentSlot = await provider.connection.getSlot('finalized');
      lookupTableObservation = lookupResponse.value
        ? `current_slot=${currentSlot} last_extended_slot=${lookupResponse.value.state.lastExtendedSlot} addresses=${lookupResponse.value.state.addresses.length} required=${lookupAddresses.length}`
        : `current_slot=${currentSlot} lookup table not found`;
      if (
        lookupResponse.value
        && currentSlot > lookupResponse.value.state.lastExtendedSlot
        && lookupResponse.value.state.addresses.length >= lookupAddresses.length
      ) {
        settlementLookupTable = lookupResponse.value;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!settlementLookupTable) {
      throw new Error(
        `settlement lookup table did not become active: ${lookupTableObservation}`,
      );
    }
    const lookupAddressSet = new Set(
      settlementLookupTable.state.addresses.map((address) => address.toBase58()),
    );
    expect(
      lookupAddresses.every((address) => lookupAddressSet.has(address.toBase58())),
    ).to.equal(true);

    const buildVersionedSettlement = async (
      instructions = maximumDistributionTransaction.instructions,
    ) => {
      const latestBlockhash = await provider.connection.getLatestBlockhash('confirmed');
      const message = new TransactionMessage({
        payerKey: settlementFeePayer.publicKey,
        recentBlockhash: latestBlockhash.blockhash,
        instructions,
      }).compileToV0Message([settlementLookupTable]);
      const transaction = new VersionedTransaction(message);
      transaction.sign([settlementFeePayer, wallet.payer]);
      return { latestBlockhash, transaction };
    };
    const simulateVersionedSettlement = async (builder: any) => {
      const legacyTransaction = await builder.transaction();
      const built = await buildVersionedSettlement(legacyTransaction.instructions);
      const simulation = await provider.connection.simulateTransaction(
        built.transaction,
        { commitment: 'processed', sigVerify: true },
      );
      if (simulation.value.err) {
        throw new Error(JSON.stringify(simulation.value.err));
      }
      return simulation.value;
    };

    expect(await isRejected(simulateVersionedSettlement(distributeWith(
      maximumStakeInventory,
      DISTRIBUTION_CONFIG,
      200_000,
    )))).to.equal(true);
    const maximumSettlementSimulation = await simulateVersionedSettlement(
      distributeWith(maximumStakeInventory),
    );
    const maximumSettlementComputeUnits = maximumSettlementSimulation.unitsConsumed as number;
    expect(maximumSettlementComputeUnits).to.be.lessThanOrEqual(
      SETTLEMENT_COMPUTE_UNIT_LIMIT,
    );
    expect(
      SETTLEMENT_COMPUTE_UNIT_LIMIT - maximumSettlementComputeUnits,
    ).to.be.greaterThanOrEqual(SETTLEMENT_MIN_COMPUTE_HEADROOM);
    console.log(
      `SETTLEMENT_CU_MEASUREMENTS empty=${emptySettlementComputeUnits} four=${typicalSettlementComputeUnits} four_default_200_rejected=${typicalAtDefaultRejected} full_board_ten_stakes=${maximumSettlementComputeUnits} limit=${SETTLEMENT_COMPUTE_UNIT_LIMIT} headroom=${SETTLEMENT_COMPUTE_UNIT_LIMIT - maximumSettlementComputeUnits}`,
    );

    const inventoryResults = {
      noncanonicalPolicy: await isRejected(simulateVersionedSettlement(distributeWith(
        maximumStakeInventory,
        {
          ...DISTRIBUTION_CONFIG,
          leaderboardShareBps: new BN(5400),
          stakerShareBps: new BN(2800),
        },
      ))),
      omittedEligible: await isRejected(simulateVersionedSettlement(distributeWith(
        maximumStakeInventory.filter((pubkey) => !pubkey.equals(eligiblePosition.stakeAccount)),
      ))),
      omittedInactive: await isRejected(simulateVersionedSettlement(distributeWith(
        maximumStakeInventory.filter((pubkey) => !pubkey.equals(inactivePosition.stakeAccount)),
      ))),
      duplicate: await isRejected(simulateVersionedSettlement(distributeWith([
        ...maximumStakeInventory,
        vaultStake,
      ]))),
      wrongOwner: await isRejected(simulateVersionedSettlement(distributeWith([
        ...maximumStakeInventory,
        attackerDungAta,
      ]))),
      malformed: await isRejected(simulateVersionedSettlement(distributeWith([
        ...maximumStakeInventory,
        vault,
      ]))),
      complete: await isRejected(simulateVersionedSettlement(
        distributeWith(maximumStakeInventory),
      )),
    };
    expect(inventoryResults).to.deep.equal({
      noncanonicalPolicy: true,
      omittedEligible: true,
      omittedInactive: true,
      duplicate: true,
      wrongOwner: true,
      malformed: true,
      complete: false,
    });

    const simulatedV0Settlement = await buildVersionedSettlement();
    const serializedV0SettlementBytes = simulatedV0Settlement.transaction.serialize().length;
    expect(serializedV0SettlementBytes).to.be.lessThanOrEqual(
      SETTLEMENT_REVIEWED_PACKET_BYTES,
    );
    expect(serializedV0SettlementBytes).to.be.lessThanOrEqual(
      SOLANA_PACKET_DATA_SIZE,
    );
    const submittedV0Settlement = await buildVersionedSettlement();
    const distributionSignature = await provider.connection.sendTransaction(
      submittedV0Settlement.transaction,
      { preflightCommitment: 'confirmed', skipPreflight: false },
    );
    await provider.connection.confirmTransaction(
      {
        signature: distributionSignature,
        ...submittedV0Settlement.latestBlockhash,
      },
      'confirmed',
    );
    console.log(
      `SETTLEMENT_V0_MEASUREMENT leaderboard=10 local_legend=1 stakes=10 signers=2 bytes=${serializedV0SettlementBytes} reviewed_limit=${SETTLEMENT_REVIEWED_PACKET_BYTES} packet_limit=${SOLANA_PACKET_DATA_SIZE} lookup_addresses=${lookupAddresses.length}`,
    );
    const distributionTransaction = await getConfirmedTransaction(distributionSignature);
    expect(distributionTransaction).to.not.equal(null);
    const eventParser = new anchor.EventParser(PROGRAM_ID, program.coder);
    const distributionEvents = Array.from(
      eventParser.parseLogs(distributionTransaction?.meta?.logMessages ?? []),
    );
    const policyEvent = distributionEvents.find(
      (event) => event.name === 'StakerRemainderPolicyApplied',
    );
    expect(policyEvent).to.not.equal(undefined);
    if (!policyEvent) {
      throw new Error('missing StakerRemainderPolicyApplied event');
    }
    const policyData = policyEvent.data as {
      policyVersion: number;
      currentLockedReallocated: BN;
      legacyCarryReallocated: BN;
    };

    const stakeAfterDistribution = await program.account.vaultStake.fetch(vaultStake) as any;
    const eligibleAfterDistribution = await program.account.vaultStake.fetch(
      eligiblePosition.stakeAccount,
    ) as any;
    const immatureAfterDistribution = await program.account.vaultStake.fetch(
      immaturePosition.stakeAccount,
    ) as any;
    const inactiveAfterDistribution = await program.account.vaultStake.fetch(
      inactivePosition.stakeAccount,
    ) as any;
    const additionalAfterDistribution = await Promise.all(
      additionalPositions.map((position) =>
        program.account.vaultStake.fetch(position.stakeAccount) as Promise<any>
      ),
    );
    const baseStakerMaximum = pendingRewards * 27n / 100n;
    const expectedEligibleStakeCount = 9n;
    const expectedUnlockedStakerRewards = baseStakerMaximum * 70n / 100n;
    const expectedPerEligibleStake =
      expectedUnlockedStakerRewards / expectedEligibleStakeCount;
    const expectedStakerDust =
      expectedUnlockedStakerRewards
      - (expectedEligibleStakeCount * expectedPerEligibleStake);
    const expectedLockedStakerAmount = baseStakerMaximum - expectedUnlockedStakerRewards;
    const baseLeaderboardPool = pendingRewards * 55n / 100n;
    const baseLocalLegend = pendingRewards * 3n / 100n;
    const basePol = pendingRewards * 5n / 100n;
    const baseProtocol = pendingRewards * 10n / 100n;
    const baseDistributionDust = pendingRewards
      - baseLeaderboardPool
      - baseStakerMaximum
      - baseLocalLegend
      - basePol
      - baseProtocol;
    const expectedLeaderboardPool = baseLeaderboardPool
      + baseDistributionDust
      + expectedLockedStakerAmount;
    const leaderboardRankPercentages = [30n, 20n, 15n, 10n, 8n, 6n, 5n, 3n, 2n, 1n];
    const expectedLeaderboardPayouts = leaderboardRankPercentages.map(
      (percentage) => expectedLeaderboardPool * percentage / 100n,
    );
    const expectedLeaderboardCarry = expectedLeaderboardPool
      - expectedLeaderboardPayouts.reduce((total, amount) => total + amount, 0n);
    expect(policyData.policyVersion).to.equal(1);
    expect(bnToBigInt(policyData.currentLockedReallocated)).to.equal(
      expectedLockedStakerAmount,
    );
    expect(bnToBigInt(policyData.legacyCarryReallocated)).to.equal(0n);
    expect(bnToBigInt(stakeAfterDistribution.rewardsEarned)).to.equal(expectedPerEligibleStake);
    expect(bnToBigInt(eligibleAfterDistribution.rewardsEarned)).to.equal(expectedPerEligibleStake);
    expect(bnToBigInt(immatureAfterDistribution.rewardsEarned)).to.equal(0n);
    expect(bnToBigInt(inactiveAfterDistribution.rewardsEarned)).to.equal(expectedPerEligibleStake);
    for (const position of additionalAfterDistribution) {
      expect(bnToBigInt(position.rewardsEarned)).to.equal(expectedPerEligibleStake);
    }

    const leaderboardBalancesAfterDistribution = await Promise.all(
      leaderboardRecipientAtas.map(async (address) =>
        (await getAccount(provider.connection, address)).amount
      ),
    );
    for (let rank = 0; rank < expectedLeaderboardPayouts.length; rank += 1) {
      expect(
        leaderboardBalancesAfterDistribution[rank]
        - leaderboardBalancesBeforeDistribution[rank],
      ).to.equal(expectedLeaderboardPayouts[rank]);
    }
    const riderDungAfterDistribution = leaderboardBalancesAfterDistribution[0];
    const founderDungAfterDistribution = (await getAccount(provider.connection, founderDungAta)).amount;
    const polAfterDistribution = (await getAccount(provider.connection, polAta)).amount;
    const treasuryAfterDistribution = (await getAccount(provider.connection, treasuryAta)).amount;
    expect(riderDungAfterDistribution - riderDungBeforeDistribution).to.equal(
      expectedLeaderboardPayouts[0],
    );
    expect(founderDungAfterDistribution - founderDungBeforeDistribution).to.equal(
      pendingRewards * 3n / 100n,
    );
    expect(polAfterDistribution - polBeforeDistribution).to.equal(pendingRewards * 5n / 100n);
    expect(treasuryAfterDistribution - treasuryBeforeDistribution).to.equal(
      pendingRewards * 10n / 100n,
    );

    const mintStateAfterDistribution = await program.account.dungMintState.fetch(dungMintState) as any;
    expect(
      bnToBigInt(mintStateAfterDistribution.communityReserved)
      - bnToBigInt(mintStateBeforeDistribution.communityReserved),
    ).to.equal(
      (expectedEligibleStakeCount * expectedPerEligibleStake)
      + expectedStakerDust
      + expectedLeaderboardCarry,
    );

    const vaultAfterDistribution = await program.account.vault.fetch(vault) as any;
    expect(vaultAfterDistribution.lastDistributionEpoch.toNumber()).to.equal(settlementWeek);
    expect(vaultAfterDistribution.openSettlementWeek.toNumber()).to.equal(settlementWeek + 1);
    expect(bnToBigInt(vaultAfterDistribution.carryRecordRoyalty)).to.equal(
      expectedLeaderboardCarry,
    );
    expect(bnToBigInt(vaultAfterDistribution.carryStakers)).to.equal(expectedStakerDust);
    expect(bnToBigInt(vaultAfterDistribution.rewardRate)).to.equal(
      STAKER_REMAINDER_POLICY_MARKER,
    );

    const riderDungBeforeHarvest = (await getAccount(provider.connection, riderDungAta)).amount;

    await expectRejected(program.methods
      .collectStakeRewardsFor()
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        staker: rider.publicKey,
        payer: wallet.publicKey,
        dungMint,
        stakerDungAccount: attackerDungAta,
        protocolTreasury: treasuryAta,
        dungMintState,
        programConfig,
        dungMintAuth: findDungMintAuth()[0],
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .rpc());

    const mintStateAfterRejectedCollection = await program.account.dungMintState.fetch(dungMintState) as any;
    expect(bnToBigInt(mintStateAfterRejectedCollection.totalMinted)).to.equal(
      bnToBigInt(mintStateAfterDistribution.totalMinted),
    );
    expect(bnToBigInt(mintStateAfterRejectedCollection.communityMinted)).to.equal(
      bnToBigInt(mintStateAfterDistribution.communityMinted),
    );
    expect(bnToBigInt(mintStateAfterRejectedCollection.communityReserved)).to.equal(
      bnToBigInt(mintStateAfterDistribution.communityReserved),
    );

    await program.methods
      .collectStakeRewardsFor()
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        staker: rider.publicKey,
        payer: wallet.publicKey,
        dungMint,
        stakerDungAccount: riderDungAta,
        protocolTreasury: treasuryAta,
        dungMintState,
        programConfig,
        dungMintAuth: findDungMintAuth()[0],
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .rpc();

    const riderDungAfterHarvest = (await getAccount(provider.connection, riderDungAta)).amount;
    const harvestFee = expectedPerEligibleStake * HARVEST_FEE_BPS / 10_000n;
    expect(riderDungAfterHarvest - riderDungBeforeHarvest).to.equal(
      expectedPerEligibleStake - harvestFee,
    );

    const stakeAfterHarvest = await program.account.vaultStake.fetch(vaultStake) as any;
    expect(bnToBigInt(stakeAfterHarvest.rewardsEarned)).to.equal(0n);

    const mintStateAfterHarvest = await program.account.dungMintState.fetch(dungMintState) as any;
    expect(
      bnToBigInt(mintStateAfterHarvest.totalMinted)
      - bnToBigInt(mintStateAfterDistribution.totalMinted),
    ).to.equal(expectedPerEligibleStake);
    expect(
      bnToBigInt(mintStateAfterHarvest.communityMinted)
      - bnToBigInt(mintStateAfterDistribution.communityMinted),
    ).to.equal(expectedPerEligibleStake);
    expect(
      bnToBigInt(mintStateAfterDistribution.communityReserved)
      - bnToBigInt(mintStateAfterHarvest.communityReserved),
    ).to.equal(expectedPerEligibleStake);
    expect(
      bnToBigInt(mintStateAfterHarvest.totalMinted)
      + bnToBigInt(mintStateAfterHarvest.communityReserved),
    ).to.equal(
      bnToBigInt(mintStateAfterDistribution.totalMinted)
      + bnToBigInt(mintStateAfterDistribution.communityReserved),
    );

    await expectRejected(program.methods
      .collectStakeRewardsFor()
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        staker: rider.publicKey,
        payer: wallet.publicKey,
        dungMint,
        stakerDungAccount: riderDungAta,
        protocolTreasury: treasuryAta,
        dungMintState,
        programConfig,
        dungMintAuth: findDungMintAuth()[0],
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .rpc());

    const mintStateAfterRetry = await program.account.dungMintState.fetch(dungMintState) as any;
    expect(bnToBigInt(mintStateAfterRetry.totalMinted)).to.equal(
      bnToBigInt(mintStateAfterHarvest.totalMinted),
    );
    expect(bnToBigInt(mintStateAfterRetry.communityMinted)).to.equal(
      bnToBigInt(mintStateAfterHarvest.communityMinted),
    );
    expect(bnToBigInt(mintStateAfterRetry.communityReserved)).to.equal(
      bnToBigInt(mintStateAfterHarvest.communityReserved),
    );

    // Composed collect-before-unstake (boulderroller-v2-71o2v): one
    // transaction must both collect the position's pending DUNG and burn its
    // LP, so a withdraw can never leave pending rewards behind. This is the
    // exact instruction sequence the backend's composed withdraw builds.
    const composedStaker = additionalStakers[0];
    const composedPosition = additionalPositions[0];
    const composedStakeBefore = await program.account.vaultStake.fetch(
      composedPosition.stakeAccount,
    ) as any;
    expect(bnToBigInt(composedStakeBefore.rewardsEarned)).to.equal(
      expectedPerEligibleStake,
    );
    expect(bnToBigInt(composedStakeBefore.lpTokens)).to.equal(MIN_CAL_STAKE);
    const composedDungAta = (await getOrCreateAssociatedTokenAccount(
      provider.connection,
      wallet.payer,
      dungMint,
      composedStaker.publicKey,
    )).address;
    const composedDungBefore = (
      await getAccount(provider.connection, composedDungAta)
    ).amount;
    const composedCalBefore = (
      await getAccount(provider.connection, composedPosition.calAccount)
    ).amount;
    const composedCollectIx = await program.methods
      .collectStakeRewardsFor()
      .accounts({
        vault,
        vaultStake: composedPosition.stakeAccount,
        vaultActivation,
        staker: composedStaker.publicKey,
        payer: wallet.publicKey,
        dungMint,
        stakerDungAccount: composedDungAta,
        protocolTreasury: treasuryAta,
        dungMintState,
        programConfig,
        dungMintAuth: findDungMintAuth()[0],
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .instruction();
    const composedSignature = await program.methods
      .unstakeCalFromVault(bn(MIN_CAL_STAKE))
      .accounts({
        vault,
        vaultStake: composedPosition.stakeAccount,
        vaultActivation,
        programConfig,
        staker: composedStaker.publicKey,
        stakerCalAta: composedPosition.calAccount,
        vaultCalEscrow,
        calMint,
        vaultLpMint,
        stakerLpAccount: composedPosition.lpAccount,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .preInstructions([composedCollectIx])
      .signers([composedStaker])
      .rpc();
    const composedTransaction = await getConfirmedTransaction(composedSignature);
    expect(composedTransaction).to.not.equal(null);
    const composedTopLevelInvocations = (
      composedTransaction?.meta?.logMessages ?? []
    ).filter((line) => line === `Program ${PROGRAM_ID.toBase58()} invoke [1]`).length;
    expect(composedTopLevelInvocations).to.equal(2);
    const composedStakeAfter = await program.account.vaultStake.fetch(
      composedPosition.stakeAccount,
    ) as any;
    const composedDungAfter = (
      await getAccount(provider.connection, composedDungAta)
    ).amount;
    const composedCalAfter = (
      await getAccount(provider.connection, composedPosition.calAccount)
    ).amount;
    const composedHarvestFee = expectedPerEligibleStake * HARVEST_FEE_BPS / 10_000n;
    const composedExitFee = MIN_CAL_STAKE * 50n / 10_000n;
    expect(bnToBigInt(composedStakeAfter.rewardsEarned)).to.equal(0n);
    expect(bnToBigInt(composedStakeAfter.lpTokens)).to.equal(0n);
    expect(bnToBigInt(composedStakeAfter.calStaked)).to.equal(0n);
    expect(composedDungAfter - composedDungBefore).to.equal(
      expectedPerEligibleStake - composedHarvestFee,
    );
    expect(composedCalAfter - composedCalBefore).to.equal(
      MIN_CAL_STAKE - composedExitFee,
    );

    await expectRejected(program.methods
      .withdrawCalToBalance(
        bn(MIN_CAL_STAKE + 1n),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.withdrawCal,
          vaultId,
          MIN_CAL_STAKE + 1n,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        programConfig,
        riderBalanceCalAccount: riderBalanceCalToken,
        vaultCalEscrow,
        calMint,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc());

    await expectRejected(program.methods
      .withdrawCalToBalance(
        bn(MIN_CAL_STAKE),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.withdrawCal,
          vaultId,
          MIN_CAL_STAKE,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        programConfig,
        riderBalanceCalAccount: riderCalAta,
        vaultCalEscrow,
        calMint,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc());

    const preRevokeAuthorization = await balanceVaultAuthorization(
      BALANCE_VAULT_OPERATION_KIND.withdrawCal,
      vaultId,
      MIN_CAL_STAKE,
    );
    await program.methods
      .revokeBalanceVaultAuthority()
      .accounts({
        riderBalance,
        rider: rider.publicKey,
        balanceVaultAuthority,
      })
      .signers([rider])
      .rpc();

    const revokedSession = await (program.account as any).balanceVaultAuthority.fetch(
      balanceVaultAuthority,
    ) as any;
    expect(revokedSession.revokedAt.toNumber()).to.be.greaterThan(0);

    await expectRejected(
      program.methods
        .withdrawCalToBalance(bn(MIN_CAL_STAKE), preRevokeAuthorization)
        .accounts({
          vault,
          vaultStake,
          vaultActivation,
          rider: rider.publicKey,
          riderBalance,
          riderBalanceAuthority,
          balanceVaultAuthority,
          operationAuthority: activeBalanceVaultOperationSigner.publicKey,
          programConfig,
          riderBalanceCalAccount: riderBalanceCalToken,
          vaultCalEscrow,
          calMint,
          vaultLpMint,
          riderBalanceLpAccount: riderPositionLpToken,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .signers([activeBalanceVaultOperationSigner])
        .rpc(),
      'InvalidBalanceVaultAuthority',
    );

    activeBalanceVaultOperationSigner = rotatedBalanceVaultOperationSigner;
    await configureBalanceVaultOperationSigner(activeBalanceVaultOperationSigner.publicKey);

    await program.methods
      .setRiderBalanceStatus({ revoked: {} } as any)
      .accounts({
        riderBalance,
        programConfig,
        admin: wallet.publicKey,
      })
      .rpc();

    await expectRejected(program.methods
      .withdrawCalToBalance(
        bn(MIN_CAL_STAKE),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.withdrawCal,
          vaultId,
          MIN_CAL_STAKE,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        programConfig,
        riderBalanceCalAccount: riderBalanceCalToken,
        vaultCalEscrow,
        calMint,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc());

    await program.methods
      .setRiderBalanceStatus({ active: {} } as any)
      .accounts({
        riderBalance,
        programConfig,
        admin: wallet.publicKey,
      })
      .rpc();

    await expectRejected(
      program.methods
        .withdrawCalToBalance(
          bn(MIN_CAL_STAKE),
          await balanceVaultAuthorization(
            BALANCE_VAULT_OPERATION_KIND.withdrawCal,
            vaultId,
            MIN_CAL_STAKE,
          ),
        )
        .accounts({
          vault,
          vaultStake,
          vaultActivation,
          rider: rider.publicKey,
          riderBalance,
          riderBalanceAuthority,
          balanceVaultAuthority,
          operationAuthority: activeBalanceVaultOperationSigner.publicKey,
          programConfig,
          riderBalanceCalAccount: riderBalanceCalToken,
          vaultCalEscrow,
          calMint,
          vaultLpMint,
          riderBalanceLpAccount: riderPositionLpToken,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .signers([activeBalanceVaultOperationSigner])
        .rpc(),
      'InvalidBalanceVaultAuthority',
    );

    await configureBalanceVaultOperationSigner(activeBalanceVaultOperationSigner.publicKey);

    const balanceCalBeforeWithdraw = (await getAccount(provider.connection, riderBalanceCalToken)).amount;
    const vaultCalBeforeWithdraw = (await getAccount(provider.connection, vaultCalEscrow)).amount;

    await program.methods
      .withdrawCalToBalance(
        bn(MIN_CAL_STAKE),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.withdrawCal,
          vaultId,
          MIN_CAL_STAKE,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        programConfig,
        riderBalanceCalAccount: riderBalanceCalToken,
        vaultCalEscrow,
        calMint,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc();

    const balanceCalAfterWithdraw = (await getAccount(provider.connection, riderBalanceCalToken)).amount;
    const vaultCalAfterWithdraw = (await getAccount(provider.connection, vaultCalEscrow)).amount;
    const positionLpAfterWithdraw = await getAccount(provider.connection, riderPositionLpToken);
    const balanceLpAfterWithdraw = (await getAccount(provider.connection, riderBalanceLpToken)).amount;
    const stakeAfterWithdraw = await program.account.vaultStake.fetch(vaultStake) as any;
    const expectedExitFee = MIN_CAL_STAKE * 50n / 10_000n;

    expect(balanceCalAfterWithdraw - balanceCalBeforeWithdraw).to.equal(MIN_CAL_STAKE - expectedExitFee);
    expect(vaultCalBeforeWithdraw - vaultCalAfterWithdraw).to.equal(MIN_CAL_STAKE);
    expect(positionLpAfterWithdraw.amount).to.equal(0n);
    expect(positionLpAfterWithdraw.isFrozen).to.equal(true);
    expect(balanceLpAfterWithdraw).to.equal(0n);
    expect(bnToBigInt(stakeAfterWithdraw.calStaked)).to.equal(0n);
    expect(bnToBigInt(stakeAfterWithdraw.lpTokens)).to.equal(0n);

    await program.methods
      .stakeCalInVault(bn(MIN_CAL_STAKE))
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        programConfig,
        sponsorAuthority: wallet.publicKey,
        staker: rider.publicKey,
        stakerCalAta: riderCalAta,
        vaultCalEscrow,
        vaultLpMint,
        stakerLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([rider])
      .rpc();
    await transfer(
      provider.connection,
      wallet.payer,
      riderCalAta,
      riderBalanceCalToken,
      rider,
      1n * CAL,
    );
    await program.methods
      .depositCalFromBalance(
        bn(MIN_CAL_STAKE),
        await balanceVaultAuthorization(
          BALANCE_VAULT_OPERATION_KIND.depositCal,
          vaultId,
          MIN_CAL_STAKE,
        ),
      )
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        rider: rider.publicKey,
        riderBalance,
        riderBalanceAuthority,
        balanceVaultAuthority,
        operationAuthority: activeBalanceVaultOperationSigner.publicKey,
        sponsorAuthority: wallet.publicKey,
        programConfig,
        riderBalanceCalAccount: riderBalanceCalToken,
        vaultCalEscrow,
        vaultLpMint,
        riderBalanceLpAccount: riderPositionLpToken,
        tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId,
      })
      .signers([activeBalanceVaultOperationSigner])
      .rpc();

    const mixedPosition = await getAccount(provider.connection, riderPositionLpToken);
    const mixedStake = await program.account.vaultStake.fetch(vaultStake) as any;
    expect(mixedPosition.amount).to.equal(2n * MIN_CAL_STAKE);
    expect(mixedPosition.isFrozen).to.equal(true);
    expect((await getAccount(provider.connection, riderLpAta)).amount).to.equal(0n);
    expect((await getAccount(provider.connection, riderBalanceLpToken)).amount).to.equal(0n);
    expect(bnToBigInt(mixedStake.lpTokens)).to.equal(2n * MIN_CAL_STAKE);

    for (const expectedRemaining of [MIN_CAL_STAKE, 0n]) {
      await program.methods
        .withdrawCalToBalance(
          bn(MIN_CAL_STAKE),
          await balanceVaultAuthorization(
            BALANCE_VAULT_OPERATION_KIND.withdrawCal,
            vaultId,
            MIN_CAL_STAKE,
          ),
        )
        .accounts({
          vault,
          vaultStake,
          vaultActivation,
          rider: rider.publicKey,
          riderBalance,
          riderBalanceAuthority,
          balanceVaultAuthority,
          operationAuthority: activeBalanceVaultOperationSigner.publicKey,
          programConfig,
          riderBalanceCalAccount: riderBalanceCalToken,
          vaultCalEscrow,
          calMint,
          vaultLpMint,
          riderBalanceLpAccount: riderPositionLpToken,
          tokenProgram: TOKEN_PROGRAM_ID,
        })
        .signers([activeBalanceVaultOperationSigner])
        .rpc();
      const remainingPosition = await getAccount(
        provider.connection,
        riderPositionLpToken,
      );
      const remainingStake = await program.account.vaultStake.fetch(vaultStake) as any;
      expect(remainingPosition.amount).to.equal(expectedRemaining);
      expect(remainingPosition.isFrozen).to.equal(true);
      expect(bnToBigInt(remainingStake.lpTokens)).to.equal(expectedRemaining);
      expect(bnToBigInt(remainingStake.calStaked)).to.equal(expectedRemaining);
    }

    const boundaryWithdrawAmount = 1n * CAL;
    const riderCalBeforeBoundaryWithdraw = (await getAccount(provider.connection, riderCalAta)).amount;
    const balanceCalBeforeBoundaryWithdraw = (await getAccount(provider.connection, riderBalanceCalToken)).amount;

    await expectRejected(program.methods
      .withdrawToWallet(bn(boundaryWithdrawAmount))
      .accounts({
        riderBalance,
        rider: rider.publicKey,
        riderBalanceAuthority,
        programConfig,
        riderBalanceSource: riderBalanceCalToken,
        riderWalletDestination: attackerDungAta,
        mint: calMint,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([rider])
      .rpc());

    await program.methods
      .withdrawToWallet(bn(boundaryWithdrawAmount))
      .accounts({
        riderBalance,
        rider: rider.publicKey,
        riderBalanceAuthority,
        programConfig,
        riderBalanceSource: riderBalanceCalToken,
        riderWalletDestination: riderCalAta,
        mint: calMint,
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .signers([rider])
      .rpc();

    const riderCalAfterBoundaryWithdraw = (await getAccount(provider.connection, riderCalAta)).amount;
    const balanceCalAfterBoundaryWithdraw = (await getAccount(provider.connection, riderBalanceCalToken)).amount;
    expect(riderCalAfterBoundaryWithdraw - riderCalBeforeBoundaryWithdraw).to.equal(boundaryWithdrawAmount);
    expect(balanceCalBeforeBoundaryWithdraw - balanceCalAfterBoundaryWithdraw).to.equal(boundaryWithdrawAmount);

    await expectRejected(program.methods
      .collectStakeRewardsFor()
      .accounts({
        vault,
        vaultStake,
        vaultActivation,
        staker: rider.publicKey,
        payer: wallet.publicKey,
        dungMint,
        stakerDungAccount: riderDungAta,
        protocolTreasury: treasuryAta,
        dungMintState,
        programConfig,
        dungMintAuth: findDungMintAuth()[0],
        tokenProgram: TOKEN_PROGRAM_ID,
      })
      .rpc());
  });
});

describe('Boulder Rollers deployable build boundary', () => {
  it('carries no test setup helpers: their discriminators reach the empty fallback', async function () {
    if (SMOKE_HELPERS_PRESENT) this.skip();
    for (const name of SMOKE_HELPER_INSTRUCTIONS) {
      let error = '';
      try {
        await provider.sendAndConfirm(new Transaction().add(new TransactionInstruction({
          programId: program.programId,
          keys: [],
          data: Buffer.concat([smokeDiscriminator(name), Buffer.alloc(16)]),
        })));
      } catch (caught: any) {
        error = `${caught?.message ?? caught}\n${(caught?.logs ?? []).join('\n')}`;
      }
      // 0x65 = InstructionFallbackNotFound: the deployable fallback has no handler.
      expect(error, name).to.include('custom program error: 0x65');
    }
  });

  it('removed instructions are gone from the IDL and reach the empty fallback', async () => {
    const removed = [
      'record_climb_completion', 'record_vault_completion', 'apply_halving', 'admin_create_vault',
      'create_vault_from_balance_cal_usdc', 'migrate_program_config', 'migrate_program_config_v3',
      'admin_initialize_user',
    ];
    const idlNames = new Set(program.idl.instructions.map(({ name }) => name));
    for (const name of removed) {
      expect(idlNames.has(name.replace(/_([a-z0-9])/g, (_, c) => c.toUpperCase())), name).to.equal(false);
      let error = '';
      try {
        await provider.sendAndConfirm(new Transaction().add(new TransactionInstruction({
          programId: program.programId,
          keys: [],
          data: Buffer.concat([smokeDiscriminator(name), Buffer.alloc(16)]),
        })));
      } catch (caught: any) {
        error = `${caught?.message ?? caught}\n${(caught?.logs ?? []).join('\n')}`;
      }
      expect(error, name).to.include('custom program error: 0x65');
    }
  });
});
