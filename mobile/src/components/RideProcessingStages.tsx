/**
 * RideProcessingStages — compact readiness list for ride results.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

import type { ProcessingStage } from '../lib/rideProcessing';
import { mobileColors } from '../theme/tokens';

interface Props {
  stages: ProcessingStage[];
}

export function RideProcessingStages({ stages }: Props) {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Ready</Text>
      {stages.map((stage) => (
        <View key={stage.key} style={styles.row}>
          <View style={[styles.dot, stage.complete && styles.dotDone]} />
          <Text
            style={[styles.label, stage.complete ? styles.labelDone : styles.labelPending]}
          >
            {stage.label}
          </Text>
          <Text style={[styles.state, stage.complete && styles.stateDone]}>
            {stage.complete ? 'Ready' : 'Waiting'}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingTop: 6,
  },
  title: {
    fontSize: 12,
    fontWeight: '700',
    color: mobileColors.textSubtle,
    marginBottom: 10,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 7,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: mobileColors.divider,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: mobileColors.textSubtle,
  },
  dotDone: {
    backgroundColor: mobileColors.proof,
  },
  label: {
    fontSize: 14,
    flex: 1,
  },
  labelDone: {
    color: mobileColors.text,
  },
  labelPending: {
    color: mobileColors.textSubtle,
  },
  state: {
    color: mobileColors.textSubtle,
    fontSize: 12,
    fontWeight: '700',
  },
  stateDone: {
    color: mobileColors.proof,
  },
});
