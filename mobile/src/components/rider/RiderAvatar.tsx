import React from 'react';
import { Image, StyleSheet, Text, View } from 'react-native';

import { riderInitial, type RiderIdentityFields } from '../../lib/riderIdentity';
import { mobileColors } from '../../theme/tokens';

interface RiderAvatarProps {
  identity: RiderIdentityFields | null | undefined;
  size?: number;
}

export default function RiderAvatar({
  identity,
  size = 44,
}: RiderAvatarProps) {
  const avatarUrl = identity?.avatarUrl?.trim();
  const style = {
    width: size,
    height: size,
    borderRadius: size / 2,
  };

  if (avatarUrl) {
    return (
      <Image
        source={{ uri: avatarUrl }}
        style={[styles.avatar, style]}
        accessibilityIgnoresInvertColors
      />
    );
  }

  return (
    <View style={[styles.avatar, styles.fallback, style]}>
      <Text style={[styles.initial, { fontSize: Math.max(14, size * 0.42) }]}>
        {riderInitial(identity)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  avatar: {
    backgroundColor: mobileColors.surfaceMuted,
  },
  fallback: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.borderStrong,
  },
  initial: {
    color: mobileColors.text,
    fontWeight: '800',
  },
});
