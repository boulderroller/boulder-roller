import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { mobileColors, mobileRadii, mobileType } from '../../theme/tokens';

interface DetailHeaderProps {
  backLabel?: string;
  title: string;
  subtitle?: string | null;
  onBack: () => void;
  tone?: 'detail' | 'deep';
  eyebrow?: string;
  statusLabel?: string | null;
  children?: React.ReactNode;
}

export default function DetailHeader({
  backLabel = 'Back',
  title,
  subtitle,
  onBack,
  tone = 'detail',
  eyebrow,
  statusLabel,
  children,
}: DetailHeaderProps) {
  return (
    <View style={styles.container}>
      <TouchableOpacity
        style={styles.backRow}
        onPress={onBack}
        activeOpacity={0.8}
      >
        <Text style={styles.backText}>‹ {backLabel}</Text>
      </TouchableOpacity>

      <View style={styles.titleBlock}>
        {eyebrow || statusLabel ? (
          <View style={styles.metaRow}>
            {eyebrow ? <Text style={styles.eyebrow}>{eyebrow}</Text> : null}
            {statusLabel ? (
              <View style={styles.statusPill}>
                <Text style={styles.statusText}>{statusLabel}</Text>
              </View>
            ) : null}
          </View>
        ) : null}
        <Text style={[styles.title, tone === 'deep' && styles.titleDeep]}>
          {title}
        </Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        {children ? <View style={styles.children}>{children}</View> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    marginBottom: 11,
  },
  backRow: {
    alignSelf: 'flex-start',
    paddingVertical: 3,
    marginBottom: 6,
  },
  backText: {
    color: mobileColors.textMuted,
    fontSize: 14,
    fontWeight: '700',
  },
  titleBlock: {
    gap: 7,
    borderRadius: mobileRadii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    backgroundColor: 'rgba(255, 253, 247, 0.82)',
    paddingHorizontal: 14,
    paddingVertical: 13,
    shadowColor: mobileColors.shadow,
    shadowOpacity: 0.045,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 5 },
    elevation: 1,
  },
  metaRow: {
    minHeight: 20,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
  },
  eyebrow: {
    color: mobileColors.textSubtle,
    fontSize: mobileType.eyebrow,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  statusPill: {
    maxWidth: '62%',
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(89, 120, 72, 0.28)',
    backgroundColor: mobileColors.proofSoft,
    paddingHorizontal: 7,
    paddingVertical: 3,
  },
  statusText: {
    color: mobileColors.proof,
    fontSize: 11,
    fontWeight: '800',
  },
  title: {
    color: mobileColors.text,
    fontSize: mobileType.display,
    lineHeight: 30,
    fontWeight: '800',
  },
  titleDeep: {
    fontSize: 25,
    fontWeight: '700',
  },
  subtitle: {
    color: mobileColors.textMuted,
    fontSize: 13,
    lineHeight: 18,
  },
  children: {
    marginTop: 2,
  },
});
