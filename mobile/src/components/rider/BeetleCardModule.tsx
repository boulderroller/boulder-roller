import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { BeetleCard } from '../../lib/api';
import SectionCard from '../surfaces/SectionCard';
import { mobileColors } from '../../theme/tokens';

interface BeetleCardModuleProps {
  cards: BeetleCard[];
}

function cardLabel(card: BeetleCard): string {
  const type = card.cardType.toLowerCase();
  if (type === 'climb') return card.scopeName ? `${card.scopeName} Climb` : 'Climb';
  if (type === 'steady') return 'Steady';
  if (type === 'exploration') return 'Explorer';
  return card.cardType;
}

export default function BeetleCardModule({ cards }: BeetleCardModuleProps) {
  if (cards.length === 0) return null;

  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>BeetleCard</Text>
      <SectionCard>
        {cards.slice(0, 3).map((card, index) => (
          <View
            key={card.id}
            style={[styles.cardRow, index > 0 && styles.divider]}
          >
            <View style={styles.copy}>
              <Text style={styles.cardTitle}>{cardLabel(card)}</Text>
              <Text style={styles.cardMeta}>
                {card.patternsScored.toLocaleString()} efforts counted
              </Text>
            </View>
            <View style={styles.scoreBlock}>
              <Text style={styles.level}>Lv {card.level}</Text>
              <Text style={styles.score}>{card.score.toLocaleString()}</Text>
            </View>
          </View>
        ))}
      </SectionCard>
    </View>
  );
}

const styles = StyleSheet.create({
  section: {
    marginBottom: 22,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: '600',
    color: mobileColors.textSubtle,
    letterSpacing: 0.5,
    marginBottom: 10,
  },
  cardRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  divider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: mobileColors.divider,
  },
  copy: {
    flex: 1,
  },
  cardTitle: {
    color: mobileColors.text,
    fontSize: 15,
    fontWeight: '800',
  },
  cardMeta: {
    color: mobileColors.textMuted,
    fontSize: 12,
    marginTop: 4,
  },
  scoreBlock: {
    alignItems: 'flex-end',
  },
  level: {
    color: mobileColors.reward,
    fontSize: 13,
    fontWeight: '800',
  },
  score: {
    color: mobileColors.textMuted,
    fontSize: 12,
    marginTop: 3,
  },
});
