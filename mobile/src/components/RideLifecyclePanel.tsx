import React from 'react';
import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';

import type { RideLifecycleAction, RideLifecycleView } from '../lib/rideLifecycle';
import {
  buildRideLifecycleDisplayModel,
  type RideLifecycleDisplayModel,
  type RideLifecycleTone,
} from '../lib/rideLifecycleDisplay';
import { mobileColors, mobileRadii } from '../theme/tokens';

interface Props {
  view: RideLifecycleView;
  title?: string;
  compact?: boolean;
  busyAction?: RideLifecycleAction | null;
  onPressAction?: (action: RideLifecycleAction) => void;
  testID?: string;
}

function toneStyle(tone: RideLifecycleTone) {
  switch (tone) {
    case 'success':
      return styles.toneSuccess;
    case 'warning':
      return styles.toneWarning;
    case 'danger':
      return styles.toneDanger;
    case 'working':
      return styles.toneWorking;
    case 'neutral':
    default:
      return styles.toneNeutral;
  }
}

function buttonStyle(tone: RideLifecycleTone) {
  return tone === 'danger' ? styles.buttonDanger : styles.buttonDefault;
}

function DetailLines({ model, compact }: { model: RideLifecycleDisplayModel; compact: boolean }) {
  if (compact || model.detailLines.length === 0) return null;
  return (
    <View style={styles.detailLines}>
      {model.detailLines.map((line) => (
        <Text key={line} style={styles.detailLine}>{line}</Text>
      ))}
    </View>
  );
}

export default function RideLifecyclePanel({
  view,
  title = 'Ride state',
  compact = false,
  busyAction = null,
  onPressAction,
  testID,
}: Props) {
  const model = buildRideLifecycleDisplayModel(view);
  const canAct = !!model.primaryAction && !!onPressAction;
  const busy = busyAction === model.primaryAction;

  return (
    <View style={[styles.panel, compact && styles.panelCompact]} testID={testID}>
      <View style={styles.headerRow}>
        <Text style={styles.eyebrow}>{title}</Text>
        <View style={[styles.statePill, toneStyle(model.tone)]}>
          <Text style={styles.statePillText}>{model.stateLabel}</Text>
        </View>
      </View>
      <Text style={styles.title}>{model.title}</Text>
      <Text style={styles.subtitle}>{model.subtitle}</Text>
      {model.failureMessage ? <Text style={styles.failure}>{model.failureMessage}</Text> : null}
      {model.qualityLabel ? <Text style={styles.quality}>{model.qualityLabel}</Text> : null}
      <DetailLines model={model} compact={compact} />
      {canAct && model.primaryActionLabel ? (
        <TouchableOpacity
          style={[styles.button, buttonStyle(model.tone), busy && styles.buttonDisabled]}
          disabled={busy}
          onPress={() => model.primaryAction && onPressAction(model.primaryAction)}
          activeOpacity={0.82}
          testID={testID ? `${testID}-action` : undefined}
        >
          <Text style={styles.buttonText}>{busy ? 'Working' : model.primaryActionLabel}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    borderRadius: mobileRadii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    backgroundColor: 'rgba(255, 255, 255, 0.5)',
    padding: 14,
    gap: 8,
    marginBottom: 14,
  },
  panelCompact: {
    padding: 12,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
  },
  eyebrow: {
    color: mobileColors.textSubtle,
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.7,
    textTransform: 'uppercase',
  },
  statePill: {
    borderRadius: mobileRadii.sm,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  toneNeutral: {
    backgroundColor: mobileColors.surfaceMuted,
  },
  toneWorking: {
    backgroundColor: mobileColors.routeSoft,
  },
  toneSuccess: {
    backgroundColor: mobileColors.proofSoft,
  },
  toneWarning: {
    backgroundColor: mobileColors.rewardSoft,
  },
  toneDanger: {
    backgroundColor: mobileColors.dangerSoft,
  },
  statePillText: {
    color: mobileColors.text,
    fontSize: 11,
    fontWeight: '800',
  },
  title: {
    color: mobileColors.text,
    fontSize: 16,
    fontWeight: '800',
  },
  subtitle: {
    color: mobileColors.textMuted,
    fontSize: 13,
    lineHeight: 18,
  },
  failure: {
    color: mobileColors.danger,
    fontSize: 12,
    lineHeight: 17,
    fontWeight: '700',
  },
  quality: {
    color: mobileColors.reward,
    fontSize: 12,
    fontWeight: '700',
  },
  detailLines: {
    gap: 4,
  },
  detailLine: {
    color: mobileColors.textMuted,
    fontSize: 12,
  },
  button: {
    alignSelf: 'flex-start',
    borderRadius: mobileRadii.sm,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginTop: 2,
  },
  buttonDefault: {
    borderColor: 'rgba(201, 99, 44, 0.28)',
    backgroundColor: mobileColors.accentSoft,
  },
  buttonDanger: {
    borderColor: 'rgba(180, 90, 77, 0.32)',
    backgroundColor: mobileColors.dangerSoft,
  },
  buttonDisabled: {
    opacity: 0.58,
  },
  buttonText: {
    color: mobileColors.accent,
    fontSize: 12,
    fontWeight: '800',
  },
});
