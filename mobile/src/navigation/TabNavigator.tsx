import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StyleSheet } from 'react-native';
import Feather from '@expo/vector-icons/Feather';

import HomeScreen from '../screens/HomeScreen';
import RecordScreen from '../screens/RecordScreen';
import ClimbsScreen from '../screens/ClimbsScreen';
import ProfileScreen from '../screens/ProfileScreen';
import { mobileColors } from '../theme/tokens';

const Tab = createBottomTabNavigator();

function TabIcon({
  name,
  color,
  focused,
}: {
  name: React.ComponentProps<typeof Feather>['name'];
  color: string;
  focused: boolean;
}) {
  return <Feather name={name} size={focused ? 22 : 20} color={color} />;
}

export default function TabNavigator() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: styles.tabBar,
        tabBarActiveTintColor: mobileColors.accent,
        tabBarInactiveTintColor: mobileColors.textSubtle,
        tabBarLabelStyle: styles.tabLabel,
      }}
    >
      <Tab.Screen
        name="Home"
        component={HomeScreen}
        options={{
          tabBarIcon: ({ focused, color }) => (
            <TabIcon name="activity" focused={focused} color={color} />
          ),
        }}
      />
      <Tab.Screen
        name="Record"
        component={RecordScreen}
        options={{
          tabBarIcon: ({ focused, color }) => (
            <TabIcon name="navigation" focused={focused} color={color} />
          ),
        }}
      />
      <Tab.Screen
        name="Climbs"
        component={ClimbsScreen}
        options={{
          tabBarIcon: ({ focused, color }) => (
            <TabIcon name="trending-up" focused={focused} color={color} />
          ),
        }}
      />
      <Tab.Screen
        name="Profile"
        component={ProfileScreen}
        options={{
          tabBarIcon: ({ focused, color }) => (
            <TabIcon name="user" focused={focused} color={color} />
          ),
        }}
      />
    </Tab.Navigator>
  );
}

const styles = StyleSheet.create({
  tabBar: {
    backgroundColor: mobileColors.surfaceStrong,
    borderTopColor: mobileColors.border,
    borderTopWidth: StyleSheet.hairlineWidth,
    height: 85,
    paddingBottom: 28,
    paddingTop: 8,
    shadowColor: mobileColors.shadow,
    shadowOpacity: 0.08,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: -8 },
    elevation: 8,
  },
  tabLabel: {
    fontSize: 11,
    fontWeight: '700',
  },
});
