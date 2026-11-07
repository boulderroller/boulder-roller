import {
  BOULDER_ROLLERS_ACCOUNTS,
  BOULDER_ROLLERS_IDL_NAME,
  BOULDER_ROLLERS_INSTRUCTIONS,
  type BoulderRollersAccountName,
} from '../boulderRollersIdl';

describe('generated Boulder Rollers IDL surface', () => {
  test('uses the committed Anchor IDL as the chain-type source', () => {
    expect(BOULDER_ROLLERS_IDL_NAME).toBe('boulder_rollers');
    expect(BOULDER_ROLLERS_ACCOUNTS).toContain('ProgramConfig');
    expect(BOULDER_ROLLERS_ACCOUNTS).toContain('RideAttestation');
    expect(BOULDER_ROLLERS_ACCOUNTS).toContain('RiderSoul');
    expect(BOULDER_ROLLERS_INSTRUCTIONS).toContain('recordRide');
    expect(BOULDER_ROLLERS_INSTRUCTIONS).toContain('recordClimbCompletionV2');
  });

  test('generated account names are compile-time literal types', () => {
    const account: BoulderRollersAccountName = 'ProgramConfig';
    expect(account).toBe('ProgramConfig');
  });
});
