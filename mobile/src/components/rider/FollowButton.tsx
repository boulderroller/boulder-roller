import React from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity } from 'react-native';

import { mobileColors, mobileRadii } from '../../theme/tokens';

export type FollowButtonState =
  | 'loading'
  | 'following'
  | 'not_following'
  | 'mutual'
  | 'self'
  | 'error';

interface FollowButtonProps {
  state: FollowButtonState;
  onPress?: () => void;
}

function labelForState(state: FollowButtonState): string {
  switch (state) {
    case 'following':
      return 'Following';
    case 'mutual':
      return 'Mutual';
    case 'self':
      return 'Your profile';
    case 'error':
      return 'Try again';
    case 'loading':
      return 'Checking';
    case 'not_following':
      return 'Follow';
  }
}

export default function FollowButton({
  state,
  onPress,
}: FollowButtonProps) {
  const disabled = state === 'loading' || state === 'self' || !onPress;
  const active = state === 'not_following' || state === 'error';

  return (
    <TouchableOpacity
      style={[styles.button, active && styles.buttonActive, disabled && styles.disabled]}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.86}
      accessibilityRole="button"
      accessibilityLabel={labelForState(state)}
    >
      {state === 'loading' ? (
        <ActivityIndicator size="small" color={mobileColors.textMuted} />
      ) : (
        <Text style={[styles.label, active && styles.labelActive]}>
          {labelForState(state)}
        </Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  button: {
    minWidth: 96,
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.borderStrong,
    backgroundColor: mobileColors.surface,
    paddingHorizontal: 14,
    paddingVertical: 9,
    alignItems: 'center',
  },
  buttonActive: {
    backgroundColor: mobileColors.accent,
    borderColor: mobileColors.accentMuted,
  },
  disabled: {
    opacity: 0.72,
  },
  label: {
    color: mobileColors.text,
    fontSize: 13,
    fontWeight: '700',
  },
  labelActive: {
    color: mobileColors.textOnAccent,
  },
});
