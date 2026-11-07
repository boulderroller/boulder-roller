/**
 * RideReviewBanner — compact rider-facing status for ride readiness.
 *
 * Surface requirements mapping: proof state -> rider-visible verification.
 */

import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

import type { RideAttestationView, AttestationState } from '../lib/attestation';
import { mobileColors } from '../theme/tokens';

interface Props {
  view: RideAttestationView;
}

export function RideReviewBanner({ view }: Props) {
  const styleForState = STATE_STYLES[view.state];
  return (
    <View style={styles.container}>
      <View style={[styles.dot, styleForState.dot]} />
      <View style={styles.copy}>
        <Text style={[styles.title, styleForState.title]}>
          {TITLES[view.state]}
        </Text>
        <Text style={[styles.body, styleForState.body]}>
          {view.message ?? BODIES[view.state]}
        </Text>
      </View>
    </View>
  );
}

const TITLES: Record<AttestationState, string> = {
  uploaded: 'Ride saved',
  provisional: 'Checking ride',
  attested: 'Verified ride',
  under_review: 'Needs review',
};

const BODIES: Record<AttestationState, string> = {
  uploaded: 'Waiting for climb matches.',
  provisional: 'Still checking this ride.',
  attested: 'Verification complete.',
  under_review: 'This ride needs a review before it counts.',
};

const STATE_STYLES: Record<
  AttestationState,
  { dot: object; title: object; body: object }
> = {
  uploaded: {
    dot: { backgroundColor: mobileColors.textSubtle },
    title: { color: mobileColors.text },
    body: { color: mobileColors.textMuted },
  },
  provisional: {
    dot: { backgroundColor: mobileColors.route },
    title: { color: mobileColors.route },
    body: { color: mobileColors.textMuted },
  },
  attested: {
    dot: { backgroundColor: mobileColors.proof },
    title: { color: mobileColors.proof },
    body: { color: mobileColors.textMuted },
  },
  under_review: {
    dot: { backgroundColor: mobileColors.reward },
    title: { color: mobileColors.reward },
    body: { color: mobileColors.textMuted },
  },
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    paddingVertical: 2,
  },
  dot: {
    width: 9,
    height: 9,
    borderRadius: 5,
    marginTop: 5,
  },
  copy: {
    flex: 1,
  },
  title: {
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 4,
  },
  body: {
    fontSize: 13,
    lineHeight: 18,
  },
});
