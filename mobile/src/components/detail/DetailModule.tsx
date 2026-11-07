import React from 'react';
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import SectionCard from '../surfaces/SectionCard';
import { mobileColors, mobileRadii, mobileType } from '../../theme/tokens';

interface DetailModuleProps {
  title: string;
  subtitle?: string | null;
  ctaLabel?: string;
  onPressCta?: () => void;
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  tone?: 'base' | 'strong' | 'muted' | 'proof' | 'reward';
}

export default function DetailModule({
  title,
  subtitle,
  ctaLabel,
  onPressCta,
  children,
  style,
  tone = 'base',
}: DetailModuleProps) {
  return (
    <SectionCard tone={tone} style={[styles.card, style]}>
      <View style={styles.header}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>

      <View style={styles.body}>{children}</View>

      {ctaLabel && onPressCta ? (
        <TouchableOpacity
          style={styles.cta}
          onPress={onPressCta}
          activeOpacity={0.8}
        >
          <Text style={styles.ctaText}>{ctaLabel}</Text>
        </TouchableOpacity>
      ) : null}
    </SectionCard>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 14,
    marginBottom: 10,
  },
  header: {
    marginBottom: 10,
  },
  title: {
    color: mobileColors.text,
    fontSize: mobileType.titleSmall,
    fontWeight: '800',
  },
  subtitle: {
    color: mobileColors.textMuted,
    fontSize: 12,
    lineHeight: 17,
    marginTop: 4,
  },
  body: {
    gap: 8,
  },
  cta: {
    marginTop: 12,
    alignSelf: 'flex-start',
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.borderStrong,
    backgroundColor: 'rgba(255, 253, 247, 0.42)',
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  ctaText: {
    color: mobileColors.accentMuted,
    fontSize: 12,
    fontWeight: '800',
  },
});
