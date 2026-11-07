import React from 'react';
import {
  StyleSheet,
  type StyleProp,
  type ViewProps,
  type ViewStyle,
} from 'react-native';

import { mobileColors, mobileRadii } from '../../theme/tokens';
import GlassSurface from './GlassSurface';

interface SectionCardProps extends ViewProps {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  tone?: 'base' | 'strong' | 'muted' | 'proof' | 'reward';
}

export default function SectionCard({
  children,
  style,
  tone = 'base',
  ...rest
}: SectionCardProps) {
  return (
    <GlassSurface tone={tone} style={[styles.card, style]} {...rest}>
      {children}
    </GlassSurface>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: mobileColors.surface,
    borderRadius: mobileRadii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    overflow: 'hidden',
  },
});
