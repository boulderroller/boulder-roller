import {
  unavailableVerification,
  verifyExact,
  verifyNumber,
} from '../verify';

describe('verify primitives', () => {
  test('on-chain-only values verify when no projection exists', () => {
    expect(verifyExact(null, 'chain-value')).toEqual({
      state: 'verified',
      projected: null,
      onchain: 'chain-value',
    });
  });

  test('exact mismatch diverges', () => {
    expect(verifyExact('projected', 'onchain').state).toBe('diverged');
  });

  test('numeric tolerance supports decimal display differences', () => {
    expect(
      verifyNumber({
        projected: 10,
        onchain: 10.004,
        tolerance: 0.01,
      }).state,
    ).toBe('verified');
  });

  test('missing chain value is unavailable when projection exists', () => {
    expect(verifyNumber({ projected: 10, onchain: null }).state).toBe('unavailable');
  });

  test('errors become unavailable with a stable message', () => {
    expect(unavailableVerification(12, new Error('RPC down'))).toEqual({
      state: 'unavailable',
      projected: 12,
      onchain: null,
      error: 'RPC down',
    });
  });
});
