import { TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID, unpackAccount } from '@solana/spl-token';
import { Operator, Operation, pk, bn, requireThat } from './stage1_operator.js';
import { assertCity } from './stage1_bootstrap.js';

export async function validateStage1(r: Operator, input: any): Promise<Operation> {
  r.validateRoles(input);
  requireThat(input.assetKind !== 'SPL test asset' || r.interface === 'devnet', 'Test asset requires devnet program interface');
  requireThat(r.options.action === 'validate', 'Validation action must be validate');
  const check = async () => {
    const city = r.pda('s1v1_city'), c = await assertCity(r, input), mint = pk(input.mint);
    requireThat(c.publisher.equals(pk(input.publisher)), 'Publisher mismatch');
    const asset = r.pda('s1v1_asset', mint.toBuffer()), a = await r.fetch('Stage1AssetConfig', asset);
    requireThat(a?.version === 1 && a.enabled && a.city.equals(city) && a.mint.equals(mint) && a.providerAccount.equals(pk(input.pool)), 'Asset identity/enablement mismatch');
    requireThat(a.observationAdmitted && a.admittedNumerator.gt(bn(0)) && a.admittedDenominator.gt(bn(0)) && a.admittedEpoch.toString() === String((await r.connection.getEpochInfo('finalized')).epoch), 'Asset admission is not current');
    if (input.assetKind === 'SPL test asset') {
      requireThat(r.options.cluster !== 'mainnet-beta' && a.adapter === 5, 'Test asset network/label mismatch');
      const registration = await r.fetch('Stage1TestPool', r.pda('s1v1_test_pool'));
      requireThat(registration?.version === 1 && registration.mint.equals(mint) && registration.provider.equals(pk(input.pool)), 'Test pool singleton mismatch');
    } else requireThat(input.assetKind === 'mainnet pinned' && [2, 3, 4].includes(a.adapter), 'Unsupported asset identity');
    await r.read(a.providerAccount); await r.read(mint);
    const climb = await r.fetch('Climb', pk(input.climb));
    requireThat(climb && climb.successorClimb.equals(pk('11111111111111111111111111111111')), 'Current non-superseded canonical climb required');
    const hill = await r.fetch('Stage1HillBond', r.pda('s1v1_hill', Buffer.from(climb.canonId)));
    requireThat(hill?.city.equals(city) && hill.climb.equals(pk(input.climb)), 'Hill admission mismatch');
    const address = r.pda('s1v1_earnings', mint.toBuffer()), custody = await r.read(address);
    requireThat(custody, 'Missing earnings custody');
    const token = unpackAccount(address, custody, TOKEN_PROGRAM_ID), l = a.ledger;
    const n = (v: any) => BigInt(v.toString());
    requireThat(token.owner.equals(asset) && token.mint.equals(mint) && token.amount >= n(l.earnings), 'Earnings custody mismatch');
    requireThat(n(l.paid) + n(a.feesAssessed) + n(l.claimable) + n(l.held) === n(a.harvestedUnits) &&
      n(l.earnings) === n(a.feesAssessed) + n(l.claimable) + n(l.held) &&
      n(l.deposited) === n(l.ownerCustody) + n(l.ownerReturns) + n(l.earnings) + n(l.paid) && n(l.pool) <= n(l.held), 'Stage1 solvency equality failed');
    // Execute the program's exact 1b decoder without writing chain state or
    // loading any signer. A cached admitted quote alone is insufficient proof.
    const ix = await (r.program.methods as any).refreshStage1Rate().accounts({ city, asset, mint, provider: a.providerAccount }).instruction();
    const block = await r.connection.getLatestBlockhash('finalized');
    const tx = new VersionedTransaction(new TransactionMessage({ payerKey: r.feePayer, recentBlockhash: block.blockhash, instructions: [ix] }).compileToLegacyMessage());
    const result = await r.connection.simulateTransaction(tx, { sigVerify: false, commitment: 'finalized', replaceRecentBlockhash: false });
    requireThat(!result.value.err, `Current provider validation failed: ${JSON.stringify(result.value.err)}`);
  };
  await check();
  return { instructions: [], assert: check, description: 'Finalized Stage1 city, caps, publisher, pool, mint, admission, hill and solvency validated; unsigned provider simulation only' };
}
