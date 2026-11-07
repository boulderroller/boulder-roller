import React from 'react';
import { Image, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import Feather from '@expo/vector-icons/Feather';

import type { StatClusterItem } from '../surfaces/StatCluster';
import type { RoutePreview } from '../../lib/routePreview';
import RoutePreviewMap from '../route/RoutePreviewMap';
import { mobileColors, mobileRadii } from '../../theme/tokens';

interface RideFeedItemProps {
  actorLabel: string;
  actorAvatarUrl?: string | null;
  title: string;
  dateLabel: string;
  locationLabel?: string;
  summaryLine: string;
  statusLine: string;
  stats: StatClusterItem[];
  routePreview?: RoutePreview | null;
  primaryMediaUrl?: string | null;
  mediaCount?: number;
  impactItems?: string[];
  kudosCount?: number | null;
  commentCount?: number | null;
  viewerHasKudos?: boolean;
  onPress: () => void;
  onPressActor?: () => void;
  onPressKudos?: () => void;
  onPressComment?: () => void;
  testID?: string;
}

export default function RideFeedItem({
  actorLabel,
  actorAvatarUrl,
  title,
  dateLabel,
  locationLabel,
  summaryLine,
  statusLine,
  stats,
  routePreview,
  primaryMediaUrl,
  mediaCount,
  impactItems = [],
  kudosCount,
  commentCount,
  viewerHasKudos,
  onPress,
  onPressActor,
  onPressKudos,
  onPressComment,
  testID,
}: RideFeedItemProps) {
  const achievementText = impactItems[0] ?? statusLine;
  const metaLine = locationLabel ? `${dateLabel} • ${locationLabel}` : dateLabel;
  const statItems = stats.slice(0, 4);

  return (
    <View
      style={styles.item}
      testID={testID}
    >
      {onPressActor ? (
        <TouchableOpacity
          style={styles.actorRow}
          onPress={onPressActor}
          activeOpacity={0.82}
          accessibilityRole="button"
          accessibilityLabel={`Open ${actorLabel}`}
          testID={testID ? `${testID}-actor` : undefined}
        >
          {actorAvatarUrl ? (
            <Image
              source={{ uri: actorAvatarUrl }}
              style={styles.avatar}
              accessibilityIgnoresInvertColors
            />
          ) : (
            <View style={styles.avatar} />
          )}
          <View style={styles.actorCopy}>
            <Text style={styles.actor}>{actorLabel}</Text>
            <Text style={styles.date}>{metaLine}</Text>
          </View>
        </TouchableOpacity>
      ) : (
        <View
          style={styles.actorRow}
          testID={testID ? `${testID}-actor` : undefined}
        >
          {actorAvatarUrl ? (
            <Image
              source={{ uri: actorAvatarUrl }}
              style={styles.avatar}
              accessibilityIgnoresInvertColors
            />
          ) : (
            <View style={styles.avatar} />
          )}
          <View style={styles.actorCopy}>
            <Text style={styles.actor}>{actorLabel}</Text>
            <Text style={styles.date}>{metaLine}</Text>
          </View>
        </View>
      )}

      <TouchableOpacity
        style={styles.content}
        onPress={onPress}
        activeOpacity={0.9}
        accessibilityRole="button"
        accessibilityLabel={`${title}, ${summaryLine}`}
        testID={testID ? `${testID}-body` : undefined}
      >
        <View style={styles.titleBlock}>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.summaryLine}>{summaryLine}</Text>
        </View>

        <View style={styles.statRow}>
          {statItems.map((item) => {
            const isRewardMetric = item.label === 'CAL' || item.label === 'DUNG';
            return (
              <View key={item.label} style={styles.statCell}>
                <Text style={styles.statLabel}>{item.label}</Text>
                <Text style={[styles.statValue, isRewardMetric && styles.statValueReward]}>
                  {item.value}
                </Text>
              </View>
            );
          })}
        </View>

        <View style={styles.achievementRow}>
          <View style={styles.achievementIcon} />
          <Text style={styles.achievementText}>
            <Text style={styles.achievementActor}>{actorLabel}</Text>
            {' '}
            {achievementText}
          </Text>
        </View>

        {primaryMediaUrl ? (
          <View style={styles.mediaFrame}>
            <Image
              source={{ uri: primaryMediaUrl }}
              style={styles.mediaImage}
              resizeMode="cover"
              accessibilityIgnoresInvertColors
            />
            {mediaCount != null && mediaCount > 1 ? (
              <View style={styles.mediaCountBadge}>
                <Text style={styles.mediaCountText}>{mediaCount} photos</Text>
              </View>
            ) : null}
          </View>
        ) : (
          <RoutePreviewMap preview={routePreview} height={196} />
        )}
      </TouchableOpacity>

      <View style={styles.actionRow}>
        <TouchableOpacity
          style={styles.actionButton}
          onPress={onPressKudos ?? onPress}
          activeOpacity={0.78}
          accessibilityLabel="Kudos"
          testID={testID ? `${testID}-kudos` : undefined}
        >
          <View style={styles.actionButtonContent}>
            <Feather
              name="heart"
              size={21}
              color={viewerHasKudos ? mobileColors.proof : mobileColors.textMuted}
            />
            {kudosCount != null && kudosCount > 0 ? (
              <Text style={[styles.actionCount, viewerHasKudos && styles.actionCountActive]}>
                {kudosCount}
              </Text>
            ) : null}
          </View>
        </TouchableOpacity>
        <View style={styles.actionDivider} />
        <TouchableOpacity
          style={styles.actionButton}
          onPress={onPressComment ?? onPress}
          activeOpacity={0.78}
          accessibilityLabel="Comments"
          testID={testID ? `${testID}-comments` : undefined}
        >
          <View style={styles.actionButtonContent}>
            <Feather name="message-circle" size={21} color={mobileColors.textMuted} />
            {commentCount != null && commentCount > 0 ? (
              <Text style={styles.actionCount}>{commentCount}</Text>
            ) : null}
          </View>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  item: {
    backgroundColor: 'rgba(255, 253, 247, 0.84)',
    borderRadius: mobileRadii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    marginHorizontal: 14,
    marginBottom: 10,
    overflow: 'hidden',
    shadowColor: mobileColors.shadow,
    shadowOpacity: 0.055,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 5 },
    elevation: 1,
  },
  content: {
    paddingHorizontal: 14,
    paddingBottom: 11,
  },
  actorRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingHorizontal: 14,
    paddingTop: 12,
    paddingBottom: 12,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: mobileColors.surfaceMuted,
  },
  actorCopy: {
    flex: 1,
    minWidth: 0,
  },
  actor: {
    color: mobileColors.text,
    fontSize: 12,
    fontWeight: '800',
  },
  date: {
    color: mobileColors.textMuted,
    fontSize: 11,
    fontWeight: '600',
    marginTop: 4,
  },
  titleBlock: {
    marginBottom: 10,
  },
  title: {
    color: mobileColors.text,
    fontSize: 19,
    lineHeight: 23,
    fontWeight: '800',
  },
  summaryLine: {
    color: mobileColors.textMuted,
    fontSize: 12,
    fontWeight: '600',
    marginTop: 4,
  },
  statRow: {
    flexDirection: 'row',
    gap: 16,
    marginBottom: 10,
  },
  statCell: {
    minWidth: 54,
  },
  statLabel: {
    color: mobileColors.textSubtle,
    fontSize: 10,
    fontWeight: '600',
    marginBottom: 4,
  },
  statValue: {
    color: mobileColors.text,
    fontSize: 21,
    lineHeight: 24,
    fontWeight: '500',
  },
  statValueReward: {
    color: mobileColors.proof,
    fontWeight: '700',
  },
  achievementRow: {
    minHeight: 36,
    backgroundColor: 'rgba(226, 234, 219, 0.42)',
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(89, 120, 72, 0.13)',
    borderRadius: mobileRadii.sm,
    paddingHorizontal: 9,
    paddingVertical: 6,
    gap: 8,
    marginBottom: 10,
  },
  achievementIcon: {
    width: 3,
    height: 24,
    borderRadius: 2,
    backgroundColor: mobileColors.proof,
  },
  achievementText: {
    flex: 1,
    color: mobileColors.textMuted,
    fontSize: 11,
    lineHeight: 15,
    fontWeight: '700',
  },
  mediaFrame: {
    position: 'relative',
    height: 184,
    backgroundColor: mobileColors.dark,
    borderRadius: mobileRadii.md,
    overflow: 'hidden',
  },
  mediaImage: {
    width: '100%',
    height: '100%',
  },
  mediaCountBadge: {
    position: 'absolute',
    right: 10,
    bottom: 10,
    backgroundColor: 'rgba(17, 17, 15, 0.78)',
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'rgba(255, 255, 255, 0.18)',
    paddingHorizontal: 8,
    paddingVertical: 5,
  },
  mediaCountText: {
    color: mobileColors.textOnAccent,
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  achievementActor: {
    fontWeight: '800',
  },
  actionRow: {
    height: 40,
    flexDirection: 'row',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: mobileColors.divider,
    backgroundColor: 'rgba(255, 253, 247, 0.58)',
  },
  actionButton: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionButtonContent: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    minWidth: 44,
  },
  actionCount: {
    color: mobileColors.textMuted,
    fontSize: 12,
    fontWeight: '800',
  },
  actionCountActive: {
    color: mobileColors.proof,
  },
  actionDivider: {
    width: StyleSheet.hairlineWidth,
    backgroundColor: mobileColors.divider,
  },
});
