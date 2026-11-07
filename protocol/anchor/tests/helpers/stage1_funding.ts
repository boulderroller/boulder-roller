import { PublicKey, SystemProgram, SYSVAR_CLOCK_PUBKEY, TransactionInstruction } from '@solana/web3.js';
import BN from 'bn.js';

// Normal program instructions create the weekly income account. In exact-clock
// simulations the initializer and sweep execute in one simulated transaction.
export async function fundedSweep(program: any, provider: any, payer: PublicKey, ix: TransactionInstruction) {
  if (!ix.programId.equals(program.programId) || (process.env.STAGE1_LOCALNET !== '1' && process.env.STAGE1_DEPLOYABLE !== '1')) return [ix];
  const decoded = program.coder.instruction.decode(ix.data);
  const slots: Record<string, number> = { harvestStage1: 3, beginWithdrawal: 5, completeWithdrawal: 4 };
  if (!decoded || slots[decoded.name] === undefined) return [ix];
  const city = ix.keys[0].pubkey, hill = ix.keys[1].pubkey, asset = ix.keys[slots[decoded.name]].pubkey;
  const [cityState, assetState, clock] = await Promise.all([
    program.account.stage1CityConfig.fetch(city), program.account.stage1AssetConfig.fetch(asset),
    provider.connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY, 'processed'),
  ]);
  const week = new BN(String((clock!.data.readBigInt64LE(32) - BigInt(cityState.seasonAnchor.toString())) / 604800n));
  const funding = PublicKey.findProgramAddressSync([Buffer.from('s1v1_funding'), hill.toBuffer(),
    assetState.mint.toBuffer(), week.toArrayLike(Buffer, 'le', 8)], program.programId)[0];
  const cursor = PublicKey.findProgramAddressSync([Buffer.from('s1v1_cursor'), hill.toBuffer(), assetState.mint.toBuffer()], program.programId)[0];
  const init = await program.methods.initStage1Settlement().accounts({ city, hillAccount: { hill }, asset, cursor, payer, systemProgram: SystemProgram.programId }).instruction();
  const open = await program.methods.openStage1Week(week).accounts({ city, hillAccount: { hill }, asset, funding,
    payer, systemProgram: SystemProgram.programId, cursor }).instruction();
  ix.keys.push({ pubkey: funding, isSigner: false, isWritable: true });
  return [init, open, ix];
}
