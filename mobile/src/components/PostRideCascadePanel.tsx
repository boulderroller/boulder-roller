/**
 * PostRideCascadePanel — rider-facing post-ride result sequence.
 *
 * It exposes the shared state model so later animation/design work stays
 * aligned with ride outcomes.
 */

import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type {
  PostRideCascadeLine,
  PostRideCascadeLineState,
  PostRideCascadeView,
} from '../lib/postRideCascade';

interface Props {
  cascade: PostRideCascadeView;
}

const MARKERS: Record<PostRideCascadeLineState, string> = {
  pending: '○',
  complete: '✓',
  review: '!',
  failed: '×',
};

function stateStyle(state: PostRideCascadeLineState) {
  switch (state) {
    case 'complete':
      return styles.complete;
    case 'review':
      return styles.review;
    case 'failed':
      return styles.failed;
    case 'pending':
      return styles.pending;
  }
}

function CascadeLine({ line }: { line: PostRideCascadeLine }) {
  const lineStyle = stateStyle(line.state);
  return (
    <View style={styles.line}>
      <Text style={[styles.marker, lineStyle]}>{MARKERS[line.state]}</Text>
      <Text style={[styles.lineLabel, lineStyle]}>{line.label}</Text>
      {line.value && <Text style={styles.lineValue}>{line.value}</Text>}
    </View>
  );
}

export function PostRideCascadePanel({ cascade }: Props) {
  return (
    <View style={[styles.container, cascade.phase === 'attested' && styles.attested]}>
      <Text style={styles.eyebrow}>Ride result</Text>
      <Text style={styles.title}>{cascade.title}</Text>
      <Text style={styles.subtitle}>{cascade.subtitle}</Text>

      {cascade.hero && (
        <View style={styles.hero}>
          <View>
            <Text style={styles.heroLabel}>{cascade.hero.label}</Text>
            <Text style={styles.heroValue}>{cascade.hero.value}</Text>
          </View>
          {cascade.hero.verified && <Text style={styles.heroVerified}>✓</Text>}
        </View>
      )}

      <View style={styles.lines}>
        {cascade.lines.map((line) => (
          <CascadeLine key={line.key} line={line} />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#2a2a2a',
    backgroundColor: '#121212',
    padding: 16,
    marginBottom: 16,
  },
  attested: {
    borderColor: '#2a5a3a',
  },
  eyebrow: {
    fontSize: 11,
    fontWeight: '700',
    color: '#888',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 6,
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
    color: '#e5e5e5',
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 13,
    color: '#888',
    lineHeight: 18,
    marginBottom: 14,
  },
  hero: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderRadius: 10,
    backgroundColor: '#1a1a1a',
    padding: 14,
    marginBottom: 14,
  },
  heroLabel: {
    fontSize: 11,
    color: '#777',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 3,
  },
  heroValue: {
    fontSize: 30,
    fontWeight: '800',
    color: '#c4a035',
  },
  heroVerified: {
    width: 24,
    height: 24,
    borderRadius: 12,
    textAlign: 'center',
    lineHeight: 24,
    overflow: 'hidden',
    color: '#101510',
    backgroundColor: '#90d5a5',
    fontSize: 15,
    fontWeight: '800',
  },
  lines: {
    gap: 8,
  },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  marker: {
    width: 20,
    fontSize: 14,
    fontWeight: '700',
  },
  lineLabel: {
    flex: 1,
    fontSize: 13,
  },
  lineValue: {
    fontSize: 12,
    color: '#aaa',
    fontVariant: ['tabular-nums'],
  },
  pending: {
    color: '#666',
  },
  complete: {
    color: '#90d5a5',
  },
  review: {
    color: '#e5d090',
  },
  failed: {
    color: '#ef4444',
  },
});
