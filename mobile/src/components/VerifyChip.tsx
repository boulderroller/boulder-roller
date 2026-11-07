import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { VerificationState } from '../lib/verify';
import { mobileColors, mobileRadii } from '../theme/tokens';

interface Props {
  state: VerificationState;
}

const LABELS: Record<VerificationState, string> = {
  unchecked: 'Unchecked',
  checking: 'Checking',
  verified: 'Verified',
  diverged: 'Mismatch',
  unavailable: 'Unavailable',
};

const COLORS: Record<VerificationState, { border: string; text: string }> = {
  unchecked: { border: mobileColors.borderStrong, text: mobileColors.textSubtle },
  checking: { border: 'rgba(168, 120, 40, 0.38)', text: mobileColors.reward },
  verified: { border: 'rgba(89, 120, 72, 0.38)', text: mobileColors.proof },
  diverged: { border: 'rgba(180, 90, 77, 0.42)', text: mobileColors.danger },
  unavailable: { border: mobileColors.borderStrong, text: mobileColors.textMuted },
};

export function VerifyChip({ state }: Props) {
  const colors = COLORS[state];
  return (
    <View style={[styles.container, { borderColor: colors.border }]}>
      <Text style={[styles.text, { color: colors.text }]}>
        {LABELS[state]}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: mobileRadii.sm,
    backgroundColor: mobileColors.surface,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  text: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
});
