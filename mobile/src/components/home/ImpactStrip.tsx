import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { mobileColors, mobileRadii } from '../../theme/tokens';

interface ImpactStripProps {
  items: string[];
}

export default function ImpactStrip({ items }: ImpactStripProps) {
  if (items.length === 0) return null;

  return (
    <View style={styles.row}>
      {items.slice(0, 2).map((item) => (
        <View key={item} style={styles.pill}>
          <Text style={styles.text}>{item}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 12,
  },
  pill: {
    backgroundColor: mobileColors.proofSoft,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(89, 120, 72, 0.22)',
    borderRadius: mobileRadii.sm,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  text: {
    color: mobileColors.proof,
    fontSize: 11,
    fontWeight: '800',
  },
});
