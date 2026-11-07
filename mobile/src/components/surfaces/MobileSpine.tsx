import React from 'react';
import {
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { mobileColors, mobileRadii, mobileType } from '../../theme/tokens';
import GlassSurface from './GlassSurface';

export interface MobileSpineMetric {
  label: string;
  value: string;
  tone?: 'default' | 'accent' | 'proof' | 'reward';
}

export interface MobileSpineTab {
  key: string;
  label: string;
}

export interface QuietProofItem {
  label: string;
  value: string;
  tone?: 'default' | 'proof' | 'reward' | 'muted';
}

interface ObjectWindowProps {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}

export function ObjectWindow({ children, style }: ObjectWindowProps) {
  return (
    <GlassSurface tone="strong" style={[styles.objectWindow, style]}>
      {children}
    </GlassSurface>
  );
}

interface LocalObjectTabsProps {
  items: MobileSpineTab[];
  activeKey: string;
  onChange?: (key: string) => void;
}

export function LocalObjectTabs({
  items,
  activeKey,
  onChange,
}: LocalObjectTabsProps) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.tabs}
    >
      {items.map((item) => {
        const active = item.key === activeKey;
        const content = (
          <Text style={[styles.tabText, active && styles.tabTextActive]}>
            {item.label}
          </Text>
        );

        if (onChange) {
          return (
            <TouchableOpacity
              key={item.key}
              style={[styles.tab, active && styles.tabActive]}
              onPress={() => onChange(item.key)}
              activeOpacity={0.84}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
              testID={`object-tab-${item.key}`}
            >
              {content}
            </TouchableOpacity>
          );
        }

        return (
          <View
            key={item.key}
            style={[styles.tab, active && styles.tabActive]}
            accessibilityRole="text"
            testID={`object-tab-${item.key}`}
          >
            {content}
          </View>
        );
      })}
    </ScrollView>
  );
}

interface MetricBandProps {
  items: MobileSpineMetric[];
  columns?: 2 | 3;
  style?: StyleProp<ViewStyle>;
}

export function MetricBand({ items, columns = 3, style }: MetricBandProps) {
  return (
    <View style={[styles.metricBand, style]}>
      {items.map((item) => (
        <View
          key={`${item.label}-${item.value}`}
          style={[styles.metricCell, columns === 2 && styles.metricCellTwo]}
        >
          <Text style={styles.metricLabel}>{item.label}</Text>
          <Text
            style={[
              styles.metricValue,
              item.tone === 'accent' && styles.metricValueAccent,
              item.tone === 'proof' && styles.metricValueProof,
              item.tone === 'reward' && styles.metricValueReward,
            ]}
            numberOfLines={2}
            adjustsFontSizeToFit
            minimumFontScale={0.82}
          >
            {item.value}
          </Text>
        </View>
      ))}
    </View>
  );
}

interface QuietProofRowProps {
  items: QuietProofItem[];
  style?: StyleProp<ViewStyle>;
}

export function QuietProofRow({ items, style }: QuietProofRowProps) {
  return (
    <View style={[styles.proofWrap, style]}>
      {items.map((item, index) => (
        <View
          key={`${item.label}-${item.value}`}
          style={[styles.proofItem, index > 0 && styles.proofItemDivider]}
        >
          <Text style={styles.proofLabel}>{item.label}</Text>
          <Text
            style={[
              styles.proofValue,
              item.tone === 'proof' && styles.proofValueProof,
              item.tone === 'reward' && styles.proofValueReward,
              item.tone === 'muted' && styles.proofValueMuted,
            ]}
            numberOfLines={1}
          >
            {item.value}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  objectWindow: {
    marginBottom: 12,
    overflow: 'hidden',
  },
  tabs: {
    gap: 5,
    paddingHorizontal: 3,
    paddingVertical: 3,
  },
  tab: {
    minHeight: 32,
    justifyContent: 'center',
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'transparent',
    paddingHorizontal: 10,
  },
  tabActive: {
    backgroundColor: 'rgba(255, 255, 255, 0.52)',
    borderColor: mobileColors.borderStrong,
  },
  tabText: {
    color: mobileColors.textMuted,
    fontSize: mobileType.bodySmall,
    fontWeight: '700',
  },
  tabTextActive: {
    color: mobileColors.text,
  },
  metricBand: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  metricCell: {
    flexBasis: '31%',
    flexGrow: 1,
    minHeight: 52,
    justifyContent: 'space-between',
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    backgroundColor: 'rgba(255, 255, 255, 0.46)',
    paddingHorizontal: 9,
    paddingVertical: 8,
  },
  metricCellTwo: {
    flexBasis: '47%',
  },
  metricLabel: {
    color: mobileColors.textSubtle,
    fontSize: 9,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  metricValue: {
    color: mobileColors.text,
    fontSize: mobileType.titleSmall,
    lineHeight: 19,
    fontWeight: '800',
    marginTop: 6,
  },
  metricValueAccent: {
    color: mobileColors.accent,
  },
  metricValueProof: {
    color: mobileColors.proof,
  },
  metricValueReward: {
    color: mobileColors.reward,
  },
  proofWrap: {
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(89, 120, 72, 0.2)',
    backgroundColor: 'rgba(226, 234, 219, 0.72)',
    overflow: 'hidden',
  },
  proofItem: {
    minHeight: 34,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    paddingHorizontal: 11,
    paddingVertical: 8,
  },
  proofItemDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: 'rgba(89, 120, 72, 0.18)',
  },
  proofLabel: {
    color: mobileColors.textMuted,
    fontSize: mobileType.caption,
    fontWeight: '700',
  },
  proofValue: {
    flex: 1,
    color: mobileColors.text,
    fontSize: mobileType.caption,
    fontWeight: '800',
    textAlign: 'right',
  },
  proofValueProof: {
    color: mobileColors.proof,
  },
  proofValueReward: {
    color: mobileColors.reward,
  },
  proofValueMuted: {
    color: mobileColors.textSubtle,
  },
});
