import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { mobileColors } from '../../theme/tokens';

interface ActionRowProps {
  title: string;
  subtitle?: string;
  onPress?: () => void;
  destructive?: boolean;
  withDivider?: boolean;
  testID?: string;
}

export default function ActionRow({
  title,
  subtitle,
  onPress,
  destructive = false,
  withDivider = false,
  testID,
}: ActionRowProps) {
  const content = (
    <View style={styles.content}>
      <View style={styles.copy}>
        <Text style={[styles.title, destructive && styles.titleDestructive]}>
          {title}
        </Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {onPress ? <Text style={styles.chevron}>›</Text> : null}
    </View>
  );

  if (onPress) {
    return (
      <TouchableOpacity
        style={[styles.row, withDivider && styles.rowDivider]}
        onPress={onPress}
        activeOpacity={0.86}
        testID={testID}
      >
        {content}
      </TouchableOpacity>
    );
  }

  return (
    <View style={[styles.row, withDivider && styles.rowDivider]} testID={testID}>
      {content}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    paddingHorizontal: 14,
    paddingVertical: 13,
    backgroundColor: 'transparent',
  },
  rowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: mobileColors.divider,
  },
  content: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 16,
  },
  copy: {
    flex: 1,
  },
  title: {
    color: mobileColors.text,
    fontSize: 14,
    fontWeight: '700',
  },
  titleDestructive: {
    color: mobileColors.danger,
  },
  subtitle: {
    marginTop: 4,
    color: mobileColors.textMuted,
    fontSize: 12,
    lineHeight: 17,
  },
  chevron: {
    color: mobileColors.textSubtle,
    fontSize: 20,
    lineHeight: 20,
  },
});
