import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import Feather from '@expo/vector-icons/Feather';

import { mobileColors, mobileRadii, mobileType } from '../../theme/tokens';

const ICON_BUTTON_SIZE = 30;
const ICON_BUTTON_GAP = 6;

interface TopTabBarProps {
  title: string;
  testIdPrefix: string;
  onPressSearch?: () => void;
  onPressAlerts?: () => void;
  onPressProfile?: () => void;
  unreadCount?: number;
}

export default function TopTabBar({
  title,
  testIdPrefix,
  onPressSearch,
  onPressAlerts,
  onPressProfile,
  unreadCount = 0,
}: TopTabBarProps) {
  const hasUnread = unreadCount > 0;

  return (
    <View style={styles.topRail}>
      <View style={styles.brandCluster}>
        <View style={styles.brandMark}>
          <Text style={styles.brandMarkText}>BR</Text>
        </View>
        <View style={styles.titleWrap}>
          <Text style={styles.brandLabel}>Boulder Roller</Text>
          <Text style={styles.title} numberOfLines={1}>{title}</Text>
        </View>
      </View>
      <View style={styles.utilityRow}>
        {onPressSearch ? (
          <TouchableOpacity
            style={styles.utilityButton}
            testID={`${testIdPrefix}-utility-search`}
            accessibilityLabel="Search"
            onPress={onPressSearch}
            activeOpacity={0.82}
          >
            <Feather name="search" size={17} color={mobileColors.textMuted} />
          </TouchableOpacity>
        ) : (
          <View style={styles.utilityPlaceholder} />
        )}
        <TouchableOpacity
          style={styles.utilityButton}
          testID={`${testIdPrefix}-utility-alerts`}
          accessibilityLabel="Alerts"
          disabled={!onPressAlerts}
          onPress={onPressAlerts}
          activeOpacity={0.82}
        >
          <Feather name="bell" size={17} color={mobileColors.textMuted} />
          {hasUnread ? (
            <View style={styles.badge} testID={`${testIdPrefix}-alerts-badge`}>
              <Text style={styles.badgeText}>
                {unreadCount > 9 ? '9+' : unreadCount}
              </Text>
            </View>
          ) : null}
        </TouchableOpacity>
        {onPressProfile ? (
          <TouchableOpacity
            style={styles.utilityButton}
            testID={`${testIdPrefix}-utility-profile`}
            accessibilityLabel="Profile"
            onPress={onPressProfile}
            activeOpacity={0.82}
          >
            <Feather name="user" size={17} color={mobileColors.textMuted} />
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  topRail: {
    paddingHorizontal: 14,
    paddingTop: 7,
    paddingBottom: 8,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    backgroundColor: mobileColors.canvas,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: mobileColors.border,
  },
  brandCluster: {
    flex: 1,
    minWidth: 0,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  brandMark: {
    width: 28,
    height: 28,
    borderRadius: mobileRadii.sm,
    backgroundColor: mobileColors.accent,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.accentMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  brandMarkText: {
    color: mobileColors.textOnAccent,
    fontSize: 9,
    fontWeight: '900',
  },
  titleWrap: {
    flex: 1,
    minWidth: 0,
    justifyContent: 'center',
  },
  brandLabel: {
    color: mobileColors.textSubtle,
    fontSize: 9,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  title: {
    color: mobileColors.text,
    fontSize: mobileType.titleSmall,
    fontWeight: '800',
    marginTop: 2,
  },
  utilityRow: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: ICON_BUTTON_GAP,
  },
  utilityButton: {
    width: ICON_BUTTON_SIZE,
    height: ICON_BUTTON_SIZE,
    borderRadius: mobileRadii.sm,
    backgroundColor: 'rgba(255, 253, 247, 0.56)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    justifyContent: 'center',
    alignItems: 'center',
  },
  utilityPlaceholder: {
    width: ICON_BUTTON_SIZE,
    height: ICON_BUTTON_SIZE,
  },
  badge: {
    position: 'absolute',
    right: -4,
    top: -5,
    minWidth: 16,
    height: 16,
    borderRadius: mobileRadii.xs,
    backgroundColor: mobileColors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  badgeText: {
    color: mobileColors.textOnAccent,
    fontSize: 9,
    fontWeight: '800',
  },
});
