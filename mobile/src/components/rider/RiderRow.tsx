import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import type { RiderIdentityFields } from '../../lib/riderIdentity';
import { riderPrimaryLabel, riderSecondaryLabel } from '../../lib/riderIdentity';
import RiderAvatar from './RiderAvatar';
import { mobileColors } from '../../theme/tokens';

interface RiderRowProps {
  identity: RiderIdentityFields;
  rankLabel?: string;
  subtitle?: string;
  value?: string;
  onPress?: () => void;
  withDivider?: boolean;
  testID?: string;
}

export default function RiderRow({
  identity,
  rankLabel,
  subtitle,
  value,
  onPress,
  withDivider = true,
  testID,
}: RiderRowProps) {
  const content = (
    <View style={[styles.row, withDivider && styles.divider]}>
      {rankLabel ? <Text style={styles.rank}>{rankLabel}</Text> : null}
      <RiderAvatar identity={identity} size={36} />
      <View style={styles.copy}>
        <Text style={styles.primary}>{riderPrimaryLabel(identity)}</Text>
        <Text style={styles.secondary}>
          {subtitle ?? riderSecondaryLabel(identity) ?? 'Rider'}
        </Text>
      </View>
      {value ? <Text style={styles.value}>{value}</Text> : null}
      {onPress ? <Text style={styles.chevron}>›</Text> : null}
    </View>
  );

  if (!onPress) {
    return <View testID={testID}>{content}</View>;
  }

  return (
    <TouchableOpacity
      activeOpacity={0.86}
      onPress={onPress}
      testID={testID}
    >
      {content}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 12,
  },
  divider: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: mobileColors.divider,
  },
  rank: {
    width: 34,
    color: mobileColors.text,
    fontSize: 14,
    fontWeight: '800',
  },
  copy: {
    flex: 1,
    minWidth: 0,
  },
  primary: {
    color: mobileColors.text,
    fontSize: 14,
    fontWeight: '700',
  },
  secondary: {
    color: mobileColors.textMuted,
    fontSize: 12,
    marginTop: 2,
  },
  value: {
    color: mobileColors.text,
    fontSize: 14,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  chevron: {
    color: mobileColors.textSubtle,
    fontSize: 18,
    lineHeight: 18,
  },
});
