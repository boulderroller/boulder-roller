import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { RiderIdentityFields } from '../../lib/riderIdentity';
import {
  formatShortWallet,
  riderPrimaryLabel,
  riderPublicLabel,
  riderSecondaryLabel,
} from '../../lib/riderIdentity';
import SectionCard from '../surfaces/SectionCard';
import StatCluster, { type StatClusterItem } from '../surfaces/StatCluster';
import RiderAvatar from './RiderAvatar';
import { mobileColors } from '../../theme/tokens';

interface RiderHeaderProps {
  identity: RiderIdentityFields;
  bio?: string | null;
  stats?: StatClusterItem[];
  action?: React.ReactNode;
  accountContext?: boolean;
  testID?: string;
}

export default function RiderHeader({
  identity,
  bio,
  stats,
  action,
  accountContext = false,
  testID,
}: RiderHeaderProps) {
  const primary = accountContext ? riderPrimaryLabel(identity) : riderPublicLabel(identity);
  const secondary = riderSecondaryLabel(identity, { includeWallet: accountContext });
  const wallet = accountContext ? formatShortWallet(identity.wallet, 6, 4) : null;
  const showWallet = wallet && wallet !== secondary;

  return (
    <SectionCard tone="strong" style={styles.card} testID={testID}>
      <View style={styles.identityRow}>
        <RiderAvatar identity={identity} size={56} />
        <View style={styles.copy}>
          <Text style={styles.primary}>{primary}</Text>
          {secondary ? <Text style={styles.secondary}>{secondary}</Text> : null}
          {showWallet ? <Text style={styles.account}>{wallet}</Text> : null}
        </View>
        {action ? <View style={styles.action}>{action}</View> : null}
      </View>

      {bio ? <Text style={styles.bio}>{bio}</Text> : null}

      {stats && stats.length > 0 ? (
        <View style={styles.stats}>
          <StatCluster variant="profile" items={stats} />
        </View>
      ) : null}
    </SectionCard>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 14,
  },
  identityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  copy: {
    flex: 1,
  },
  primary: {
    color: mobileColors.text,
    fontSize: 19,
    fontWeight: '800',
  },
  secondary: {
    color: mobileColors.textMuted,
    fontSize: 13,
    marginTop: 3,
  },
  account: {
    color: mobileColors.textSubtle,
    fontSize: 12,
    marginTop: 3,
  },
  action: {
    alignSelf: 'center',
  },
  bio: {
    color: mobileColors.textMuted,
    fontSize: 13,
    lineHeight: 19,
    marginTop: 12,
  },
  stats: {
    marginTop: 14,
  },
});
