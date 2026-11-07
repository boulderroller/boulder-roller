import { Connection, PublicKey } from '@solana/web3.js';
import {
  DecodedAccount,
  decodeAccount,
  pubkeyToString,
} from '../decoder';
import { config } from '../config';
import { programVersionWindow } from '../program-version-window';
import { ReleaseAuthorityProjectionPending } from '../releaseWeek';
import { writeStage1Account } from '../stage1';
import { writeVault, writeVaultCounter } from './vault';
import {
  quarantineCanonAccount,
  requireCanonIndexerProgramVersion,
  writeClimb,
} from './canon';
import {
  CURRENT_PROGRAM_VERSION,
  PROGRAM_VERSION_FAMILY,
} from '../generated-program-version';
import { writeActivation } from './activation';
import { writeLeaderboard } from './leaderboard';
import { writeStake, writeCompletion } from './stake';
import {
  writeCalMintReceipt,
  writeClimbCompletionReceipt,
  writeClimbCompletionReceiptV2,
  writeHeldRideReleaseAuthority,
  writeReleasedCalMintReceipt,
  writeReleasedClimbCompletionReceipt,
  writeRideAttestation,
  writeRiderSoul,
} from './identity';
import {
  writeLegend,
  writeUserState,
  writeBeetleCard,
  writeDungMintState,
  writeProgramConfig,
} from './legend';

/**
 * Route a decoded account to the appropriate writer.
 *
 * Account types we index (15 primary types from the current program):
 *   Vault, VaultLeaderboard, VaultStake, VaultCompletion, VaultCounter,
 *   VaultActivation, LocalLegend, UserState, RiderSoul, RideAttestation,
 *   CalMintReceipt, ClimbCompletionReceipt, BeetleCard, DungMintState,
 *   ProgramConfig
 *
 * Account types we skip (not indexed):
 *   RideTributeBudget - enforced on-chain; completion events remain the projection source
 *   Segment, SegmentCounter, Claim - legacy segment system
 */
export interface RouteAccountContext {
  connection?: Pick<Connection, 'getAccountInfoAndContext'>;
}

export async function routeFinalizedExpectedAccount(
  connection: Pick<Connection, 'getAccountInfoAndContext'>,
  pda: string,
  expectedType: string,
  minContextSlot: number
): Promise<void> {
  const response = await connection.getAccountInfoAndContext(
    new PublicKey(pda),
    { commitment: 'finalized', minContextSlot }
  );
  if (response.context.slot < minContextSlot) {
    throw new Error(
      `${expectedType} ${pda} was fetched below finalized slot ${minContextSlot}`
    );
  }
  const account = response.value;
  if (!account) {
    throw new Error(`${expectedType} ${pda} is missing at finalized state`);
  }
  if (account.owner.toBase58() !== config.programId) {
    throw new Error(`${expectedType} ${pda} is not owned by the configured program`);
  }
  const decoded = decodeAccount(Buffer.from(account.data));
  if (!decoded || decoded.type !== expectedType) {
    throw new Error(`${expectedType} ${pda} has the wrong finalized account type`);
  }
  const wrote = await routeAccount(decoded, pda, response.context.slot, {
    connection,
  });
  if (!wrote) {
    throw new Error(`${expectedType} ${pda} was not projected`);
  }
}

async function writeReleasedReceiptWithAuthorityHydration(
  decoded: DecodedAccount,
  pda: string,
  slot: number,
  context: RouteAccountContext,
  writer: (
    fields: Record<string, any>,
    receiptPda: string,
    receiptSlot: number
  ) => Promise<void>
): Promise<boolean> {
  try {
    await writer(decoded.fields, pda, slot);
    return true;
  } catch (error) {
    if (
      !(error instanceof ReleaseAuthorityProjectionPending) ||
      !context.connection
    ) {
      throw error;
    }
    const releaseAuthorityPda = pubkeyToString(
      decoded.fields.releaseAuthority
    );
    if (releaseAuthorityPda !== error.releaseAuthorityPda) {
      throw error;
    }
    await routeFinalizedExpectedAccount(
      context.connection,
      releaseAuthorityPda,
      'HeldRideReleaseAuthority',
      slot
    );
    await writer(decoded.fields, pda, slot);
    return true;
  }
}

export async function routeAccount(
  decoded: DecodedAccount,
  pda: string,
  slot: number,
  context: RouteAccountContext = {}
): Promise<boolean> {
  if (decoded.type !== 'ProgramConfig') programVersionWindow.assertNoFailure();
  if (decoded.type.startsWith('Stage1')) {
    programVersionWindow.requireStage1();
    await writeStage1Account(decoded.type,pda,decoded.fields,slot);
    return true;
  }
  switch (decoded.type) {
    case 'Climb':
      try {
        requireCanonIndexerProgramVersion(
          CURRENT_PROGRAM_VERSION,
          PROGRAM_VERSION_FAMILY
        );
      } catch (error) {
        await quarantineCanonAccount({
          pda,
          accountType: 'Climb',
          reason: error instanceof Error ? error.message : 'program family mismatch',
          programVersion: CURRENT_PROGRAM_VERSION,
          slot,
          fields: decoded.fields,
        });
        return false;
      }
      return writeClimb(decoded.fields, pda, slot);

    case 'Vault':
      return writeVault(decoded.fields, pda, slot);

    case 'VaultCounter':
      await writeVaultCounter(decoded.fields, pda, slot);
      return true;

    case 'VaultActivation':
      await writeActivation(decoded.fields, pda, slot);
      return true;

    case 'VaultLeaderboard':
      await writeLeaderboard(decoded.fields, pda, slot);
      return true;

    case 'VaultStake':
      await writeStake(decoded.fields, pda, slot);
      return true;

    case 'VaultCompletion':
      await writeCompletion(decoded.fields, pda, slot);
      return true;

    case 'RiderSoul':
      await writeRiderSoul(decoded.fields, pda, slot);
      return true;

    case 'RideAttestation':
      await writeRideAttestation(decoded.fields, pda, slot);
      return true;

    case 'HeldRideReleaseAuthority':
      await writeHeldRideReleaseAuthority(decoded.fields, pda, slot);
      return true;

    case 'CalMintReceipt':
      await writeCalMintReceipt(decoded.fields, pda, slot);
      return true;

    case 'ReleasedCalMintReceipt':
      return writeReleasedReceiptWithAuthorityHydration(
        decoded,
        pda,
        slot,
        context,
        writeReleasedCalMintReceipt
      );

    case 'ClimbCompletionReceipt':
      await writeClimbCompletionReceipt(decoded.fields, pda, slot);
      return true;

    case 'ClimbCompletionReceiptV2':
      await writeClimbCompletionReceiptV2(decoded.fields, pda, slot);
      return true;

    case 'ReleasedClimbCompletionReceipt':
      return writeReleasedReceiptWithAuthorityHydration(
        decoded,
        pda,
        slot,
        context,
        writeReleasedClimbCompletionReceipt
      );

    case 'LocalLegend':
      await writeLegend(decoded.fields, pda, slot);
      return true;

    case 'UserState':
      await writeUserState(decoded.fields, pda, slot);
      return true;

    case 'BeetleCard':
      await writeBeetleCard(decoded.fields, pda, slot);
      return true;

    case 'DungMintState':
      await writeDungMintState(decoded.fields, pda, slot);
      return true;

    case 'ProgramConfig':
      await writeProgramConfig(decoded.fields, pda, slot);
      return true;

    // Types we intentionally skip
    case 'RideTributeBudget':
    case 'ReleasedRideTributeBudget':
    case 'Segment':
    case 'SegmentCounter':
    case 'Claim':
    case 'ClimbVersionIndex':
      return false;

    default:
      console.warn(`[Router] Unknown account type: ${decoded.type}`);
      return false;
  }
}
