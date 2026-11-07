import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { mobileColors, mobileRadii } from '../../theme/tokens';

interface AssetStat {
  label: string;
  value: string;
}

interface AssetRowProps {
  title: string;
  subtitle?: string | null;
  stats: AssetStat[];
  detail: string;
  onPress: () => void;
  testID?: string;
}

export default function AssetRow({
  title,
  subtitle,
  stats,
  detail,
  onPress,
  testID,
}: AssetRowProps) {
  return (
    <TouchableOpacity
      style={styles.row}
      onPress={onPress}
      activeOpacity={0.86}
      testID={testID}
    >
      <View style={styles.header}>
        <View style={styles.titleBlock}>
          <Text style={styles.title}>{title}</Text>
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        </View>
        <Text style={styles.chevron}>›</Text>
      </View>

      <View style={styles.statsRow}>
        {stats.map((stat) => (
          <View key={stat.label} style={styles.stat}>
            <Text style={styles.statValue}>{stat.value}</Text>
            <Text style={styles.statLabel}>{stat.label}</Text>
          </View>
        ))}
      </View>

      <Text style={styles.detail}>{detail}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: {
    backgroundColor: mobileColors.surface,
    paddingHorizontal: 16,
    paddingVertical: 16,
    marginHorizontal: 16,
    marginBottom: 10,
    borderRadius: mobileRadii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    shadowColor: mobileColors.shadow,
    shadowOpacity: 0.05,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 5 },
    elevation: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 16,
  },
  titleBlock: {
    flex: 1,
  },
  title: {
    color: mobileColors.text,
    fontSize: 17,
    fontWeight: '800',
  },
  subtitle: {
    marginTop: 4,
    color: mobileColors.textMuted,
    fontSize: 12,
  },
  chevron: {
    color: mobileColors.textSubtle,
    fontSize: 18,
    lineHeight: 18,
  },
  statsRow: {
    flexDirection: 'row',
    gap: 20,
    marginTop: 12,
  },
  stat: {
    alignItems: 'flex-start',
  },
  statValue: {
    color: mobileColors.text,
    fontSize: 15,
    fontWeight: '800',
  },
  statLabel: {
    color: mobileColors.textSubtle,
    fontSize: 11,
    marginTop: 2,
  },
  detail: {
    color: mobileColors.textMuted,
    fontSize: 13,
    lineHeight: 18,
    marginTop: 12,
  },
});
