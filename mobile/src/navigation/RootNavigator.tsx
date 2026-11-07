/**
 * RootNavigator
 *
 * Auth-gated navigation root. Reads the Zustand auth store to decide
 * whether to show the AuthStack (login) or MainStack (app).
 *
 * The MainStack wraps the TabNavigator plus modal screens like PostRide
 * and RideRecovery that overlay the tabs.
 *
 * The 'refreshing' status still shows the app — we never flash the
 * login screen during a background token refresh.
 */

import React from 'react';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import {
  localRideOwnerKeyForWallet,
  useAuthStore,
} from '../stores/authStore';
import TabNavigator from './TabNavigator';
import AuthStack from './AuthStack';
import PostRideScreen from '../screens/PostRideScreen';
import PairingScreen from '../screens/PairingScreen';
import WalletScreen from '../screens/WalletScreen';
import RideDetailScreen from '../screens/RideDetailScreen';
import ClimbDetailScreen from '../screens/ClimbDetailScreen';
import ClimbLeaderboardScreen from '../screens/ClimbLeaderboardScreen';
import RiderDetailScreen from '../screens/RiderDetailScreen';
import SearchScreen from '../screens/SearchScreen';
import NotificationsScreen from '../screens/NotificationsScreen';
import PrivacySettingsScreen from '../screens/PrivacySettingsScreen';
import NotificationPreferencesScreen from '../screens/NotificationPreferencesScreen';
import EditProfileScreen from '../screens/EditProfileScreen';
import MyReportsScreen from '../screens/MyReportsScreen';
import { mobileColors } from '../theme/tokens';

const Stack = createNativeStackNavigator();

function MainStack() {
  return (
    <Stack.Navigator
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: mobileColors.canvas },
      }}
    >
      <Stack.Screen name="Tabs" component={TabNavigator} />
      <Stack.Screen
        name="PostRide"
        component={PostRideScreen}
        options={{ presentation: 'modal' }}
      />
      <Stack.Screen
        name="RideDetail"
        component={RideDetailScreen}
      />
      <Stack.Screen
        name="ClimbDetail"
        component={ClimbDetailScreen}
      />
      <Stack.Screen
        name="ClimbLeaderboard"
        component={ClimbLeaderboardScreen}
      />
      <Stack.Screen
        name="RiderDetail"
        component={RiderDetailScreen}
      />
      <Stack.Screen
        name="Search"
        component={SearchScreen}
      />
      <Stack.Screen
        name="Notifications"
        component={NotificationsScreen}
      />
      <Stack.Screen
        name="PrivacySettings"
        component={PrivacySettingsScreen}
      />
      <Stack.Screen
        name="NotificationPreferences"
        component={NotificationPreferencesScreen}
      />
      <Stack.Screen
        name="EditProfile"
        component={EditProfileScreen}
      />
      <Stack.Screen
        name="MyReports"
        component={MyReportsScreen}
      />
      <Stack.Screen
        name="Pairing"
        component={PairingScreen}
        options={{ presentation: 'modal' }}
      />
      <Stack.Screen
        name="Wallet"
        component={WalletScreen}
        options={{ presentation: 'modal' }}
      />
    </Stack.Navigator>
  );
}

export default function RootNavigator() {
  const status = useAuthStore((s) => s.status);
  const ownerKey = useAuthStore((state) =>
    state.status === 'authenticated' || state.status === 'refreshing'
      ? localRideOwnerKeyForWallet(state.wallet)
      : null,
  );

  if (status === 'loading') {
    return (
      <View style={styles.splash}>
        <ActivityIndicator size="large" color="#e5e5e5" />
      </View>
    );
  }

  if (status === 'unauthenticated' || !ownerKey) {
    return <AuthStack />;
  }

  // Key by stable local owner so an A -> B replacement cannot retain A's
  // in-memory RideDetail/Home state even if auth never passes through the
  // unauthenticated stack between sessions. Refreshing the same owner keeps
  // the navigator intact.
  return <MainStack key={ownerKey} />;
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    backgroundColor: mobileColors.canvas,
    justifyContent: 'center',
    alignItems: 'center',
  },
});
