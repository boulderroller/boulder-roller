import {
  formatShortWallet,
  formatUsername,
  riderInitial,
  riderPrimaryLabel,
  riderSecondaryLabel,
} from '../riderIdentity';

describe('rider identity labels', () => {
  test('prefers display name over username and wallet', () => {
    const identity = {
      displayName: 'Tim',
      username: 'boulder_tim',
      wallet: '3boUdoRSqJKMn1sNFMoc8WLDFjzZELQEMQabV2hVnsWu',
    };

    expect(riderPrimaryLabel(identity)).toBe('Tim');
    expect(riderSecondaryLabel(identity, { includeWallet: true })).toBe('@boulder_tim');
    expect(riderInitial(identity)).toBe('T');
  });

  test('uses username when display name is absent', () => {
    expect(riderPrimaryLabel({ username: '@wallhunter' })).toBe('@wallhunter');
    expect(formatUsername('wallhunter')).toBe('@wallhunter');
  });

  test('uses rider wallet fallback only when profile labels are absent', () => {
    const wallet = '3boUdoRSqJKMn1sNFMoc8WLDFjzZELQEMQabV2hVnsWu';

    expect(formatShortWallet(wallet)).toBe('3boU...nsWu');
    expect(riderPrimaryLabel({ wallet })).toBe('Rider 3boU...nsWu');
    expect(riderPrimaryLabel(null)).toBe('Rider');
  });
});
