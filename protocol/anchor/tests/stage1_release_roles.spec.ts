import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { Keypair, PublicKey, SystemProgram } from '@solana/web3.js';

// Isolated validator suite: actual program authorization with disposable keys.
(process.env.STAGE1_RELEASE_ROLES === '1' ? describe : describe.skip)('Stage1 release roles', () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program: any = anchor.workspace.BoulderRollers;
  const wallet = provider.wallet as anchor.Wallet;
  const guardian = Keypair.generate(), registrar = Keypair.generate(), replacement = Keypair.generate(), outsider = Keypair.generate();
  const pda = (seed: string, ...parts: Buffer[]) => PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], program.programId)[0];
  const city = pda('s1v1_city'), programConfig = pda('program_config');
  const common = (admin = wallet.publicKey) => ({ city, programConfig, admin, systemProgram: SystemProgram.programId });
  const send = (call: any, signer?: Keypair) => call.signers(signer ? [signer] : []).rpc();
  async function refuses(action: Promise<any>) {
    let failed = false; try { await action; } catch { failed = true; }
    expect(failed, 'unauthorized transaction succeeded').to.equal(true);
  }
  before(async () => {
    expect(['127.0.0.1', 'localhost']).to.include(new URL(provider.connection.rpcEndpoint).hostname);
    const executable = (await provider.connection.getAccountInfo(program.programId))!;
    await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig, program: program.programId,
      programData: new PublicKey(executable.data.subarray(4, 36)), admin: wallet.publicKey, systemProgram: SystemProgram.programId}));
    await send(program.methods.initCityConfig(new BN(1791201600)).accounts(common()));
    for (const key of [guardian, registrar, replacement, outsider]) await provider.sendAndConfirm(new anchor.web3.Transaction().add(
      SystemProgram.transfer({fromPubkey: wallet.publicKey, toPubkey: key.publicKey, lamports: 1e9})));
    await send(program.methods.setStage1Guardian(guardian.publicKey).accounts(common()));
  });
  it('lets the guardian pause and resume intake and settlement immediately', async () => {
    await send(program.methods.pauseStage1Intake().accounts({city, guardian: guardian.publicKey}), guardian);
    await send(program.methods.pauseStage1Settlement().accounts({city, guardian: guardian.publicKey}), guardian);
    let state = await program.account.stage1CityConfig.fetch(city);
    expect([state.intakePaused, state.settlementPaused]).to.deep.equal([true, true]);
    await send(program.methods.resumeStage1Intake().accounts(common(guardian.publicKey)), guardian);
    await send(program.methods.resumeStage1Settlement().accounts(common(guardian.publicKey)), guardian);
    state = await program.account.stage1CityConfig.fetch(city);
    expect([state.intakePaused, state.settlementPaused]).to.deep.equal([false, false]);
  });
  it('restricts guardian and outsider administration and outsider resume', async () => {
    for (const signer of [guardian, outsider]) {
      await refuses(send(program.methods.setStage1Publisher(signer.publicKey).accounts(common(signer.publicKey)), signer));
      await refuses(send(program.methods.setStage1Guardian(signer.publicKey).accounts(common(signer.publicKey)), signer));
      await refuses(send(program.methods.configureStage1Dung(new BN(1), null).accounts(common(signer.publicKey)), signer));
    }
    await refuses(send(program.methods.resumeStage1Intake().accounts(common(outsider.publicKey)), outsider));
    await refuses(send(program.methods.resumeStage1Settlement().accounts(common(outsider.publicKey)), outsider));
  });
  async function admission(signer: Keypair, sequence: number) {
    const id = Buffer.alloc(16, sequence), profile = Buffer.alloc(32, sequence);
    const commitment = Buffer.alloc(64); commitment[0] = 1; id.copy(commitment, 1); commitment.writeUInt16BE(1, 17); profile.copy(commitment, 32);
    const digest = createHash('sha256').update(commitment).digest();
    const climb = pda('climb', digest), hill = pda('s1v1_hill', id);
    await send(program.methods.registerRatifiedClimb({canonId: [...id], canonVersion: 1, canonicalProfileHash: [...profile],
      commitmentHash: [...digest], recordContinuityPolicy: {newRecordBoard: {}}, name: `Registrar hill ${sequence}`,
      vertM: 100, distanceM: 1000, avgGradientPct: 1000}).accounts({climb,
        climbVersionIndex: pda('climb_version', id, Buffer.from([0, 1])), predecessorClimb: null,
        programConfig, admin: signer.publicKey, systemProgram: SystemProgram.programId})
      .remainingAccounts([{pubkey: city, isWritable: false, isSigner: false}]), signer);
    await send(program.methods.initHillBond().accounts({...common(signer.publicKey), climb, hill}), signer);
    expect((await program.account.stage1HillBond.fetch(hill)).climb.equals(climb)).to.equal(true);
  }
  it('admits climbs and hills using only the registrar, then revokes the replaced key', async () => {
    await send(program.methods.setStage1Registrar(registrar.publicKey).accounts(common()));
    await admission(registrar, 11);
    await send(program.methods.setStage1Registrar(replacement.publicKey).accounts(common()));
    await refuses(admission(registrar, 12));
    await admission(replacement, 13);
  });
  it('does not let the registrar publish, configure issuance, rotate roles or resume', async () => {
    for (const call of [program.methods.setStage1Publisher(replacement.publicKey), program.methods.setStage1Guardian(replacement.publicKey),
      program.methods.setStage1Registrar(outsider.publicKey), program.methods.configureStage1Dung(new BN(1), null),
      program.methods.resumeStage1Intake(), program.methods.resumeStage1Settlement()])
      await refuses(send(call.accounts(common(replacement.publicKey)), replacement));
  });
  it('keeps role keys separate and preserves pause flags on rotation', async () => {
    await refuses(send(program.methods.setStage1Guardian(replacement.publicKey).accounts(common())));
    await refuses(send(program.methods.setStage1Registrar(guardian.publicKey).accounts(common())));
    await refuses(send(program.methods.setStage1Publisher(replacement.publicKey).accounts(common())));
    await send(program.methods.pauseStage1Intake().accounts({city, guardian: guardian.publicKey}), guardian);
    await send(program.methods.setStage1Guardian(outsider.publicKey).accounts(common()));
    expect((await program.account.stage1CityConfig.fetch(city)).intakePaused).to.equal(true);
    await refuses(send(program.methods.resumeStage1Intake().accounts(common(guardian.publicKey)), guardian));
    await send(program.methods.resumeStage1Intake().accounts(common(outsider.publicKey)), outsider);
  });
});
