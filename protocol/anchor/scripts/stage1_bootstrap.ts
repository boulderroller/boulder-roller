// Each action is one reviewable transaction: city, publisher, asset, refresh,
// enable, hill. Existing desired state is an asserted no-op; mismatches fail.
import { SystemProgram, SYSVAR_RENT_PUBKEY } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID } from '@solana/spl-token';
import { fileURLToPath } from 'url';
import { resolve } from 'path';
import { Operator, Operation, bn, pk, requireThat, runOperator } from './stage1_operator.js';

export const CAPS = { line: '10000000000', live: '5000000000', token: '2000000000000', hill: '500000000000', total: '5000000000000', seasonWeeks: 26 };
export async function assertCity(r: Operator, input: any) {
  const c = await r.fetch('Stage1CityConfig', r.pda('s1v1_city'));
  requireThat(c?.version === 1 && c.seasonAnchor.toString() === String(input.seasonAnchor), 'City season anchor mismatch');
  for (const [field, value] of Object.entries({ lineLamports: CAPS.line, liveLamports: CAPS.live,
    tokenCapLamports: CAPS.token, hillCapLamports: CAPS.hill, totalCapLamports: CAPS.total, seasonWeeks: CAPS.seasonWeeks })) {
    requireThat(String(c[field]) === String(value), `City ${field} mismatch`);
  }
  return c;
}

export async function bootstrap(r: Operator, input: any): Promise<Operation> {
  r.validateRoles(input);
  requireThat(input.assetKind !== 'SPL test asset' || r.interface === 'devnet', 'Test asset requires devnet program interface');
  requireThat(JSON.stringify(input.caps) === JSON.stringify(CAPS), 'Input must state the exact ratified caps');
  const m: any = r.program.methods, city = r.pda('s1v1_city'), programConfig = r.pda('program_config');
  const mint = pk(input.mint), provider = pk(input.pool), asset = r.pda('s1v1_asset', mint.toBuffer());
  const earnings = r.pda('s1v1_earnings', mint.toBuffer()), testPool = r.pda('s1v1_test_pool');
  const common = { city, programConfig, admin: r.admin, systemProgram: SystemProgram.programId };
  const assetAccounts = { ...common, asset, mint, earnings, tokenProgram: TOKEN_PROGRAM_ID, rent: SYSVAR_RENT_PUBKEY };
  const pair = [provider, mint].map(pubkey => ({ pubkey, isWritable: false, isSigner: false }));
  const action = r.options.action;
  let builder: any;
  let check: () => Promise<void>;
  if (action === 'city') {
    const existing = await r.fetch('Stage1CityConfig', city);
    if (!existing) builder = m.initCityConfig(bn(input.seasonAnchor)).accounts(common);
    check = async () => { await assertCity(r, input); };
    if (existing) await check();
  } else {
    await assertCity(r, input);
    if (action === 'publisher') {
      const c = await r.fetch('Stage1CityConfig', city);
      requireThat(c.publisher.equals(pk(input.publisher)) || c.publisher.equals(pk('11111111111111111111111111111111')), 'Refusing to replace another publisher');
      if (!c.publisher.equals(pk(input.publisher))) builder = m.setStage1Publisher(pk(input.publisher)).accounts(common);
      check = async () => { requireThat((await r.fetch('Stage1CityConfig', city)).publisher.equals(pk(input.publisher)), 'Publisher mismatch'); };
    } else if (['asset', 'refresh', 'enable', 'disable'].includes(action)) {
      const a = await r.fetch('Stage1AssetConfig', asset);
      await r.read(provider); await r.read(mint);
      const test = input.assetKind === 'SPL test asset';
      requireThat(test || input.assetKind === 'mainnet pinned', 'Explicit assetKind required');
      if (test) {
        requireThat(r.options.cluster !== 'mainnet-beta', 'Test asset cannot target mainnet');
        const registration = await r.fetch('Stage1TestPool', testPool);
        if (registration) requireThat(registration.provider.equals(provider) && registration.mint.equals(mint), 'Immutable test pool mismatch');
        else requireThat(action === 'asset', 'Register test pool first');
        if (action === 'asset' && !registration) builder = m.registerStage1TestPool().accounts({ ...assetAccounts, provider, testPool });
      } else if (action === 'asset' && !a) builder = m.configureAsset(false).accounts(assetAccounts).remainingAccounts(pair);
      if (a) requireThat(a.providerAccount.equals(provider) && a.mint.equals(mint) && (test ? a.adapter === 5 : [2, 3, 4].includes(a.adapter)), 'Asset identity mismatch');
      if (action !== 'asset') {
        requireThat(a, 'Register asset first');
        const epoch = (await r.connection.getEpochInfo('finalized')).epoch;
        if (action === 'refresh') builder = m.refreshStage1Rate().accounts({ city, asset, mint, provider });
        if (action === 'disable') builder = m.configureAsset(false).accounts(assetAccounts);
        if (action === 'enable') builder = m.configureAsset(true).accounts(assetAccounts).remainingAccounts(pair);
      }
      check = async () => {
        const value = await r.fetch('Stage1AssetConfig', asset);
        requireThat(value?.mint.equals(mint) && value.providerAccount.equals(provider) && (test ? value.adapter === 5 : [2, 3, 4].includes(value.adapter)), 'Finalized asset identity mismatch');
        if (test) {
          const registration = await r.fetch('Stage1TestPool', testPool);
          requireThat(registration?.provider.equals(provider) && registration.mint.equals(mint), 'Finalized singleton mismatch');
        }
        if (action === 'enable') requireThat(value.enabled, 'Asset not enabled');
        if (action === 'disable') requireThat(!value.enabled, 'Asset not disabled');
        if (action === 'refresh' || action === 'enable') requireThat(value.observationAdmitted && value.admittedNumerator.gt(bn(0)) && value.admittedDenominator.gt(bn(0)) &&
          value.admittedEpoch.toString() === String((await r.connection.getEpochInfo('finalized')).epoch), 'Rate is not current');
      };
    } else if (action === 'hill') {
      const climb = pk(input.climb), c = await r.fetch('Climb', climb);
      requireThat(c && c.successorClimb.equals(pk('11111111111111111111111111111111')), 'Current admitted canonical climb required');
      const hill = r.pda('s1v1_hill', Buffer.from(c.canonId));
      if (!await r.fetch('Stage1HillBond', hill)) builder = m.initHillBond().accounts({ ...common, climb, hill });
      check = async () => { const h = await r.fetch('Stage1HillBond', hill); requireThat(h?.city.equals(city) && h.climb.equals(climb), 'Hill admission mismatch'); };
    } else throw new Error('Unknown bootstrap action');
  }
  if (!builder) await check!();
  return { instructions: builder ? [await builder.instruction()] : [], assert: check!, description: `Stage1 ${action}: ${input.assetKind}` };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runOperator('stage1-bootstrap', bootstrap).catch(e => { console.error(e.message); process.exitCode = 1; });
}
