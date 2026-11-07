import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import { mobileColors, mobileRadii } from '../../theme/tokens';

export interface SegmentedControlItem {
  key: string;
  label: string;
}

interface SegmentedControlProps {
  items: SegmentedControlItem[];
  activeKey: string;
  onChange: (key: string) => void;
}

export default function SegmentedControl({
  items,
  activeKey,
  onChange,
}: SegmentedControlProps) {
  return (
    <View style={styles.shell}>
      {items.map((item) => {
        const isActive = item.key === activeKey;
        return (
          <TouchableOpacity
            key={item.key}
            style={[styles.segment, isActive && styles.segmentActive]}
            onPress={() => onChange(item.key)}
            activeOpacity={0.85}
            accessibilityRole="button"
            accessibilityLabel={item.label}
            accessibilityHint={`Select ${item.label}`}
            accessibilityState={{ selected: isActive }}
            hitSlop={{ top: 8, bottom: 8, left: 6, right: 6 }}
            testID={`segmented-${item.key}`}
          >
            <Text
              style={[styles.segmentText, isActive && styles.segmentTextActive]}
            >
              {item.label}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    flexDirection: 'row',
    alignSelf: 'flex-start',
    backgroundColor: 'rgba(255, 253, 247, 0.58)',
    borderRadius: mobileRadii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    padding: 4,
    gap: 4,
  },
  segment: {
    borderRadius: mobileRadii.sm,
    minHeight: 32,
    minWidth: 68,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  segmentActive: {
    backgroundColor: 'rgba(255, 255, 255, 0.62)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.borderStrong,
  },
  segmentText: {
    fontSize: 12,
    fontWeight: '700',
    color: mobileColors.textMuted,
  },
  segmentTextActive: {
    color: mobileColors.text,
  },
});
