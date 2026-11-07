import { pubkeyToString, isDefaultPubkey, bytesToHex, bnToString, safeInt } from '../decoder';
import { query } from '../db';
import { Connection } from '@solana/web3.js';
import { config } from '../config';
import { observeFinalizedProgramVersion } from '../program-version-state';
import { ProgramVersionWindow, programVersionWindow } from '../program-version-window';
import { upsert } from './common';

/**
 * Write a decoded LocalLegend account to indexed_legends.
 *
 * LocalLegend IDL fields:
 *   vaultId: u64, holder: PublicKey, electionPeriod: u64,
 *   termStartEpoch: u64, termEndEpoch: u64, completionsAtElection: u32,
 *   runnerUp: PublicKey, runnerUpCompletions: u32, totalEarned: u64,
 *   isActive: bool, isBootstrap: bool, bump: u8
 */
export async function writeLegend(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  const holder = isDefaultPubkey(fields.holder)
    ? null
    : pubkeyToString(fields.holder);

  const runnerUp = isDefaultPubkey(fields.runnerUp)
    ? null
    : pubkeyToString(fields.runnerUp);
  const isBootstrap =
    fields.isBootstrap === undefined || fields.isBootstrap === null
      ? bnToString(fields.electionPeriod) === '0' && safeInt(fields.completionsAtElection) === 0
      : Boolean(fields.isBootstrap);

  await upsert(
    'indexed_legends',
    [
      'vault_id',
      'holder', 'election_period', 'term_start_epoch', 'term_end_epoch',
      'completions_at_election', 'runner_up', 'runner_up_completions',
      'total_earned', 'is_active', 'is_bootstrap',
      'chain_slot', 'indexed_at', 'bump',
    ],
    [
      bnToString(fields.vaultId),           // u64
      holder,
      bnToString(fields.electionPeriod),    // u64
      bnToString(fields.termStartEpoch),    // u64
      bnToString(fields.termEndEpoch),      // u64
      safeInt(fields.completionsAtElection), // u32
      runnerUp,
      safeInt(fields.runnerUpCompletions),   // u32
      bnToString(fields.totalEarned),
      fields.isActive,
      isBootstrap,
      slot,
      new Date(),
      safeInt(fields.bump),                  // u8
    ],
    ['vault_id']
  );
}

/**
 * Write a decoded UserState account to indexed_accounts.
 *
 * UserState IDL fields:
 *   owner: PublicKey, legacyCalSnapshot: u64, legacyCalEarnedToday: u64,
 *   legacyLastCalMint: i64, totalRides: u64, totalTss: u64,
 *   bioScore: u16, bump: u8
 */
export async function writeUserState(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_accounts',
    [
      'owner_pubkey',
      'cal_balance', 'cal_earned_today', 'last_cal_mint',
      'total_rides', 'total_tss', 'bio_score',
      'pda', 'chain_slot', 'indexed_at', 'bump',
    ],
    [
      pubkeyToString(fields.owner),
      bnToString(fields.legacyCalSnapshot),
      bnToString(fields.legacyCalEarnedToday),
      bnToString(fields.legacyLastCalMint),       // i64
      bnToString(fields.totalRides),        // u64
      bnToString(fields.totalTss),
      safeInt(fields.bioScore),              // u16
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),                  // u8
    ],
    ['owner_pubkey']
  );
}

/**
 * Write a decoded BeetleCard account to indexed_beetle_cards.
 *
 * BeetleCard IDL fields:
 *   owner: PublicKey, cardType: CardType (enum), scopeId: [u8;32],
 *   score: u64, level: u8, patternsScored: u32,
 *   lastUpdated: i64, createdAt: i64, bump: u8
 */
export async function writeBeetleCard(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  // CardType is an enum: { Climb: {}, Steady: {}, Explorer: {} }
  // Anchor decodes it as an object with a single key
  let cardTypeNum = 0;
  if (fields.cardType) {
    if ('climb' in fields.cardType || 'Climb' in fields.cardType) cardTypeNum = 0;
    else if ('steady' in fields.cardType || 'Steady' in fields.cardType) cardTypeNum = 1;
    else if ('explorer' in fields.cardType || 'Explorer' in fields.cardType) cardTypeNum = 2;
  }

  const scopeIdHex = bytesToHex(fields.scopeId);

  await upsert(
    'indexed_beetle_cards',
    [
      'owner_pubkey', 'card_type', 'scope_id_hex',
      'score', 'level', 'patterns_scored',
      'total_dung_burned', 'last_updated', 'created_at',
      'pda', 'chain_slot', 'indexed_at', 'bump',
    ],
    [
      pubkeyToString(fields.owner),
      cardTypeNum,
      scopeIdHex,
      bnToString(fields.score),
      safeInt(fields.level),                 // u8
      safeInt(fields.patternsScored),        // u32
      '0', // total_dung_burned not stored on-chain in BeetleCard, tracked via events
      bnToString(fields.lastUpdated),       // i64
      bnToString(fields.createdAt),         // i64
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),                  // u8
    ],
    ['owner_pubkey', 'card_type', 'scope_id_hex']
  );
}

/**
 * Write a decoded DungMintState singleton to indexed_supply.
 *
 * DungMintState IDL fields:
 *   authority: PublicKey, maxSupply: u64, totalMinted: u64,
 *   totalBurned: u64, communityMinted: u64, treasuryMinted: u64,
 *   teamMinted: u64, investorMinted: u64, polMinted: u64,
 *   currentEmissionRateBps: u64, lastHalvingEpoch: u64, bump: u8,
 *   communityReserved: u64, reservationPolicyVersion: u8
 */
export async function writeDungMintState(
  fields: Record<string, any>,
  pda: string,
  slot: number
): Promise<void> {
  await upsert(
    'indexed_supply',
    [
      'id',
      'authority', 'max_supply', 'total_minted', 'total_burned',
      'community_minted', 'treasury_minted', 'team_minted',
      'investor_minted', 'pol_minted',
      'current_emission_rate_bps', 'last_halving_epoch',
      'community_reserved', 'reservation_policy_version',
      'pda', 'chain_slot', 'indexed_at', 'bump',
    ],
    [
      1,
      pubkeyToString(fields.authority),
      bnToString(fields.maxSupply),
      bnToString(fields.totalMinted),
      bnToString(fields.totalBurned),
      bnToString(fields.communityMinted),
      bnToString(fields.treasuryMinted),
      bnToString(fields.teamMinted),
      bnToString(fields.investorMinted),
      bnToString(fields.polMinted),
      bnToString(fields.currentEmissionRateBps),
      bnToString(fields.lastHalvingEpoch),  // u64
      bnToString(fields.communityReserved),
      safeInt(fields.reservationPolicyVersion),
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['id']
  );
}

const U64_MAX = (1n << 64n) - 1n;

/** Project canonical SPL mint supply separately from program burn telemetry. */
export async function writeDungMintSupply(
  supply: string,
  slot: number
): Promise<boolean> {
  if (!/^\d+$/.test(supply) || BigInt(supply) > U64_MAX) {
    throw new Error('[Supply] SPL mint supply must be a canonical u64 decimal string');
  }
  if (!Number.isSafeInteger(slot) || slot < 0) {
    throw new Error('[Supply] SPL mint supply requires a valid chain slot');
  }

  const result = await query(
    `UPDATE indexed_supply
     SET spl_mint_supply = $1::NUMERIC,
         spl_mint_supply_slot = $2::BIGINT,
         spl_mint_supply_indexed_at = $3::TIMESTAMPTZ
     WHERE id = 1
       AND (
         $2::BIGINT > COALESCE(spl_mint_supply_slot, -1)
         OR (
           $2::BIGINT = spl_mint_supply_slot
           AND $1::NUMERIC = spl_mint_supply
         )
       )`,
    [supply, slot, new Date()]
  );
  return (result.rowCount ?? 0) > 0;
}

/**
 * Write a decoded ProgramConfig singleton to indexed_program_config.
 *
 * ProgramConfig IDL fields:
 *   adminAuthority: PublicKey, backendAuthority: PublicKey,
 *   initialized: bool, bump: u8, programVersion: u8,
 *   calMint: PublicKey, dungMint: PublicKey,
 *   calMintAuthBump: u8, dungMintAuthBump: u8,
 *   polTokenAccount: PublicKey, treasuryTokenAccount: PublicKey,
 *   vaultCreationDung: u64, vaultCreationCal: u64,
 *   harvestFeeBps: u64, minterRightsEpochs: u64,
 *   localLegendTermEpochs: u64, epochsPerHalving: u64,
 *   settlementClockV2StartsAt: i64, settlementClockVersion: u8
 */
export async function writeProgramConfig(
  fields: Record<string, any>,
  pda: string,
  slot: number,
  window: ProgramVersionWindow = programVersionWindow
): Promise<void> {
  if (fields.initialized !== true) {
    const error = new Error('ProgramConfig is not initialized');
    window.invalidate(error);
    throw error;
  }
  const programVersion = await observeFinalizedProgramVersion(
    new Connection(config.rpcUrl, 'finalized'), fields.programVersion, window
  );
  await upsert(
    'indexed_program_config',
    [
      'id',
      'admin_authority', 'backend_authority', 'initialized', 'program_version',
      'cal_mint', 'dung_mint',
      'cal_mint_auth_bump', 'dung_mint_auth_bump',
      'pol_token_account', 'treasury_token_account',
      'vault_creation_dung', 'vault_creation_cal', 'harvest_fee_bps',
      'minter_rights_epochs', 'local_legend_term_epochs', 'epochs_per_halving',
      'settlement_clock_v2_starts_at', 'settlement_clock_version',
      'settlement_clock_source_commitment',
      'pda', 'chain_slot', 'indexed_at', 'bump',
    ],
    [
      1,
      pubkeyToString(fields.adminAuthority),
      pubkeyToString(fields.backendAuthority),
      fields.initialized,
      programVersion,
      pubkeyToString(fields.calMint),
      pubkeyToString(fields.dungMint),
      safeInt(fields.calMintAuthBump),
      safeInt(fields.dungMintAuthBump),
      pubkeyToString(fields.polTokenAccount),
      pubkeyToString(fields.treasuryTokenAccount),
      bnToString(fields.vaultCreationDung),
      bnToString(fields.vaultCreationCal),
      bnToString(fields.harvestFeeBps),
      bnToString(fields.minterRightsEpochs),
      bnToString(fields.localLegendTermEpochs),
      bnToString(fields.epochsPerHalving),
      bnToString(fields.settlementClockV2StartsAt),
      safeInt(fields.settlementClockVersion),
      'finalized',
      pda,
      slot,
      new Date(),
      safeInt(fields.bump),
    ],
    ['id']
  );
}
