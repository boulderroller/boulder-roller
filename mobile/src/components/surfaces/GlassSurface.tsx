import React from 'react';
import {
  StyleSheet,
  View,
  type StyleProp,
  type ViewProps,
  type ViewStyle,
} from 'react-native';

import { mobileColors, mobileRadii } from '../../theme/tokens';

interface GlassSurfaceProps extends ViewProps {
  children: React.ReactNode;
  padded?: boolean;
  tone?: 'base' | 'strong' | 'muted' | 'proof' | 'reward';
  style?: StyleProp<ViewStyle>;
}

export default function GlassSurface({
  children,
  padded = false,
  tone = 'base',
  style,
  ...rest
}: GlassSurfaceProps) {
  return (
    <View
      style={[
        styles.surface,
        padded && styles.padded,
        tone === 'strong' && styles.strong,
        tone === 'muted' && styles.muted,
        tone === 'proof' && styles.proof,
        tone === 'reward' && styles.reward,
        style,
      ]}
      {...rest}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  surface: {
    backgroundColor: mobileColors.surface,
    borderRadius: mobileRadii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    shadowColor: mobileColors.shadow,
    shadowOpacity: 0.045,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 1,
  },
  padded: {
    padding: 14,
  },
  strong: {
    backgroundColor: mobileColors.surfaceStrong,
    borderColor: mobileColors.borderStrong,
  },
  muted: {
    backgroundColor: mobileColors.surfaceMuted,
  },
  proof: {
    backgroundColor: mobileColors.proofSoft,
    borderColor: 'rgba(89, 120, 72, 0.24)',
  },
  reward: {
    backgroundColor: mobileColors.rewardSoft,
    borderColor: 'rgba(168, 120, 40, 0.26)',
  },
});
