import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';

import FollowButton from '../FollowButton';
import RiderHeader from '../RiderHeader';
import RiderRow from '../RiderRow';

const IDENTITY = {
  id: 'user-1',
  wallet: '3boUdoRSqJKMn1sNFMoc8WLDFjzZELQEMQabV2hVnsWu',
  username: 'tim',
  displayName: 'Tim',
  avatarUrl: null,
};

describe('rider primitives', () => {
  test('RiderHeader keeps identity primary and wallet secondary', () => {
    render(
      <RiderHeader
        identity={IDENTITY}
        accountContext
        stats={[{ label: 'Rides', value: '7' }]}
      />,
    );

    expect(screen.getByText('Tim')).toBeTruthy();
    expect(screen.getByText('@tim')).toBeTruthy();
    expect(screen.getByText('3boUdo...nsWu')).toBeTruthy();
    expect(screen.getByText('Rides')).toBeTruthy();
  });

  test('RiderHeader does not expose wallet on third-person profiles', () => {
    render(
      <RiderHeader
        identity={{ ...IDENTITY, username: null, displayName: null }}
      />,
    );

    expect(screen.getByText('Rider')).toBeTruthy();
    expect(screen.queryByText(/3boUdo/)).toBeNull();
  });

  test('RiderRow opens the supplied rider action', () => {
    const onPress = jest.fn();
    render(
      <RiderRow
        rankLabel="#1"
        identity={IDENTITY}
        subtitle="Top time"
        value="5:12"
        onPress={onPress}
      />,
    );

    fireEvent.press(screen.getByText('Tim'));

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  test('FollowButton only calls action for actionable states', () => {
    const onPress = jest.fn();
    render(<FollowButton state="not_following" onPress={onPress} />);

    fireEvent.press(screen.getByText('Follow'));

    expect(onPress).toHaveBeenCalledTimes(1);
  });
});
