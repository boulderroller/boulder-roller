import { goBackOrReset } from '../backNavigation';

describe('goBackOrReset', () => {
  test('uses stack back when history exists', () => {
    const navigation = {
      canGoBack: jest.fn(() => true),
      goBack: jest.fn(),
      reset: jest.fn(),
    };

    goBackOrReset(navigation as any, 'Profile');

    expect(navigation.goBack).toHaveBeenCalledTimes(1);
    expect(navigation.reset).not.toHaveBeenCalled();
  });

  test('resets to fallback tab when opened from a cold deep link', () => {
    const navigation = {
      canGoBack: jest.fn(() => false),
      goBack: jest.fn(),
      reset: jest.fn(),
    };

    goBackOrReset(navigation as any, 'Climbs');

    expect(navigation.goBack).not.toHaveBeenCalled();
    expect(navigation.reset).toHaveBeenCalledWith({
      index: 0,
      routes: [
        {
          name: 'Tabs',
          params: { screen: 'Climbs' },
        },
      ],
    });
  });
});
