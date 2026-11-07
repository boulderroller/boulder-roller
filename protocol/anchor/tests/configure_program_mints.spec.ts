import { expect } from 'chai';
import * as fs from 'fs';
import { PublicKey } from '@solana/web3.js';

import {
  chooseSettlementClockCutover,
  parseArgs,
} from '../scripts/configure_program_mints.js';

const V2_ANCHOR = 1_704_110_400n;
const WEEK_SECONDS = 604_800n;

describe('configure_program_mints cutover controls', () => {
  it('imports under ESM and rejects unknown or incomplete arguments', () => {
    const mint = PublicKey.default.toBase58();

    expect(() => parseArgs(['--unknown'])).to.throw('Unknown argument');
    expect(() => parseArgs([
      '--cal-mint', mint,
      '--dung-mint', mint,
      '--settlement-clock-cutover',
    ])).to.throw('Missing value for --settlement-clock-cutover');
    expect(() => parseArgs([
      '--cal-mint', mint,
      '--dung-mint', mint,
      '--settlement-clock-cutover', 'not-an-integer',
    ])).to.throw('Invalid settlement clock cutover');
    expect(() => parseArgs([
      '--cal-mint', mint,
      '--dung-mint', mint,
      '--admin-keypair',
    ])).to.throw('Missing value for --admin-keypair');
  });

  it('rejects every legacy layout because the program no longer migrates ProgramConfig', () => {
    const cutover = V2_ANCHOR + 200n * WEEK_SECONDS;
    for (const size of [141, 182, 205, 246, 253, 325]) {
      expect(() => chooseSettlementClockCutover(Buffer.alloc(size), null))
        .to.throw('no longer migrates ProgramConfig');
      expect(() => chooseSettlementClockCutover(Buffer.alloc(size), cutover))
        .to.throw('no longer migrates ProgramConfig');
    }
  });

  it('accepts only the already-bound value for the current layout', () => {
    const current = Buffer.alloc(334);
    const cutover = V2_ANCHOR + 200n * WEEK_SECONDS;
    current.writeBigInt64LE(cutover, 325);
    current.writeUInt8(2, 333);

    expect(chooseSettlementClockCutover(current, null)).to.equal(cutover);
    expect(() => chooseSettlementClockCutover(current, cutover + WEEK_SECONDS))
      .to.throw('already bound');
  });

  it('uses finalized commitment for configuration and deployment verification', () => {
    const migrationSource = fs.readFileSync(
      new URL('../scripts/configure_program_mints.ts', import.meta.url),
      'utf8',
    );
    const validationSource = fs.readFileSync(
      new URL('../scripts/validate_deployment.ts', import.meta.url),
      'utf8',
    );
    const setupSource = fs.readFileSync(
      new URL('../scripts/setup-devnet.ts', import.meta.url),
      'utf8',
    );

    expect(migrationSource).to.include('new Connection(CLUSTER, "finalized")');
    expect(validationSource).to.include('new Connection(CLUSTER, "finalized")');
    expect(validationSource).to.include('chooseSettlementClockCutover');
    expect(validationSource).to.include('--configuration-only');
    expect(validationSource).to.include('Configuration-Only Summary');
    expect(migrationSource).to.include('[feePayer, admin]');
    expect(migrationSource).to.include('configureTx.feePayer = feePayer.publicKey');
    expect(migrationSource).not.to.include('migrate_program_config');
    expect(migrationSource).to.include('ProgramConfig admin cannot be used as the transaction fee payer');
    expect(migrationSource).not.to.include('devnet-deployer.json');
    expect(setupSource).to.include('chooseSettlementClockCutover');
    expect(setupSource).to.include('new Connection(opts.cluster, "finalized")');
    expect(setupSource).not.to.include('nextSettlementClockCutover');
  });

  it('preflights lookup-table creation against a bank newer than the finalized seed slot', () => {
    const reservationMigrationSource = fs.readFileSync(
      new URL('../scripts/migrate_dung_liability_reservation.ts', import.meta.url),
      'utf8',
    );

    expect(reservationMigrationSource).to.include(
      'const LOOKUP_TABLE_CREATE_SEND_OPTIONS = {\n'
      + '  commitment: "finalized",\n'
      + '  preflightCommitment: "confirmed",\n'
      + '} as const;',
    );
    expect(reservationMigrationSource).to.include(
      'new Transaction().add(createInstruction),\n'
      + '      [payer],\n'
      + '      LOOKUP_TABLE_CREATE_SEND_OPTIONS,',
    );
  });
});
