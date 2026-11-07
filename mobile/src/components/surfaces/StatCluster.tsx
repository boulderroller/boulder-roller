import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { mobileColors, mobileType } from '../../theme/tokens';

export interface StatClusterItem {
  label: string;
  value: string;
}

interface StatClusterProps {
  items: StatClusterItem[];
  variant?: 'feed' | 'profile';
}

export default function StatCluster({
  items,
  variant = 'feed',
}: StatClusterProps) {
  const withDividers = variant === 'profile';

  return (
    <View style={styles.row}>
      {items.map((item, index) => (
        <React.Fragment key={item.label}>
          {withDividers && index > 0 ? <View style={styles.divider} /> : null}
          <View style={styles.cell}>
            <Text
              style={[
                styles.value,
                variant === 'profile' && styles.valueProfile,
              ]}
            >
              {item.value}
            </Text>
            <Text style={styles.label}>{item.label}</Text>
          </View>
        </React.Fragment>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'stretch',
    gap: 8,
  },
  divider: {
    width: StyleSheet.hairlineWidth,
    backgroundColor: mobileColors.divider,
  },
  cell: {
    flex: 1,
    alignItems: 'flex-start',
  },
  value: {
    color: mobileColors.text,
    fontSize: 16,
    fontWeight: '800',
  },
  valueProfile: {
    fontSize: 17,
  },
  label: {
    color: mobileColors.textSubtle,
    fontSize: mobileType.eyebrow,
    fontWeight: '700',
    marginTop: 3,
  },
});
