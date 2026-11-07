import {
  assessProgramVersion,
  decodeProgramConfigVersion,
  fetchProgramVersionGate,
} from '../programVersion';
import { PublicKey, type Connection } from '@solana/web3.js';
import { SOLANA_PROGRAM_ID } from '../../constants/config';
import {
  CURRENT_PROGRAM_VERSION,
} from '../../generated/boulderRollersProgramVersion';

describe('ProgramConfig client compatibility gate', () => {
  test('enables verification only for the generated exact version', () => {
    const incompatibleProgramVersion = CURRENT_PROGRAM_VERSION ^ 0x01;

    expect(assessProgramVersion(CURRENT_PROGRAM_VERSION)).toEqual({
      status: 'compatible',
      expectedVersion: CURRENT_PROGRAM_VERSION,
      observedVersion: CURRENT_PROGRAM_VERSION,
      verifyEnabled: true,
    });

    expect(assessProgramVersion(incompatibleProgramVersion)).toEqual({
      status: 'mismatch',
      expectedVersion: CURRENT_PROGRAM_VERSION,
      observedVersion: incompatibleProgramVersion,
      verifyEnabled: false,
    });
    expect(
      assessProgramVersion(CURRENT_PROGRAM_VERSION, incompatibleProgramVersion),
    ).toEqual({
      status: 'mismatch',
      expectedVersion: incompatibleProgramVersion,
      observedVersion: CURRENT_PROGRAM_VERSION,
      verifyEnabled: false,
    });
  });

  test('fails closed when ProgramConfig is unavailable', () => {
    expect(assessProgramVersion(null)).toEqual({
      status: 'unavailable',
      expectedVersion: CURRENT_PROGRAM_VERSION,
      observedVersion: null,
      verifyEnabled: false,
    });
  });

  test('reads the stable version byte and rejects truncated accounts', () => {
    const accountData = new Uint8Array(75);
    accountData[72] = CURRENT_PROGRAM_VERSION;

    expect(decodeProgramConfigVersion(accountData)).toBe(CURRENT_PROGRAM_VERSION);
    expect(() => decodeProgramConfigVersion(accountData.subarray(0, 72))).toThrow(
      'ProgramConfig stable prefix is truncated',
    );
  });

  test('fails closed when ProgramConfig exists but is not initialized', async () => {
    const programId = new PublicKey(SOLANA_PROGRAM_ID);
    const data = Buffer.alloc(75);
    Buffer.from('c4d25ae790958c3f', 'hex').copy(data, 0);
    data[72] = CURRENT_PROGRAM_VERSION;
    data[73] = 0;
    const connection = {
      getAccountInfo: jest.fn(async () => ({ owner: programId, data })),
    } as unknown as Connection;

    await expect(fetchProgramVersionGate(connection)).resolves.toEqual({
      status: 'unavailable',
      expectedVersion: CURRENT_PROGRAM_VERSION,
      observedVersion: null,
      verifyEnabled: false,
    });
  });
});
